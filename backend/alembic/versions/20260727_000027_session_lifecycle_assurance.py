"""assure bounded session activity, expiry, and helper disclosure

Revision ID: 20260727_000027
Revises: 20260726_000026
Create Date: 2026-07-27

The session table introduced in revision 000023 already contains the complete
idle/absolute lifecycle model.  This migration narrows the callable helper
surface, adds an atomic interval-gated touch helper, and makes signed RLS
context cease to validate when its backing session is revoked or reaches
either server-side deadline.
"""

from __future__ import annotations

from alembic import op


revision = "20260727_000027"
down_revision = "20260726_000026"
branch_labels = None
depends_on = None


RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"

OLD_RUNTIME_FUNCTIONS = (
    "rotate_app_session(bytea,uuid,uuid,bytea,bytea,integer,bytea)",
)
OLD_AUTH_FUNCTIONS = (
    "issue_staff_app_session(uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)",
    "issue_resident_app_session(text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)",
    "issue_external_resident_app_session(text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)",
)
OLD_SHARED_FUNCTIONS = (
    "resolve_app_session(bytea,boolean,integer)",
)

NEW_RUNTIME_FUNCTIONS = (
    "rotate_app_session_lifecycle(bytea,uuid,uuid,bytea,bytea,integer,bytea)",
)
NEW_AUTH_FUNCTIONS = (
    "issue_staff_app_session_lifecycle(uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)",
    "issue_resident_app_session_lifecycle(text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)",
    "issue_external_resident_app_session_lifecycle(text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)",
    "revoke_app_session_family_for_logout(bytea,bytea,text)",
)
NEW_SHARED_FUNCTIONS = (
    "resolve_app_session_lifecycle(bytea,integer)",
    "touch_app_session_lifecycle(bytea,uuid,integer,integer)",
    "validate_app_session_csrf(bytea,uuid,bytea)",
)


def _execute(statement: str) -> None:
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(statement)


def _replace_context_signature(*, enforce_session_lifecycle: bool) -> None:
    active_guard = ""
    if enforce_session_lifecycle:
        active_guard = r"""
    SELECT EXISTS (
        SELECT 1
        FROM public.app_sessions AS app_session
        WHERE app_session.id = p_app_session_id
          AND app_session.subject_type = p_subject_type
          AND app_session.subject_id = p_subject_id
          AND app_session.revoked_at IS NULL
          AND pg_catalog.clock_timestamp() < app_session.idle_expires_at
          AND pg_catalog.clock_timestamp() < app_session.absolute_expires_at
          AND mata_private.authorization_fingerprint(
                app_session.subject_type,
                app_session.subject_id,
                app_session.subject_session_generation,
                p_app_role,
                p_admin_level,
                p_programme_scope,
                p_posting_code,
                app_session.id,
                app_session.auth_source
              ) = p_authorization_fingerprint
    )
    INTO session_is_active;

    -- Return a domain-separated, secret-derived value that can never equal
    -- the active-context signature.  A predictable sentinel would be unsafe:
    -- runtime roles can set custom GUCs and could copy that sentinel.
    IF NOT session_is_active THEN
        RETURN pg_catalog.lower(
            pg_catalog.encode(
                public.hmac(
                    pg_catalog.convert_to(
                        pg_catalog.jsonb_build_array(
                            'inactive-session-context-v1',
                            p_subject_type,
                            p_subject_id::text,
                            p_app_role,
                            COALESCE(p_admin_level, ''),
                            mata_private.normalized_scope(p_programme_scope),
                            COALESCE(p_posting_code, ''),
                            p_app_session_id::text,
                            p_authorization_fingerprint,
                            p_transaction_id,
                            p_backend_pid,
                            p_database_oid::text,
                            SESSION_USER
                        )::text,
                        'UTF8'
                    ),
                    signing_key,
                    'sha256'
                ),
                'hex'
            )
        );
    END IF;
"""
    lifecycle_declaration = (
        "    session_is_active boolean;\n"
        if enforce_session_lifecycle
        else ""
    )
    _execute(
        rf"""
CREATE OR REPLACE FUNCTION mata_private.context_signature(
    p_subject_type text,
    p_subject_id uuid,
    p_app_role text,
    p_admin_level text,
    p_programme_scope text[],
    p_posting_code text,
    p_app_session_id uuid,
    p_authorization_fingerprint text,
    p_transaction_id bigint,
    p_backend_pid integer,
    p_database_oid oid
)
RETURNS text
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    signing_key bytea;
{lifecycle_declaration}BEGIN
    SELECT key_material
    INTO STRICT signing_key
    FROM mata_private.context_signing_key
    WHERE singleton;

{active_guard}
    RETURN pg_catalog.lower(
        pg_catalog.encode(
            public.hmac(
                pg_catalog.convert_to(
                    pg_catalog.jsonb_build_array(
                        p_subject_type,
                        p_subject_id::text,
                        p_app_role,
                        COALESCE(p_admin_level, ''),
                        mata_private.normalized_scope(p_programme_scope),
                        COALESCE(p_posting_code, ''),
                        p_app_session_id::text,
                        p_authorization_fingerprint,
                        p_transaction_id,
                        p_backend_pid,
                        p_database_oid::text,
                        SESSION_USER
                    )::text,
                    'UTF8'
                ),
                signing_key,
                'sha256'
            ),
            'hex'
        )
    );
END
$function$;
"""
    )


def _create_minimum_session_helpers() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.issue_staff_app_session_lifecycle(
    p_expected_user_id uuid,
    p_upstream_subject_id uuid,
    p_expected_generation bigint,
    p_session_id uuid,
    p_token_digest bytea,
    p_csrf_token_digest bytea,
    p_idle_timeout_seconds integer,
    p_absolute_timeout_seconds integer,
    p_user_agent_hash bytea
)
RETURNS TABLE (
    id uuid,
    subject_type text,
    subject_id uuid,
    subject_session_generation bigint,
    session_family_id uuid,
    auth_source text
)
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT
        issued.id,
        issued.subject_type,
        issued.subject_id,
        issued.subject_session_generation,
        issued.session_family_id,
        issued.auth_source
    FROM mata_rls.issue_staff_app_session(
        p_expected_user_id,
        p_upstream_subject_id,
        p_expected_generation,
        p_session_id,
        p_token_digest,
        p_csrf_token_digest,
        p_idle_timeout_seconds,
        p_absolute_timeout_seconds,
        p_user_agent_hash
    ) AS issued
$function$;

CREATE FUNCTION mata_rls.issue_resident_app_session_lifecycle(
    p_normalized_mcr text,
    p_expected_subject_type text,
    p_expected_resident_id uuid,
    p_expected_generation bigint,
    p_session_id uuid,
    p_token_digest bytea,
    p_csrf_token_digest bytea,
    p_idle_timeout_seconds integer,
    p_absolute_timeout_seconds integer,
    p_user_agent_hash bytea
)
RETURNS TABLE (
    id uuid,
    subject_type text,
    subject_id uuid,
    subject_session_generation bigint,
    session_family_id uuid,
    auth_source text
)
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT
        issued.id,
        issued.subject_type,
        issued.subject_id,
        issued.subject_session_generation,
        issued.session_family_id,
        issued.auth_source
    FROM mata_rls.issue_resident_app_session(
        p_normalized_mcr,
        p_expected_subject_type,
        p_expected_resident_id,
        p_expected_generation,
        p_session_id,
        p_token_digest,
        p_csrf_token_digest,
        p_idle_timeout_seconds,
        p_absolute_timeout_seconds,
        p_user_agent_hash
    ) AS issued
$function$;

CREATE FUNCTION mata_rls.issue_external_resident_app_session_lifecycle(
    p_normalized_mcr text,
    p_expected_subject_type text,
    p_expected_resident_id uuid,
    p_expected_generation bigint,
    p_session_id uuid,
    p_token_digest bytea,
    p_csrf_token_digest bytea,
    p_idle_timeout_seconds integer,
    p_absolute_timeout_seconds integer,
    p_user_agent_hash bytea
)
RETURNS TABLE (
    id uuid,
    subject_type text,
    subject_id uuid,
    subject_session_generation bigint,
    session_family_id uuid,
    auth_source text
)
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT
        issued.id,
        issued.subject_type,
        issued.subject_id,
        issued.subject_session_generation,
        issued.session_family_id,
        issued.auth_source
    FROM mata_rls.issue_external_resident_app_session(
        p_normalized_mcr,
        p_expected_subject_type,
        p_expected_resident_id,
        p_expected_generation,
        p_session_id,
        p_token_digest,
        p_csrf_token_digest,
        p_idle_timeout_seconds,
        p_absolute_timeout_seconds,
        p_user_agent_hash
    ) AS issued
$function$;

CREATE FUNCTION mata_rls.resolve_app_session_lifecycle(
    p_token_digest bytea,
    p_rotation_threshold_seconds integer
)
RETURNS TABLE (
    id uuid,
    subject_type text,
    subject_id uuid,
    subject_session_generation bigint,
    session_family_id uuid,
    auth_source text,
    authorization_fingerprint text,
    app_role text,
    admin_level text,
    programme_scope text[],
    posting_code text,
    current_staff_actor_name text,
    session_refresh_required boolean
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF p_rotation_threshold_seconds IS NULL
       OR p_rotation_threshold_seconds < 1
       OR p_rotation_threshold_seconds > 604800
    THEN
        RETURN;
    END IF;

    RETURN QUERY
    SELECT
        hydrated.session_id,
        hydrated.subject_type,
        hydrated.subject_id,
        hydrated.subject_session_generation,
        hydrated.session_family_id,
        hydrated.auth_source,
        hydrated.authorization_fingerprint,
        hydrated.app_role,
        hydrated.admin_level,
        hydrated.programme_scope,
        hydrated.posting_code,
        hydrated.current_staff_actor_name,
        pg_catalog.clock_timestamp() >= (
            hydrated.created_at
            + pg_catalog.make_interval(
                secs => p_rotation_threshold_seconds::double precision
            )
        )
    FROM mata_private.hydrate_app_session(
        p_token_digest,
        'shared',
        false,
        0
    ) AS hydrated;
END
$function$;

CREATE FUNCTION mata_rls.touch_app_session_lifecycle(
    p_token_digest bytea,
    p_expected_session_id uuid,
    p_idle_timeout_seconds integer,
    p_touch_interval_seconds integer
)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    hydrated record;
    locked_session record;
    observed_at timestamptz;
BEGIN
    IF p_expected_session_id IS NULL
       OR p_token_digest IS NULL
       OR pg_catalog.octet_length(p_token_digest) <> 32
       OR p_idle_timeout_seconds IS NULL
       OR p_idle_timeout_seconds < 1
       OR p_idle_timeout_seconds > 86400
       OR p_touch_interval_seconds IS NULL
       OR p_touch_interval_seconds < 1
       OR p_touch_interval_seconds >= p_idle_timeout_seconds
    THEN
        RETURN false;
    END IF;

    -- Hydration acquires the reviewed subject and shared family locks before
    -- this helper takes the session row lock.
    SELECT *
    INTO hydrated
    FROM mata_private.hydrate_app_session(
        p_token_digest,
        'shared',
        false,
        0
    );

    IF NOT FOUND OR hydrated.session_id <> p_expected_session_id THEN
        RETURN false;
    END IF;

    SELECT app_session.*
    INTO locked_session
    FROM public.app_sessions AS app_session
    WHERE app_session.id = hydrated.session_id
      AND app_session.token_digest = p_token_digest
      AND app_session.subject_type = hydrated.subject_type
      AND app_session.subject_id = hydrated.subject_id
      AND app_session.subject_session_generation
            = hydrated.subject_session_generation
      AND app_session.session_family_id = hydrated.session_family_id
      AND app_session.auth_source = hydrated.auth_source
    FOR UPDATE;

    observed_at := pg_catalog.clock_timestamp();
    IF NOT FOUND
       OR locked_session.revoked_at IS NOT NULL
       OR observed_at >= locked_session.idle_expires_at
       OR observed_at >= locked_session.absolute_expires_at
    THEN
        RETURN false;
    END IF;

    IF observed_at >= (
        locked_session.last_seen_at
        + pg_catalog.make_interval(
            secs => p_touch_interval_seconds::double precision
        )
    ) THEN
        UPDATE public.app_sessions AS app_session
        SET
            last_seen_at = observed_at,
            idle_expires_at = LEAST(
                observed_at
                    + pg_catalog.make_interval(
                        secs => p_idle_timeout_seconds::double precision
                    ),
                app_session.absolute_expires_at
            )
        WHERE app_session.id = locked_session.id;
    END IF;

    RETURN true;
END
$function$;

CREATE FUNCTION mata_rls.validate_app_session_csrf(
    p_token_digest bytea,
    p_expected_session_id uuid,
    p_csrf_token_digest bytea
)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    hydrated record;
BEGIN
    IF p_expected_session_id IS NULL
       OR p_token_digest IS NULL
       OR pg_catalog.octet_length(p_token_digest) <> 32
       OR p_csrf_token_digest IS NULL
       OR pg_catalog.octet_length(p_csrf_token_digest) <> 32
    THEN
        RETURN false;
    END IF;

    SELECT *
    INTO hydrated
    FROM mata_private.hydrate_app_session(
        p_token_digest,
        'shared',
        false,
        0
    );

    IF NOT FOUND OR hydrated.session_id <> p_expected_session_id THEN
        RETURN NULL;
    END IF;
    RETURN hydrated.csrf_token_digest = p_csrf_token_digest;
END
$function$;

CREATE FUNCTION mata_rls.rotate_app_session_lifecycle(
    p_old_token_digest bytea,
    p_expected_parent_session_id uuid,
    p_new_session_id uuid,
    p_new_token_digest bytea,
    p_new_csrf_token_digest bytea,
    p_idle_timeout_seconds integer,
    p_new_user_agent_hash bytea
)
RETURNS TABLE (
    id uuid,
    subject_type text,
    subject_id uuid,
    subject_session_generation bigint,
    session_family_id uuid,
    auth_source text,
    rotated_from_session_id uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    rotated record;
    bounded record;
BEGIN
    SELECT *
    INTO rotated
    FROM mata_rls.rotate_app_session(
        p_old_token_digest,
        p_expected_parent_session_id,
        p_new_session_id,
        p_new_token_digest,
        p_new_csrf_token_digest,
        p_idle_timeout_seconds,
        p_new_user_agent_hash
    );
    IF NOT FOUND THEN
        RETURN;
    END IF;

    UPDATE public.app_sessions AS child
    SET
        last_seen_at = parent.last_seen_at,
        idle_expires_at = LEAST(
            child.idle_expires_at,
            parent.idle_expires_at
        )
    FROM public.app_sessions AS parent
    WHERE child.id = rotated.id
      AND parent.id = rotated.rotated_from_session_id
    RETURNING child.*
    INTO bounded;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    id := bounded.id;
    subject_type := bounded.subject_type;
    subject_id := bounded.subject_id;
    subject_session_generation := bounded.subject_session_generation;
    session_family_id := bounded.session_family_id;
    auth_source := bounded.auth_source;
    rotated_from_session_id := bounded.rotated_from_session_id;
    RETURN NEXT;
END
$function$;

CREATE FUNCTION mata_rls.revoke_app_session_family_for_logout(
    p_token_digest bytea,
    p_csrf_token_digest bytea,
    p_reason text
)
RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    candidate record;
    locked_proof record;
    current_generation bigint;
    observed_at timestamptz := pg_catalog.clock_timestamp();
    affected_count integer;
BEGIN
    IF p_token_digest IS NULL
       OR pg_catalog.octet_length(p_token_digest) <> 32
       OR p_csrf_token_digest IS NULL
       OR pg_catalog.octet_length(p_csrf_token_digest) <> 32
    THEN
        RETURN 0;
    END IF;

    -- This helper is termination-only. The caller cannot supply a subject,
    -- session id, or family id. Normally both digests locate the same active
    -- or rotated row. A stale browser tab may instead present the active child
    -- cookie with a retained CSRF value from a rotated ancestor; accept that
    -- mixed proof only when both rows have the same immutable subject,
    -- generation, family, and auth source.
    SELECT
        token_session.id AS token_session_id,
        csrf_session.id AS csrf_session_id,
        token_session.subject_type,
        token_session.subject_id,
        token_session.subject_session_generation,
        token_session.session_family_id,
        token_session.auth_source
    INTO candidate
    FROM public.app_sessions AS token_session
    JOIN public.app_sessions AS csrf_session
      ON csrf_session.subject_type = token_session.subject_type
     AND csrf_session.subject_id = token_session.subject_id
     AND csrf_session.subject_session_generation
            = token_session.subject_session_generation
     AND csrf_session.session_family_id = token_session.session_family_id
     AND csrf_session.auth_source = token_session.auth_source
    WHERE token_session.token_digest = p_token_digest
      AND csrf_session.csrf_token_digest = p_csrf_token_digest
      AND observed_at < token_session.absolute_expires_at
      AND observed_at < csrf_session.absolute_expires_at
      AND (
            (
                token_session.id = csrf_session.id
                AND (
                    (
                        token_session.revoked_at IS NULL
                        AND observed_at < token_session.idle_expires_at
                    )
                    OR (
                        token_session.revoked_at IS NOT NULL
                        AND token_session.revoked_reason = 'rotated'
                    )
                )
            )
            OR (
                token_session.id <> csrf_session.id
                AND token_session.revoked_at IS NULL
                AND observed_at < token_session.idle_expires_at
                AND csrf_session.revoked_at IS NOT NULL
                AND csrf_session.revoked_reason = 'rotated'
            )
      );

    IF NOT FOUND THEN
        RETURN 0;
    END IF;

    -- Match the global lifecycle lock order: subject -> family -> session.
    -- The subject lock also serializes this termination proof with account
    -- invalidation and refresh rotation.
    IF candidate.subject_type = 'staff' THEN
        SELECT staff.session_generation
        INTO current_generation
        FROM public.users AS staff
        WHERE staff.id = candidate.subject_id
          AND staff.role IN ('admin', 'secretary')
          AND staff.is_active
          AND NOT staff.session_issuance_blocked
        FOR UPDATE;
    ELSIF candidate.subject_type = 'resident' THEN
        SELECT resident.session_generation
        INTO current_generation
        FROM public.residents AS resident
        WHERE resident.id = candidate.subject_id
          AND resident.status = 'active'
        FOR UPDATE;
    ELSIF candidate.subject_type = 'external_resident' THEN
        SELECT external_resident.session_generation
        INTO current_generation
        FROM public.external_residents AS external_resident
        WHERE external_resident.id = candidate.subject_id
          AND external_resident.status = 'active'
        FOR UPDATE;
    ELSE
        RETURN 0;
    END IF;

    IF NOT FOUND
       OR current_generation IS NULL
       OR current_generation <> candidate.subject_session_generation
    THEN
        RETURN 0;
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        mata_rls.uuid_advisory_key(candidate.session_family_id)
    );

    -- A refresh may have committed while this request was resolving. Recheck
    -- both proof rows after the exclusive family lock. A descendant may have
    -- slid its idle deadline beyond an ancestor's inherited idle deadline,
    -- but never beyond the immutable family absolute expiry.
    observed_at := pg_catalog.clock_timestamp();
    SELECT
        token_session.id AS token_session_id,
        token_session.revoked_at AS token_revoked_at,
        token_session.revoked_reason AS token_revoked_reason,
        token_session.idle_expires_at AS token_idle_expires_at,
        token_session.absolute_expires_at AS token_absolute_expires_at,
        csrf_session.id AS csrf_session_id,
        csrf_session.revoked_at AS csrf_revoked_at,
        csrf_session.revoked_reason AS csrf_revoked_reason,
        csrf_session.absolute_expires_at AS csrf_absolute_expires_at
    INTO locked_proof
    FROM public.app_sessions AS token_session
    JOIN public.app_sessions AS csrf_session
      ON csrf_session.subject_type = token_session.subject_type
     AND csrf_session.subject_id = token_session.subject_id
     AND csrf_session.subject_session_generation
            = token_session.subject_session_generation
     AND csrf_session.session_family_id = token_session.session_family_id
     AND csrf_session.auth_source = token_session.auth_source
    WHERE token_session.id = candidate.token_session_id
      AND csrf_session.id = candidate.csrf_session_id
      AND token_session.token_digest = p_token_digest
      AND csrf_session.csrf_token_digest = p_csrf_token_digest
      AND token_session.subject_type = candidate.subject_type
      AND token_session.subject_id = candidate.subject_id
      AND token_session.subject_session_generation = current_generation
      AND token_session.session_family_id = candidate.session_family_id
      AND token_session.auth_source = candidate.auth_source
      AND observed_at < token_session.absolute_expires_at
      AND observed_at < csrf_session.absolute_expires_at
      AND (
            (
                token_session.id = csrf_session.id
                AND (
                    (
                        token_session.revoked_at IS NULL
                        AND observed_at < token_session.idle_expires_at
                    )
                    OR (
                        token_session.revoked_at IS NOT NULL
                        AND token_session.revoked_reason = 'rotated'
                    )
                )
            )
            OR (
                token_session.id <> csrf_session.id
                AND token_session.revoked_at IS NULL
                AND observed_at < token_session.idle_expires_at
                AND csrf_session.revoked_at IS NOT NULL
                AND csrf_session.revoked_reason = 'rotated'
            )
      )
    FOR UPDATE OF token_session, csrf_session;

    IF NOT FOUND THEN
        RETURN 0;
    END IF;

    observed_at := pg_catalog.clock_timestamp();
    IF observed_at >= locked_proof.token_absolute_expires_at
       OR observed_at >= locked_proof.csrf_absolute_expires_at
       OR NOT (
            (
                locked_proof.token_session_id = locked_proof.csrf_session_id
                AND (
                    (
                        locked_proof.token_revoked_at IS NULL
                        AND observed_at < locked_proof.token_idle_expires_at
                    )
                    OR (
                        locked_proof.token_revoked_at IS NOT NULL
                        AND locked_proof.token_revoked_reason = 'rotated'
                    )
                )
            )
            OR (
                locked_proof.token_session_id <> locked_proof.csrf_session_id
                AND locked_proof.token_revoked_at IS NULL
                AND observed_at < locked_proof.token_idle_expires_at
                AND locked_proof.csrf_revoked_at IS NOT NULL
                AND locked_proof.csrf_revoked_reason = 'rotated'
            )
       )
    THEN
        RETURN 0;
    END IF;

    UPDATE public.app_sessions AS app_session
    SET
        revoked_at = observed_at,
        revoked_reason = COALESCE(
            NULLIF(pg_catalog.btrim(p_reason), ''),
            'logout'
        )
    WHERE app_session.session_family_id = candidate.session_family_id
      AND app_session.subject_type = candidate.subject_type
      AND app_session.subject_id = candidate.subject_id
      AND app_session.subject_session_generation
            = current_generation
      AND app_session.auth_source = candidate.auth_source
      AND app_session.revoked_at IS NULL;
    GET DIAGNOSTICS affected_count = ROW_COUNT;
    RETURN affected_count;
END
$function$;
"""
    )


def _replace_cleanup_helper(*, protect_rotated_logout_proof: bool) -> None:
    cleanup_predicate = r"""(
                app_session.revoked_at IS NOT NULL
                AND app_session.revoked_at <= cutoff
              )
           OR app_session.idle_expires_at <= cutoff
           OR app_session.absolute_expires_at <= cutoff"""
    if protect_rotated_logout_proof:
        cleanup_predicate = rf"""(
{cleanup_predicate}
        )
          AND (
                app_session.revoked_at IS NULL
                OR app_session.revoked_reason IS DISTINCT FROM 'rotated'
                OR app_session.absolute_expires_at
                    <= pg_catalog.clock_timestamp()
          )"""

    _execute(
        rf"""
CREATE OR REPLACE FUNCTION mata_rls.cleanup_app_sessions(
    p_retention_seconds integer,
    p_batch_size integer
)
RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    affected_count integer;
    cutoff timestamptz;
BEGIN
    IF p_retention_seconds IS NULL
       OR p_retention_seconds < 0
       OR p_retention_seconds > 31536000
       OR p_batch_size IS NULL
       OR p_batch_size < 1
       OR p_batch_size > 1000
    THEN
        RAISE EXCEPTION 'Invalid application-session cleanup bounds'
            USING ERRCODE = '22023';
    END IF;
    cutoff := (
        pg_catalog.clock_timestamp()
        - pg_catalog.make_interval(
            secs => p_retention_seconds::double precision
        )
    );

    WITH cleanup_candidates AS (
        SELECT app_session.id
        FROM public.app_sessions AS app_session
        WHERE {cleanup_predicate}
        ORDER BY
            LEAST(
                COALESCE(
                    app_session.revoked_at,
                    app_session.absolute_expires_at
                ),
                app_session.idle_expires_at,
                app_session.absolute_expires_at
            ),
            app_session.id
        LIMIT p_batch_size
        FOR UPDATE SKIP LOCKED
    )
    DELETE FROM public.app_sessions AS app_session
    USING cleanup_candidates
    WHERE app_session.id = cleanup_candidates.id;
    GET DIAGNOSTICS affected_count = ROW_COUNT;
    RETURN affected_count;
END
$function$
"""
    )


def _set_helper_acl(*, upgrade: bool) -> None:
    old_functions = (
        OLD_RUNTIME_FUNCTIONS + OLD_AUTH_FUNCTIONS + OLD_SHARED_FUNCTIONS
    )
    new_functions = (
        NEW_RUNTIME_FUNCTIONS + NEW_AUTH_FUNCTIONS + NEW_SHARED_FUNCTIONS
    )
    if upgrade:
        _strip_non_owner_helper_acl(old_functions + new_functions)
        for signature in NEW_RUNTIME_FUNCTIONS:
            _execute(
                f"GRANT EXECUTE ON FUNCTION mata_rls.{signature} "
                f"TO {RUNTIME_ROLE}"
            )
        for signature in NEW_AUTH_FUNCTIONS:
            _execute(
                f"GRANT EXECUTE ON FUNCTION mata_rls.{signature} "
                f"TO {AUTH_ROLE}"
            )
        for signature in NEW_SHARED_FUNCTIONS:
            _execute(
                f"GRANT EXECUTE ON FUNCTION mata_rls.{signature} "
                f"TO {RUNTIME_ROLE}, {AUTH_ROLE}"
            )
        return

    _strip_non_owner_helper_acl(old_functions)
    for signature in OLD_RUNTIME_FUNCTIONS:
        _execute(
            f"GRANT EXECUTE ON FUNCTION mata_rls.{signature} "
            f"TO {RUNTIME_ROLE}"
        )
    for signature in OLD_AUTH_FUNCTIONS:
        _execute(
            f"GRANT EXECUTE ON FUNCTION mata_rls.{signature} "
            f"TO {AUTH_ROLE}"
        )
    for signature in OLD_SHARED_FUNCTIONS:
        _execute(
            f"GRANT EXECUTE ON FUNCTION mata_rls.{signature} "
            f"TO {RUNTIME_ROLE}, {AUTH_ROLE}"
        )


def _strip_non_owner_helper_acl(signatures: tuple[str, ...]) -> None:
    """Remove default, inherited-by-grant, and drifted helper ACL entries."""

    for signature in signatures:
        _execute(
            f"REVOKE ALL PRIVILEGES ON FUNCTION mata_rls.{signature} "
            "FROM PUBLIC CASCADE"
        )
        escaped_signature = signature.replace("'", "''")
        _execute(
            rf"""
DO $migration$
DECLARE
    grantee_role text;
BEGIN
    FOR grantee_role IN
        SELECT role.rolname
        FROM pg_catalog.pg_proc AS procedure
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                procedure.proacl,
                pg_catalog.acldefault('f', procedure.proowner)
            )
        ) AS acl
        JOIN pg_catalog.pg_roles AS role
          ON role.oid = acl.grantee
        WHERE procedure.oid = pg_catalog.to_regprocedure(
            'mata_rls.{escaped_signature}'
        )
          AND acl.grantee <> procedure.proowner
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE ALL PRIVILEGES ON FUNCTION mata_rls.{signature} '
            'FROM %I CASCADE',
            grantee_role
        );
    END LOOP;
END
$migration$
"""
        )


def _assert_new_helper_security() -> None:
    _execute(
        r"""
DO $migration$
DECLARE
    unsafe_helper text;
    browser_role text;
BEGIN
    SELECT required.signature
    INTO unsafe_helper
    FROM (
        VALUES
            ('issue_staff_app_session_lifecycle(uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)', false, true),
            ('issue_resident_app_session_lifecycle(text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)', false, true),
            ('issue_external_resident_app_session_lifecycle(text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)', false, true),
            ('resolve_app_session_lifecycle(bytea,integer)', true, true),
            ('touch_app_session_lifecycle(bytea,uuid,integer,integer)', true, true),
            ('validate_app_session_csrf(bytea,uuid,bytea)', true, true),
            ('rotate_app_session_lifecycle(bytea,uuid,uuid,bytea,bytea,integer,bytea)', true, false),
            ('revoke_app_session_family_for_logout(bytea,bytea,text)', false, true)
    ) AS required(signature, runtime_allowed, auth_allowed)
    LEFT JOIN pg_catalog.pg_proc AS procedure
      ON procedure.oid = pg_catalog.to_regprocedure(
          'mata_rls.' || required.signature
      )
    LEFT JOIN pg_catalog.pg_roles AS owner_role
      ON owner_role.oid = procedure.proowner
    WHERE procedure.oid IS NULL
       OR NOT procedure.prosecdef
       OR procedure.proconfig
            IS DISTINCT FROM ARRAY['search_path=pg_catalog, pg_temp']::text[]
       OR owner_role.rolname IN (
            'mata_app_runtime',
            'mata_auth_internal',
            'anon',
            'authenticated',
            'service_role'
       )
       OR required.runtime_allowed IS DISTINCT FROM EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(
                    procedure.proacl,
                    pg_catalog.acldefault('f', procedure.proowner)
                )
            ) AS acl
            JOIN pg_catalog.pg_roles AS grantee_role
              ON grantee_role.oid = acl.grantee
            WHERE grantee_role.rolname = 'mata_app_runtime'
              AND acl.privilege_type = 'EXECUTE'
              AND NOT acl.is_grantable
       )
       OR required.auth_allowed IS DISTINCT FROM EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(
                    procedure.proacl,
                    pg_catalog.acldefault('f', procedure.proowner)
                )
            ) AS acl
            JOIN pg_catalog.pg_roles AS grantee_role
              ON grantee_role.oid = acl.grantee
            WHERE grantee_role.rolname = 'mata_auth_internal'
              AND acl.privilege_type = 'EXECUTE'
              AND NOT acl.is_grantable
       )
       OR EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(
                    procedure.proacl,
                    pg_catalog.acldefault('f', procedure.proowner)
                )
            ) AS acl
            LEFT JOIN pg_catalog.pg_roles AS grantee_role
              ON grantee_role.oid = acl.grantee
            WHERE acl.privilege_type = 'EXECUTE'
              AND acl.grantee <> procedure.proowner
              AND NOT (
                    required.runtime_allowed
                    AND grantee_role.rolname = 'mata_app_runtime'
                    AND NOT acl.is_grantable
              )
              AND NOT (
                    required.auth_allowed
                    AND grantee_role.rolname = 'mata_auth_internal'
                    AND NOT acl.is_grantable
              )
       )
    ORDER BY required.signature
    LIMIT 1;

    IF unsafe_helper IS NOT NULL THEN
        RAISE EXCEPTION
            'Unsafe session-lifecycle helper: %',
            unsafe_helper
            USING ERRCODE = '42501';
    END IF;

    SELECT retired.signature
    INTO unsafe_helper
    FROM (
        VALUES
            ('issue_staff_app_session(uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)'),
            ('issue_resident_app_session(text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)'),
            ('issue_external_resident_app_session(text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)'),
            ('resolve_app_session(bytea,boolean,integer)'),
            ('rotate_app_session(bytea,uuid,uuid,bytea,bytea,integer,bytea)')
    ) AS retired(signature)
    LEFT JOIN pg_catalog.pg_proc AS procedure
      ON procedure.oid = pg_catalog.to_regprocedure(
          'mata_rls.' || retired.signature
      )
    WHERE procedure.oid IS NULL
       OR EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(
                    procedure.proacl,
                    pg_catalog.acldefault('f', procedure.proowner)
                )
            ) AS acl
            WHERE acl.grantee <> procedure.proowner
       )
    ORDER BY retired.signature
    LIMIT 1;

    IF unsafe_helper IS NOT NULL THEN
        RAISE EXCEPTION
            'Retired session helper remains callable: %',
            unsafe_helper
            USING ERRCODE = '42501';
    END IF;

    FOREACH browser_role IN ARRAY ARRAY[
        'anon',
        'authenticated',
        'service_role'
    ]
    LOOP
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_roles
            WHERE rolname = browser_role
        ) AND EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS procedure
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            WHERE namespace.nspname = 'mata_rls'
              AND procedure.proname LIKE '%app_session%'
              AND pg_catalog.has_function_privilege(
                    browser_role,
                    procedure.oid,
                    'EXECUTE'
              )
        ) THEN
            RAISE EXCEPTION
                'Browser/service role % can execute a session helper',
                browser_role
                USING ERRCODE = '42501';
        END IF;
    END LOOP;
END
$migration$
"""
    )


def upgrade() -> None:
    _replace_context_signature(enforce_session_lifecycle=True)
    _create_minimum_session_helpers()
    _replace_cleanup_helper(protect_rotated_logout_proof=True)
    _set_helper_acl(upgrade=True)
    _assert_new_helper_security()


def downgrade() -> None:
    _set_helper_acl(upgrade=False)
    for signature in reversed(
        NEW_RUNTIME_FUNCTIONS + NEW_AUTH_FUNCTIONS + NEW_SHARED_FUNCTIONS
    ):
        _execute(f"DROP FUNCTION IF EXISTS mata_rls.{signature}")
    _replace_cleanup_helper(protect_rotated_logout_proof=False)
    _replace_context_signature(enforce_session_lifecycle=False)
