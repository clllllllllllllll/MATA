"""add deterministic native teaching-target resolution seam

Revision ID: 20260805_000037
Revises: 20260805_000036
Create Date: 2026-08-05

"""

from __future__ import annotations

from alembic import op


revision = "20260805_000037"
down_revision = "20260805_000036"
branch_labels = None
depends_on = None


RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"
OPTIONAL_BROWSER_ROLES = ("anon", "authenticated", "service_role")
RESOLUTION_SIGNATURE = "resolve_native_teaching_target(uuid,uuid)"


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
                'REVOKE ALL PRIVILEGES ON FUNCTION '
                'mata_rls.{RESOLUTION_SIGNATURE} FROM %I',
                optional_role
            );
        END IF;
    END LOOP;
END
$migration$
"""
    )


def _secure_runtime_helper() -> None:
    _execute(
        f"REVOKE ALL PRIVILEGES ON FUNCTION mata_rls.{RESOLUTION_SIGNATURE} "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        f"GRANT EXECUTE ON FUNCTION mata_rls.{RESOLUTION_SIGNATURE} "
        f"TO {RUNTIME_ROLE}"
    )
    _revoke_optional_function_privileges(RESOLUTION_SIGNATURE)


def upgrade() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.resolve_native_teaching_target(
    p_resident_id uuid,
    p_event_id uuid
)
RETURNS TABLE(
    outcome text,
    unavailable_reason text,
    event_id uuid,
    reporting_period_id uuid,
    programme_code text,
    posting_code text,
    r_year text,
    global_session_type_id uuid,
    teaching_name_id uuid,
    mapping_id uuid,
    mapping_revision integer,
    teaching_target_id uuid,
    session_type_id uuid
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    v_event record;
    v_phase record;
    v_mapping record;
    v_target record;
    v_resident_programme text;
    v_phase_count integer;
BEGIN
    -- This helper is deliberately read-only and does not replace route-level
    -- authorization.  Its runtime grant must not widen the generic event or
    -- resident visibility surface: only a signed native resident context for
    -- itself, a signed scoped Programme PC context, or a signed Master context
    -- may invoke it.  In particular, Secretary and external-resident contexts
    -- fail before any event, mapping, or target evidence is selected.
    IF mata_rls.is_master_admin()
       OR mata_rls.is_native_resident(p_resident_id)
    THEN
        NULL;
    ELSIF mata_rls.current_subject_type() = 'staff'
       AND mata_rls.current_app_role() = 'admin'
       AND mata_rls.current_admin_level() = 'programme'
    THEN
        IF NOT EXISTS (
            SELECT 1
            FROM public.residents AS resident
            WHERE resident.id = p_resident_id
              AND resident.programme_code IS NOT NULL
              AND mata_rls.has_programme_scope(resident.programme_code)
        ) THEN
            RETURN;
        END IF;
    ELSE
        RETURN;
    END IF;

    -- Preserve the ordinary event visibility relation after applying the
    -- resolver-specific role boundary above.
    IF NOT mata_rls.can_select_teaching_event(p_event_id) THEN
        RETURN;
    END IF;

    SELECT
        teaching_event.id,
        teaching_event.is_adhoc,
        teaching_event.event_date,
        teaching_event.teaching_name,
        teaching_event.duration_hours,
        teaching_event.session_type_id,
        teaching_event.created_by_role,
        teaching_event.created_by_resident_id,
        teaching_event.teaching_name_id,
        teaching_event.global_session_type_id,
        teaching_event.source_programme_code,
        teaching_event.source_reporting_period_id
    INTO v_event
    FROM public.teaching_events AS teaching_event
    WHERE teaching_event.id = p_event_id;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    -- Explicit global identity always wins.  Activity gates only new choices;
    -- an inactive historical global source remains excluded on every read.
    IF v_event.global_session_type_id IS NOT NULL THEN
        IF v_event.is_adhoc
           OR v_event.teaching_name_id IS NOT NULL
           OR v_event.source_programme_code IS NOT NULL
           OR v_event.source_reporting_period_id IS NOT NULL
        THEN
            RETURN QUERY SELECT
                NULL::text, 'invalid_source_provenance', v_event.id,
                NULL::uuid, NULL::text, NULL::text, NULL::text,
                NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
                NULL::uuid, NULL::uuid;
            RETURN;
        END IF;

        RETURN QUERY SELECT
            'global_excluded'::text, NULL::text, v_event.id,
            NULL::uuid, NULL::text, NULL::text, NULL::text,
            v_event.global_session_type_id, NULL::uuid, NULL::uuid,
            NULL::integer, NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    IF v_event.is_adhoc THEN
        IF v_event.teaching_name_id IS NOT NULL
           OR v_event.source_programme_code IS NOT NULL
           OR v_event.source_reporting_period_id IS NOT NULL
           OR v_event.created_by_role IS DISTINCT FROM 'resident'
           OR v_event.created_by_resident_id IS DISTINCT FROM p_resident_id
           OR v_event.teaching_name
               IS DISTINCT FROM 'Department/Programme Teaching [1h]'
           OR v_event.duration_hours IS DISTINCT FROM 1.00::numeric
           OR v_event.session_type_id IS NOT NULL
        THEN
            RETURN QUERY SELECT
                NULL::text, 'invalid_adhoc_provenance', v_event.id,
                NULL::uuid, NULL::text, NULL::text, NULL::text,
                NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
                NULL::uuid, NULL::uuid;
            RETURN;
        END IF;

        SELECT resident.programme_code
        INTO v_resident_programme
        FROM public.residents AS resident
        WHERE resident.id = p_resident_id;

        IF NOT FOUND OR v_resident_programme IS NULL THEN
            RETURN QUERY SELECT
                NULL::text, 'resident_programme_unavailable', v_event.id,
                NULL::uuid, NULL::text, NULL::text, NULL::text,
                NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
                NULL::uuid, NULL::uuid;
            RETURN;
        END IF;

        SELECT count(*)
        INTO v_phase_count
        FROM public.resident_postings AS phase
        WHERE phase.resident_id = p_resident_id
          AND phase.start_date <= v_event.event_date
          AND phase.end_date >= v_event.event_date
          AND phase.status IN ('active', 'loa_working');

        IF v_phase_count <> 1 THEN
            RETURN QUERY SELECT
                NULL::text, 'native_phase_unavailable', v_event.id,
                NULL::uuid, NULL::text, NULL::text, NULL::text,
                NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
                NULL::uuid, NULL::uuid;
            RETURN;
        END IF;

        SELECT
            phase.reporting_period_id,
            phase.posting_code,
            phase.r_year
        INTO v_phase
        FROM public.resident_postings AS phase
        WHERE phase.resident_id = p_resident_id
          AND phase.start_date <= v_event.event_date
          AND phase.end_date >= v_event.event_date
          AND phase.status IN ('active', 'loa_working');

        -- A posting date range alone is not enough: malformed historical data
        -- could attach the matching phase to another reporting period.  The
        -- fixed target is valid only when the event date is also within that
        -- phase's own reporting-period boundaries.
        PERFORM 1
        FROM public.reporting_periods AS period
        WHERE period.id = v_phase.reporting_period_id
          AND v_event.event_date BETWEEN period.start_date AND period.end_date;

        IF NOT FOUND THEN
            RETURN QUERY SELECT
                NULL::text, 'native_phase_period_unavailable', v_event.id,
                NULL::uuid, NULL::text, NULL::text, NULL::text,
                NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
                NULL::uuid, NULL::uuid;
            RETURN;
        END IF;

        SELECT
            target.id,
            target.session_type_id
        INTO v_target
        FROM public.teaching_targets AS target
        JOIN public.session_types AS session_type
          ON session_type.id = target.session_type_id
        WHERE target.reporting_period_id = v_phase.reporting_period_id
          AND target.programme_code = v_resident_programme
          AND target.posting_code = v_phase.posting_code
          AND target.r_year = v_phase.r_year
          AND session_type.name = 'Department/Programme Teaching [1h]'
          AND session_type.duration_hours = 1.00::numeric;

        IF NOT FOUND THEN
            RETURN QUERY SELECT
            NULL::text, 'fixed_adhoc_target_unavailable', v_event.id,
            v_phase.reporting_period_id, v_resident_programme::text,
            v_phase.posting_code::text, v_phase.r_year::text,
                NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
                NULL::uuid, NULL::uuid;
            RETURN;
        END IF;

        RETURN QUERY SELECT
            'fixed_adhoc_target'::text, NULL::text, v_event.id,
            v_phase.reporting_period_id, v_resident_programme::text,
            v_phase.posting_code::text, v_phase.r_year::text,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
            v_target.id, v_target.session_type_id;
        RETURN;
    END IF;

    -- Both source identities absent is a true legacy row only if no scoped
    -- provenance remains.  Neither it nor malformed provenance can be guessed
    -- from the display snapshot, session type, posting, or any other text.
    IF v_event.teaching_name_id IS NULL THEN
        RETURN QUERY SELECT
            NULL::text,
            CASE
                WHEN v_event.source_programme_code IS NULL
                 AND v_event.source_reporting_period_id IS NULL
                THEN 'legacy_source_unsupported'
                ELSE 'pool_identity_unavailable'
            END,
            v_event.id,
            NULL::uuid, NULL::text, NULL::text, NULL::text,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
            NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    IF v_event.source_programme_code IS NULL
       OR v_event.source_reporting_period_id IS NULL
    THEN
        RETURN QUERY SELECT
            NULL::text, 'invalid_source_provenance', v_event.id,
            NULL::uuid, NULL::text, NULL::text, NULL::text,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
            NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    PERFORM 1
    FROM public.reporting_periods AS period
    WHERE period.id = v_event.source_reporting_period_id
      AND v_event.event_date BETWEEN period.start_date AND period.end_date;
    IF NOT FOUND THEN
        RETURN QUERY SELECT
            NULL::text, 'invalid_source_provenance', v_event.id,
            NULL::uuid, NULL::text, NULL::text, NULL::text,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
            NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    PERFORM 1
    FROM public.teaching_names AS teaching_name
    WHERE teaching_name.id = v_event.teaching_name_id
      AND teaching_name.reporting_period_id = v_event.source_reporting_period_id
      AND teaching_name.programme_code = v_event.source_programme_code;
    IF NOT FOUND THEN
        RETURN QUERY SELECT
            NULL::text, 'invalid_source_provenance', v_event.id,
            NULL::uuid, NULL::text, NULL::text, NULL::text,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
            NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    SELECT resident.programme_code
    INTO v_resident_programme
    FROM public.residents AS resident
    WHERE resident.id = p_resident_id;

    IF NOT FOUND
       OR v_resident_programme IS NULL
       OR v_resident_programme <> v_event.source_programme_code
    THEN
        RETURN QUERY SELECT
            NULL::text, 'source_programme_mismatch', v_event.id,
            NULL::uuid, NULL::text, NULL::text, NULL::text,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
            NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    SELECT count(*)
    INTO v_phase_count
    FROM public.resident_postings AS phase
    WHERE phase.resident_id = p_resident_id
      AND phase.reporting_period_id = v_event.source_reporting_period_id
      AND phase.start_date <= v_event.event_date
      AND phase.end_date >= v_event.event_date
      AND phase.status IN ('active', 'loa_working');

    IF v_phase_count <> 1 THEN
        RETURN QUERY SELECT
            NULL::text, 'native_phase_unavailable', v_event.id,
            NULL::uuid, NULL::text, NULL::text, NULL::text,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
            NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    SELECT
        phase.reporting_period_id,
        phase.posting_code,
        phase.r_year
    INTO v_phase
    FROM public.resident_postings AS phase
    WHERE phase.resident_id = p_resident_id
      AND phase.reporting_period_id = v_event.source_reporting_period_id
      AND phase.start_date <= v_event.event_date
      AND phase.end_date >= v_event.event_date
      AND phase.status IN ('active', 'loa_working');

    SELECT
        mapping.id,
        mapping.revision,
        mapping.teaching_target_id
    INTO v_mapping
    FROM public.teaching_name_mappings AS mapping
    WHERE mapping.teaching_name_id = v_event.teaching_name_id
      AND mapping.reporting_period_id = v_event.source_reporting_period_id
      AND mapping.programme_code = v_event.source_programme_code
      AND mapping.posting_code = v_phase.posting_code
      AND mapping.r_year = v_phase.r_year;

    IF NOT FOUND THEN
        RETURN QUERY SELECT
            NULL::text, 'mapping_unavailable', v_event.id,
            v_phase.reporting_period_id, v_event.source_programme_code::text,
            v_phase.posting_code::text, v_phase.r_year::text,
            NULL::uuid, v_event.teaching_name_id, NULL::uuid, NULL::integer,
            NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    IF v_mapping.teaching_target_id IS NULL THEN
        RETURN QUERY SELECT
            'pending_mapping'::text, NULL::text, v_event.id,
            v_phase.reporting_period_id, v_event.source_programme_code::text,
            v_phase.posting_code::text, v_phase.r_year::text,
            NULL::uuid, v_event.teaching_name_id, v_mapping.id,
            v_mapping.revision, NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    SELECT
        target.id,
        target.session_type_id
    INTO v_target
    FROM public.teaching_targets AS target
    WHERE target.id = v_mapping.teaching_target_id
      AND target.reporting_period_id = v_event.source_reporting_period_id
      AND target.programme_code = v_event.source_programme_code
      AND target.posting_code = v_phase.posting_code
      AND target.r_year = v_phase.r_year;

    IF NOT FOUND THEN
        RETURN QUERY SELECT
            NULL::text, 'target_scope_mismatch', v_event.id,
            v_phase.reporting_period_id, v_event.source_programme_code::text,
            v_phase.posting_code::text, v_phase.r_year::text,
            NULL::uuid, v_event.teaching_name_id, v_mapping.id,
            v_mapping.revision, NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    RETURN QUERY SELECT
        'mapped_target'::text, NULL::text, v_event.id,
        v_phase.reporting_period_id, v_event.source_programme_code::text,
        v_phase.posting_code::text, v_phase.r_year::text,
        NULL::uuid, v_event.teaching_name_id, v_mapping.id,
        v_mapping.revision, v_target.id, v_target.session_type_id;
END
$function$
"""
    )
    _secure_runtime_helper()


def downgrade() -> None:
    _execute(f"DROP FUNCTION mata_rls.{RESOLUTION_SIGNATURE}")
