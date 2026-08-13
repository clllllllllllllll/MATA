"""align Programme PC pool-event RLS with exact mapping scope

Revision ID: 20260806_000038
Revises: 20260805_000037
Create Date: 2026-08-06

Programme PCs may create or edit a pool-backed event only where its Teaching
Name has an exact persisted mapping for the source reporting period,
programme, and requested posting.  Secretary and Master boundaries are
unchanged: the additional predicate is confined to the scoped admin branch.
"""

from __future__ import annotations

from alembic import op


revision = "20260806_000038"
down_revision = "20260805_000037"
branch_labels = None
depends_on = None


RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"
OPTIONAL_BROWSER_ROLES = ("anon", "authenticated", "service_role")
INSERT_SOURCE_SIGNATURE = (
    "can_insert_scheduled_event_source("
    "text,text,uuid,uuid,text,uuid,date,boolean,text)"
)
MANAGE_ROW_SIGNATURE = (
    "can_manage_teaching_event_row("
    "text,text,date,boolean,text,uuid,uuid,text,uuid)"
)


def _execute(statement: str) -> None:
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(statement)


def _revoke_optional_function_privileges(function_signature: str) -> None:
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
                'REVOKE ALL PRIVILEGES ON FUNCTION mata_rls.{function_signature} FROM %I',
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
        f"GRANT EXECUTE ON FUNCTION mata_rls.{function_signature} "
        f"TO {RUNTIME_ROLE}"
    )
    _revoke_optional_function_privileges(function_signature)


def _replace_pc_pool_event_helpers(*, require_mapping_scope: bool) -> None:
    mapping_scope = (
        """
               AND EXISTS (
                   SELECT 1
                   FROM public.teaching_name_mappings AS mapping
                   WHERE mapping.teaching_name_id = p_teaching_name_id
                     AND mapping.reporting_period_id
                         = p_source_reporting_period_id
                     AND mapping.programme_code = p_source_programme_code
                     AND mapping.posting_code = p_posting_code
               )"""
        if require_mapping_scope
        else ""
    )
    _execute(
        f"""
CREATE OR REPLACE FUNCTION mata_rls.can_insert_scheduled_event_source(
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
               AND mata_rls.has_programme_scope(p_source_programme_code){mapping_scope};
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
        f"""
CREATE OR REPLACE FUNCTION mata_rls.can_manage_teaching_event_row(
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
            RETURN mata_rls.has_programme_scope(p_source_programme_code){mapping_scope};
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
    for function_signature in (INSERT_SOURCE_SIGNATURE, MANAGE_ROW_SIGNATURE):
        _secure_runtime_helper(function_signature)


def upgrade() -> None:
    _replace_pc_pool_event_helpers(require_mapping_scope=True)


def downgrade() -> None:
    _replace_pc_pool_event_helpers(require_mapping_scope=False)
