"""close D/F/G scheduled-source authorization and overlap gaps

Revision ID: 20260804_000035
Revises: 20260804_000034
Create Date: 2026-08-04

Persist immutable pool provenance, make event RLS row-local for INSERT
RETURNING, remove catalogue/display-text authorization, retain inactive global
history, enforce exact owner/source equality, and compare full datetime
intervals for native and external attendance.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260804_000035"
down_revision = "20260804_000034"
branch_labels = None
depends_on = None


RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"
DEFINER_ROLE = "mata_adhoc_attendance_definer"
OPTIONAL_BROWSER_ROLES = ("anon", "authenticated", "service_role")

SELECT_ROW_SIGNATURE = (
    "can_select_teaching_event_row("
    "uuid,boolean,text,date,text,text,uuid,uuid,uuid,uuid,text,uuid)"
)
MANAGE_ROW_SIGNATURE = (
    "can_manage_teaching_event_row("
    "text,text,date,boolean,text,uuid,uuid,text,uuid)"
)
INSERT_SOURCE_SIGNATURE = (
    "can_insert_scheduled_event_source("
    "text,text,uuid,uuid,text,uuid,date,boolean,text)"
)
SOURCE_SCOPE_SIGNATURE = "scheduled_event_source_scope(uuid)"
OVERLAP_TRIGGER_SIGNATURE = "enforce_attendance_no_overlap()"
PROVENANCE_TRIGGER_SIGNATURE = "enforce_teaching_event_source_provenance_immutable()"


def _execute(statement: str) -> None:
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(statement)


def _revoke_optional_function_privileges(
    schema_name: str,
    function_signature: str,
) -> None:
    optional_roles = ", ".join(repr(role) for role in OPTIONAL_BROWSER_ROLES)
    _execute(
        f"""
DO $migration$
DECLARE
    optional_role text;
BEGIN
    FOREACH optional_role IN ARRAY ARRAY[{optional_roles}]::text[]
    LOOP
        IF pg_catalog.to_regrole(optional_role) IS NOT NULL THEN
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON FUNCTION {schema_name}.{function_signature} FROM %I',
                optional_role
            );
        END IF;
    END LOOP;
END
$migration$
"""
    )


def _secure_runtime_helper(function_signature: str) -> None:
    _execute(
        f"REVOKE ALL PRIVILEGES ON FUNCTION mata_rls.{function_signature} "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        f"GRANT EXECUTE ON FUNCTION mata_rls.{function_signature} TO {RUNTIME_ROLE}"
    )
    _revoke_optional_function_privileges("mata_rls", function_signature)


def _secure_private_helper(function_signature: str) -> None:
    _execute(
        f"REVOKE ALL PRIVILEGES ON FUNCTION mata_private.{function_signature} "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _revoke_optional_function_privileges("mata_private", function_signature)


def _grant_definer_ownership() -> None:
    _execute(
        rf"""
DO $migration$
DECLARE
    migration_role_is_superuser boolean;
BEGIN
    IF CURRENT_USER <> SESSION_USER THEN
        RAISE EXCEPTION 'Migration role must be the direct session role'
            USING ERRCODE = '42501';
    END IF;
    SELECT rolsuper INTO STRICT migration_role_is_superuser
    FROM pg_catalog.pg_roles WHERE rolname = SESSION_USER;
    IF NOT migration_role_is_superuser THEN
        EXECUTE pg_catalog.format(
            'GRANT %I TO %I WITH INHERIT FALSE GRANTED BY %I',
            '{DEFINER_ROLE}', SESSION_USER, SESSION_USER
        );
        EXECUTE pg_catalog.format(
            'GRANT %I TO %I WITH SET TRUE GRANTED BY %I',
            '{DEFINER_ROLE}', SESSION_USER, SESSION_USER
        );
        EXECUTE pg_catalog.format(
            'GRANT %I TO %I WITH ADMIN FALSE GRANTED BY %I',
            '{DEFINER_ROLE}', SESSION_USER, SESSION_USER
        );
    END IF;
END
$migration$
"""
    )


def _revoke_definer_ownership() -> None:
    _execute(
        rf"""
DO $migration$
DECLARE
    migration_role_is_superuser boolean;
BEGIN
    SELECT rolsuper INTO STRICT migration_role_is_superuser
    FROM pg_catalog.pg_roles WHERE rolname = SESSION_USER;
    IF NOT migration_role_is_superuser THEN
        EXECUTE pg_catalog.format(
            'REVOKE %I FROM %I GRANTED BY %I RESTRICT',
            '{DEFINER_ROLE}', SESSION_USER, SESSION_USER
        );
    END IF;
END
$migration$
"""
    )


def _add_source_provenance() -> None:
    op.add_column(
        "teaching_events",
        sa.Column("source_programme_code", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "teaching_events",
        sa.Column("source_reporting_period_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_teaching_events_source_programme_code_programmes",
        "teaching_events",
        "programmes",
        ["source_programme_code"],
        ["code"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_teaching_events_source_reporting_period_id_reporting_periods",
        "teaching_events",
        "reporting_periods",
        ["source_reporting_period_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    _execute(
        r"""
DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.teaching_events AS event
        JOIN public.teaching_names AS teaching_name
          ON teaching_name.id = event.teaching_name_id
        JOIN public.reporting_periods AS period
          ON period.id = teaching_name.reporting_period_id
        WHERE event.teaching_name_id IS NOT NULL
          AND (
              event.is_adhoc
              OR event.global_session_type_id IS NOT NULL
              OR event.event_date NOT BETWEEN period.start_date AND period.end_date
              OR (
                  event.created_for_programme_code IS NOT NULL
                  AND event.created_for_programme_code <> teaching_name.programme_code
              )
          )
    ) THEN
        RAISE EXCEPTION
            'Explicit Teaching Name event provenance is contradictory';
    END IF;
END
$migration$
"""
    )
    _execute(
        """
UPDATE public.teaching_events AS event
SET
    source_programme_code = teaching_name.programme_code,
    source_reporting_period_id = teaching_name.reporting_period_id
FROM public.teaching_names AS teaching_name
WHERE teaching_name.id = event.teaching_name_id
  AND event.teaching_name_id IS NOT NULL
"""
    )

    op.create_check_constraint(
        "ck_teaching_events_source_scope_pair",
        "teaching_events",
        "(source_programme_code IS NULL) = (source_reporting_period_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_teaching_events_pool_source_scope_required",
        "teaching_events",
        "teaching_name_id IS NULL OR "
        "(source_programme_code IS NOT NULL AND source_reporting_period_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_teaching_events_adhoc_has_no_scheduled_source",
        "teaching_events",
        "NOT is_adhoc OR (teaching_name_id IS NULL "
        "AND global_session_type_id IS NULL "
        "AND source_programme_code IS NULL "
        "AND source_reporting_period_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_teaching_events_global_has_no_pool_scope",
        "teaching_events",
        "global_session_type_id IS NULL OR "
        "(source_programme_code IS NULL AND source_reporting_period_id IS NULL)",
    )
    op.create_index(
        "idx_teaching_events_source_scope",
        "teaching_events",
        ["source_reporting_period_id", "source_programme_code"],
        postgresql_where=sa.text("source_reporting_period_id IS NOT NULL"),
    )


def _create_provenance_trigger() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_private.enforce_teaching_event_source_provenance_immutable()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF OLD.created_for_programme_code
           IS DISTINCT FROM NEW.created_for_programme_code
       OR OLD.source_programme_code
           IS DISTINCT FROM NEW.source_programme_code
       OR OLD.source_reporting_period_id
           IS DISTINCT FROM NEW.source_reporting_period_id
    THEN
        RAISE EXCEPTION
            'Teaching-event owner and source provenance are immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$
"""
    )
    _execute(
        """
CREATE TRIGGER mata_enforce_teaching_event_source_provenance_immutable
BEFORE UPDATE OF
    created_for_programme_code,
    source_programme_code,
    source_reporting_period_id
ON public.teaching_events
FOR EACH ROW
EXECUTE FUNCTION mata_private.enforce_teaching_event_source_provenance_immutable()
"""
    )
    _secure_private_helper(PROVENANCE_TRIGGER_SIGNATURE)


def _create_source_validation_helper() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_private.scheduled_event_source_is_valid(
    p_event_date date,
    p_teaching_name_id uuid,
    p_global_session_type_id uuid,
    p_source_programme_code text,
    p_source_reporting_period_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT CASE
        WHEN (p_source_programme_code IS NULL)
             <> (p_source_reporting_period_id IS NULL)
        THEN false
        WHEN p_source_programme_code IS NOT NULL THEN
            p_global_session_type_id IS NULL
            AND EXISTS (
                SELECT 1
                FROM public.reporting_periods AS period
                WHERE period.id = p_source_reporting_period_id
                  AND p_event_date BETWEEN period.start_date AND period.end_date
            )
            AND (
                p_teaching_name_id IS NULL
                OR EXISTS (
                    SELECT 1
                    FROM public.teaching_names AS teaching_name
                    WHERE teaching_name.id = p_teaching_name_id
                      AND teaching_name.programme_code = p_source_programme_code
                      AND teaching_name.reporting_period_id
                          = p_source_reporting_period_id
                )
            )
        WHEN p_teaching_name_id IS NOT NULL THEN false
        WHEN p_global_session_type_id IS NOT NULL THEN EXISTS (
            SELECT 1
            FROM public.global_session_types AS global_type
            WHERE global_type.id = p_global_session_type_id
        )
        ELSE true
    END
$function$
"""
    )
    _secure_private_helper(
        "scheduled_event_source_is_valid(date,uuid,uuid,text,uuid)"
    )


def _create_row_local_selection_helper() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.can_select_teaching_event_row(
    p_event_id uuid,
    p_is_adhoc boolean,
    p_posting_code text,
    p_event_date date,
    p_created_for_programme_code text,
    p_created_by_role text,
    p_created_by_resident_id uuid,
    p_created_by_external_resident_id uuid,
    p_teaching_name_id uuid,
    p_global_session_type_id uuid,
    p_source_programme_code text,
    p_source_reporting_period_id uuid
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    subject_type text := mata_rls.current_subject_type();
    subject_id uuid := mata_rls.current_subject_id();
    app_role text := mata_rls.current_app_role();
    is_pool_source boolean := p_source_programme_code IS NOT NULL;
    is_global_source boolean := p_global_session_type_id IS NOT NULL;
BEGIN
    IF COALESCE(p_is_adhoc, false) THEN
        IF p_teaching_name_id IS NOT NULL
           OR p_global_session_type_id IS NOT NULL
           OR p_source_programme_code IS NOT NULL
           OR p_source_reporting_period_id IS NOT NULL
        THEN
            RETURN false;
        END IF;
        IF mata_rls.is_master_admin() THEN
            RETURN true;
        END IF;
        IF subject_type = 'resident' THEN
            RETURN p_created_by_resident_id = subject_id
               AND p_created_by_external_resident_id IS NULL;
        END IF;
        IF subject_type = 'external_resident' THEN
            RETURN p_created_by_external_resident_id = subject_id
               AND p_created_by_resident_id IS NULL;
        END IF;
        IF subject_type = 'staff' AND app_role = 'admin' THEN
            RETURN (
                p_created_by_resident_id IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM public.residents AS resident
                    WHERE resident.id = p_created_by_resident_id
                      AND resident.programme_code IS NOT NULL
                      AND mata_rls.has_programme_scope(resident.programme_code)
                )
            ) OR (
                p_created_by_external_resident_id IS NOT NULL
                AND EXISTS (
                    SELECT 1
                    FROM public.external_resident_postings AS external_posting
                    WHERE external_posting.external_resident_id
                        = p_created_by_external_resident_id
                      AND external_posting.posting_code = p_posting_code
                      AND external_posting.programme_code IS NOT NULL
                      AND external_posting.start_date <= p_event_date
                      AND COALESCE(external_posting.end_date, 'infinity'::date)
                          >= p_event_date
                      AND NOT EXISTS (
                          SELECT 1
                          FROM public.external_resident_postings AS competing
                          WHERE competing.external_resident_id
                              = p_created_by_external_resident_id
                            AND competing.start_date <= p_event_date
                            AND COALESCE(competing.end_date, 'infinity'::date)
                                >= p_event_date
                            AND competing.id <> external_posting.id
                      )
                      AND mata_rls.has_programme_scope(
                          external_posting.programme_code
                      )
                )
            );
        END IF;
        RETURN false;
    END IF;

    IF NOT (
        p_created_by_role IN ('secretary', 'programme_pc')
        OR p_created_by_role IS NULL
    ) OR NOT mata_private.scheduled_event_source_is_valid(
        p_event_date,
        p_teaching_name_id,
        p_global_session_type_id,
        p_source_programme_code,
        p_source_reporting_period_id
    ) OR (
        is_pool_source
        AND p_created_for_programme_code IS NOT NULL
        AND p_created_for_programme_code <> p_source_programme_code
    ) THEN
        RETURN false;
    END IF;

    IF mata_rls.is_master_admin() THEN
        RETURN true;
    END IF;

    IF subject_type = 'staff' AND app_role = 'admin' THEN
        IF is_pool_source THEN
            RETURN mata_rls.has_programme_scope(p_source_programme_code);
        END IF;
        IF p_created_for_programme_code IS NOT NULL THEN
            RETURN mata_rls.has_programme_scope(
                p_created_for_programme_code
            );
        END IF;
        RETURN EXISTS (
            SELECT 1
            FROM public.secretary_programme_pools AS pool
            WHERE pool.posting_code = p_posting_code
              AND pool.is_active
              AND mata_rls.has_programme_scope(pool.programme_code)
        ) OR EXISTS (
            SELECT 1
            FROM public.attendance_records AS attendance
            JOIN public.residents AS resident
              ON resident.id = attendance.resident_id
            WHERE attendance.teaching_event_id = p_event_id
              AND resident.programme_code IS NOT NULL
              AND mata_rls.has_programme_scope(resident.programme_code)
        ) OR EXISTS (
            SELECT 1
            FROM public.external_attendance_records AS attendance
            JOIN public.external_resident_postings AS external_posting
              ON external_posting.external_resident_id
                  = attendance.external_resident_id
             AND external_posting.posting_code = p_posting_code
             AND external_posting.start_date <= p_event_date
             AND COALESCE(external_posting.end_date, 'infinity'::date)
                 >= p_event_date
            WHERE attendance.teaching_event_id = p_event_id
              AND external_posting.programme_code IS NOT NULL
              AND mata_rls.has_programme_scope(external_posting.programme_code)
        );
    END IF;

    IF subject_type = 'staff' AND app_role = 'secretary' THEN
        IF NOT mata_rls.is_secretary_for_posting(p_posting_code) THEN
            RETURN false;
        END IF;
        IF is_pool_source THEN
            RETURN EXISTS (
                SELECT 1
                FROM public.secretary_programme_pools AS pool
                WHERE pool.posting_code = p_posting_code
                  AND pool.programme_code = p_source_programme_code
                  AND pool.is_active
                  AND pool.can_manage_teaching_names
            );
        END IF;
        RETURN p_created_for_programme_code IS NULL
            OR EXISTS (
                SELECT 1
                FROM public.secretary_programme_pools AS pool
                WHERE pool.posting_code = p_posting_code
                  AND pool.programme_code = p_created_for_programme_code
                  AND pool.is_active
            );
    END IF;

    IF subject_type = 'resident' THEN
        RETURN EXISTS (
            SELECT 1
            FROM public.residents AS resident
            JOIN public.programmes AS programme
              ON programme.code = resident.programme_code
            JOIN public.resident_postings AS resident_posting
              ON resident_posting.resident_id = resident.id
             AND resident_posting.start_date <= p_event_date
             AND resident_posting.end_date >= p_event_date
             AND resident_posting.status IN ('active', 'loa_working')
            WHERE resident.id = subject_id
              AND resident.status = 'active'
              AND (
                  p_created_for_programme_code IS NULL
                  OR p_created_for_programme_code = resident.programme_code
              )
              AND (
                  resident_posting.posting_code = p_posting_code
                  OR programme.native_teaching_posting_code = p_posting_code
              )
              AND (
                  is_global_source
                  OR (
                      is_pool_source
                      AND p_source_programme_code = resident.programme_code
                      AND p_source_reporting_period_id
                          = resident_posting.reporting_period_id
                  )
                  OR (
                      NOT is_pool_source
                      AND NOT is_global_source
                  )
              )
        );
    END IF;

    IF subject_type = 'external_resident' THEN
        RETURN EXISTS (
            SELECT 1
            FROM public.external_residents AS external_resident
            JOIN public.external_resident_postings AS external_posting
              ON external_posting.external_resident_id = external_resident.id
             AND external_posting.start_date <= p_event_date
             AND COALESCE(external_posting.end_date, 'infinity'::date)
                 >= p_event_date
            JOIN public.posting_codes AS posting
              ON posting.code = external_posting.posting_code
            WHERE external_resident.id = subject_id
              AND external_resident.status = 'active'
              AND external_posting.posting_code = p_posting_code
              AND NOT EXISTS (
                  SELECT 1
                  FROM public.external_resident_postings AS competing
                  WHERE competing.external_resident_id = external_resident.id
                    AND competing.start_date <= p_event_date
                    AND COALESCE(competing.end_date, 'infinity'::date)
                        >= p_event_date
                    AND competing.id <> external_posting.id
              )
              AND (
                  (
                      p_created_for_programme_code IS NULL
                      AND posting.supports_secretary_events
                  )
                  OR (
                      p_created_for_programme_code IS NOT NULL
                      AND external_posting.programme_code IS NOT NULL
                      AND p_created_for_programme_code
                          = external_posting.programme_code
                  )
              )
              AND (
                  is_global_source
                  OR (
                      is_pool_source
                      AND external_posting.programme_code IS NOT NULL
                      AND p_source_programme_code
                          = external_posting.programme_code
                  )
                  OR (
                      NOT is_pool_source
                      AND NOT is_global_source
                  )
              )
        );
    END IF;

    RETURN false;
END
$function$
"""
    )
    _execute(
        r"""
CREATE OR REPLACE FUNCTION mata_rls.can_select_teaching_event(p_event_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT COALESCE((
        SELECT mata_rls.can_select_teaching_event_row(
            event.id,
            event.is_adhoc,
            event.posting_code,
            event.event_date,
            event.created_for_programme_code,
            event.created_by_role,
            event.created_by_resident_id,
            event.created_by_external_resident_id,
            event.teaching_name_id,
            event.global_session_type_id,
            event.source_programme_code,
            event.source_reporting_period_id
        )
        FROM public.teaching_events AS event
        WHERE event.id = p_event_id
    ), false)
$function$
"""
    )
    for signature in (SELECT_ROW_SIGNATURE, "can_select_teaching_event(uuid)"):
        _secure_runtime_helper(signature)


def _create_write_helpers() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.can_insert_scheduled_event_source(
    p_posting_code text,
    p_created_for_programme_code text,
    p_teaching_name_id uuid,
    p_global_session_type_id uuid,
    p_source_programme_code text,
    p_source_reporting_period_id uuid,
    p_event_date date,
    p_is_adhoc boolean,
    p_created_by_role text
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF COALESCE(p_is_adhoc, false)
       OR (p_teaching_name_id IS NULL) = (p_global_session_type_id IS NULL)
    THEN
        RETURN false;
    END IF;

    IF p_teaching_name_id IS NOT NULL THEN
        IF p_source_programme_code IS NULL
           OR p_source_reporting_period_id IS NULL
           OR NOT EXISTS (
               SELECT 1
               FROM public.teaching_names AS teaching_name
               JOIN public.reporting_periods AS period
                 ON period.id = teaching_name.reporting_period_id
               WHERE teaching_name.id = p_teaching_name_id
                 AND teaching_name.is_active
                 AND teaching_name.programme_code = p_source_programme_code
                 AND teaching_name.reporting_period_id
                     = p_source_reporting_period_id
                 AND p_event_date BETWEEN period.start_date AND period.end_date
           )
        THEN
            RETURN false;
        END IF;

        IF p_created_for_programme_code IS NOT NULL
           AND p_created_for_programme_code <> p_source_programme_code
        THEN
            RETURN false;
        END IF;

        IF mata_rls.is_master_admin() THEN
            RETURN true;
        END IF;
        IF mata_rls.current_subject_type() = 'staff'
           AND mata_rls.current_app_role() = 'admin'
           AND p_created_by_role = 'programme_pc'
        THEN
            RETURN p_created_for_programme_code = p_source_programme_code
               AND mata_rls.has_programme_scope(p_source_programme_code);
        END IF;
        RETURN mata_rls.current_subject_type() = 'staff'
           AND mata_rls.current_app_role() = 'secretary'
           AND p_created_by_role = 'secretary'
           AND p_created_for_programme_code IS NULL
           AND mata_rls.is_secretary_for_posting(p_posting_code)
           AND EXISTS (
               SELECT 1
               FROM public.secretary_programme_pools AS pool
               WHERE pool.posting_code = p_posting_code
                 AND pool.programme_code = p_source_programme_code
                 AND pool.is_active
                 AND pool.can_manage_teaching_names
           );
    END IF;

    IF p_source_programme_code IS NOT NULL
       OR p_source_reporting_period_id IS NOT NULL
       OR NOT EXISTS (
           SELECT 1
           FROM public.global_session_types AS global_type
           WHERE global_type.id = p_global_session_type_id
             AND global_type.is_active
       )
    THEN
        RETURN false;
    END IF;
    IF mata_rls.is_master_admin() THEN
        RETURN true;
    END IF;
    IF mata_rls.current_subject_type() = 'staff'
       AND mata_rls.current_app_role() = 'admin'
       AND p_created_by_role = 'programme_pc'
    THEN
        RETURN p_created_for_programme_code IS NOT NULL
           AND mata_rls.has_programme_scope(p_created_for_programme_code)
           AND EXISTS (
               SELECT 1
               FROM public.secretary_programme_pools AS pool
               WHERE pool.programme_code = p_created_for_programme_code
                 AND pool.posting_code = p_posting_code
                 AND pool.is_active
           );
    END IF;
    RETURN mata_rls.current_subject_type() = 'staff'
       AND mata_rls.current_app_role() = 'secretary'
       AND p_created_by_role = 'secretary'
       AND p_created_for_programme_code IS NULL
       AND mata_rls.is_secretary_for_posting(p_posting_code);
END
$function$
"""
    )

    _execute(
        r"""
CREATE FUNCTION mata_rls.can_manage_teaching_event_row(
    p_posting_code text,
    p_created_for_programme_code text,
    p_event_date date,
    p_is_adhoc boolean,
    p_created_by_role text,
    p_teaching_name_id uuid,
    p_global_session_type_id uuid,
    p_source_programme_code text,
    p_source_reporting_period_id uuid
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    is_pool_source boolean := p_source_programme_code IS NOT NULL;
BEGIN
    IF COALESCE(p_is_adhoc, false)
       OR NOT (
           p_created_by_role IN ('secretary', 'programme_pc')
           OR p_created_by_role IS NULL
       )
       OR NOT mata_private.scheduled_event_source_is_valid(
           p_event_date,
           p_teaching_name_id,
           p_global_session_type_id,
           p_source_programme_code,
           p_source_reporting_period_id
       )
       OR (
           is_pool_source
           AND p_created_for_programme_code IS NOT NULL
           AND p_created_for_programme_code <> p_source_programme_code
       )
    THEN
        RETURN false;
    END IF;

    IF mata_rls.is_master_admin() THEN
        RETURN true;
    END IF;

    IF mata_rls.current_subject_type() = 'staff'
       AND mata_rls.current_app_role() = 'admin'
    THEN
        IF is_pool_source THEN
            RETURN mata_rls.has_programme_scope(p_source_programme_code);
        END IF;
        IF p_created_for_programme_code IS NOT NULL THEN
            RETURN mata_rls.has_programme_scope(
                p_created_for_programme_code
            );
        END IF;
        RETURN EXISTS (
            SELECT 1
            FROM public.secretary_programme_pools AS pool
            WHERE pool.posting_code = p_posting_code
              AND pool.is_active
              AND mata_rls.has_programme_scope(pool.programme_code)
        );
    END IF;

    IF mata_rls.current_subject_type() = 'staff'
       AND mata_rls.current_app_role() = 'secretary'
       AND mata_rls.is_secretary_for_posting(p_posting_code)
    THEN
        IF is_pool_source THEN
            RETURN EXISTS (
                SELECT 1
                FROM public.secretary_programme_pools AS pool
                WHERE pool.posting_code = p_posting_code
                  AND pool.programme_code = p_source_programme_code
                  AND pool.is_active
                  AND pool.can_manage_teaching_names
            );
        END IF;
        RETURN p_created_for_programme_code IS NULL
            OR EXISTS (
                SELECT 1
                FROM public.secretary_programme_pools AS pool
                WHERE pool.posting_code = p_posting_code
                  AND pool.programme_code = p_created_for_programme_code
                  AND pool.is_active
            );
    END IF;
    RETURN false;
END
$function$
"""
    )

    _execute(
        r"""
CREATE OR REPLACE FUNCTION mata_rls.can_manage_teaching_event(
    p_posting_code text,
    p_created_for_programme_code text,
    p_teaching_name text,
    p_event_date date,
    p_is_adhoc boolean,
    p_created_by_role text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT mata_rls.is_master_admin()
        OR (
            mata_rls.current_subject_type() = 'staff'
            AND mata_rls.current_app_role() = 'admin'
            AND NOT COALESCE(p_is_adhoc, false)
            AND (
                p_created_by_role IN ('secretary', 'programme_pc')
                OR p_created_by_role IS NULL
            )
            AND (
                (
                    p_created_for_programme_code IS NOT NULL
                    AND mata_rls.has_programme_scope(
                        p_created_for_programme_code
                    )
                )
                OR (
                    p_created_for_programme_code IS NULL
                    AND EXISTS (
                        SELECT 1
                        FROM public.secretary_programme_pools AS pool
                        WHERE pool.posting_code = p_posting_code
                          AND pool.is_active
                          AND mata_rls.has_programme_scope(pool.programme_code)
                    )
                )
            )
        )
        OR (
            mata_rls.current_subject_type() = 'staff'
            AND mata_rls.current_app_role() = 'secretary'
            AND NOT COALESCE(p_is_adhoc, false)
            AND mata_rls.is_secretary_for_posting(p_posting_code)
            AND (
                p_created_for_programme_code IS NULL
                OR EXISTS (
                    SELECT 1
                    FROM public.secretary_programme_pools AS pool
                    WHERE pool.posting_code = p_posting_code
                      AND pool.programme_code = p_created_for_programme_code
                      AND pool.is_active
                )
            )
        )
$function$
"""
    )
    for signature in (
        INSERT_SOURCE_SIGNATURE,
        MANAGE_ROW_SIGNATURE,
        "can_manage_teaching_event(text,text,text,date,boolean,text)",
    ):
        _secure_runtime_helper(signature)


def _replace_event_policies() -> None:
    for operation in ("select", "insert", "update", "delete"):
        _execute(
            f'DROP POLICY "mata_rls_teaching_events_{operation}" '
            "ON public.teaching_events"
        )
    row_call = """
mata_rls.can_select_teaching_event_row(
    id,
    is_adhoc,
    posting_code,
    event_date,
    created_for_programme_code,
    created_by_role,
    created_by_resident_id,
    created_by_external_resident_id,
    teaching_name_id,
    global_session_type_id,
    source_programme_code,
    source_reporting_period_id
)
"""
    manage_call = """
mata_rls.can_manage_teaching_event_row(
    posting_code,
    created_for_programme_code,
    event_date,
    is_adhoc,
    created_by_role,
    teaching_name_id,
    global_session_type_id,
    source_programme_code,
    source_reporting_period_id
)
"""
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_events_select"
ON public.teaching_events
AS PERMISSIVE
FOR SELECT
TO {RUNTIME_ROLE}
USING ({row_call})
"""
    )
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_events_insert"
ON public.teaching_events
AS PERMISSIVE
FOR INSERT
TO {RUNTIME_ROLE}
WITH CHECK (
    (
        NOT COALESCE(is_adhoc, false)
        AND mata_rls.can_insert_scheduled_event_source(
            posting_code,
            created_for_programme_code,
            teaching_name_id,
            global_session_type_id,
            source_programme_code,
            source_reporting_period_id,
            event_date,
            is_adhoc,
            created_by_role
        )
    )
    OR (
        COALESCE(is_adhoc, false)
        AND mata_rls.can_insert_teaching_event(
            posting_code,
            created_for_programme_code,
            teaching_name,
            event_date,
            is_adhoc,
            created_by_role
        )
    )
)
"""
    )
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_events_update"
ON public.teaching_events
AS PERMISSIVE
FOR UPDATE
TO {RUNTIME_ROLE}
USING ({manage_call})
WITH CHECK ({manage_call})
"""
    )
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_events_delete"
ON public.teaching_events
AS PERMISSIVE
FOR DELETE
TO {RUNTIME_ROLE}
USING ({manage_call})
"""
    )


def _replace_source_scope_helper() -> None:
    _execute(f"DROP FUNCTION mata_rls.{SOURCE_SCOPE_SIGNATURE}")
    _execute(
        r"""
CREATE FUNCTION mata_rls.scheduled_event_source_scope(p_event_id uuid)
RETURNS TABLE(reporting_period_id uuid, programme_code varchar(20))
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF NOT mata_rls.can_select_teaching_event(p_event_id) THEN
        RETURN;
    END IF;
    RETURN QUERY
    SELECT
        event.source_reporting_period_id,
        event.source_programme_code
    FROM public.teaching_events AS event
    WHERE event.id = p_event_id
      AND NOT event.is_adhoc
      AND event.global_session_type_id IS NULL
      AND event.source_reporting_period_id IS NOT NULL
      AND event.source_programme_code IS NOT NULL;
END
$function$
"""
    )
    _secure_runtime_helper(SOURCE_SCOPE_SIGNATURE)


def _replace_external_attendance_helper() -> None:
    _execute(
        r"""
CREATE OR REPLACE FUNCTION mata_rls.can_access_external_attendance(
    p_external_resident_id uuid,
    p_teaching_event_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT mata_rls.is_master_admin()
        OR mata_rls.is_external_resident(p_external_resident_id)
        OR (
            mata_rls.current_subject_type() = 'staff'
            AND mata_rls.current_app_role() IN ('admin', 'secretary')
            AND EXISTS (
                SELECT 1
                FROM public.teaching_events AS event
                JOIN public.external_resident_postings AS external_posting
                  ON external_posting.external_resident_id
                      = p_external_resident_id
                 AND external_posting.posting_code = event.posting_code
                 AND external_posting.start_date <= event.event_date
                 AND COALESCE(external_posting.end_date, 'infinity'::date)
                     >= event.event_date
                JOIN public.posting_codes AS posting
                  ON posting.code = event.posting_code
                WHERE event.id = p_teaching_event_id
                  AND NOT EXISTS (
                      SELECT 1
                      FROM public.external_resident_postings AS competing
                      WHERE competing.external_resident_id
                          = p_external_resident_id
                        AND competing.start_date <= event.event_date
                        AND COALESCE(competing.end_date, 'infinity'::date)
                            >= event.event_date
                        AND competing.id <> external_posting.id
                  )
                  AND (
                      (
                          event.created_for_programme_code IS NULL
                          AND posting.supports_secretary_events
                      )
                      OR (
                          event.created_for_programme_code IS NOT NULL
                          AND external_posting.programme_code IS NOT NULL
                          AND event.created_for_programme_code
                              = external_posting.programme_code
                      )
                  )
                  AND (
                      event.source_programme_code IS NULL
                      OR (
                          external_posting.programme_code IS NOT NULL
                          AND event.source_programme_code
                              = external_posting.programme_code
                          AND event.source_reporting_period_id IS NOT NULL
                          AND event.global_session_type_id IS NULL
                          AND (
                              event.created_for_programme_code IS NULL
                              OR event.created_for_programme_code
                                  = event.source_programme_code
                          )
                      )
                  )
                  AND (
                      mata_rls.current_app_role() = 'secretary'
                      OR (
                          external_posting.programme_code IS NOT NULL
                          AND mata_rls.has_programme_scope(
                              external_posting.programme_code
                          )
                      )
                  )
                  AND mata_rls.can_select_teaching_event(event.id)
            )
        )
$function$
"""
    )
    _secure_runtime_helper("can_access_external_attendance(uuid,uuid)")


def _create_overlap_trigger() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_private.enforce_attendance_no_overlap()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    event_row record;
    attendance_subject_id uuid;
    candidate_start timestamp without time zone;
    candidate_end timestamp without time zone;
    lock_date date;
BEGIN
    IF NEW.status <> 'submitted' THEN
        RETURN NEW;
    END IF;
    IF TG_TABLE_NAME = 'attendance_records' THEN
        attendance_subject_id := NEW.resident_id;
        IF NOT mata_rls.can_submit_native_attendance(
            NEW.resident_id,
            NEW.teaching_event_id
        ) THEN
            RETURN NEW;
        END IF;
    ELSIF TG_TABLE_NAME = 'external_attendance_records' THEN
        attendance_subject_id := NEW.external_resident_id;
        IF NOT mata_rls.can_submit_external_attendance(
            NEW.external_resident_id,
            NEW.teaching_event_id
        ) THEN
            RETURN NEW;
        END IF;
    ELSE
        RAISE EXCEPTION 'Unexpected attendance table'
            USING ERRCODE = '23514';
    END IF;

    SELECT event.event_date, event.start_time, event.end_time
    INTO STRICT event_row
    FROM public.teaching_events AS event
    WHERE event.id = NEW.teaching_event_id;

    candidate_start := event_row.event_date + event_row.start_time;
    candidate_end := CASE
        WHEN event_row.end_time IS NULL THEN candidate_start
        WHEN event_row.end_time <= event_row.start_time THEN
            event_row.event_date + event_row.end_time + INTERVAL '1 day'
        ELSE event_row.event_date + event_row.end_time
    END;

    FOR lock_date IN
        SELECT day::date
        FROM pg_catalog.generate_series(
            event_row.event_date::timestamp,
            candidate_end::date::timestamp,
            INTERVAL '1 day'
        ) AS day
    LOOP
        PERFORM pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended(
                CASE TG_TABLE_NAME
                    WHEN 'attendance_records' THEN 'native-attendance:'
                    ELSE 'external-attendance:'
                END || attendance_subject_id::text || ':' || lock_date::text,
                0
            )
        );
    END LOOP;

    IF TG_TABLE_NAME = 'attendance_records' AND EXISTS (
        SELECT 1
        FROM public.attendance_records AS attendance
        JOIN public.teaching_events AS existing
          ON existing.id = attendance.teaching_event_id
        WHERE attendance.resident_id = attendance_subject_id
          AND attendance.status = 'submitted'
          AND attendance.id IS DISTINCT FROM NEW.id
          AND existing.event_date IN (
              event_row.event_date - 1,
              event_row.event_date,
              candidate_end::date
          )
          AND candidate_start < CASE
              WHEN existing.end_time IS NULL THEN
                  existing.event_date + existing.start_time
              WHEN existing.end_time <= existing.start_time THEN
                  existing.event_date + existing.end_time + INTERVAL '1 day'
              ELSE existing.event_date + existing.end_time
          END
          AND existing.event_date + existing.start_time < candidate_end
    ) THEN
        RAISE EXCEPTION 'Attendance overlaps an earlier accepted event'
            USING ERRCODE = '23P01';
    END IF;

    IF TG_TABLE_NAME = 'external_attendance_records' AND EXISTS (
        SELECT 1
        FROM public.external_attendance_records AS attendance
        JOIN public.teaching_events AS existing
          ON existing.id = attendance.teaching_event_id
        WHERE attendance.external_resident_id = attendance_subject_id
          AND attendance.status = 'submitted'
          AND attendance.id IS DISTINCT FROM NEW.id
          AND existing.event_date IN (
              event_row.event_date - 1,
              event_row.event_date,
              candidate_end::date
          )
          AND candidate_start < CASE
              WHEN existing.end_time IS NULL THEN
                  existing.event_date + existing.start_time
              WHEN existing.end_time <= existing.start_time THEN
                  existing.event_date + existing.end_time + INTERVAL '1 day'
              ELSE existing.event_date + existing.end_time
          END
          AND existing.event_date + existing.start_time < candidate_end
    ) THEN
        RAISE EXCEPTION 'Attendance overlaps an earlier accepted event'
            USING ERRCODE = '23P01';
    END IF;
    RETURN NEW;
END
$function$
"""
    )
    for table_name, trigger_name in (
        ("attendance_records", "mata_enforce_native_attendance_no_overlap"),
        (
            "external_attendance_records",
            "mata_enforce_external_attendance_no_overlap",
        ),
    ):
        _execute(
            f"""
CREATE TRIGGER {trigger_name}
BEFORE INSERT OR UPDATE OF status, teaching_event_id
ON public.{table_name}
FOR EACH ROW
EXECUTE FUNCTION mata_private.enforce_attendance_no_overlap()
"""
        )
    _secure_private_helper(OVERLAP_TRIGGER_SIGNATURE)


def _replace_atomic_adhoc_helper() -> None:
    _execute(f"GRANT CREATE ON SCHEMA mata_rls TO {DEFINER_ROLE}")
    _execute(f"SET LOCAL ROLE {DEFINER_ROLE}")
    _execute(
        r"""
CREATE OR REPLACE FUNCTION mata_rls.create_adhoc_attendance(
    p_posting_code text,
    p_attended_posting_code text,
    p_attended_teaching_name text,
    p_teaching_name text,
    p_details_of_session text,
    p_event_date date,
    p_start_time time without time zone,
    p_end_time time without time zone,
    p_duration_hours numeric,
    p_session_type_id uuid
)
RETURNS TABLE(event_id uuid, attendance_id uuid)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    subject_type text := mata_rls.current_subject_type();
    subject_id uuid := mata_rls.current_subject_id();
    new_event_id uuid;
    new_attendance_id uuid;
    resolved_period_id uuid;
    resolved_posting_code text;
    matching_count integer;
    candidate_start timestamp without time zone;
    candidate_end timestamp without time zone;
    lock_date date;
BEGIN
    IF subject_type NOT IN ('resident', 'external_resident')
       OR subject_id IS NULL
    THEN
        RAISE EXCEPTION 'Verified resident context required'
            USING ERRCODE = '28000';
    END IF;
    IF pg_catalog.btrim(COALESCE(p_posting_code, '')) = ''
       OR pg_catalog.btrim(COALESCE(p_attended_posting_code, '')) = ''
       OR p_posting_code <> p_attended_posting_code
       OR p_attended_teaching_name <> 'Department/Programme Teaching [1h]'
       OR p_teaching_name <> 'Department/Programme Teaching [1h]'
       OR p_event_date IS NULL
       OR p_start_time IS NULL
       OR p_end_time IS NULL
       OR p_duration_hours IS NULL
       OR p_duration_hours <> 1.00::numeric
       OR p_session_type_id IS NOT NULL
       OR p_end_time <> (p_start_time + INTERVAL '1 hour')::time
    THEN
        RAISE EXCEPTION 'Invalid ad-hoc teaching event'
            USING ERRCODE = '22023';
    END IF;

    candidate_start := p_event_date + p_start_time;
    candidate_end := CASE
        WHEN p_end_time <= p_start_time THEN
            p_event_date + p_end_time + INTERVAL '1 day'
        ELSE p_event_date + p_end_time
    END;
    IF candidate_end <> candidate_start + INTERVAL '1 hour' THEN
        RAISE EXCEPTION 'Invalid ad-hoc teaching event'
            USING ERRCODE = '22023';
    END IF;

    SELECT COUNT(*), pg_catalog.min(period.id::text)::uuid
    INTO matching_count, resolved_period_id
    FROM public.reporting_periods AS period
    WHERE p_event_date BETWEEN period.start_date AND period.end_date
      AND (
          CASE
              WHEN period.deactivate_on IS NOT NULL
               AND CURRENT_DATE >= period.deactivate_on
               AND (
                   period.activate_on IS NULL
                   OR CURRENT_DATE < period.activate_on
                   OR period.deactivate_on >= period.activate_on
               )
              THEN 'inactive'
              WHEN period.activate_on IS NOT NULL
               AND CURRENT_DATE >= period.activate_on
              THEN 'active'
              ELSE period.status
          END
      ) = 'active';
    IF matching_count <> 1 THEN
        RAISE EXCEPTION 'Exactly one effective reporting period is required'
            USING ERRCODE = '22023';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.public_holidays AS holiday
        WHERE holiday.holiday_date = p_event_date
    ) THEN
        RAISE EXCEPTION 'Ad-hoc teaching is unavailable on a public holiday'
            USING ERRCODE = '22023';
    END IF;

    FOR lock_date IN
        SELECT day::date
        FROM pg_catalog.generate_series(
            p_event_date::timestamp,
            candidate_end::date::timestamp,
            INTERVAL '1 day'
        ) AS day
    LOOP
        PERFORM pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended(
                CASE subject_type
                    WHEN 'resident' THEN 'native-attendance:'
                    ELSE 'external-attendance:'
                END || subject_id::text || ':' || lock_date::text,
                0
            )
        );
    END LOOP;

    IF subject_type = 'resident' THEN
        SELECT COUNT(*), pg_catalog.min(resident_posting.posting_code)
        INTO matching_count, resolved_posting_code
        FROM public.residents AS resident
        JOIN public.resident_postings AS resident_posting
          ON resident_posting.resident_id = resident.id
        WHERE resident.id = subject_id
          AND resident.status = 'active'
          AND resident.programme_code IS NOT NULL
          AND resident_posting.reporting_period_id = resolved_period_id
          AND resident_posting.status IN ('active', 'loa_working')
          AND p_event_date BETWEEN
              resident_posting.start_date AND resident_posting.end_date;
    ELSE
        SELECT COUNT(*), pg_catalog.min(external_posting.posting_code)
        INTO matching_count, resolved_posting_code
        FROM public.external_residents AS external_resident
        JOIN public.external_resident_postings AS external_posting
          ON external_posting.external_resident_id = external_resident.id
        WHERE external_resident.id = subject_id
          AND external_resident.status = 'active'
          AND external_posting.start_date <= p_event_date
          AND COALESCE(external_posting.end_date, 'infinity'::date)
              >= p_event_date;
    END IF;
    IF matching_count <> 1
       OR resolved_posting_code IS DISTINCT FROM p_posting_code
    THEN
        RAISE EXCEPTION 'Ad-hoc teaching event is outside the resident scope'
            USING ERRCODE = '22023';
    END IF;

    IF subject_type = 'resident' AND EXISTS (
        SELECT 1
        FROM public.attendance_records AS attendance
        JOIN public.teaching_events AS existing
          ON existing.id = attendance.teaching_event_id
        WHERE attendance.resident_id = subject_id
          AND attendance.status = 'submitted'
          AND existing.event_date IN (
              p_event_date - 1,
              p_event_date,
              candidate_end::date
          )
          AND candidate_start < CASE
              WHEN existing.end_time IS NULL THEN
                  existing.event_date + existing.start_time
              WHEN existing.end_time <= existing.start_time THEN
                  existing.event_date + existing.end_time + INTERVAL '1 day'
              ELSE existing.event_date + existing.end_time
          END
          AND existing.event_date + existing.start_time < candidate_end
    ) THEN
        RAISE EXCEPTION 'Attendance overlaps an earlier accepted event'
            USING ERRCODE = '23P01';
    END IF;
    IF subject_type = 'external_resident' AND EXISTS (
        SELECT 1
        FROM public.external_attendance_records AS attendance
        JOIN public.teaching_events AS existing
          ON existing.id = attendance.teaching_event_id
        WHERE attendance.external_resident_id = subject_id
          AND attendance.status = 'submitted'
          AND existing.event_date IN (
              p_event_date - 1,
              p_event_date,
              candidate_end::date
          )
          AND candidate_start < CASE
              WHEN existing.end_time IS NULL THEN
                  existing.event_date + existing.start_time
              WHEN existing.end_time <= existing.start_time THEN
                  existing.event_date + existing.end_time + INTERVAL '1 day'
              ELSE existing.event_date + existing.end_time
          END
          AND existing.event_date + existing.start_time < candidate_end
    ) THEN
        RAISE EXCEPTION 'Attendance overlaps an earlier accepted event'
            USING ERRCODE = '23P01';
    END IF;

    INSERT INTO public.teaching_events (
        posting_code,
        teaching_name,
        details_of_session,
        event_date,
        start_time,
        end_time,
        duration_hours,
        session_type_id,
        is_adhoc,
        created_by_role,
        created_by_resident_id,
        created_by_external_resident_id
    ) VALUES (
        p_posting_code,
        'Department/Programme Teaching [1h]',
        p_details_of_session,
        p_event_date,
        p_start_time,
        p_end_time,
        1.00::numeric,
        NULL,
        true,
        subject_type,
        CASE WHEN subject_type = 'resident' THEN subject_id END,
        CASE WHEN subject_type = 'external_resident' THEN subject_id END
    ) RETURNING id INTO new_event_id;

    IF subject_type = 'resident' THEN
        INSERT INTO public.attendance_records (
            resident_id, teaching_event_id, status, posting_code
        ) VALUES (
            subject_id, new_event_id, 'submitted', p_posting_code
        ) RETURNING id INTO new_attendance_id;
    ELSE
        INSERT INTO public.external_attendance_records (
            external_resident_id, teaching_event_id, status, posting_code
        ) VALUES (
            subject_id, new_event_id, 'submitted', p_posting_code
        ) RETURNING id INTO new_attendance_id;
    END IF;
    RETURN QUERY SELECT new_event_id, new_attendance_id;
END
$function$
"""
    )
    _execute("SET LOCAL ROLE NONE")
    _execute(f"REVOKE CREATE ON SCHEMA mata_rls FROM {DEFINER_ROLE}")
    _secure_runtime_helper(
        "create_adhoc_attendance("
        "text,text,text,text,text,date,time without time zone,"
        "time without time zone,numeric,uuid)"
    )


def _assert_security_and_backfill() -> None:
    _execute(
        rf"""
DO $migration$
DECLARE
    helper_signature text;
    helper_oid regprocedure;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.teaching_events
        WHERE teaching_name_id IS NOT NULL
          AND (
              source_programme_code IS NULL
              OR source_reporting_period_id IS NULL
          )
    ) THEN
        RAISE EXCEPTION 'Teaching-event source provenance backfill is incomplete';
    END IF;

    FOREACH helper_signature IN ARRAY ARRAY[
        'mata_rls.{SELECT_ROW_SIGNATURE}',
        'mata_rls.{MANAGE_ROW_SIGNATURE}',
        'mata_rls.{INSERT_SOURCE_SIGNATURE}',
        'mata_rls.{SOURCE_SCOPE_SIGNATURE}',
        'mata_rls.can_select_teaching_event(uuid)',
        'mata_rls.can_access_external_attendance(uuid,uuid)'
    ]::text[]
    LOOP
        helper_oid := pg_catalog.to_regprocedure(helper_signature);
        IF helper_oid IS NULL
           OR NOT EXISTS (
               SELECT 1
               FROM pg_catalog.pg_proc AS procedure
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = procedure.pronamespace
               WHERE procedure.oid = helper_oid
                 AND procedure.prosecdef
                 AND procedure.proconfig
                     @> ARRAY['search_path=pg_catalog, pg_temp']::text[]
                  AND procedure.proowner = namespace.nspowner
           )
           OR EXISTS (
               SELECT 1
               FROM pg_catalog.pg_proc AS procedure
               CROSS JOIN LATERAL pg_catalog.aclexplode(
                   COALESCE(
                       procedure.proacl,
                       pg_catalog.acldefault('f', procedure.proowner)
                   )
               ) AS privilege
               WHERE procedure.oid = helper_oid
                 AND privilege.grantee = 0
                 AND privilege.privilege_type = 'EXECUTE'
           )
           OR pg_catalog.has_function_privilege(
               '{AUTH_ROLE}', helper_oid, 'EXECUTE'
           )
           OR NOT pg_catalog.has_function_privilege(
               '{RUNTIME_ROLE}', helper_oid, 'EXECUTE'
           )
        THEN
            RAISE EXCEPTION 'Unsafe D/F/G helper: %', helper_signature;
        END IF;
    END LOOP;

    IF (
        SELECT COUNT(*)
        FROM pg_catalog.pg_policy AS policy
        JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'teaching_events'
    ) <> 4 THEN
        RAISE EXCEPTION 'Unexpected teaching_events policy count';
    END IF;
END
$migration$
"""
    )


def upgrade() -> None:
    _grant_definer_ownership()
    _add_source_provenance()
    _create_provenance_trigger()
    _create_source_validation_helper()
    _create_row_local_selection_helper()
    _create_write_helpers()
    _replace_event_policies()
    _replace_source_scope_helper()
    _replace_external_attendance_helper()
    _create_overlap_trigger()
    _replace_atomic_adhoc_helper()
    _assert_security_and_backfill()
    _revoke_definer_ownership()


def downgrade() -> None:
    _grant_definer_ownership()
    for operation in ("select", "insert", "update", "delete"):
        _execute(
            f'DROP POLICY "mata_rls_teaching_events_{operation}" '
            "ON public.teaching_events"
        )

    _execute(f"DROP FUNCTION mata_rls.{SOURCE_SCOPE_SIGNATURE}")
    _execute(
        r"""
CREATE FUNCTION mata_rls.scheduled_event_source_scope(p_event_id uuid)
RETURNS TABLE(reporting_period_id uuid, programme_code text)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF NOT mata_rls.can_select_teaching_event(p_event_id) THEN
        RETURN;
    END IF;
    RETURN QUERY
    SELECT teaching_name.reporting_period_id, teaching_name.programme_code
    FROM public.teaching_events AS event
    JOIN public.teaching_names AS teaching_name
      ON teaching_name.id = event.teaching_name_id
    WHERE event.id = p_event_id
      AND NOT event.is_adhoc
      AND event.global_session_type_id IS NULL;
END
$function$
"""
    )
    _secure_runtime_helper(SOURCE_SCOPE_SIGNATURE)

    _execute(
        r"""
CREATE OR REPLACE FUNCTION mata_rls.can_select_teaching_event(p_event_id uuid)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF mata_rls.current_subject_type() = 'external_resident' THEN
        RETURN mata_rls.is_external_resident(
            mata_rls.current_subject_id()
        ) AND mata_private.can_select_external_teaching_event_000027(
            p_event_id
        );
    END IF;
    RETURN mata_private.can_select_teaching_event_000027(p_event_id);
END
$function$
"""
    )
    _execute(
        r"""
CREATE OR REPLACE FUNCTION mata_rls.can_access_external_attendance(
    p_external_resident_id uuid,
    p_teaching_event_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT mata_rls.is_master_admin()
        OR mata_rls.is_external_resident(p_external_resident_id)
        OR (
            mata_rls.current_subject_type() = 'staff'
            AND mata_rls.current_app_role() IN ('admin', 'secretary')
            AND EXISTS (
                SELECT 1
                FROM public.teaching_events AS event
                JOIN public.external_resident_postings AS external_posting
                  ON external_posting.external_resident_id
                      = p_external_resident_id
                 AND external_posting.posting_code = event.posting_code
                 AND external_posting.start_date <= event.event_date
                 AND COALESCE(external_posting.end_date, 'infinity'::date)
                     >= event.event_date
                WHERE event.id = p_teaching_event_id
                  AND mata_rls.can_select_teaching_event(event.id)
            )
        )
$function$
"""
    )

    for table_name, trigger_name in (
        ("attendance_records", "mata_enforce_native_attendance_no_overlap"),
        (
            "external_attendance_records",
            "mata_enforce_external_attendance_no_overlap",
        ),
    ):
        _execute(f"DROP TRIGGER {trigger_name} ON public.{table_name}")
    _execute(
        f"DROP FUNCTION mata_private.{OVERLAP_TRIGGER_SIGNATURE}"
    )
    _execute(
        "DROP TRIGGER mata_enforce_teaching_event_source_provenance_immutable "
        "ON public.teaching_events"
    )
    _execute(
        f"DROP FUNCTION mata_private.{PROVENANCE_TRIGGER_SIGNATURE}"
    )

    _execute(f"DROP FUNCTION mata_rls.{SELECT_ROW_SIGNATURE}")
    _execute(f"DROP FUNCTION mata_rls.{MANAGE_ROW_SIGNATURE}")
    _execute(f"DROP FUNCTION mata_rls.{INSERT_SOURCE_SIGNATURE}")
    _execute(
        "DROP FUNCTION mata_private.scheduled_event_source_is_valid("
        "date,uuid,uuid,text,uuid)"
    )

    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_events_select"
ON public.teaching_events AS PERMISSIVE FOR SELECT TO {RUNTIME_ROLE}
USING (mata_rls.can_select_teaching_event(id))
"""
    )
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_events_insert"
ON public.teaching_events AS PERMISSIVE FOR INSERT TO {RUNTIME_ROLE}
WITH CHECK (
    (
        NOT COALESCE(is_adhoc, false)
        AND mata_rls.can_insert_scheduled_event_source(
            posting_code,
            created_for_programme_code,
            teaching_name_id,
            global_session_type_id,
            event_date,
            is_adhoc,
            created_by_role
        )
    )
    OR (
        COALESCE(is_adhoc, false)
        AND mata_rls.can_insert_teaching_event(
            posting_code,
            created_for_programme_code,
            teaching_name,
            event_date,
            is_adhoc,
            created_by_role
        )
    )
)
"""
    )
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_events_update"
ON public.teaching_events AS PERMISSIVE FOR UPDATE TO {RUNTIME_ROLE}
USING (
    mata_rls.can_manage_teaching_event(
        posting_code, created_for_programme_code, teaching_name,
        event_date, is_adhoc, created_by_role
    )
)
WITH CHECK (
    mata_rls.can_manage_teaching_event(
        posting_code, created_for_programme_code, teaching_name,
        event_date, is_adhoc, created_by_role
    )
    AND (
        COALESCE(is_adhoc, false)
        OR mata_rls.can_manage_scheduled_event_source(
            posting_code,
            teaching_name_id,
            global_session_type_id,
            event_date,
            is_adhoc
        )
    )
)
"""
    )
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_events_delete"
ON public.teaching_events AS PERMISSIVE FOR DELETE TO {RUNTIME_ROLE}
USING (
    mata_rls.can_manage_teaching_event(
        posting_code, created_for_programme_code, teaching_name,
        event_date, is_adhoc, created_by_role
    )
)
"""
    )

    op.drop_index("idx_teaching_events_source_scope", table_name="teaching_events")
    op.drop_constraint(
        "ck_teaching_events_global_has_no_pool_scope",
        "teaching_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_teaching_events_adhoc_has_no_scheduled_source",
        "teaching_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_teaching_events_pool_source_scope_required",
        "teaching_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_teaching_events_source_scope_pair",
        "teaching_events",
        type_="check",
    )
    op.drop_constraint(
        "fk_teaching_events_source_reporting_period_id_reporting_periods",
        "teaching_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_teaching_events_source_programme_code_programmes",
        "teaching_events",
        type_="foreignkey",
    )
    op.drop_column("teaching_events", "source_reporting_period_id")
    op.drop_column("teaching_events", "source_programme_code")
    _revoke_definer_ownership()
