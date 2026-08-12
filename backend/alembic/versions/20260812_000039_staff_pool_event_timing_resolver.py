"""add protected staff pool-event timing resolver

Revision ID: 20260812_000039
Revises: 20260806_000038
Create Date: 2026-08-12

Secretary timing previews need mapping-derived durations without granting
Secretaries direct SELECT access to the Programme-PC mapping table.  This
bounded read-only helper applies the existing trusted staff context and exact
programme/posting capability rules before returning timing rows.
"""

from __future__ import annotations

from alembic import op


revision = "20260812_000039"
down_revision = "20260806_000038"
branch_labels = None
depends_on = None


RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"
OPTIONAL_BROWSER_ROLES = ("anon", "authenticated", "service_role")
FUNCTION_SIGNATURE = "resolve_staff_pool_event_timings(uuid[],uuid,text,text)"


def _execute(statement: str) -> None:
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(statement)


def _revoke_optional_function_privileges() -> None:
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
                'REVOKE ALL PRIVILEGES ON FUNCTION '
                'mata_rls.{FUNCTION_SIGNATURE} FROM %I',
                optional_role
            );
        END IF;
    END LOOP;
END
$migration$
"""
    )


def upgrade() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.resolve_staff_pool_event_timings(
    p_teaching_name_ids uuid[],
    p_reporting_period_id uuid,
    p_programme_code text,
    p_posting_code text
)
RETURNS TABLE(
    teaching_name_id uuid,
    posting_code text,
    r_year text,
    teaching_target_id uuid,
    session_type_id uuid,
    session_type_name text,
    duration_hours numeric
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF NOT mata_rls.context_is_valid()
       OR mata_rls.current_subject_type() <> 'staff'
       OR p_teaching_name_ids IS NULL
       OR p_reporting_period_id IS NULL
       OR p_programme_code IS NULL
    THEN
        RETURN;
    END IF;

    IF mata_rls.current_app_role() = 'admin' THEN
        IF NOT (
            mata_rls.is_master_admin()
            OR mata_rls.has_programme_scope(p_programme_code)
        ) THEN
            RETURN;
        END IF;
    ELSIF mata_rls.current_app_role() = 'secretary' THEN
        IF p_posting_code IS NULL
           OR NOT mata_rls.is_secretary_for_posting(p_posting_code)
           OR NOT EXISTS (
               SELECT 1
               FROM public.secretary_programme_pools AS pool
               WHERE pool.posting_code = p_posting_code
                 AND pool.programme_code = p_programme_code
                 AND pool.is_active
                 AND pool.can_manage_teaching_names
           )
        THEN
            RETURN;
        END IF;
    ELSE
        RETURN;
    END IF;

    RETURN QUERY
    SELECT
        mapping.teaching_name_id,
        mapping.posting_code::text,
        mapping.r_year::text,
        mapping.teaching_target_id,
        target.session_type_id,
        session_type.name::text,
        session_type.duration_hours
    FROM public.teaching_name_mappings AS mapping
    JOIN public.teaching_names AS name
      ON name.id = mapping.teaching_name_id
    LEFT JOIN public.teaching_targets AS target
      ON target.id = mapping.teaching_target_id
    LEFT JOIN public.session_types AS session_type
      ON session_type.id = target.session_type_id
    WHERE mapping.teaching_name_id = ANY(p_teaching_name_ids)
      AND name.reporting_period_id = p_reporting_period_id
      AND name.programme_code = p_programme_code
      AND mapping.reporting_period_id = p_reporting_period_id
      AND mapping.programme_code = p_programme_code
      AND (
          p_posting_code IS NULL
          OR mapping.posting_code = p_posting_code
      )
    ORDER BY mapping.teaching_name_id, mapping.posting_code, mapping.r_year;
END
$function$
"""
    )
    _execute(
        f"REVOKE ALL PRIVILEGES ON FUNCTION mata_rls.{FUNCTION_SIGNATURE} "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        f"GRANT EXECUTE ON FUNCTION mata_rls.{FUNCTION_SIGNATURE} "
        f"TO {RUNTIME_ROLE}"
    )
    _revoke_optional_function_privileges()


def downgrade() -> None:
    _execute(f"DROP FUNCTION mata_rls.{FUNCTION_SIGNATURE}")
