"""allow admitted host Secretary events through resident RLS

Revision ID: 20260813_000041
Revises: 20260812_000040
Create Date: 2026-08-13
"""

from alembic import op


revision = "20260813_000041"
down_revision = "20260812_000040"
branch_labels = None
depends_on = None

RUNTIME_ROLE = "mata_app_runtime"


def _execute(statement: str) -> None:
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(statement)


def _replace_native_resolver(*, cast_cross_posting_phase: bool) -> None:
    programme = (
        "v_resident_programme::text"
        if cast_cross_posting_phase
        else "v_resident_programme"
    )
    posting = (
        "v_phase.posting_code::text"
        if cast_cross_posting_phase
        else "v_phase.posting_code"
    )
    r_year = "v_phase.r_year::text" if cast_cross_posting_phase else "v_phase.r_year"
    _execute(
        f"""
CREATE OR REPLACE FUNCTION mata_rls.resolve_native_teaching_target_v2(
    p_resident_id uuid,
    p_event_id uuid
)
RETURNS TABLE(
    outcome text, unavailable_reason text, event_id uuid,
    reporting_period_id uuid, programme_code text, posting_code text,
    r_year text, global_session_type_id uuid, teaching_name_id uuid,
    mapping_id uuid, mapping_revision integer, teaching_target_id uuid,
    session_type_id uuid
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    v_existing record;
    v_event record;
    v_resident_programme text;
    v_phase record;
    v_mapping record;
    v_target record;
BEGIN
    SELECT * INTO v_existing
    FROM mata_rls.resolve_native_teaching_target(p_resident_id, p_event_id);

    IF v_existing.outcome IS NULL AND v_existing.unavailable_reason IS NULL THEN
        RETURN;
    END IF;

    IF v_existing.outcome IS NOT NULL
       OR v_existing.unavailable_reason IS DISTINCT FROM 'source_programme_mismatch'
    THEN
        RETURN QUERY SELECT
            v_existing.outcome, v_existing.unavailable_reason,
            v_existing.event_id, v_existing.reporting_period_id,
            v_existing.programme_code, v_existing.posting_code,
            v_existing.r_year, v_existing.global_session_type_id,
            v_existing.teaching_name_id, v_existing.mapping_id,
            v_existing.mapping_revision, v_existing.teaching_target_id,
            v_existing.session_type_id;
        RETURN;
    END IF;

    SELECT event.* INTO v_event
    FROM public.teaching_events AS event
    WHERE event.id = p_event_id
      AND mata_rls.can_select_teaching_event(event.id);
    IF NOT FOUND OR v_event.created_for_programme_code IS NOT NULL THEN
        RETURN QUERY SELECT
            NULL::text, 'source_programme_mismatch', p_event_id,
            NULL::uuid, NULL::text, NULL::text, NULL::text,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
            NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    SELECT resident.programme_code INTO v_resident_programme
    FROM public.residents AS resident
    WHERE resident.id = p_resident_id;

    SELECT resident_posting.reporting_period_id,
           resident_posting.posting_code,
           resident_posting.r_year
    INTO v_phase
    FROM public.resident_postings AS resident_posting
    WHERE resident_posting.resident_id = p_resident_id
      AND resident_posting.reporting_period_id = v_event.source_reporting_period_id
      AND resident_posting.posting_code = v_event.posting_code
      AND resident_posting.start_date <= v_event.event_date
      AND resident_posting.end_date >= v_event.event_date
      AND resident_posting.status IN ('active', 'loa_working');
    IF NOT FOUND THEN
        RETURN QUERY SELECT
            NULL::text, 'native_phase_unavailable', v_event.id,
            NULL::uuid, NULL::text, NULL::text, NULL::text,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
            NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    SELECT mapping.id, mapping.revision, mapping.teaching_target_id
    INTO v_mapping
    FROM public.teaching_name_mappings AS mapping
    JOIN public.teaching_name_programme_scopes AS scope
      ON scope.teaching_name_id = mapping.teaching_name_id
     AND scope.reporting_period_id = mapping.reporting_period_id
     AND scope.programme_code = mapping.programme_code
    WHERE mapping.teaching_name_id = v_event.teaching_name_id
      AND mapping.reporting_period_id = v_phase.reporting_period_id
      AND mapping.programme_code = v_resident_programme
      AND mapping.posting_code = v_phase.posting_code
      AND mapping.r_year = v_phase.r_year;
    IF NOT FOUND THEN
        RETURN QUERY SELECT
            NULL::text, 'mapping_unavailable', v_event.id,
            v_phase.reporting_period_id, {programme},
            {posting}, {r_year},
            NULL::uuid, v_event.teaching_name_id,
            NULL::uuid, NULL::integer, NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    IF v_mapping.teaching_target_id IS NULL THEN
        RETURN QUERY SELECT
            'pending_mapping'::text, NULL::text, v_event.id,
            v_phase.reporting_period_id, {programme},
            {posting}, {r_year},
            NULL::uuid, v_event.teaching_name_id,
            v_mapping.id, v_mapping.revision, NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    SELECT target.id, target.session_type_id INTO v_target
    FROM public.teaching_targets AS target
    WHERE target.id = v_mapping.teaching_target_id
      AND target.reporting_period_id = v_phase.reporting_period_id
      AND target.programme_code = v_resident_programme
      AND target.posting_code = v_phase.posting_code
      AND target.r_year = v_phase.r_year;
    IF NOT FOUND THEN
        RETURN QUERY SELECT
            NULL::text, 'target_scope_mismatch', v_event.id,
            v_phase.reporting_period_id, {programme},
            {posting}, {r_year},
            NULL::uuid, v_event.teaching_name_id,
            v_mapping.id, v_mapping.revision, NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    RETURN QUERY SELECT
        'mapped_target'::text, NULL::text, v_event.id,
        v_phase.reporting_period_id, {programme},
        {posting}, {r_year},
        NULL::uuid, v_event.teaching_name_id,
        v_mapping.id, v_mapping.revision, v_target.id,
        v_target.session_type_id;
END
$function$;
"""
    )


def upgrade() -> None:
    _replace_native_resolver(cast_cross_posting_phase=True)
    _execute('DROP POLICY "mata_rls_teaching_events_select" ON public.teaching_events')
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_events_select"
ON public.teaching_events
AS PERMISSIVE
FOR SELECT
TO {RUNTIME_ROLE}
USING (
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
    OR mata_rls.can_select_teaching_event(id)
)
"""
    )


def downgrade() -> None:
    _execute('DROP POLICY "mata_rls_teaching_events_select" ON public.teaching_events')
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_events_select"
ON public.teaching_events
AS PERMISSIVE
FOR SELECT
TO {RUNTIME_ROLE}
USING (
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
)
"""
    )
    _replace_native_resolver(cast_cross_posting_phase=False)
