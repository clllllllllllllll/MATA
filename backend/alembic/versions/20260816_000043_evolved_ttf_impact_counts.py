"""protect evolved TTF impact counts and Secretary timing reads

Revision ID: 20260816_000043
Revises: 20260813_000042
Create Date: 2026-08-16
"""

from __future__ import annotations

from alembic import op


revision = "20260816_000043"
down_revision = "20260813_000042"
branch_labels = None
depends_on = None

RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"
OPTIONAL_BROWSER_ROLES = ("anon", "authenticated", "service_role")
MAPPING_IMPACT_SIGNATURE = "teaching_name_mapping_impact(uuid)"
TARGET_IMPACT_SIGNATURE = "teaching_target_mapping_impacts(uuid[])"
STAFF_TIMING_SIGNATURE = "resolve_staff_pool_event_timings(uuid[],uuid,text,text)"


def _execute(statement: str) -> None:
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(statement)


def _secure_runtime_function(signature: str) -> None:
    _execute(
        f"REVOKE ALL PRIVILEGES ON FUNCTION mata_rls.{signature} "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(f"GRANT EXECUTE ON FUNCTION mata_rls.{signature} TO {RUNTIME_ROLE}")
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
                'REVOKE ALL PRIVILEGES ON FUNCTION mata_rls.{signature} FROM %I',
                optional_role
            );
        END IF;
    END LOOP;
END
$migration$
"""
    )


def _replace_staff_timing_resolver(*, use_programme_pool: bool) -> None:
    pc_private_authorization = (
        """
                      name.visibility_scope = 'programme_private'
                      AND EXISTS (
                          SELECT 1
                          FROM public.secretary_programme_pools AS pool
                          WHERE pool.posting_code = p_posting_code
                            AND pool.programme_code = name.programme_code
                            AND pool.is_active
                            AND pool.can_manage_teaching_names
                      )
"""
        if use_programme_pool
        else """
                      name.visibility_scope = 'programme_private'
                      AND EXISTS (
                          SELECT 1
                          FROM public.programmes AS programme
                          WHERE programme.code = name.programme_code
                            AND programme.native_teaching_posting_code
                                = p_posting_code
                      )
"""
    )
    _execute(
        f"""
CREATE OR REPLACE FUNCTION mata_rls.resolve_staff_pool_event_timings(
    p_teaching_name_ids uuid[],
    p_reporting_period_id uuid,
    p_programme_code text,
    p_posting_code text
)
RETURNS TABLE(
    teaching_name_id uuid, programme_code text, posting_code text, r_year text,
    teaching_target_id uuid, session_type_id uuid,
    session_type_name text, duration_hours numeric
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF p_teaching_name_ids IS NULL
       OR cardinality(p_teaching_name_ids) = 0
       OR cardinality(p_teaching_name_ids) > 500
       OR p_reporting_period_id IS NULL
    THEN
        RETURN;
    END IF;

    IF mata_rls.is_master_admin() THEN
        NULL;
    ELSIF p_programme_code IS NOT NULL
       AND mata_rls.has_programme_scope(p_programme_code)
    THEN
        NULL;
    ELSIF mata_rls.current_subject_type() = 'staff'
       AND mata_rls.current_app_role() = 'secretary'
       AND p_posting_code IS NOT NULL
       AND mata_rls.is_secretary_for_posting(p_posting_code)
       AND NOT EXISTS (
           SELECT 1
           FROM unnest(p_teaching_name_ids) AS requested(id)
           JOIN public.teaching_names AS name ON name.id = requested.id
           WHERE name.reporting_period_id <> p_reporting_period_id
              OR (
                  name.origin_posting_code <> p_posting_code
                  AND NOT (
{pc_private_authorization}
                  )
              )
       )
    THEN
        NULL;
    ELSE
        RETURN;
    END IF;

    RETURN QUERY
    SELECT
        mapping.teaching_name_id,
        mapping.programme_code::text,
        mapping.posting_code::text,
        mapping.r_year::text,
        mapping.teaching_target_id,
        target.session_type_id,
        session_type.name::text,
        session_type.duration_hours
    FROM public.teaching_name_mappings AS mapping
    LEFT JOIN public.teaching_targets AS target
      ON target.id = mapping.teaching_target_id
    LEFT JOIN public.session_types AS session_type
      ON session_type.id = target.session_type_id
    WHERE mapping.teaching_name_id = ANY(p_teaching_name_ids)
      AND mapping.reporting_period_id = p_reporting_period_id
      AND (p_programme_code IS NULL
           OR mapping.programme_code = p_programme_code)
      AND (p_posting_code IS NULL OR mapping.posting_code = p_posting_code)
    ORDER BY mapping.teaching_name_id, mapping.programme_code, mapping.r_year;
END
$function$;
"""
    )
    _secure_runtime_function(STAFF_TIMING_SIGNATURE)


def upgrade() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.teaching_name_mapping_impact(p_mapping_id uuid)
RETURNS TABLE(affected_event_count bigint, affected_attendance_count bigint)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    v_programme_code text;
BEGIN
    SELECT mapping.programme_code
    INTO v_programme_code
    FROM public.teaching_name_mappings AS mapping
    WHERE mapping.id = p_mapping_id;

    IF v_programme_code IS NULL
       OR NOT (
           mata_rls.is_master_admin()
           OR mata_rls.has_programme_scope(v_programme_code)
       )
    THEN
        RETURN;
    END IF;

    RETURN QUERY
    WITH mapping_scope AS (
        SELECT
            mapping.teaching_name_id,
            mapping.reporting_period_id,
            mapping.programme_code AS mapping_programme_code,
            name.programme_code AS source_programme_code,
            mapping.posting_code
        FROM public.teaching_name_mappings AS mapping
        JOIN public.teaching_names AS name
          ON name.id = mapping.teaching_name_id
        WHERE mapping.id = p_mapping_id
    ), affected_events AS (
        SELECT DISTINCT event.id
        FROM mapping_scope AS scope
        JOIN public.teaching_events AS event
          ON event.teaching_name_id = scope.teaching_name_id
         AND event.source_reporting_period_id = scope.reporting_period_id
         AND event.source_programme_code = scope.source_programme_code
         AND event.posting_code = scope.posting_code
         AND event.global_session_type_id IS NULL
         AND NOT event.is_adhoc
         AND (
             event.created_for_programme_code IS NULL
             OR event.created_for_programme_code = scope.mapping_programme_code
         )
    )
    SELECT
        COUNT(DISTINCT event.id),
        COUNT(DISTINCT native_attendance.id)
            + COUNT(DISTINCT external_attendance.id)
    FROM affected_events AS event
    LEFT JOIN public.attendance_records AS native_attendance
      ON native_attendance.teaching_event_id = event.id
     AND native_attendance.status = 'submitted'
    LEFT JOIN public.external_attendance_records AS external_attendance
      ON external_attendance.teaching_event_id = event.id
     AND external_attendance.status = 'submitted';
END
$function$;
"""
    )
    _secure_runtime_function(MAPPING_IMPACT_SIGNATURE)

    _execute(
        r"""
CREATE FUNCTION mata_rls.teaching_target_mapping_impacts(p_target_ids uuid[])
RETURNS TABLE(
    mapped_target_count bigint,
    affected_event_count bigint,
    affected_attendance_count bigint
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    v_requested_count integer;
    v_target_count integer;
BEGIN
    IF p_target_ids IS NULL
       OR cardinality(p_target_ids) = 0
       OR cardinality(p_target_ids) > 500
    THEN
        RETURN;
    END IF;

    SELECT COUNT(DISTINCT requested.id)
    INTO v_requested_count
    FROM unnest(p_target_ids) AS requested(id);

    SELECT COUNT(*)
    INTO v_target_count
    FROM public.teaching_targets AS target
    WHERE target.id = ANY(p_target_ids)
      AND (
          mata_rls.is_master_admin()
          OR mata_rls.has_programme_scope(target.programme_code)
      );

    IF v_target_count <> v_requested_count THEN
        RETURN;
    END IF;

    RETURN QUERY
    WITH affected_mappings AS (
        SELECT
            mapping.id,
            mapping.teaching_name_id,
            mapping.reporting_period_id,
            mapping.programme_code AS mapping_programme_code,
            name.programme_code AS source_programme_code,
            mapping.posting_code
        FROM public.teaching_name_mappings AS mapping
        JOIN public.teaching_names AS name
          ON name.id = mapping.teaching_name_id
        WHERE mapping.teaching_target_id = ANY(p_target_ids)
    ), affected_events AS (
        SELECT DISTINCT event.id
        FROM affected_mappings AS mapping
        JOIN public.teaching_events AS event
          ON event.teaching_name_id = mapping.teaching_name_id
         AND event.source_reporting_period_id = mapping.reporting_period_id
         AND event.source_programme_code = mapping.source_programme_code
         AND event.posting_code = mapping.posting_code
         AND event.global_session_type_id IS NULL
         AND NOT event.is_adhoc
         AND (
             event.created_for_programme_code IS NULL
             OR event.created_for_programme_code = mapping.mapping_programme_code
         )
    ), mapping_count AS (
        SELECT COUNT(*) AS value FROM affected_mappings
    )
    SELECT
        mapping_count.value,
        COUNT(DISTINCT event.id),
        COUNT(DISTINCT native_attendance.id)
            + COUNT(DISTINCT external_attendance.id)
    FROM mapping_count
    LEFT JOIN affected_events AS event ON true
    LEFT JOIN public.attendance_records AS native_attendance
      ON native_attendance.teaching_event_id = event.id
     AND native_attendance.status = 'submitted'
    LEFT JOIN public.external_attendance_records AS external_attendance
      ON external_attendance.teaching_event_id = event.id
     AND external_attendance.status = 'submitted'
    GROUP BY mapping_count.value;
END
$function$;
"""
    )
    _secure_runtime_function(TARGET_IMPACT_SIGNATURE)
    _replace_staff_timing_resolver(use_programme_pool=True)


def downgrade() -> None:
    _replace_staff_timing_resolver(use_programme_pool=False)
    _execute(f"DROP FUNCTION mata_rls.{TARGET_IMPACT_SIGNATURE}")
    _execute(f"DROP FUNCTION mata_rls.{MAPPING_IMPACT_SIGNATURE}")
