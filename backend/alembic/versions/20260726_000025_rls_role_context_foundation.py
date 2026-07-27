"""add RLS role, trusted-context, and narrow helper foundation

Revision ID: 20260726_000025
Revises: 20260722_000024
Create Date: 2026-07-26

This migration deliberately does not create table policies or grant direct
application-table access.  The following revision performs the policy/grant
cutover after these helpers can be exercised independently.
"""

from __future__ import annotations

from alembic import op


revision = "20260726_000025"
down_revision = "20260722_000024"
branch_labels = None
depends_on = None


RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"

RUNTIME_ONLY_FUNCTIONS = (
    "uuid_advisory_key(uuid)",
    "install_request_context(bytea,text,text,uuid,uuid,text)",
    "context_is_valid()",
    "current_subject_type()",
    "current_subject_id()",
    "current_app_role()",
    "current_admin_level()",
    "current_programme_scope()",
    "current_posting_code()",
    "current_app_session_id()",
    "current_authorization_fingerprint()",
    "is_authenticated()",
    "is_master_admin()",
    "has_programme_scope(text)",
    "is_secretary_for_posting(text)",
    "is_native_resident(uuid)",
    "is_external_resident(uuid)",
    "rotate_app_session(bytea,uuid,uuid,bytea,bytea,integer,bytea)",
    "revoke_app_session_family(bytea,uuid,text)",
    "invalidate_subject_app_sessions(text,uuid,text,boolean)",
    "replace_external_resident_schedule(uuid,jsonb)",
    "set_external_resident_current_posting(uuid,text,text)",
    "resolve_ttf_session_type(text,numeric,text,text)",
    "ensure_ttf_posting_code(text,text)",
    "append_audit_log(text,text,text,jsonb,jsonb,jsonb)",
    "update_own_staff_actor_name(text)",
    "reporting_period_dependency_counts(uuid)",
    "hibernate_stale_surplus(uuid)",
)

AUTH_ONLY_FUNCTIONS = (
    "staff_login_snapshot(text)",
    "staff_login_candidate(text)",
    "staff_login_identity(uuid,uuid,bigint)",
    "resident_login_candidate(text)",
    "issue_staff_app_session(uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)",
    "issue_resident_app_session(text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)",
    "issue_external_resident_app_session(text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)",
    "external_registration_options()",
    "register_external_resident(text,text,text,jsonb)",
)

SHARED_FUNCTIONS = (
    "resolve_app_session(bytea,boolean,integer)",
    "revoke_app_session(bytea,uuid,text)",
    "cleanup_app_sessions(integer,integer)",
    "consume_rate_limit(text,text,integer,integer,integer,integer)",
)

PRIVATE_FUNCTIONS = (
    "normalized_scope(text[])",
    "normalize_mcr(text)",
    "authorization_fingerprint(text,uuid,bigint,text,text,text[],text,uuid,text)",
    "context_signature(text,uuid,text,text,text[],text,uuid,text,bigint,integer,oid)",
    "verified_context()",
    "hydrate_app_session(bytea,text,boolean,integer)",
    "mcr_advisory_key(text)",
    "enforce_global_mcr_uniqueness()",
    "insert_root_app_session(text,uuid,bigint,text,uuid,bytea,bytea,integer,integer,bytea)",
    "resolve_external_schedule(jsonb)",
)


def _execute(statement: str) -> None:
    # These definitions contain PostgreSQL casts and PL/pgSQL bodies.  Driver
    # SQL avoids treating their colon/cast syntax as SQLAlchemy bind markers.
    # ``no_parameters`` is also required because psycopg otherwise interprets
    # PL/pgSQL RAISE/format percent tokens as DBAPI placeholders.
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(statement)


def _create_roles_and_schemas() -> None:
    _execute(
        r"""
DO $migration$
DECLARE
    role_name text;
    role_row record;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['mata_app_runtime', 'mata_auth_internal']
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_roles
            WHERE rolname = role_name
        ) THEN
            EXECUTE pg_catalog.format(
                'CREATE ROLE %I NOLOGIN NOSUPERUSER NOBYPASSRLS '
                'NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT',
                role_name
            );
        END IF;

        SELECT
            rolcanlogin,
            rolinherit,
            rolsuper,
            rolbypassrls,
            rolcreatedb,
            rolcreaterole,
            rolreplication
        INTO STRICT role_row
        FROM pg_catalog.pg_roles
        WHERE rolname = role_name;

        IF role_row.rolcanlogin
           OR role_row.rolinherit
           OR role_row.rolsuper
           OR role_row.rolbypassrls
           OR role_row.rolcreatedb
           OR role_row.rolcreaterole
           OR role_row.rolreplication
        THEN
            RAISE EXCEPTION
                'Unsafe pre-existing role attributes for %',
                role_name
                USING ERRCODE = '42501';
        END IF;

        -- A helper group may have deployment LOGIN members, but it must not
        -- itself inherit or SET ROLE into any other privilege-bearing role.
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_auth_members membership
            JOIN pg_catalog.pg_roles member_role
              ON member_role.oid = membership.member
            WHERE member_role.rolname = role_name
        ) THEN
            RAISE EXCEPTION
                'Role % must not be a member of another role',
                role_name
                USING ERRCODE = '42501';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid = relation.relnamespace
            JOIN pg_catalog.pg_roles owner_role
              ON owner_role.oid = relation.relowner
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p', 'v', 'm', 'S')
              AND owner_role.rolname = role_name
        ) THEN
            RAISE EXCEPTION
                'Role % must not own public application objects',
                role_name
                USING ERRCODE = '42501';
        END IF;
    END LOOP;
END
$migration$;
"""
    )

    _execute(
        r"""
DO $migration$
DECLARE
    unsafe_function text;
BEGIN
    SELECT required.signature
    INTO unsafe_function
    FROM (
        VALUES
            ('public.digest(bytea,text)'),
            ('public.hmac(bytea,bytea,text)'),
            ('public.gen_random_bytes(integer)'),
            ('public.gen_random_uuid()')
    ) AS required(signature)
    LEFT JOIN pg_catalog.pg_proc AS procedure
      ON procedure.oid = pg_catalog.to_regprocedure(required.signature)
    LEFT JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = procedure.pronamespace
    LEFT JOIN pg_catalog.pg_roles AS owner_role
      ON owner_role.oid = procedure.proowner
    LEFT JOIN pg_catalog.pg_language AS language
      ON language.oid = procedure.prolang
    LEFT JOIN pg_catalog.pg_depend AS dependency
      ON dependency.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass
     AND dependency.objid = procedure.oid
     AND dependency.deptype = 'e'
    LEFT JOIN pg_catalog.pg_extension AS extension
      ON extension.oid = dependency.refobjid
    WHERE procedure.oid IS NULL
       OR namespace.nspname <> 'public'
       OR extension.extname IS DISTINCT FROM 'pgcrypto'
       OR language.lanname IS DISTINCT FROM 'c'
       OR procedure.prosecdef
       OR owner_role.rolname IN (
           'mata_app_runtime',
           'mata_auth_internal',
           'anon',
           'authenticated',
           'service_role'
       )
    ORDER BY required.signature
    LIMIT 1;

    IF unsafe_function IS NOT NULL THEN
        RAISE EXCEPTION
            'Missing or unsafe reviewed pgcrypto function: %',
            unsafe_function
            USING ERRCODE = '0A000';
    END IF;
END
$migration$;
"""
    )
    _execute(
        "REVOKE EXECUTE ON FUNCTION "
        "public.digest(bytea,text), "
        "public.hmac(bytea,bytea,text), "
        "public.gen_random_bytes(integer), "
        "public.gen_random_uuid() "
        "FROM PUBLIC, mata_app_runtime, mata_auth_internal"
    )
    _execute(
        r"""
DO $migration$
DECLARE
    inaccessible_function text;
BEGIN
    SELECT required.signature
    INTO inaccessible_function
    FROM (
        VALUES
            ('public.digest(bytea,text)'),
            ('public.hmac(bytea,bytea,text)'),
            ('public.gen_random_bytes(integer)'),
            ('public.gen_random_uuid()')
    ) AS required(signature)
    WHERE NOT pg_catalog.has_function_privilege(
        CURRENT_USER,
        pg_catalog.to_regprocedure(required.signature),
        'EXECUTE'
    )
    ORDER BY required.signature
    LIMIT 1;

    IF inaccessible_function IS NOT NULL THEN
        RAISE EXCEPTION
            'Migration owner lacks reviewed pgcrypto EXECUTE: %',
            inaccessible_function
            USING ERRCODE = '42501';
    END IF;
END
$migration$;
"""
    )

    _execute(
        r"""
DO $migration$
DECLARE
    optional_role text;
    capability_role text;
BEGIN
    FOREACH optional_role IN ARRAY ARRAY[
        'anon',
        'authenticated',
        'service_role'
    ]
    LOOP
        IF pg_catalog.to_regrole(optional_role) IS NULL THEN
            CONTINUE;
        END IF;
        FOREACH capability_role IN ARRAY ARRAY[
            'mata_app_runtime',
            'mata_auth_internal'
        ]
        LOOP
            IF pg_catalog.pg_has_role(
                optional_role,
                capability_role,
                'MEMBER'
            ) THEN
                RAISE EXCEPTION
                    'Browser/service role % must not inherit capability %',
                    optional_role,
                    capability_role
                    USING ERRCODE = '42501';
            END IF;
        END LOOP;
    END LOOP;
END
$migration$;
"""
    )

    _execute("CREATE SCHEMA IF NOT EXISTS mata_private")
    _execute("CREATE SCHEMA IF NOT EXISTS mata_rls")
    _execute("REVOKE ALL PRIVILEGES ON SCHEMA mata_private FROM PUBLIC")
    _execute("REVOKE ALL PRIVILEGES ON SCHEMA mata_rls FROM PUBLIC")
    _execute("REVOKE ALL PRIVILEGES ON SCHEMA mata_private FROM mata_app_runtime")
    _execute("REVOKE ALL PRIVILEGES ON SCHEMA mata_private FROM mata_auth_internal")
    _execute("GRANT USAGE ON SCHEMA mata_rls TO mata_app_runtime")
    _execute("GRANT USAGE ON SCHEMA mata_rls TO mata_auth_internal")

    _execute(
        r"""
DO $migration$
DECLARE
    schema_name text;
BEGIN
    FOREACH schema_name IN ARRAY ARRAY['mata_private', 'mata_rls']
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_namespace namespace
            JOIN pg_catalog.pg_roles owner_role
              ON owner_role.oid = namespace.nspowner
            WHERE namespace.nspname = schema_name
              AND owner_role.rolname = CURRENT_USER
        ) THEN
            RAISE EXCEPTION
                'Schema % must be owned by the migration role',
                schema_name
                USING ERRCODE = '42501';
        END IF;
    END LOOP;
END
$migration$;
"""
    )


def _create_private_context_foundation() -> None:
    _execute(
        r"""
CREATE TABLE mata_private.context_signing_key (
    singleton boolean PRIMARY KEY DEFAULT true,
    key_material bytea NOT NULL,
    CONSTRAINT ck_mata_context_signing_key_singleton
        CHECK (singleton),
    CONSTRAINT ck_mata_context_signing_key_length
        CHECK (pg_catalog.octet_length(key_material) = 32)
)
"""
    )
    _execute(
        r"""
INSERT INTO mata_private.context_signing_key (singleton, key_material)
VALUES (true, public.gen_random_bytes(32))
"""
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON mata_private.context_signing_key FROM PUBLIC"
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON mata_private.context_signing_key "
        "FROM mata_app_runtime, mata_auth_internal"
    )

    _execute(
        r"""
CREATE FUNCTION mata_private.normalized_scope(p_scope text[])
RETURNS text[]
LANGUAGE sql
IMMUTABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT COALESCE(
        pg_catalog.array_agg(scope_value ORDER BY scope_value),
        ARRAY[]::text[]
    )
    FROM (
        SELECT DISTINCT pg_catalog.upper(pg_catalog.btrim(raw_value)) AS scope_value
        FROM pg_catalog.unnest(COALESCE(p_scope, ARRAY[]::text[])) AS raw(raw_value)
        WHERE pg_catalog.btrim(raw_value) <> ''
    ) AS normalized
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_private.normalize_mcr(p_mcr text)
RETURNS text
LANGUAGE sql
IMMUTABLE
STRICT
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT pg_catalog.upper(pg_catalog.btrim(p_mcr))
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.uuid_advisory_key(p_value uuid)
RETURNS bigint
LANGUAGE plpgsql
IMMUTABLE
STRICT
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    value_bytes bytea := pg_catalog.uuid_send(p_value);
    folded_value numeric := 0;
    byte_index integer;
BEGIN
    -- This is exactly the Python app_sessions.py fold: XOR the two UUID
    -- 64-bit halves byte-for-byte, then reinterpret the result as int64.
    FOR byte_index IN 0..7
    LOOP
        folded_value := (
            folded_value * 256
            + (
                pg_catalog.get_byte(value_bytes, byte_index)
                # pg_catalog.get_byte(value_bytes, byte_index + 8)
            )
        );
    END LOOP;

    IF folded_value >= 9223372036854775808::numeric THEN
        folded_value := folded_value - 18446744073709551616::numeric;
    END IF;
    RETURN folded_value::bigint;
END
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_private.authorization_fingerprint(
    p_subject_type text,
    p_subject_id uuid,
    p_subject_session_generation bigint,
    p_app_role text,
    p_admin_level text,
    p_programme_scope text[],
    p_posting_code text,
    p_app_session_id uuid,
    p_auth_source text
)
RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT pg_catalog.lower(
        pg_catalog.encode(
            public.digest(
                pg_catalog.convert_to(
                    pg_catalog.jsonb_build_array(
                        p_subject_type,
                        p_subject_id::text,
                        p_subject_session_generation,
                        p_app_role,
                        COALESCE(p_admin_level, ''),
                        mata_private.normalized_scope(p_programme_scope),
                        COALESCE(p_posting_code, ''),
                        p_app_session_id::text,
                        p_auth_source
                    )::text,
                    'UTF8'
                ),
                'sha256'
            ),
            'hex'
        )
    )
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_private.context_signature(
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
BEGIN
    SELECT key_material
    INTO STRICT signing_key
    FROM mata_private.context_signing_key
    WHERE singleton;

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
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_private.verified_context()
RETURNS TABLE (
    subject_type text,
    subject_id uuid,
    app_role text,
    admin_level text,
    programme_scope text[],
    posting_code text,
    app_session_id uuid,
    authorization_fingerprint text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    raw_subject_type text;
    raw_subject_id text;
    raw_app_role text;
    raw_admin_level text;
    raw_scope text;
    raw_posting_code text;
    raw_app_session_id text;
    raw_fingerprint text;
    raw_signature text;
    parsed_scope text[];
    expected_signature text;
    database_oid oid;
BEGIN
    raw_subject_type := pg_catalog.current_setting('mata.subject_type', true);
    raw_subject_id := pg_catalog.current_setting('mata.subject_id', true);
    raw_app_role := pg_catalog.current_setting('mata.app_role', true);
    raw_admin_level := pg_catalog.current_setting('mata.admin_level', true);
    raw_scope := pg_catalog.current_setting('mata.programme_scope_json', true);
    raw_posting_code := pg_catalog.current_setting('mata.posting_code', true);
    raw_app_session_id := pg_catalog.current_setting('mata.app_session_id', true);
    raw_fingerprint := pg_catalog.current_setting(
        'mata.authorization_fingerprint',
        true
    );
    raw_signature := pg_catalog.current_setting('mata.context_signature', true);

    IF raw_subject_type IS NULL
       OR raw_subject_id IS NULL
       OR raw_app_role IS NULL
       OR raw_scope IS NULL
       OR raw_app_session_id IS NULL
       OR raw_fingerprint IS NULL
       OR raw_signature IS NULL
       OR raw_subject_type NOT IN ('staff', 'resident', 'external_resident')
       OR raw_app_role NOT IN ('admin', 'secretary', 'resident', 'external_resident')
       OR raw_fingerprint !~ '^[0-9a-f]{64}$'
       OR raw_signature !~ '^[0-9a-f]{64}$'
    THEN
        RETURN;
    END IF;

    BEGIN
        subject_id := raw_subject_id::uuid;
        app_session_id := raw_app_session_id::uuid;
        SELECT mata_private.normalized_scope(
            COALESCE(
                pg_catalog.array_agg(scope_item),
                ARRAY[]::text[]
            )
        )
        INTO parsed_scope
        FROM pg_catalog.jsonb_array_elements_text(raw_scope::jsonb)
             AS scope_values(scope_item);
    EXCEPTION
        WHEN invalid_text_representation OR invalid_parameter_value THEN
            RETURN;
    END;

    SELECT database.oid
    INTO STRICT database_oid
    FROM pg_catalog.pg_database AS database
    WHERE database.datname = pg_catalog.current_database();

    expected_signature := mata_private.context_signature(
        raw_subject_type,
        subject_id,
        raw_app_role,
        NULLIF(raw_admin_level, ''),
        parsed_scope,
        NULLIF(raw_posting_code, ''),
        app_session_id,
        raw_fingerprint,
        pg_catalog.txid_current(),
        pg_catalog.pg_backend_pid(),
        database_oid
    );

    IF expected_signature <> raw_signature THEN
        RETURN;
    END IF;

    subject_type := raw_subject_type;
    app_role := raw_app_role;
    admin_level := NULLIF(raw_admin_level, '');
    programme_scope := parsed_scope;
    posting_code := NULLIF(raw_posting_code, '');
    authorization_fingerprint := raw_fingerprint;
    RETURN NEXT;
END
$function$
"""
    )


def _create_private_session_hydrator() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_private.hydrate_app_session(
    p_token_digest bytea,
    p_lock_mode text,
    p_touch boolean,
    p_idle_timeout_seconds integer
)
RETURNS TABLE (
    session_id uuid,
    token_digest bytea,
    subject_type text,
    subject_id uuid,
    subject_session_generation bigint,
    session_family_id uuid,
    auth_source text,
    csrf_token_digest bytea,
    created_at timestamptz,
    last_seen_at timestamptz,
    idle_expires_at timestamptz,
    absolute_expires_at timestamptz,
    revoked_at timestamptz,
    revoked_reason text,
    rotated_from_session_id uuid,
    user_agent_hash bytea,
    app_role text,
    admin_level text,
    programme_scope text[],
    posting_code text,
    current_staff_actor_name text,
    authorization_fingerprint text
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    candidate record;
    locked_session record;
    current_generation bigint;
    resolved_app_role text;
    resolved_admin_level text;
    resolved_scope text[] := ARRAY[]::text[];
    resolved_posting text;
    resolved_staff_actor_name text;
    observed_at timestamptz := pg_catalog.clock_timestamp();
BEGIN
    IF p_token_digest IS NULL
       OR pg_catalog.octet_length(p_token_digest) <> 32
       OR p_lock_mode IS NULL
       OR p_lock_mode NOT IN ('shared', 'exclusive')
       OR p_touch IS NULL
       OR (
           p_touch
           AND (
               p_idle_timeout_seconds IS NULL
               OR p_idle_timeout_seconds < 1
               OR p_idle_timeout_seconds > 86400
           )
       )
       OR (NOT p_touch AND COALESCE(p_idle_timeout_seconds, 0) <> 0)
    THEN
        RETURN;
    END IF;

    -- This first read acquires no row lock.  It locates the subject/family so
    -- the actual lock order can remain subject -> family -> session.
    SELECT
        app_session.id,
        app_session.subject_type,
        app_session.subject_id,
        app_session.subject_session_generation,
        app_session.session_family_id,
        app_session.auth_source
    INTO candidate
    FROM public.app_sessions AS app_session
    WHERE app_session.token_digest = p_token_digest
      AND app_session.revoked_at IS NULL
      AND observed_at < app_session.idle_expires_at
      AND observed_at < app_session.absolute_expires_at;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    IF candidate.subject_type = 'staff' THEN
        IF p_lock_mode = 'exclusive' THEN
            PERFORM 1
            FROM public.users AS staff
            WHERE staff.id = candidate.subject_id
              AND staff.role IN ('admin', 'secretary')
              AND staff.is_active
              AND NOT staff.session_issuance_blocked
            FOR UPDATE;
        ELSE
            PERFORM 1
            FROM public.users AS staff
            WHERE staff.id = candidate.subject_id
              AND staff.role IN ('admin', 'secretary')
              AND staff.is_active
              AND NOT staff.session_issuance_blocked
            FOR SHARE;
        END IF;
        IF NOT FOUND THEN
            RETURN;
        END IF;

        SELECT
            staff.session_generation,
            staff.role,
            CASE WHEN staff.role = 'admin' THEN staff.admin_level ELSE NULL END,
            CASE
                WHEN staff.role = 'admin'
                THEN mata_private.normalized_scope(staff.programme_scope)
                ELSE ARRAY[]::text[]
            END,
            CASE WHEN staff.role = 'secretary' THEN staff.posting_code ELSE NULL END,
            NULLIF(pg_catalog.btrim(staff.current_staff_actor_name), '')
        INTO
            current_generation,
            resolved_app_role,
            resolved_admin_level,
            resolved_scope,
            resolved_posting,
            resolved_staff_actor_name
        FROM public.users AS staff
        WHERE staff.id = candidate.subject_id
          AND staff.role IN ('admin', 'secretary')
          AND staff.is_active
          AND NOT staff.session_issuance_blocked;
    ELSIF candidate.subject_type = 'resident' THEN
        IF p_lock_mode = 'exclusive' THEN
            PERFORM 1
            FROM public.residents AS resident
            WHERE resident.id = candidate.subject_id
              AND resident.status = 'active'
            FOR UPDATE;
        ELSE
            PERFORM 1
            FROM public.residents AS resident
            WHERE resident.id = candidate.subject_id
              AND resident.status = 'active'
            FOR SHARE;
        END IF;
        IF NOT FOUND THEN
            RETURN;
        END IF;

        SELECT
            resident.session_generation,
            mata_private.normalized_scope(ARRAY[resident.programme_code])
        INTO current_generation, resolved_scope
        FROM public.residents AS resident
        WHERE resident.id = candidate.subject_id
          AND resident.status = 'active';

        resolved_app_role := 'resident';
        resolved_admin_level := NULL;
        resolved_staff_actor_name := NULL;
        resolved_posting := NULL;
    ELSIF candidate.subject_type = 'external_resident' THEN
        IF p_lock_mode = 'exclusive' THEN
            PERFORM 1
            FROM public.external_residents AS external_resident
            WHERE external_resident.id = candidate.subject_id
              AND external_resident.status = 'active'
            FOR UPDATE;
        ELSE
            PERFORM 1
            FROM public.external_residents AS external_resident
            WHERE external_resident.id = candidate.subject_id
              AND external_resident.status = 'active'
            FOR SHARE;
        END IF;
        IF NOT FOUND THEN
            RETURN;
        END IF;

        SELECT external_resident.session_generation
        INTO current_generation
        FROM public.external_residents AS external_resident
        WHERE external_resident.id = candidate.subject_id
          AND external_resident.status = 'active';

        resolved_app_role := 'external_resident';
        resolved_admin_level := NULL;
        resolved_scope := ARRAY[]::text[];
        resolved_staff_actor_name := NULL;
        resolved_posting := NULL;
    ELSE
        RETURN;
    END IF;

    IF current_generation IS NULL
       OR current_generation <> candidate.subject_session_generation
    THEN
        RETURN;
    END IF;

    IF p_lock_mode = 'exclusive' THEN
        PERFORM pg_catalog.pg_advisory_xact_lock(
            mata_rls.uuid_advisory_key(candidate.session_family_id)
        );
    ELSE
        PERFORM pg_catalog.pg_advisory_xact_lock_shared(
            mata_rls.uuid_advisory_key(candidate.session_family_id)
        );
    END IF;

    -- Every validity decision after a potentially blocking lock uses a fresh
    -- wall-clock value.  A session that expires while waiting must never be
    -- hydrated or have its idle deadline extended.
    observed_at := pg_catalog.clock_timestamp();

    IF p_touch THEN
        SELECT app_session.*
        INTO locked_session
        FROM public.app_sessions AS app_session
        WHERE app_session.id = candidate.id
          AND app_session.token_digest = p_token_digest
          AND app_session.subject_type = candidate.subject_type
          AND app_session.subject_id = candidate.subject_id
          AND app_session.subject_session_generation = current_generation
          AND app_session.session_family_id = candidate.session_family_id
          AND app_session.auth_source = candidate.auth_source
          AND app_session.revoked_at IS NULL
          AND observed_at < app_session.idle_expires_at
          AND observed_at < app_session.absolute_expires_at
        FOR UPDATE;
    ELSE
        SELECT app_session.*
        INTO locked_session
        FROM public.app_sessions AS app_session
        WHERE app_session.id = candidate.id
          AND app_session.token_digest = p_token_digest
          AND app_session.subject_type = candidate.subject_type
          AND app_session.subject_id = candidate.subject_id
          AND app_session.subject_session_generation = current_generation
          AND app_session.session_family_id = candidate.session_family_id
          AND app_session.auth_source = candidate.auth_source
          AND app_session.revoked_at IS NULL
          AND observed_at < app_session.idle_expires_at
          AND observed_at < app_session.absolute_expires_at;
    END IF;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    -- Recheck after the authoritative post-family-lock SELECT.  Touching calls
    -- hold the row FOR UPDATE; read-only calls deliberately retain no row lock
    -- so a later touch in the same transaction cannot deadlock on an upgrade.
    observed_at := pg_catalog.clock_timestamp();
    IF locked_session.revoked_at IS NOT NULL
       OR observed_at >= locked_session.idle_expires_at
       OR observed_at >= locked_session.absolute_expires_at
    THEN
        RETURN;
    END IF;

    IF p_touch THEN
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
        WHERE app_session.id = locked_session.id
        RETURNING app_session.*
        INTO STRICT locked_session;
    END IF;

    session_id := locked_session.id;
    token_digest := locked_session.token_digest;
    subject_type := locked_session.subject_type;
    subject_id := locked_session.subject_id;
    subject_session_generation := locked_session.subject_session_generation;
    session_family_id := locked_session.session_family_id;
    auth_source := locked_session.auth_source;
    csrf_token_digest := locked_session.csrf_token_digest;
    created_at := locked_session.created_at;
    last_seen_at := locked_session.last_seen_at;
    idle_expires_at := locked_session.idle_expires_at;
    absolute_expires_at := locked_session.absolute_expires_at;
    revoked_at := locked_session.revoked_at;
    revoked_reason := locked_session.revoked_reason;
    rotated_from_session_id := locked_session.rotated_from_session_id;
    user_agent_hash := locked_session.user_agent_hash;
    app_role := resolved_app_role;
    admin_level := resolved_admin_level;
    programme_scope := resolved_scope;
    posting_code := resolved_posting;
    current_staff_actor_name := resolved_staff_actor_name;
    authorization_fingerprint := mata_private.authorization_fingerprint(
        locked_session.subject_type,
        locked_session.subject_id,
        locked_session.subject_session_generation,
        resolved_app_role,
        resolved_admin_level,
        resolved_scope,
        resolved_posting,
        locked_session.id,
        locked_session.auth_source
    );
    RETURN NEXT;
END
$function$
"""
    )


def _create_context_installer_and_accessors() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.install_request_context(
    p_token_digest bytea,
    p_lock_mode text,
    p_expected_subject_type text,
    p_expected_subject_id uuid,
    p_expected_app_session_id uuid,
    p_expected_authorization_fingerprint text
)
RETURNS TABLE (
    subject_type text,
    subject_id uuid,
    app_role text,
    admin_level text,
    programme_scope text[],
    posting_code text,
    app_session_id uuid,
    authorization_fingerprint text
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    hydrated record;
    context_signature text;
    database_oid oid;
BEGIN
    -- All expected bindings are mandatory.  A mismatch returns no row and,
    -- critically, performs no set_config call.
    IF p_expected_subject_type IS NULL
       OR p_expected_subject_id IS NULL
       OR p_expected_app_session_id IS NULL
       OR p_expected_authorization_fingerprint IS NULL
       OR p_expected_authorization_fingerprint !~ '^[0-9a-f]{64}$'
    THEN
        RETURN;
    END IF;

    SELECT *
    INTO hydrated
    FROM mata_private.hydrate_app_session(
        p_token_digest,
        p_lock_mode,
        false,
        0
    );

    IF NOT FOUND
       OR hydrated.subject_type IS DISTINCT FROM p_expected_subject_type
       OR hydrated.subject_id IS DISTINCT FROM p_expected_subject_id
       OR hydrated.session_id IS DISTINCT FROM p_expected_app_session_id
       OR hydrated.authorization_fingerprint
            IS DISTINCT FROM p_expected_authorization_fingerprint
    THEN
        RETURN;
    END IF;

    SELECT database.oid
    INTO STRICT database_oid
    FROM pg_catalog.pg_database AS database
    WHERE database.datname = pg_catalog.current_database();

    context_signature := mata_private.context_signature(
        hydrated.subject_type,
        hydrated.subject_id,
        hydrated.app_role,
        hydrated.admin_level,
        hydrated.programme_scope,
        hydrated.posting_code,
        hydrated.session_id,
        hydrated.authorization_fingerprint,
        pg_catalog.txid_current(),
        pg_catalog.pg_backend_pid(),
        database_oid
    );

    PERFORM pg_catalog.set_config(
        'mata.subject_type',
        hydrated.subject_type,
        true
    );
    PERFORM pg_catalog.set_config(
        'mata.subject_id',
        hydrated.subject_id::text,
        true
    );
    PERFORM pg_catalog.set_config('mata.app_role', hydrated.app_role, true);
    PERFORM pg_catalog.set_config(
        'mata.admin_level',
        COALESCE(hydrated.admin_level, ''),
        true
    );
    PERFORM pg_catalog.set_config(
        'mata.programme_scope_json',
        pg_catalog.to_jsonb(hydrated.programme_scope)::text,
        true
    );
    PERFORM pg_catalog.set_config(
        'mata.posting_code',
        COALESCE(hydrated.posting_code, ''),
        true
    );
    PERFORM pg_catalog.set_config(
        'mata.app_session_id',
        hydrated.session_id::text,
        true
    );
    PERFORM pg_catalog.set_config(
        'mata.authorization_fingerprint',
        hydrated.authorization_fingerprint,
        true
    );
    PERFORM pg_catalog.set_config(
        'mata.context_signature',
        context_signature,
        true
    );

    subject_type := hydrated.subject_type;
    subject_id := hydrated.subject_id;
    app_role := hydrated.app_role;
    admin_level := hydrated.admin_level;
    programme_scope := hydrated.programme_scope;
    posting_code := hydrated.posting_code;
    app_session_id := hydrated.session_id;
    authorization_fingerprint := hydrated.authorization_fingerprint;
    RETURN NEXT;
END
$function$
"""
    )

    accessor_definitions = {
        "context_is_valid": (
            "boolean",
            "SELECT EXISTS("
            "SELECT 1 FROM mata_private.verified_context())",
        ),
        "current_subject_type": (
            "text",
            "SELECT context.subject_type "
            "FROM mata_private.verified_context() AS context",
        ),
        "current_subject_id": (
            "uuid",
            "SELECT context.subject_id "
            "FROM mata_private.verified_context() AS context",
        ),
        "current_app_role": (
            "text",
            "SELECT context.app_role "
            "FROM mata_private.verified_context() AS context",
        ),
        "current_admin_level": (
            "text",
            "SELECT context.admin_level "
            "FROM mata_private.verified_context() AS context",
        ),
        "current_programme_scope": (
            "text[]",
            "SELECT context.programme_scope "
            "FROM mata_private.verified_context() AS context",
        ),
        "current_posting_code": (
            "text",
            "SELECT context.posting_code "
            "FROM mata_private.verified_context() AS context",
        ),
        "current_app_session_id": (
            "uuid",
            "SELECT context.app_session_id "
            "FROM mata_private.verified_context() AS context",
        ),
        "current_authorization_fingerprint": (
            "text",
            "SELECT context.authorization_fingerprint "
            "FROM mata_private.verified_context() AS context",
        ),
    }
    for function_name, (return_type, body) in accessor_definitions.items():
        _execute(
            f"""
CREATE FUNCTION mata_rls.{function_name}()
RETURNS {return_type}
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    {body}
$function$
"""
        )

    _execute(
        r"""
CREATE FUNCTION mata_rls.is_authenticated()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT mata_rls.context_is_valid()
$function$
"""
    )
    _execute(
        r"""
CREATE FUNCTION mata_rls.is_master_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT COALESCE(
        (
            SELECT context.subject_type = 'staff'
               AND context.app_role = 'admin'
               AND context.admin_level = 'master'
            FROM mata_private.verified_context() AS context
        ),
        false
    )
$function$
"""
    )
    _execute(
        r"""
CREATE FUNCTION mata_rls.has_programme_scope(p_programme_code text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT COALESCE(
        (
            SELECT context.subject_type = 'staff'
               AND context.app_role = 'admin'
               AND context.admin_level = 'programme'
               AND pg_catalog.upper(pg_catalog.btrim(p_programme_code))
                   = ANY(context.programme_scope)
            FROM mata_private.verified_context() AS context
        ),
        false
    )
$function$
"""
    )
    _execute(
        r"""
CREATE FUNCTION mata_rls.is_secretary_for_posting(p_posting_code text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT COALESCE(
        (
            SELECT context.subject_type = 'staff'
               AND context.app_role = 'secretary'
               AND context.posting_code = p_posting_code
            FROM mata_private.verified_context() AS context
        ),
        false
    )
$function$
"""
    )
    _execute(
        r"""
CREATE FUNCTION mata_rls.is_native_resident(p_resident_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT COALESCE(
        (
            SELECT context.subject_type = 'resident'
               AND context.app_role = 'resident'
               AND context.subject_id = p_resident_id
            FROM mata_private.verified_context() AS context
        ),
        false
    )
$function$
"""
    )
    _execute(
        r"""
CREATE FUNCTION mata_rls.is_external_resident(p_external_resident_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT COALESCE(
        (
            SELECT context.subject_type = 'external_resident'
               AND context.app_role = 'external_resident'
               AND context.subject_id = p_external_resident_id
            FROM mata_private.verified_context() AS context
        ),
        false
    )
$function$
"""
    )


def _create_global_mcr_enforcement() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_private.mcr_advisory_key(p_mcr text)
RETURNS bigint
LANGUAGE plpgsql
IMMUTABLE
STRICT
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    digest_bytes bytea;
    key_value numeric := 0;
    byte_index integer;
BEGIN
    digest_bytes := public.digest(
        pg_catalog.convert_to(
            'mata:global-mcr:v1:' || mata_private.normalize_mcr(p_mcr),
            'UTF8'
        ),
        'sha256'
    );
    FOR byte_index IN 0..7
    LOOP
        key_value := (
            key_value * 256
            + pg_catalog.get_byte(digest_bytes, byte_index)
        );
    END LOOP;
    IF key_value >= 9223372036854775808::numeric THEN
        key_value := key_value - 18446744073709551616::numeric;
    END IF;
    RETURN key_value::bigint;
END
$function$
"""
    )

    _execute(
        r"""
DO $migration$
DECLARE
    duplicate_mcr text;
BEGIN
    -- Freeze both identity families for the audit, canonicalization, and
    -- trigger installation.  Without this lock a concurrent writer could
    -- commit between the preflight and CREATE TRIGGER.
    LOCK TABLE public.residents, public.external_residents
        IN SHARE ROW EXCLUSIVE MODE;

    IF EXISTS (
        SELECT 1
        FROM public.residents AS resident
        WHERE mata_private.normalize_mcr(resident.mcr) = ''
    )
       OR EXISTS (
           SELECT 1
           FROM public.external_residents AS external_resident
           WHERE mata_private.normalize_mcr(external_resident.mcr) = ''
       )
    THEN
        RAISE EXCEPTION
            'Blank normalized MCR blocks global uniqueness migration'
            USING ERRCODE = '23514';
    END IF;

    SELECT normalized_mcr
    INTO duplicate_mcr
    FROM (
        SELECT mata_private.normalize_mcr(resident.mcr) AS normalized_mcr
        FROM public.residents AS resident
        UNION ALL
        SELECT mata_private.normalize_mcr(external_resident.mcr)
        FROM public.external_residents AS external_resident
    ) AS all_mcrs
    GROUP BY normalized_mcr
    HAVING pg_catalog.count(*) > 1
    ORDER BY normalized_mcr
    LIMIT 1;

    IF duplicate_mcr IS NOT NULL THEN
        RAISE EXCEPTION
            'Duplicate normalized MCR blocks global uniqueness migration'
            USING ERRCODE = '23505';
    END IF;
END
$migration$;
"""
    )

    # Persist the same canonical form already used by the service layer so the
    # existing per-table unique constraints also enforce case-normalized keys.
    _execute(
        r"""
UPDATE public.residents
SET mcr = mata_private.normalize_mcr(mcr)
WHERE mcr IS DISTINCT FROM mata_private.normalize_mcr(mcr)
"""
    )
    _execute(
        r"""
UPDATE public.external_residents
SET mcr = mata_private.normalize_mcr(mcr)
WHERE mcr IS DISTINCT FROM mata_private.normalize_mcr(mcr)
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_private.enforce_global_mcr_uniqueness()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    -- The opposite-family lookup must observe the advisory-lock winner's
    -- commit.  READ COMMITTED takes a fresh statement snapshot after the
    -- blocking lock; stronger snapshot isolation could retain a stale view,
    -- so fail closed rather than silently weaken global uniqueness.
    IF pg_catalog.current_setting('transaction_isolation') <> 'read committed'
    THEN
        RAISE EXCEPTION
            'Global MCR writes require READ COMMITTED isolation'
            USING ERRCODE = '0A000';
    END IF;

    NEW.mcr := mata_private.normalize_mcr(NEW.mcr);
    IF NEW.mcr = '' THEN
        RAISE EXCEPTION 'MCR cannot be blank'
            USING ERRCODE = '23514';
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        mata_private.mcr_advisory_key(NEW.mcr)
    );

    IF TG_TABLE_NAME = 'residents' THEN
        IF EXISTS (
            SELECT 1
            FROM public.external_residents AS external_resident
            WHERE external_resident.mcr = NEW.mcr
        ) THEN
            RAISE EXCEPTION 'MCR already belongs to another identity family'
                USING ERRCODE = '23505',
                      CONSTRAINT = 'uq_global_mcr_identity';
        END IF;
    ELSIF TG_TABLE_NAME = 'external_residents' THEN
        IF EXISTS (
            SELECT 1
            FROM public.residents AS resident
            WHERE resident.mcr = NEW.mcr
        ) THEN
            RAISE EXCEPTION 'MCR already belongs to another identity family'
                USING ERRCODE = '23505',
                      CONSTRAINT = 'uq_global_mcr_identity';
        END IF;
    ELSE
        RAISE EXCEPTION 'Global MCR trigger attached to unexpected table'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$function$
"""
    )
    _execute(
        r"""
CREATE TRIGGER trg_residents_global_mcr_uniqueness
BEFORE INSERT OR UPDATE OF mcr ON public.residents
FOR EACH ROW
EXECUTE FUNCTION mata_private.enforce_global_mcr_uniqueness()
"""
    )
    _execute(
        r"""
CREATE TRIGGER trg_external_residents_global_mcr_uniqueness
BEFORE INSERT OR UPDATE OF mcr ON public.external_residents
FOR EACH ROW
EXECUTE FUNCTION mata_private.enforce_global_mcr_uniqueness()
"""
    )


def _create_session_service_helpers() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_private.insert_root_app_session(
    p_subject_type text,
    p_subject_id uuid,
    p_subject_session_generation bigint,
    p_auth_source text,
    p_session_id uuid,
    p_token_digest bytea,
    p_csrf_token_digest bytea,
    p_idle_timeout_seconds integer,
    p_absolute_timeout_seconds integer,
    p_user_agent_hash bytea
)
RETURNS SETOF public.app_sessions
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    issued_at timestamptz := pg_catalog.clock_timestamp();
BEGIN
    IF p_subject_type IS NULL
       OR p_subject_type NOT IN ('staff', 'resident', 'external_resident')
       OR p_subject_id IS NULL
       OR p_subject_session_generation IS NULL
       OR p_subject_session_generation < 0
       OR p_auth_source IS NULL
       OR (
           p_subject_type = 'staff'
           AND p_auth_source <> 'supabase_staff'
       )
       OR (
           p_subject_type IN ('resident', 'external_resident')
           AND p_auth_source <> 'mata_resident'
       )
       OR p_session_id IS NULL
       OR p_token_digest IS NULL
       OR pg_catalog.octet_length(p_token_digest) <> 32
       OR p_csrf_token_digest IS NULL
       OR pg_catalog.octet_length(p_csrf_token_digest) <> 32
       OR (
           p_user_agent_hash IS NOT NULL
           AND pg_catalog.octet_length(p_user_agent_hash) <> 32
       )
       OR p_idle_timeout_seconds IS NULL
       OR p_idle_timeout_seconds < 1
       OR p_idle_timeout_seconds > 86400
       OR p_absolute_timeout_seconds IS NULL
       OR p_absolute_timeout_seconds < p_idle_timeout_seconds
       OR p_absolute_timeout_seconds > 604800
    THEN
        RAISE EXCEPTION 'Invalid application-session issuance parameters'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    INSERT INTO public.app_sessions (
        id,
        token_digest,
        subject_type,
        subject_id,
        subject_session_generation,
        session_family_id,
        auth_source,
        csrf_token_digest,
        created_at,
        last_seen_at,
        idle_expires_at,
        absolute_expires_at,
        revoked_at,
        revoked_reason,
        rotated_from_session_id,
        user_agent_hash
    )
    VALUES (
        p_session_id,
        p_token_digest,
        p_subject_type,
        p_subject_id,
        p_subject_session_generation,
        p_session_id,
        p_auth_source,
        p_csrf_token_digest,
        issued_at,
        issued_at,
        issued_at
            + pg_catalog.make_interval(
                secs => p_idle_timeout_seconds::double precision
            ),
        issued_at
            + pg_catalog.make_interval(
                secs => p_absolute_timeout_seconds::double precision
            ),
        NULL,
        NULL,
        NULL,
        p_user_agent_hash
    )
    RETURNING app_sessions.*;
END
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.issue_staff_app_session(
    p_user_id uuid,
    p_expected_supabase_user_id uuid,
    p_expected_subject_session_generation bigint,
    p_session_id uuid,
    p_token_digest bytea,
    p_csrf_token_digest bytea,
    p_idle_timeout_seconds integer,
    p_absolute_timeout_seconds integer,
    p_user_agent_hash bytea
)
RETURNS SETOF public.app_sessions
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    current_generation bigint;
BEGIN
    IF p_user_id IS NULL
       OR p_expected_supabase_user_id IS NULL
       OR p_expected_subject_session_generation IS NULL
       OR p_expected_subject_session_generation < 0
    THEN
        RETURN;
    END IF;

    SELECT staff.session_generation
    INTO current_generation
    FROM public.users AS staff
    WHERE staff.id = p_user_id
      AND staff.supabase_user_id = p_expected_supabase_user_id
      AND staff.role IN ('admin', 'secretary')
      AND staff.is_active
      AND NOT staff.session_issuance_blocked
    FOR SHARE;

    IF current_generation IS NULL
       OR current_generation <> p_expected_subject_session_generation
    THEN
        RETURN;
    END IF;

    RETURN QUERY
    SELECT *
    FROM mata_private.insert_root_app_session(
        'staff',
        p_user_id,
        current_generation,
        'supabase_staff',
        p_session_id,
        p_token_digest,
        p_csrf_token_digest,
        p_idle_timeout_seconds,
        p_absolute_timeout_seconds,
        p_user_agent_hash
    );
END
$function$
"""
    )

    for function_name, subject_type, table_name in (
        ("issue_resident_app_session", "resident", "residents"),
        (
            "issue_external_resident_app_session",
            "external_resident",
            "external_residents",
        ),
    ):
        other_table = (
            "external_residents" if table_name == "residents" else "residents"
        )
        _execute(
            f"""
CREATE FUNCTION mata_rls.{function_name}(
    p_normalized_mcr text,
    p_expected_subject_type text,
    p_expected_subject_id uuid,
    p_expected_subject_session_generation bigint,
    p_session_id uuid,
    p_token_digest bytea,
    p_csrf_token_digest bytea,
    p_idle_timeout_seconds integer,
    p_absolute_timeout_seconds integer,
    p_user_agent_hash bytea
)
RETURNS SETOF public.app_sessions
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    normalized_mcr text;
    candidate_id uuid;
    current_generation bigint;
    opposite_count bigint;
BEGIN
    normalized_mcr := mata_private.normalize_mcr(p_normalized_mcr);
    IF normalized_mcr = ''
       OR p_expected_subject_type IS NULL
       OR p_expected_subject_type <> '{subject_type}'
       OR p_expected_subject_id IS NULL
       OR p_expected_subject_session_generation IS NULL
       OR p_expected_subject_session_generation < 0
    THEN
        RETURN;
    END IF;

    -- Locate without locking, then preserve subject -> MCR advisory lock
    -- ordering.  The post-lock queries below are authoritative.
    SELECT identity_row.id
    INTO candidate_id
    FROM public.{table_name} AS identity_row
    WHERE identity_row.mcr = normalized_mcr
      AND identity_row.status = 'active';

    IF candidate_id IS DISTINCT FROM p_expected_subject_id THEN
        RETURN;
    END IF;

    SELECT identity_row.session_generation
    INTO current_generation
    FROM public.{table_name} AS identity_row
    WHERE identity_row.id = candidate_id
      AND identity_row.mcr = normalized_mcr
      AND identity_row.status = 'active'
    FOR SHARE;

    IF current_generation IS NULL
       OR current_generation <> p_expected_subject_session_generation
    THEN
        RETURN;
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock_shared(
        mata_private.mcr_advisory_key(normalized_mcr)
    );

    SELECT pg_catalog.count(*)
    INTO opposite_count
    FROM public.{other_table} AS opposite_identity
    WHERE opposite_identity.mcr = normalized_mcr;

    IF opposite_count <> 0
       OR NOT EXISTS (
           SELECT 1
           FROM public.{table_name} AS current_identity
           WHERE current_identity.id = candidate_id
             AND current_identity.mcr = normalized_mcr
             AND current_identity.status = 'active'
             AND current_identity.session_generation = current_generation
       )
    THEN
        RETURN;
    END IF;

    RETURN QUERY
    SELECT *
    FROM mata_private.insert_root_app_session(
        '{subject_type}',
        candidate_id,
        current_generation,
        'mata_resident',
        p_session_id,
        p_token_digest,
        p_csrf_token_digest,
        p_idle_timeout_seconds,
        p_absolute_timeout_seconds,
        p_user_agent_hash
    );
END
$function$
"""
        )

    _execute(
        r"""
CREATE FUNCTION mata_rls.resolve_app_session(
    p_token_digest bytea,
    p_touch boolean,
    p_idle_timeout_seconds integer
)
RETURNS TABLE (
    id uuid,
    token_digest bytea,
    subject_type text,
    subject_id uuid,
    subject_session_generation bigint,
    session_family_id uuid,
    auth_source text,
    csrf_token_digest bytea,
    created_at timestamptz,
    last_seen_at timestamptz,
    idle_expires_at timestamptz,
    absolute_expires_at timestamptz,
    revoked_at timestamptz,
    revoked_reason text,
    rotated_from_session_id uuid,
    user_agent_hash bytea,
    authorization_fingerprint text,
    app_role text,
    admin_level text,
    programme_scope text[],
    posting_code text,
    current_staff_actor_name text
)
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT
        hydrated.session_id,
        hydrated.token_digest,
        hydrated.subject_type,
        hydrated.subject_id,
        hydrated.subject_session_generation,
        hydrated.session_family_id,
        hydrated.auth_source,
        hydrated.csrf_token_digest,
        hydrated.created_at,
        hydrated.last_seen_at,
        hydrated.idle_expires_at,
        hydrated.absolute_expires_at,
        hydrated.revoked_at,
        hydrated.revoked_reason,
        hydrated.rotated_from_session_id,
        hydrated.user_agent_hash,
        hydrated.authorization_fingerprint,
        hydrated.app_role,
        hydrated.admin_level,
        hydrated.programme_scope,
        hydrated.posting_code,
        hydrated.current_staff_actor_name
    FROM mata_private.hydrate_app_session(
        p_token_digest,
        'shared',
        p_touch,
        p_idle_timeout_seconds
    ) AS hydrated
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.rotate_app_session(
    p_old_token_digest bytea,
    p_expected_parent_session_id uuid,
    p_new_session_id uuid,
    p_new_token_digest bytea,
    p_new_csrf_token_digest bytea,
    p_idle_timeout_seconds integer,
    p_new_user_agent_hash bytea
)
RETURNS SETOF public.app_sessions
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    hydrated record;
    parent_session record;
    rotation_time timestamptz := pg_catalog.clock_timestamp();
    new_idle_expiry timestamptz;
BEGIN
    IF p_expected_parent_session_id IS NULL
       OR p_new_session_id IS NULL
       OR p_new_session_id = p_expected_parent_session_id
       OR p_new_token_digest IS NULL
       OR pg_catalog.octet_length(p_new_token_digest) <> 32
       OR p_new_csrf_token_digest IS NULL
       OR pg_catalog.octet_length(p_new_csrf_token_digest) <> 32
       OR (
           p_new_user_agent_hash IS NOT NULL
           AND pg_catalog.octet_length(p_new_user_agent_hash) <> 32
       )
       OR p_idle_timeout_seconds IS NULL
       OR p_idle_timeout_seconds < 1
       OR p_idle_timeout_seconds > 86400
    THEN
        RAISE EXCEPTION 'Invalid application-session rotation parameters'
            USING ERRCODE = '22023';
    END IF;

    SELECT *
    INTO hydrated
    FROM mata_private.hydrate_app_session(
        p_old_token_digest,
        'exclusive',
        false,
        0
    );

    IF NOT FOUND
       OR hydrated.session_id IS DISTINCT FROM p_expected_parent_session_id
    THEN
        RETURN;
    END IF;

    rotation_time := pg_catalog.clock_timestamp();
    SELECT app_session.*
    INTO parent_session
    FROM public.app_sessions AS app_session
    WHERE app_session.id = hydrated.session_id
      AND app_session.token_digest = p_old_token_digest
      AND app_session.revoked_at IS NULL
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    rotation_time := pg_catalog.clock_timestamp();
    IF parent_session.revoked_at IS NOT NULL
       OR rotation_time >= parent_session.idle_expires_at
       OR rotation_time >= parent_session.absolute_expires_at
    THEN
        RETURN;
    END IF;

    new_idle_expiry := LEAST(
        rotation_time
            + pg_catalog.make_interval(
                secs => p_idle_timeout_seconds::double precision
            ),
        parent_session.absolute_expires_at
    );
    IF new_idle_expiry <= rotation_time THEN
        RETURN;
    END IF;

    UPDATE public.app_sessions AS app_session
    SET
        revoked_at = rotation_time,
        revoked_reason = 'rotated'
    WHERE app_session.id = parent_session.id
      AND app_session.revoked_at IS NULL;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    RETURN QUERY
    INSERT INTO public.app_sessions (
        id,
        token_digest,
        subject_type,
        subject_id,
        subject_session_generation,
        session_family_id,
        auth_source,
        csrf_token_digest,
        created_at,
        last_seen_at,
        idle_expires_at,
        absolute_expires_at,
        revoked_at,
        revoked_reason,
        rotated_from_session_id,
        user_agent_hash
    )
    VALUES (
        p_new_session_id,
        p_new_token_digest,
        parent_session.subject_type,
        parent_session.subject_id,
        parent_session.subject_session_generation,
        parent_session.session_family_id,
        parent_session.auth_source,
        p_new_csrf_token_digest,
        rotation_time,
        rotation_time,
        new_idle_expiry,
        parent_session.absolute_expires_at,
        NULL,
        NULL,
        parent_session.id,
        COALESCE(p_new_user_agent_hash, parent_session.user_agent_hash)
    )
    RETURNING app_sessions.*;
END
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.revoke_app_session(
    p_token_digest bytea,
    p_expected_session_id uuid,
    p_reason text
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
    SELECT *
    INTO hydrated
    FROM mata_private.hydrate_app_session(
        p_token_digest,
        'exclusive',
        false,
        0
    );
    IF NOT FOUND
       OR hydrated.session_id IS DISTINCT FROM p_expected_session_id
    THEN
        RETURN false;
    END IF;

    UPDATE public.app_sessions AS app_session
    SET
        revoked_at = pg_catalog.clock_timestamp(),
        revoked_reason = COALESCE(
            NULLIF(pg_catalog.btrim(p_reason), ''),
            'revoked'
        )
    WHERE app_session.id = hydrated.session_id
      AND app_session.token_digest = p_token_digest
      AND app_session.revoked_at IS NULL;
    RETURN FOUND;
END
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.revoke_app_session_family(
    p_token_digest bytea,
    p_expected_session_id uuid,
    p_reason text
)
RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    hydrated record;
    affected_count integer;
BEGIN
    SELECT *
    INTO hydrated
    FROM mata_private.hydrate_app_session(
        p_token_digest,
        'exclusive',
        false,
        0
    );
    IF NOT FOUND
       OR hydrated.session_id IS DISTINCT FROM p_expected_session_id
    THEN
        RETURN 0;
    END IF;

    UPDATE public.app_sessions AS app_session
    SET
        revoked_at = pg_catalog.clock_timestamp(),
        revoked_reason = COALESCE(
            NULLIF(pg_catalog.btrim(p_reason), ''),
            'family_revoked'
        )
    WHERE app_session.session_family_id = hydrated.session_family_id
      AND app_session.subject_type = hydrated.subject_type
      AND app_session.subject_id = hydrated.subject_id
      AND app_session.revoked_at IS NULL;
    GET DIAGNOSTICS affected_count = ROW_COUNT;
    RETURN affected_count;
END
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.invalidate_subject_app_sessions(
    p_subject_type text,
    p_subject_id uuid,
    p_reason text,
    p_block_staff_session_issuance boolean
)
RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    updated_generation bigint;
    affected_count integer;
BEGIN
    IF NOT mata_rls.is_master_admin() THEN
        RAISE EXCEPTION 'Master Admin context required'
            USING ERRCODE = '42501';
    END IF;
    IF p_subject_type IS NULL
       OR p_subject_type NOT IN ('staff', 'resident', 'external_resident')
       OR p_subject_id IS NULL
       OR p_block_staff_session_issuance IS NULL
       OR (
           p_block_staff_session_issuance
           AND p_subject_type <> 'staff'
       )
    THEN
        RAISE EXCEPTION 'Invalid subject invalidation parameters'
            USING ERRCODE = '22023';
    END IF;

    IF p_subject_type = 'staff' THEN
        UPDATE public.users AS staff
        SET
            session_generation = staff.session_generation + 1,
            session_issuance_blocked = CASE
                WHEN p_block_staff_session_issuance THEN true
                ELSE staff.session_issuance_blocked
            END,
            updated_at = pg_catalog.clock_timestamp()
        WHERE staff.id = p_subject_id
          AND staff.role IN ('admin', 'secretary')
        RETURNING staff.session_generation
        INTO updated_generation;
    ELSIF p_subject_type = 'resident' THEN
        UPDATE public.residents AS resident
        SET
            session_generation = resident.session_generation + 1,
            updated_at = pg_catalog.clock_timestamp()
        WHERE resident.id = p_subject_id
        RETURNING resident.session_generation
        INTO updated_generation;
    ELSE
        UPDATE public.external_residents AS external_resident
        SET
            session_generation = external_resident.session_generation + 1,
            updated_at = pg_catalog.clock_timestamp()
        WHERE external_resident.id = p_subject_id
        RETURNING external_resident.session_generation
        INTO updated_generation;
    END IF;

    IF updated_generation IS NULL THEN
        RETURN 0;
    END IF;

    UPDATE public.app_sessions AS app_session
    SET
        revoked_at = pg_catalog.clock_timestamp(),
        revoked_reason = COALESCE(
            NULLIF(pg_catalog.btrim(p_reason), ''),
            'subject_revoked'
        )
    WHERE app_session.subject_type = p_subject_type
      AND app_session.subject_id = p_subject_id
      AND app_session.revoked_at IS NULL;
    GET DIAGNOSTICS affected_count = ROW_COUNT;
    RETURN affected_count;
END
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.cleanup_app_sessions(
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
        WHERE (
                app_session.revoked_at IS NOT NULL
                AND app_session.revoked_at <= cutoff
              )
           OR app_session.idle_expires_at <= cutoff
           OR app_session.absolute_expires_at <= cutoff
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


def _create_login_helpers() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.staff_login_snapshot(p_email text)
RETURNS TABLE (
    id uuid,
    supabase_user_id uuid,
    session_generation bigint
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT
        staff.id,
        staff.supabase_user_id,
        staff.session_generation
    FROM public.users AS staff
    WHERE pg_catalog.lower(staff.email)
          = pg_catalog.lower(pg_catalog.btrim(p_email))
      AND staff.role IN ('admin', 'secretary')
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.staff_login_candidate(p_email text)
RETURNS TABLE (
    id uuid,
    email text,
    supabase_user_id uuid,
    password_hash text,
    role text,
    name text,
    posting_code text,
    programme_scope text[],
    admin_level text,
    is_active boolean,
    session_generation bigint,
    session_issuance_blocked boolean,
    current_staff_actor_name text,
    staff_actor_name_updated_at timestamptz,
    staff_actor_name_updated_by_user_id uuid
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT
        staff.id,
        staff.email::text,
        staff.supabase_user_id,
        staff.password_hash::text,
        staff.role::text,
        staff.name::text,
        staff.posting_code::text,
        CASE
            WHEN staff.role = 'admin'
            THEN mata_private.normalized_scope(staff.programme_scope)
            ELSE ARRAY[]::text[]
        END,
        CASE WHEN staff.role = 'admin' THEN staff.admin_level::text ELSE NULL END,
        staff.is_active,
        staff.session_generation,
        staff.session_issuance_blocked,
        NULLIF(pg_catalog.btrim(staff.current_staff_actor_name), ''),
        staff.staff_actor_name_updated_at,
        staff.staff_actor_name_updated_by_user_id
    FROM public.users AS staff
    WHERE pg_catalog.lower(staff.email)
          = pg_catalog.lower(pg_catalog.btrim(p_email))
      AND staff.role IN ('admin', 'secretary')
      AND staff.is_active
      AND NOT staff.session_issuance_blocked
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.staff_login_identity(
    p_user_id uuid,
    p_expected_supabase_user_id uuid,
    p_expected_subject_session_generation bigint
)
RETURNS TABLE (
    id uuid,
    email text,
    role text,
    name text,
    posting_code text,
    programme_scope text[],
    admin_level text,
    is_active boolean,
    session_generation bigint,
    session_issuance_blocked boolean,
    current_staff_actor_name text,
    staff_actor_name_updated_at timestamptz,
    staff_actor_name_updated_by_user_id uuid
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT
        staff.id,
        staff.email::text,
        staff.role::text,
        staff.name::text,
        staff.posting_code::text,
        CASE
            WHEN staff.role = 'admin'
            THEN mata_private.normalized_scope(staff.programme_scope)
            ELSE ARRAY[]::text[]
        END,
        CASE WHEN staff.role = 'admin' THEN staff.admin_level::text ELSE NULL END,
        staff.is_active,
        staff.session_generation,
        staff.session_issuance_blocked,
        NULLIF(pg_catalog.btrim(staff.current_staff_actor_name), ''),
        staff.staff_actor_name_updated_at,
        staff.staff_actor_name_updated_by_user_id
    FROM public.users AS staff
    WHERE staff.id = p_user_id
      AND staff.supabase_user_id = p_expected_supabase_user_id
      AND staff.session_generation = p_expected_subject_session_generation
      AND staff.role IN ('admin', 'secretary')
      AND staff.is_active
      AND NOT staff.session_issuance_blocked
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.resident_login_candidate(p_mcr text)
RETURNS TABLE (
    subject_type text,
    subject_id uuid,
    name text,
    mcr text,
    programme_code text,
    home_cluster text,
    current_posting_code text,
    current_posting_label text,
    session_generation bigint
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    normalized_mcr text;
    native_count bigint;
    external_count bigint;
BEGIN
    normalized_mcr := mata_private.normalize_mcr(p_mcr);
    IF normalized_mcr = '' THEN
        RETURN;
    END IF;

    -- This is a projection-only candidate lookup.  The exact issuer performs
    -- the authoritative subject -> MCR lock/revalidation; taking MCR first
    -- here would invert that canonical order across the login transaction.
    SELECT pg_catalog.count(*)
    INTO native_count
    FROM public.residents AS resident
    WHERE resident.mcr = normalized_mcr;
    SELECT pg_catalog.count(*)
    INTO external_count
    FROM public.external_residents AS external_resident
    WHERE external_resident.mcr = normalized_mcr;

    IF native_count + external_count <> 1 THEN
        RETURN;
    END IF;

    IF native_count = 1 THEN
        RETURN QUERY
        SELECT
            'resident'::text,
            resident.id,
            resident.name::text,
            resident.mcr::text,
            resident.programme_code::text,
            NULL::text,
            current_posting.posting_code::text,
            COALESCE(
                posting.display_name,
                current_posting.posting_code
            )::text,
            resident.session_generation
        FROM public.residents AS resident
        LEFT JOIN LATERAL (
            SELECT resident_posting.posting_code
            FROM public.resident_postings AS resident_posting
            WHERE resident_posting.resident_id = resident.id
              AND resident_posting.start_date <= CURRENT_DATE
              AND resident_posting.end_date >= CURRENT_DATE
              AND resident_posting.status IN ('active', 'loa_working')
              AND resident_posting.posting_code IS NOT NULL
            ORDER BY
                resident_posting.start_date DESC,
                resident_posting.day_part NULLS FIRST,
                resident_posting.id
            LIMIT 1
        ) AS current_posting ON true
        LEFT JOIN public.posting_codes AS posting
          ON posting.code = current_posting.posting_code
        WHERE resident.mcr = normalized_mcr
          AND resident.status = 'active';
    ELSE
        RETURN QUERY
        SELECT
            'external_resident'::text,
            external_resident.id,
            external_resident.name::text,
            external_resident.mcr::text,
            NULL::text,
            external_resident.home_cluster::text,
            current_posting.posting_code::text,
            COALESCE(
                posting.display_name,
                current_posting.posting_code
            )::text,
            external_resident.session_generation
        FROM public.external_residents AS external_resident
        LEFT JOIN LATERAL (
            SELECT external_posting.posting_code
            FROM public.external_resident_postings AS external_posting
            WHERE external_posting.external_resident_id = external_resident.id
            ORDER BY
                CASE
                    WHEN external_posting.start_date <= CURRENT_DATE
                     AND (
                         external_posting.end_date IS NULL
                         OR external_posting.end_date >= CURRENT_DATE
                     )
                    THEN 0
                    WHEN external_posting.start_date > CURRENT_DATE
                    THEN 1
                    ELSE 2
                END,
                CASE
                    WHEN external_posting.start_date > CURRENT_DATE
                    THEN external_posting.start_date - CURRENT_DATE
                    ELSE CURRENT_DATE - COALESCE(
                        external_posting.end_date,
                        external_posting.start_date
                    )
                END,
                external_posting.start_date DESC,
                external_posting.posting_code
            LIMIT 1
        ) AS current_posting ON true
        LEFT JOIN public.posting_codes AS posting
          ON posting.code = current_posting.posting_code
        WHERE external_resident.mcr = normalized_mcr
          AND external_resident.status = 'active';
    END IF;
END
$function$
"""
    )


def _create_external_registration_helpers() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.external_registration_options()
RETURNS TABLE (
    programme_code text,
    programme_name text,
    institution_code text,
    status text,
    available boolean,
    display_order integer
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT
        programme.code::text,
        programme.name::text,
        mapping.institution_code::text,
        mapping.status::text,
        (
            mapping.status = 'active'
            AND mapping.posting_code IS NOT NULL
            AND posting.code IS NOT NULL
        ),
        mapping.display_order
    FROM public.programme_institution_posting_map AS mapping
    JOIN public.programmes AS programme
      ON programme.code = mapping.programme_code
    LEFT JOIN public.posting_codes AS posting
      ON posting.code = mapping.posting_code
    WHERE mapping.status IN ('pending', 'active')
    ORDER BY
        mapping.display_order,
        programme.code,
        mapping.institution_code
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_private.resolve_external_schedule(p_schedule jsonb)
RETURNS TABLE (
    programme_code text,
    institution_code text,
    posting_code text,
    start_date date,
    end_date date,
    is_current boolean
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    schedule_item jsonb;
    normalized_programme text;
    normalized_institution text;
    resolved_posting text;
    parsed_start_date date;
    parsed_end_date date;
    resolved_schedule jsonb := '[]'::jsonb;
BEGIN
    IF p_schedule IS NULL
       OR pg_catalog.jsonb_typeof(p_schedule) <> 'array'
       OR pg_catalog.jsonb_array_length(p_schedule) < 1
       OR pg_catalog.jsonb_array_length(p_schedule) > 100
    THEN
        RAISE EXCEPTION 'Invalid posting schedule'
            USING ERRCODE = '22023';
    END IF;

    FOR schedule_item IN
        SELECT item
        FROM pg_catalog.jsonb_array_elements(p_schedule) AS items(item)
    LOOP
        IF pg_catalog.jsonb_typeof(schedule_item) <> 'object'
           OR COALESCE(schedule_item->>'programme_code', '') = ''
           OR COALESCE(
               schedule_item->>'institution',
               schedule_item->>'institution_code',
               ''
           ) = ''
           OR COALESCE(schedule_item->>'start_date', '')
                !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
           OR COALESCE(schedule_item->>'end_date', '')
                !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
        THEN
            RAISE EXCEPTION 'Invalid posting schedule row'
                USING ERRCODE = '22023';
        END IF;

        normalized_programme := pg_catalog.upper(
            pg_catalog.btrim(schedule_item->>'programme_code')
        );
        normalized_institution := pg_catalog.upper(
            pg_catalog.btrim(
                COALESCE(
                    schedule_item->>'institution',
                    schedule_item->>'institution_code'
                )
            )
        );
        IF pg_catalog.length(normalized_programme) > 20
           OR pg_catalog.length(normalized_institution) > 20
        THEN
            RAISE EXCEPTION 'Invalid posting schedule code'
                USING ERRCODE = '22023';
        END IF;

        BEGIN
            parsed_start_date := (schedule_item->>'start_date')::date;
            parsed_end_date := (schedule_item->>'end_date')::date;
        EXCEPTION
            WHEN invalid_datetime_format OR datetime_field_overflow THEN
                RAISE EXCEPTION 'Invalid posting schedule date'
                    USING ERRCODE = '22023';
        END;
        IF parsed_start_date > parsed_end_date THEN
            RAISE EXCEPTION 'Invalid posting schedule date range'
                USING ERRCODE = '22023';
        END IF;

        SELECT mapping.posting_code
        INTO resolved_posting
        FROM public.programme_institution_posting_map AS mapping
        JOIN public.programmes AS programme
          ON programme.code = mapping.programme_code
        JOIN public.posting_codes AS posting
          ON posting.code = mapping.posting_code
        WHERE mapping.programme_code = normalized_programme
          AND mapping.institution_code = normalized_institution
          AND mapping.status = 'active'
          AND mapping.posting_code IS NOT NULL
        FOR SHARE OF mapping;
        IF resolved_posting IS NULL THEN
            RAISE EXCEPTION 'Posting mapping is unavailable'
                USING ERRCODE = '22023';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM pg_catalog.jsonb_array_elements(resolved_schedule)
                 AS existing(item)
            WHERE parsed_start_date <= (existing.item->>'end_date')::date
              AND parsed_end_date >= (existing.item->>'start_date')::date
        ) THEN
            RAISE EXCEPTION 'Posting schedule rows overlap'
                USING ERRCODE = '22023';
        END IF;

        resolved_schedule := resolved_schedule || pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
                'programme_code', normalized_programme,
                'institution_code', normalized_institution,
                'posting_code', resolved_posting,
                'start_date', parsed_start_date,
                'end_date', parsed_end_date
            )
        );
    END LOOP;

    RETURN QUERY
    WITH schedule_rows AS (
        SELECT
            item->>'programme_code' AS programme_code,
            item->>'institution_code' AS institution_code,
            item->>'posting_code' AS posting_code,
            (item->>'start_date')::date AS start_date,
            (item->>'end_date')::date AS end_date
        FROM pg_catalog.jsonb_array_elements(resolved_schedule) AS items(item)
    ),
    ranked AS (
        SELECT
            schedule_rows.*,
            pg_catalog.row_number() OVER (
                ORDER BY
                    CASE
                        WHEN schedule_rows.start_date <= CURRENT_DATE
                         AND schedule_rows.end_date >= CURRENT_DATE
                        THEN 0
                        WHEN schedule_rows.start_date > CURRENT_DATE
                        THEN 1
                        ELSE 2
                    END,
                    CASE
                        WHEN schedule_rows.start_date > CURRENT_DATE
                        THEN schedule_rows.start_date - CURRENT_DATE
                        ELSE CURRENT_DATE - schedule_rows.end_date
                    END,
                    schedule_rows.start_date DESC,
                    schedule_rows.posting_code
            ) AS current_rank
        FROM schedule_rows
    )
    SELECT
        ranked.programme_code,
        ranked.institution_code,
        ranked.posting_code,
        ranked.start_date,
        ranked.end_date,
        ranked.current_rank = 1
    FROM ranked
    ORDER BY ranked.start_date, ranked.end_date, ranked.posting_code;
END
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.register_external_resident(
    p_name text,
    p_mcr text,
    p_home_cluster text,
    p_schedule jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    normalized_name text := pg_catalog.btrim(p_name);
    normalized_mcr text := mata_private.normalize_mcr(p_mcr);
    resident_row record;
    schedule_row record;
    inserted_posting record;
    current_posting jsonb;
    posting_rows jsonb := '[]'::jsonb;
    current_posting_code text;
BEGIN
    IF p_name IS NULL
       OR p_mcr IS NULL
       OR p_home_cluster IS NULL
       OR normalized_name = ''
       OR pg_catalog.length(normalized_name) > 100
       OR normalized_mcr = ''
       OR pg_catalog.length(normalized_mcr) > 20
       OR p_home_cluster NOT IN ('NUH', 'SingHealth')
    THEN
        RAISE EXCEPTION 'Invalid Non-NHG Resident registration'
            USING ERRCODE = '22023';
    END IF;

    SELECT resolved.posting_code
    INTO current_posting_code
    FROM mata_private.resolve_external_schedule(p_schedule) AS resolved
    WHERE resolved.is_current;
    IF current_posting_code IS NULL THEN
        RAISE EXCEPTION 'Invalid posting schedule'
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO public.external_residents (
        name,
        mcr,
        home_cluster,
        current_nhg_posting_code,
        status
    )
    VALUES (
        normalized_name,
        normalized_mcr,
        p_home_cluster,
        current_posting_code,
        'active'
    )
    RETURNING
        external_residents.id,
        external_residents.name,
        external_residents.mcr,
        external_residents.home_cluster,
        external_residents.current_nhg_posting_code,
        external_residents.status
    INTO STRICT resident_row;

    FOR schedule_row IN
        SELECT *
        FROM mata_private.resolve_external_schedule(p_schedule)
        ORDER BY start_date, end_date, posting_code
    LOOP
        INSERT INTO public.external_resident_postings (
            external_resident_id,
            posting_code,
            programme_code,
            start_date,
            end_date,
            is_current
        )
        VALUES (
            resident_row.id,
            schedule_row.posting_code,
            schedule_row.programme_code,
            schedule_row.start_date,
            schedule_row.end_date,
            schedule_row.is_current
        )
        RETURNING
            external_resident_postings.id,
            external_resident_postings.external_resident_id,
            external_resident_postings.posting_code,
            external_resident_postings.programme_code,
            external_resident_postings.start_date,
            external_resident_postings.end_date,
            external_resident_postings.is_current
        INTO STRICT inserted_posting;

        posting_rows := posting_rows || pg_catalog.jsonb_build_array(
            pg_catalog.to_jsonb(inserted_posting)
        );
        IF schedule_row.is_current THEN
            current_posting := pg_catalog.to_jsonb(inserted_posting);
        END IF;
    END LOOP;

    RETURN pg_catalog.jsonb_build_object(
        'resident', pg_catalog.to_jsonb(resident_row),
        'posting_history', current_posting,
        'posting_schedule', posting_rows
    );
END
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.replace_external_resident_schedule(
    p_external_resident_id uuid,
    p_schedule jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    resident_row record;
    schedule_row record;
    inserted_posting record;
    posting_rows jsonb := '[]'::jsonb;
    current_posting_code text;
BEGIN
    IF p_external_resident_id IS NULL
       OR NOT mata_rls.is_external_resident(p_external_resident_id)
    THEN
        RAISE EXCEPTION 'Verified Non-NHG Resident owner context required'
            USING ERRCODE = 'MTR01';
    END IF;

    SELECT external_resident.*
    INTO resident_row
    FROM public.external_residents AS external_resident
    WHERE external_resident.id = p_external_resident_id
      AND external_resident.status = 'active'
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Verified Non-NHG Resident owner is unavailable'
            USING ERRCODE = 'MTR01';
    END IF;

    SELECT resolved.posting_code
    INTO current_posting_code
    FROM mata_private.resolve_external_schedule(p_schedule) AS resolved
    WHERE resolved.is_current;
    IF current_posting_code IS NULL THEN
        RAISE EXCEPTION 'Invalid posting schedule'
            USING ERRCODE = '22023';
    END IF;

    DELETE FROM public.external_resident_postings AS external_posting
    WHERE external_posting.external_resident_id = p_external_resident_id;

    FOR schedule_row IN
        SELECT *
        FROM mata_private.resolve_external_schedule(p_schedule)
        ORDER BY start_date, end_date, posting_code
    LOOP
        INSERT INTO public.external_resident_postings (
            external_resident_id,
            posting_code,
            programme_code,
            start_date,
            end_date,
            is_current
        )
        VALUES (
            p_external_resident_id,
            schedule_row.posting_code,
            schedule_row.programme_code,
            schedule_row.start_date,
            schedule_row.end_date,
            schedule_row.is_current
        )
        RETURNING
            external_resident_postings.id,
            external_resident_postings.external_resident_id,
            external_resident_postings.posting_code,
            external_resident_postings.programme_code,
            external_resident_postings.start_date,
            external_resident_postings.end_date,
            external_resident_postings.is_current
        INTO STRICT inserted_posting;
        posting_rows := posting_rows || pg_catalog.jsonb_build_array(
            pg_catalog.to_jsonb(inserted_posting)
        );
    END LOOP;

    UPDATE public.external_residents AS external_resident
    SET
        current_nhg_posting_code = current_posting_code,
        updated_at = pg_catalog.clock_timestamp()
    WHERE external_resident.id = p_external_resident_id
    RETURNING
        external_resident.id,
        external_resident.name,
        external_resident.mcr,
        external_resident.home_cluster,
        external_resident.current_nhg_posting_code,
        external_resident.status
    INTO STRICT resident_row;

    RETURN pg_catalog.jsonb_build_object(
        'resident', pg_catalog.to_jsonb(resident_row),
        'posting_schedule', posting_rows,
        'changed', true
    );
END
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.set_external_resident_current_posting(
    p_external_resident_id uuid,
    p_programme_code text,
    p_institution_code text
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    normalized_programme text := pg_catalog.upper(
        pg_catalog.btrim(p_programme_code)
    );
    normalized_institution text := pg_catalog.upper(
        pg_catalog.btrim(p_institution_code)
    );
    resolved_posting text;
    resident_row record;
    current_posting record;
    inserted_posting record;
    replacement_end_date date;
    next_future_start date;
BEGIN
    IF p_external_resident_id IS NULL
       OR NOT mata_rls.is_external_resident(p_external_resident_id)
    THEN
        RAISE EXCEPTION 'Verified Non-NHG Resident owner context required'
            USING ERRCODE = 'MTR01';
    END IF;
    IF p_programme_code IS NULL
       OR p_institution_code IS NULL
       OR normalized_programme = ''
       OR normalized_institution = ''
       OR pg_catalog.length(normalized_programme) > 20
       OR pg_catalog.length(normalized_institution) > 20
    THEN
        RAISE EXCEPTION 'Invalid posting mapping'
            USING ERRCODE = '22023';
    END IF;

    SELECT mapping.posting_code
    INTO resolved_posting
    FROM public.programme_institution_posting_map AS mapping
    JOIN public.programmes AS programme
      ON programme.code = mapping.programme_code
    JOIN public.posting_codes AS posting
      ON posting.code = mapping.posting_code
    WHERE mapping.programme_code = normalized_programme
      AND mapping.institution_code = normalized_institution
      AND mapping.status = 'active'
      AND mapping.posting_code IS NOT NULL
    FOR SHARE OF mapping;
    IF resolved_posting IS NULL THEN
        RAISE EXCEPTION 'Posting mapping is unavailable'
            USING ERRCODE = '22023';
    END IF;

    SELECT external_resident.*
    INTO resident_row
    FROM public.external_residents AS external_resident
    WHERE external_resident.id = p_external_resident_id
      AND external_resident.status = 'active'
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Verified Non-NHG Resident owner is unavailable'
            USING ERRCODE = 'MTR01';
    END IF;

    SELECT external_posting.*
    INTO current_posting
    FROM public.external_resident_postings AS external_posting
    WHERE external_posting.external_resident_id = p_external_resident_id
      AND external_posting.is_current
    FOR UPDATE;

    IF FOUND
       AND current_posting.posting_code = resolved_posting
       AND current_posting.programme_code = normalized_programme
    THEN
        RETURN pg_catalog.jsonb_build_object(
            'resident',
            pg_catalog.jsonb_build_object(
                'id', resident_row.id,
                'name', resident_row.name,
                'mcr', resident_row.mcr,
                'home_cluster', resident_row.home_cluster,
                'current_nhg_posting_code',
                    resident_row.current_nhg_posting_code,
                'status', resident_row.status
            ),
            'changed',
            false
        );
    END IF;

    IF FOUND AND current_posting.start_date >= CURRENT_DATE THEN
        UPDATE public.external_resident_postings AS external_posting
        SET
            posting_code = resolved_posting,
            programme_code = normalized_programme,
            updated_at = pg_catalog.clock_timestamp()
        WHERE external_posting.id = current_posting.id
        RETURNING
            external_posting.id,
            external_posting.external_resident_id,
            external_posting.posting_code,
            external_posting.programme_code,
            external_posting.start_date,
            external_posting.end_date,
            external_posting.is_current
        INTO STRICT inserted_posting;
    ELSE
        replacement_end_date := NULL;
        IF FOUND THEN
            IF current_posting.end_date IS NOT NULL
               AND current_posting.end_date >= CURRENT_DATE
            THEN
                replacement_end_date := current_posting.end_date;
            END IF;
            UPDATE public.external_resident_postings AS external_posting
            SET
                end_date = LEAST(
                    COALESCE(
                        external_posting.end_date,
                        CURRENT_DATE
                    ),
                    CURRENT_DATE - 1
                ),
                is_current = false,
                updated_at = pg_catalog.clock_timestamp()
            WHERE external_posting.id = current_posting.id;
        END IF;

        SELECT external_posting.start_date
        INTO next_future_start
        FROM public.external_resident_postings AS external_posting
        WHERE external_posting.external_resident_id = p_external_resident_id
          AND external_posting.start_date > CURRENT_DATE
          AND (
              current_posting.id IS NULL
              OR external_posting.id <> current_posting.id
          )
        ORDER BY external_posting.start_date, external_posting.id
        LIMIT 1;
        IF next_future_start IS NOT NULL THEN
            replacement_end_date := LEAST(
                COALESCE(
                    replacement_end_date,
                    next_future_start - 1
                ),
                next_future_start - 1
            );
        END IF;

        INSERT INTO public.external_resident_postings (
            external_resident_id,
            posting_code,
            programme_code,
            start_date,
            end_date,
            is_current
        )
        VALUES (
            p_external_resident_id,
            resolved_posting,
            normalized_programme,
            CURRENT_DATE,
            replacement_end_date,
            true
        )
        RETURNING
            external_resident_postings.id,
            external_resident_postings.external_resident_id,
            external_resident_postings.posting_code,
            external_resident_postings.programme_code,
            external_resident_postings.start_date,
            external_resident_postings.end_date,
            external_resident_postings.is_current
        INTO STRICT inserted_posting;
    END IF;

    UPDATE public.external_residents AS external_resident
    SET
        current_nhg_posting_code = resolved_posting,
        updated_at = pg_catalog.clock_timestamp()
    WHERE external_resident.id = p_external_resident_id
    RETURNING
        external_resident.id,
        external_resident.name,
        external_resident.mcr,
        external_resident.home_cluster,
        external_resident.current_nhg_posting_code,
        external_resident.status
    INTO STRICT resident_row;

    RETURN pg_catalog.jsonb_build_object(
        'resident', pg_catalog.to_jsonb(resident_row),
        'posting_history', pg_catalog.to_jsonb(inserted_posting),
        'changed', true
    );
END
$function$
"""
    )


def _create_rate_limit_helper() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.consume_rate_limit(
    p_scope text,
    p_key_hash text,
    p_limit integer,
    p_window_seconds integer,
    p_cleanup_retention_seconds integer,
    p_cleanup_batch_size integer
)
RETURNS TABLE (
    allowed boolean,
    request_count integer,
    retry_after_seconds integer,
    cleaned_count integer
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    observed_at timestamptz := pg_catalog.clock_timestamp();
    window_epoch numeric;
    bucket_window_start timestamptz;
    bucket_expires_at timestamptz;
    resulting_count integer;
    deleted_count integer := 0;
BEGIN
    IF p_scope IS NULL
       OR pg_catalog.btrim(p_scope) = ''
       OR pg_catalog.length(p_scope) > 100
       OR p_key_hash IS NULL
       OR p_key_hash !~ '^[0-9a-f]{64}$'
       OR p_limit IS NULL
       OR p_limit < 1
       OR p_limit > 1000000
       OR p_window_seconds IS NULL
       OR p_window_seconds < 1
       OR p_window_seconds > 86400
       OR p_cleanup_retention_seconds IS NULL
       OR p_cleanup_retention_seconds < 0
       OR p_cleanup_retention_seconds > 31536000
       OR p_cleanup_batch_size IS NULL
       OR p_cleanup_batch_size < 1
       OR p_cleanup_batch_size > 1000
    THEN
        RAISE EXCEPTION 'Invalid persistent rate-limit parameters'
            USING ERRCODE = '22023';
    END IF;

    window_epoch := (
        pg_catalog.floor(
            EXTRACT(epoch FROM observed_at)
            / p_window_seconds
        )
        * p_window_seconds
    );
    bucket_window_start := pg_catalog.to_timestamp(window_epoch);
    bucket_expires_at := (
        bucket_window_start
        + pg_catalog.make_interval(
            secs => p_window_seconds::double precision
        )
    );

    INSERT INTO public.rate_limit_buckets (
        scope,
        key_hash,
        window_start,
        window_seconds,
        request_count,
        expires_at
    )
    VALUES (
        pg_catalog.btrim(p_scope),
        p_key_hash,
        bucket_window_start,
        p_window_seconds,
        1,
        bucket_expires_at
    )
    ON CONFLICT (scope, key_hash, window_start, window_seconds)
    DO UPDATE
    SET
        request_count = rate_limit_buckets.request_count + 1,
        expires_at = EXCLUDED.expires_at,
        updated_at = observed_at
    RETURNING rate_limit_buckets.request_count
    INTO STRICT resulting_count;

    WITH cleanup_candidates AS (
        SELECT bucket.id
        FROM public.rate_limit_buckets AS bucket
        WHERE bucket.expires_at < (
            observed_at
            - pg_catalog.make_interval(
                secs => p_cleanup_retention_seconds::double precision
            )
        )
        ORDER BY bucket.expires_at, bucket.id
        LIMIT p_cleanup_batch_size
        FOR UPDATE SKIP LOCKED
    )
    DELETE FROM public.rate_limit_buckets AS bucket
    USING cleanup_candidates
    WHERE bucket.id = cleanup_candidates.id;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;

    allowed := resulting_count <= p_limit;
    request_count := resulting_count;
    retry_after_seconds := GREATEST(
        1,
        pg_catalog.ceil(
            EXTRACT(epoch FROM (bucket_expires_at - observed_at))
        )::integer
    );
    cleaned_count := deleted_count;
    RETURN NEXT;
END
$function$
"""
    )


def _create_ttf_helpers() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.resolve_ttf_session_type(
    p_name text,
    p_duration_hours numeric,
    p_duration_label text,
    p_programme_code text
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    normalized_name text := pg_catalog.btrim(p_name);
    normalized_programme text := pg_catalog.upper(
        pg_catalog.btrim(p_programme_code)
    );
    existing_session record;
    inserted_id uuid;
    master_allowed boolean := mata_rls.is_master_admin();
    programme_allowed boolean;
BEGIN
    programme_allowed := mata_rls.has_programme_scope(normalized_programme);
    IF NOT master_allowed AND NOT programme_allowed THEN
        RAISE EXCEPTION 'TTF programme scope required'
            USING ERRCODE = '42501';
    END IF;
    IF p_name IS NULL
       OR p_programme_code IS NULL
       OR normalized_name = ''
       OR pg_catalog.length(normalized_name) > 100
       OR p_duration_hours IS NULL
       OR p_duration_hours <= 0
       OR p_duration_hours > 99.99
       OR (
           p_duration_label IS NOT NULL
           AND pg_catalog.length(p_duration_label) > 10
       )
       OR normalized_programme = ''
    THEN
        RAISE EXCEPTION 'Invalid TTF session type'
            USING ERRCODE = '22023';
    END IF;

    SELECT session_type.*
    INTO existing_session
    FROM public.session_types AS session_type
    WHERE session_type.name = normalized_name
    FOR UPDATE;

    IF FOUND THEN
        IF existing_session.duration_hours = p_duration_hours
           AND existing_session.duration_label
               IS NOT DISTINCT FROM p_duration_label
        THEN
            RETURN existing_session.id;
        END IF;
        IF NOT master_allowed THEN
            RAISE EXCEPTION
                'Programme coordinators cannot alter a shared session type'
                USING ERRCODE = '42501';
        END IF;

        UPDATE public.session_types AS session_type
        SET
            duration_hours = p_duration_hours,
            duration_label = p_duration_label,
            updated_at = pg_catalog.clock_timestamp()
        WHERE session_type.id = existing_session.id
        RETURNING session_type.id
        INTO STRICT inserted_id;
        RETURN inserted_id;
    END IF;

    INSERT INTO public.session_types (
        name,
        duration_hours,
        duration_label
    )
    VALUES (
        normalized_name,
        p_duration_hours,
        p_duration_label
    )
    ON CONFLICT (name) DO NOTHING
    RETURNING session_types.id
    INTO inserted_id;

    IF inserted_id IS NOT NULL THEN
        RETURN inserted_id;
    END IF;

    -- Resolve a concurrent insert and re-apply the same conflict rule.
    SELECT session_type.*
    INTO STRICT existing_session
    FROM public.session_types AS session_type
    WHERE session_type.name = normalized_name
    FOR UPDATE;
    IF existing_session.duration_hours = p_duration_hours
       AND existing_session.duration_label IS NOT DISTINCT FROM p_duration_label
    THEN
        RETURN existing_session.id;
    END IF;
    IF NOT master_allowed THEN
        RAISE EXCEPTION
            'Programme coordinators cannot alter a shared session type'
            USING ERRCODE = '42501';
    END IF;
    UPDATE public.session_types AS session_type
    SET
        duration_hours = p_duration_hours,
        duration_label = p_duration_label,
        updated_at = pg_catalog.clock_timestamp()
    WHERE session_type.id = existing_session.id
    RETURNING session_type.id
    INTO STRICT inserted_id;
    RETURN inserted_id;
END
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.ensure_ttf_posting_code(
    p_code text,
    p_programme_code text
)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    normalized_code text := pg_catalog.btrim(p_code);
    normalized_programme text := pg_catalog.upper(
        pg_catalog.btrim(p_programme_code)
    );
    inserted_id uuid;
BEGIN
    IF NOT mata_rls.is_master_admin()
       AND NOT mata_rls.has_programme_scope(normalized_programme)
    THEN
        RAISE EXCEPTION 'TTF programme scope required'
            USING ERRCODE = '42501';
    END IF;
    IF p_code IS NULL
       OR p_programme_code IS NULL
       OR normalized_code = ''
       OR pg_catalog.length(normalized_code) > 50
       OR normalized_programme = ''
    THEN
        RAISE EXCEPTION 'Invalid TTF posting code'
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO public.posting_codes (code)
    VALUES (normalized_code)
    ON CONFLICT (code) DO NOTHING
    RETURNING posting_codes.id
    INTO inserted_id;
    RETURN inserted_id IS NOT NULL;
END
$function$
"""
    )


def _create_audit_dependency_and_surplus_helpers() -> None:
    _execute(
        r"""
ALTER TABLE public.audit_logs
ALTER COLUMN entity_id TYPE text
USING entity_id::text
"""
    )
    _execute(
        r"""
CREATE FUNCTION mata_rls.append_audit_log(
    p_action text,
    p_entity_type text,
    p_entity_id text,
    p_before_json jsonb,
    p_after_json jsonb,
    p_metadata_json jsonb
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    context_row record;
    staff_row record;
    audit_id uuid := public.gen_random_uuid();
    actor_programme text;
BEGIN
    SELECT *
    INTO context_row
    FROM mata_private.verified_context();
    IF NOT FOUND
       OR context_row.subject_type <> 'staff'
       OR context_row.app_role NOT IN ('admin', 'secretary')
    THEN
        RAISE EXCEPTION 'Verified staff context required'
            USING ERRCODE = '42501';
    END IF;
    IF pg_catalog.btrim(COALESCE(p_action, '')) = ''
       OR pg_catalog.length(pg_catalog.btrim(p_action)) > 80
       OR pg_catalog.btrim(COALESCE(p_entity_type, '')) = ''
       OR pg_catalog.length(pg_catalog.btrim(p_entity_type)) > 80
    THEN
        RAISE EXCEPTION 'Invalid audit labels'
            USING ERRCODE = '22023';
    END IF;

    SELECT staff.*
    INTO staff_row
    FROM public.users AS staff
    WHERE staff.id = context_row.subject_id
      AND staff.role = context_row.app_role
      AND staff.is_active
    FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Verified staff subject is unavailable'
            USING ERRCODE = '42501';
    END IF;

    IF context_row.app_role = 'admin'
       AND pg_catalog.cardinality(context_row.programme_scope) = 1
    THEN
        actor_programme := context_row.programme_scope[1];
    END IF;

    INSERT INTO public.audit_logs (
        id,
        actor_user_id,
        actor_role,
        actor_name,
        actor_site,
        actor_programme,
        actor_admin_level,
        action,
        entity_type,
        entity_id,
        before_json,
        after_json,
        metadata_json
    )
    VALUES (
        audit_id,
        context_row.subject_id,
        context_row.app_role,
        COALESCE(
            NULLIF(pg_catalog.btrim(staff_row.current_staff_actor_name), ''),
            staff_row.name
        ),
        CASE
            WHEN context_row.app_role = 'secretary'
            THEN context_row.posting_code
            ELSE NULL
        END,
        actor_programme,
        context_row.admin_level,
        pg_catalog.btrim(p_action),
        pg_catalog.btrim(p_entity_type),
        p_entity_id,
        p_before_json,
        p_after_json,
        p_metadata_json
    );
    RETURN audit_id;
END
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.update_own_staff_actor_name(p_actor_name text)
RETURNS TABLE (
    id uuid,
    email text,
    role text,
    name text,
    posting_code text,
    programme_scope text[],
    admin_level text,
    is_active boolean,
    current_staff_actor_name text,
    staff_actor_name_updated_at timestamptz,
    staff_actor_name_updated_by_user_id uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    context_row record;
    normalized_actor_name text := pg_catalog.btrim(p_actor_name);
BEGIN
    SELECT *
    INTO context_row
    FROM mata_private.verified_context();
    IF NOT FOUND
       OR context_row.subject_type <> 'staff'
       OR context_row.app_role NOT IN ('admin', 'secretary')
    THEN
        RAISE EXCEPTION 'Verified staff context required'
            USING ERRCODE = '42501';
    END IF;
    IF p_actor_name IS NULL
       OR normalized_actor_name = ''
       OR pg_catalog.length(normalized_actor_name) > 120
    THEN
        RAISE EXCEPTION 'Invalid staff actor name'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    UPDATE public.users AS staff
    SET
        current_staff_actor_name = normalized_actor_name,
        staff_actor_name_updated_at = pg_catalog.clock_timestamp(),
        staff_actor_name_updated_by_user_id = context_row.subject_id,
        updated_at = pg_catalog.clock_timestamp()
    WHERE staff.id = context_row.subject_id
      AND staff.role = context_row.app_role
      AND staff.is_active
    RETURNING
        staff.id,
        staff.email::text,
        staff.role::text,
        staff.name::text,
        staff.posting_code::text,
        CASE
            WHEN staff.role = 'admin'
            THEN mata_private.normalized_scope(staff.programme_scope)
            ELSE ARRAY[]::text[]
        END,
        CASE WHEN staff.role = 'admin' THEN staff.admin_level::text ELSE NULL END,
        staff.is_active,
        staff.current_staff_actor_name,
        staff.staff_actor_name_updated_at,
        staff.staff_actor_name_updated_by_user_id;
END
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.reporting_period_dependency_counts(
    p_reporting_period_id uuid
)
RETURNS TABLE (
    dependency_name text,
    dependency_count bigint
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF NOT mata_rls.is_master_admin() THEN
        RAISE EXCEPTION 'Master Admin context required'
            USING ERRCODE = '42501';
    END IF;
    IF p_reporting_period_id IS NULL THEN
        RAISE EXCEPTION 'Reporting period is required'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT 'upload_logs'::text, pg_catalog.count(*)
    FROM public.upload_logs
    WHERE reporting_period_id = p_reporting_period_id
    UNION ALL
    SELECT 'resident_postings', pg_catalog.count(*)
    FROM public.resident_postings
    WHERE reporting_period_id = p_reporting_period_id
    UNION ALL
    SELECT 'teaching_targets', pg_catalog.count(*)
    FROM public.teaching_targets
    WHERE reporting_period_id = p_reporting_period_id
    UNION ALL
    SELECT 'teaching_name_catalogue', pg_catalog.count(*)
    FROM public.teaching_name_catalogue
    WHERE reporting_period_id = p_reporting_period_id
    UNION ALL
    SELECT 'form_f1_records', pg_catalog.count(*)
    FROM public.form_f1_records
    WHERE reporting_period_id = p_reporting_period_id
    UNION ALL
    SELECT 'academic_month_boundaries', pg_catalog.count(*)
    FROM public.academic_month_boundaries AS boundary
    JOIN public.upload_logs AS upload_log
      ON upload_log.id = boundary.upload_id
    WHERE upload_log.reporting_period_id = p_reporting_period_id
    UNION ALL
    SELECT 'period_snapshots', pg_catalog.count(*)
    FROM public.period_snapshots
    WHERE reporting_period_id = p_reporting_period_id
    UNION ALL
    SELECT 'clawback_records', pg_catalog.count(*)
    FROM public.clawback_records
    WHERE reporting_period_id = p_reporting_period_id
    UNION ALL
    SELECT 'surplus_ledger', pg_catalog.count(*)
    FROM public.surplus_ledger
    WHERE reporting_period_id = p_reporting_period_id;
END
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.hibernate_stale_surplus(p_reporting_period_id uuid)
RETURNS bigint
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    affected_count bigint;
BEGIN
    IF NOT mata_rls.is_master_admin() THEN
        RAISE EXCEPTION 'Master Admin context required'
            USING ERRCODE = '42501';
    END IF;
    IF p_reporting_period_id IS NULL THEN
        RAISE EXCEPTION 'Reporting period is required'
            USING ERRCODE = '22023';
    END IF;

    UPDATE public.surplus_ledger AS surplus
    SET
        is_hibernating = true,
        updated_at = pg_catalog.clock_timestamp()
    WHERE surplus.reporting_period_id = p_reporting_period_id
      AND NOT surplus.is_hibernating
      AND NOT EXISTS (
          SELECT 1
          FROM public.resident_postings AS resident_posting
          WHERE resident_posting.resident_id = surplus.resident_id
            AND resident_posting.posting_code = surplus.posting_code
            AND resident_posting.reporting_period_id = p_reporting_period_id
            AND resident_posting.status IN ('active', 'loa_working')
      );
    GET DIAGNOSTICS affected_count = ROW_COUNT;
    RETURN affected_count;
END
$function$
"""
    )


def _apply_exact_helper_acls_and_assertions() -> None:
    _execute("REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA mata_rls FROM PUBLIC")
    _execute(
        "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA mata_private FROM PUBLIC"
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA mata_rls "
        "FROM mata_app_runtime, mata_auth_internal"
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA mata_private "
        "FROM mata_app_runtime, mata_auth_internal"
    )
    _execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA mata_rls "
        "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
    )
    _execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA mata_private "
        "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
    )

    _execute(
        r"""
DO $migration$
DECLARE
    optional_role text;
BEGIN
    FOREACH optional_role IN ARRAY ARRAY[
        'anon',
        'authenticated',
        'service_role'
    ]
    LOOP
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_roles
            WHERE rolname = optional_role
        ) THEN
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON SCHEMA mata_rls FROM %I',
                optional_role
            );
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON SCHEMA mata_private FROM %I',
                optional_role
            );
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA mata_rls FROM %I',
                optional_role
            );
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA mata_private FROM %I',
                optional_role
            );
        END IF;
    END LOOP;
END
$migration$;
"""
    )

    for signature in RUNTIME_ONLY_FUNCTIONS:
        _execute(
            f"GRANT EXECUTE ON FUNCTION mata_rls.{signature} "
            "TO mata_app_runtime"
        )
    for signature in AUTH_ONLY_FUNCTIONS:
        _execute(
            f"GRANT EXECUTE ON FUNCTION mata_rls.{signature} "
            "TO mata_auth_internal"
        )
    for signature in SHARED_FUNCTIONS:
        _execute(
            f"GRANT EXECUTE ON FUNCTION mata_rls.{signature} "
            "TO mata_app_runtime, mata_auth_internal"
        )

    _execute(
        r"""
DO $migration$
DECLARE
    unsafe_function text;
BEGIN
    SELECT pg_catalog.format(
        '%I.%I(%s)',
        namespace.nspname,
        procedure.proname,
        pg_catalog.pg_get_function_identity_arguments(procedure.oid)
    )
    INTO unsafe_function
    FROM pg_catalog.pg_proc AS procedure
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = procedure.pronamespace
    JOIN pg_catalog.pg_roles AS owner_role
      ON owner_role.oid = procedure.proowner
    WHERE namespace.nspname IN ('mata_private', 'mata_rls')
      AND (
          NOT procedure.prosecdef
          OR owner_role.rolname IN ('mata_app_runtime', 'mata_auth_internal')
          OR NOT (
              COALESCE(procedure.proconfig, ARRAY[]::text[])
              @> ARRAY['search_path=pg_catalog, pg_temp']
          )
      )
    ORDER BY namespace.nspname, procedure.proname
    LIMIT 1;
    IF unsafe_function IS NOT NULL THEN
        RAISE EXCEPTION
            'Unsafe helper definition: %',
            unsafe_function
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                procedure.proacl,
                pg_catalog.acldefault('f', procedure.proowner)
            )
        ) AS privilege
        WHERE namespace.nspname IN ('mata_private', 'mata_rls')
          AND privilege.grantee = 0
          AND privilege.privilege_type = 'EXECUTE'
    ) THEN
        RAISE EXCEPTION
            'PUBLIC execute remains on an H-E helper'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                relation.relacl,
                pg_catalog.acldefault(
                    CASE
                        WHEN relation.relkind = 'S' THEN 'S'::"char"
                        ELSE 'r'::"char"
                    END,
                    relation.relowner
                )
            )
        ) AS privilege
        JOIN pg_catalog.pg_roles AS grantee_role
          ON grantee_role.oid = privilege.grantee
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'S')
          AND grantee_role.rolname IN (
              'mata_app_runtime',
              'mata_auth_internal'
          )
    ) THEN
        RAISE EXCEPTION
            'Foundation roles must not have direct public object grants'
            USING ERRCODE = '42501';
    END IF;
END
$migration$;
"""
    )


def upgrade() -> None:
    _create_roles_and_schemas()
    _create_private_context_foundation()
    _create_private_session_hydrator()
    _create_context_installer_and_accessors()
    _create_global_mcr_enforcement()
    _create_session_service_helpers()
    _create_login_helpers()
    _create_external_registration_helpers()
    _create_rate_limit_helper()
    _create_ttf_helpers()
    _create_audit_dependency_and_surplus_helpers()
    _apply_exact_helper_acls_and_assertions()


def downgrade() -> None:
    # Fail before removing any helper if post-upgrade text audit identifiers
    # cannot be losslessly restored to the pre-H-E UUID column.
    _execute(
        r"""
DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.audit_logs AS audit_log
        WHERE audit_log.entity_id IS NOT NULL
          AND audit_log.entity_id !~
              '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
              '[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
    ) THEN
        RAISE EXCEPTION
            'Cannot downgrade audit_logs.entity_id: non-UUID keys exist'
            USING ERRCODE = '22023';
    END IF;
END
$migration$;
"""
    )

    _execute(
        "REVOKE ALL PRIVILEGES ON SCHEMA mata_rls "
        "FROM mata_app_runtime, mata_auth_internal"
    )
    for signature in reversed(
        (*RUNTIME_ONLY_FUNCTIONS, *AUTH_ONLY_FUNCTIONS, *SHARED_FUNCTIONS)
    ):
        _execute(f"DROP FUNCTION IF EXISTS mata_rls.{signature}")

    _execute(
        "DROP TRIGGER IF EXISTS trg_external_residents_global_mcr_uniqueness "
        "ON public.external_residents"
    )
    _execute(
        "DROP TRIGGER IF EXISTS trg_residents_global_mcr_uniqueness "
        "ON public.residents"
    )

    for signature in reversed(PRIVATE_FUNCTIONS):
        _execute(f"DROP FUNCTION IF EXISTS mata_private.{signature}")

    _execute("DROP TABLE mata_private.context_signing_key")
    _execute("DROP SCHEMA mata_rls")
    _execute("DROP SCHEMA mata_private")

    _execute(
        r"""
ALTER TABLE public.audit_logs
ALTER COLUMN entity_id TYPE uuid
USING entity_id::uuid
"""
    )
    # Roles are intentionally retained: they may already be bound to external
    # credentialed LOGIN roles.  Browser grants/defaults are never restored.
