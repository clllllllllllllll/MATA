"""allow LOA attendance and persist event-date classification

Revision ID: 20260813_000042
Revises: 20260813_000041
Create Date: 2026-08-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260813_000042"
down_revision = "20260813_000041"
branch_labels = None
depends_on = None

RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"
OPTIONAL_BROWSER_ROLES = ("anon", "authenticated", "service_role")
RECLASSIFY_SIGNATURE = "reclassify_native_attendance_loa(uuid,uuid)"
LOA_ADHOC_SIGNATURE = (
    "create_native_loa_adhoc_attendance("
    "text,text,text,date,time without time zone,time without time zone,numeric)"
)


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


def _replace_attendance_integrity(*, allow_loa_reclassification: bool) -> None:
    loa_declaration = (
        "    loa_row record;\n"
        if allow_loa_reclassification
        else ""
    )
    loa_update_guard = (
        r"""
    IF runtime_origin
       AND TG_OP = 'UPDATE'
       AND (
           pg_catalog.to_jsonb(OLD) - ARRAY[
               'submitted_during_loa',
               'loa_resident_posting_id',
               'loa_type',
               'loa_classified_at',
               'updated_at'
           ]
       ) IS NOT DISTINCT FROM (
           pg_catalog.to_jsonb(NEW) - ARRAY[
               'submitted_during_loa',
               'loa_resident_posting_id',
               'loa_type',
               'loa_classified_at',
               'updated_at'
           ]
       )
    THEN
        SELECT posting.id, posting.loa_type
        INTO loa_row
        FROM public.teaching_events AS event
        JOIN public.resident_postings AS posting
          ON posting.resident_id = NEW.resident_id
         AND posting.status IN ('loa', 'loa_working')
         AND event.event_date BETWEEN posting.start_date AND posting.end_date
         AND event.event_date BETWEEN
             COALESCE(posting.loa_start_date, posting.start_date)
             AND COALESCE(posting.loa_end_date, posting.end_date)
        WHERE event.id = NEW.teaching_event_id
        ORDER BY
            CASE posting.status WHEN 'loa' THEN 0 ELSE 1 END,
            posting.start_date DESC,
            posting.id
        LIMIT 1;

        IF NEW.submitted_during_loa IS DISTINCT FROM FOUND
           OR NEW.loa_resident_posting_id IS DISTINCT FROM loa_row.id
           OR NEW.loa_type IS DISTINCT FROM loa_row.loa_type
        THEN
            RAISE EXCEPTION 'LOA attendance classification is inconsistent'
                USING ERRCODE = '23514';
        END IF;

        NEW.loa_classified_at := clock_timestamp();
        NEW.updated_at := OLD.updated_at;
        RETURN NEW;
    END IF;
"""
        if allow_loa_reclassification
        else ""
    )
    _execute(
        f"""
CREATE OR REPLACE FUNCTION mata_private.enforce_attendance_integrity()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    event_row record;
    attendance_subject_id uuid;
    old_attendance_subject_id uuid;
{loa_declaration}    runtime_origin boolean := pg_catalog.pg_has_role(
        SESSION_USER,
        'mata_app_runtime',
        'MEMBER'
    );
BEGIN
    IF TG_TABLE_NAME = 'attendance_records' THEN
        attendance_subject_id := (
            pg_catalog.to_jsonb(NEW) ->> 'resident_id'
        )::uuid;
        IF TG_OP = 'UPDATE' THEN
            old_attendance_subject_id := (
                pg_catalog.to_jsonb(OLD) ->> 'resident_id'
            )::uuid;
        END IF;
    ELSIF TG_TABLE_NAME = 'external_attendance_records' THEN
        attendance_subject_id := (
            pg_catalog.to_jsonb(NEW) ->> 'external_resident_id'
        )::uuid;
        IF TG_OP = 'UPDATE' THEN
            old_attendance_subject_id := (
                pg_catalog.to_jsonb(OLD) ->> 'external_resident_id'
            )::uuid;
        END IF;
    ELSE
        RAISE EXCEPTION 'Unexpected attendance table'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF OLD.status = 'removed' AND NEW.status <> 'removed' THEN
            RAISE EXCEPTION 'Removed attendance is immutable'
                USING ERRCODE = '23514';
        END IF;

        IF old_attendance_subject_id
               IS DISTINCT FROM attendance_subject_id
           OR OLD.teaching_event_id
              IS DISTINCT FROM NEW.teaching_event_id
        THEN
            IF TG_TABLE_NAME = 'attendance_records' THEN
                RAISE EXCEPTION 'Native attendance identity is immutable'
                    USING ERRCODE = '23514';
            ELSE
                RAISE EXCEPTION 'External attendance identity is immutable'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;

{loa_update_guard}    SELECT
        event.is_adhoc,
        event.posting_code,
        event.created_by_resident_id,
        event.created_by_external_resident_id
    INTO event_row
    FROM public.teaching_events AS event
    WHERE event.id = NEW.teaching_event_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Teaching event is unavailable'
            USING ERRCODE = '23503';
    END IF;

    IF runtime_origin AND TG_OP = 'INSERT' THEN
        IF NEW.status <> 'submitted'
           OR NEW.posting_code IS DISTINCT FROM event_row.posting_code
        THEN
            RAISE EXCEPTION
                'Runtime attendance inserts must be submitted event copies'
                USING ERRCODE = '23514';
        END IF;
        NEW.submitted_at := CURRENT_TIMESTAMP;
        NEW.created_at := CURRENT_TIMESTAMP;
        NEW.updated_at := CURRENT_TIMESTAMP;
    END IF;

    IF runtime_origin AND TG_OP = 'UPDATE' THEN
        IF OLD.id IS DISTINCT FROM NEW.id
           OR OLD.submitted_at IS DISTINCT FROM NEW.submitted_at
           OR OLD.posting_code IS DISTINCT FROM NEW.posting_code
           OR OLD.created_at IS DISTINCT FROM NEW.created_at
           OR NOT (
               OLD.status = 'submitted'
               AND NEW.status = 'removed'
           )
        THEN
            RAISE EXCEPTION
                'Runtime attendance permits only submitted-to-removed'
                USING ERRCODE = '23514';
        END IF;
        NEW.updated_at := CURRENT_TIMESTAMP;
    END IF;

    IF TG_OP = 'UPDATE'
       AND event_row.is_adhoc
       AND NOT runtime_origin
       AND (
           (pg_catalog.to_jsonb(OLD) - ARRAY['status', 'updated_at'])
               IS DISTINCT FROM
           (pg_catalog.to_jsonb(NEW) - ARRAY['status', 'updated_at'])
           OR NOT (
               (
                   OLD.status IS NOT DISTINCT FROM NEW.status
                   AND OLD.updated_at IS NOT DISTINCT FROM NEW.updated_at
               )
               OR (
                   OLD.status = 'submitted'
                   AND NEW.status = 'removed'
                   AND NEW.updated_at >= OLD.updated_at
               )
           )
       )
    THEN
        RAISE EXCEPTION
            'Ad-hoc attendance permits only submitted-to-removed'
            USING ERRCODE = '23514';
    END IF;

    IF event_row.is_adhoc
       AND TG_TABLE_NAME = 'attendance_records'
       AND (
           event_row.created_by_resident_id
               IS DISTINCT FROM attendance_subject_id
           OR event_row.created_by_external_resident_id IS NOT NULL
       )
    THEN
        RAISE EXCEPTION
            'Native attendance must match the ad-hoc creator'
            USING ERRCODE = '23514';
    END IF;

    IF event_row.is_adhoc
       AND TG_TABLE_NAME = 'external_attendance_records'
       AND (
           event_row.created_by_external_resident_id
               IS DISTINCT FROM attendance_subject_id
           OR event_row.created_by_resident_id IS NOT NULL
       )
    THEN
        RAISE EXCEPTION
            'External attendance must match the ad-hoc creator'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;
"""
    )


def _create_classification_contract() -> None:
    op.add_column(
        "attendance_records",
        sa.Column(
            "submitted_during_loa",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "attendance_records",
        sa.Column("loa_resident_posting_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "attendance_records",
        sa.Column("loa_type", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "attendance_records",
        sa.Column(
            "loa_classified_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_foreign_key(
        "fk_attendance_records_loa_resident_posting",
        "attendance_records",
        "resident_postings",
        ["loa_resident_posting_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_attendance_records_loa_classification",
        "attendance_records",
        ["resident_id", "submitted_during_loa", "status"],
    )
    _replace_attendance_integrity(allow_loa_reclassification=True)
    _execute(
        r"""
CREATE FUNCTION mata_private.classify_native_attendance_loa()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    loa_row record;
BEGIN
    SELECT posting.id, posting.loa_type
    INTO loa_row
    FROM public.teaching_events AS event
    JOIN public.resident_postings AS posting
      ON posting.resident_id = NEW.resident_id
     AND posting.status IN ('loa', 'loa_working')
     AND event.event_date BETWEEN posting.start_date AND posting.end_date
     AND event.event_date BETWEEN
         COALESCE(posting.loa_start_date, posting.start_date)
         AND COALESCE(posting.loa_end_date, posting.end_date)
    WHERE event.id = NEW.teaching_event_id
    ORDER BY
        CASE posting.status WHEN 'loa' THEN 0 ELSE 1 END,
        posting.start_date DESC,
        posting.id
    LIMIT 1;

    NEW.submitted_during_loa := FOUND;
    NEW.loa_resident_posting_id := loa_row.id;
    NEW.loa_type := loa_row.loa_type;
    NEW.loa_classified_at := clock_timestamp();
    RETURN NEW;
END
$function$;

REVOKE ALL PRIVILEGES ON FUNCTION
mata_private.classify_native_attendance_loa()
FROM PUBLIC, mata_app_runtime, mata_auth_internal;

CREATE TRIGGER mata_classify_native_attendance_loa
BEFORE INSERT OR UPDATE OF resident_id, teaching_event_id
ON public.attendance_records
FOR EACH ROW
EXECUTE FUNCTION mata_private.classify_native_attendance_loa();
"""
    )
    _execute(
        r"""
CREATE FUNCTION mata_rls.reclassify_native_attendance_loa(
    p_reporting_period_id uuid,
    p_resident_id uuid DEFAULT NULL
)
RETURNS TABLE(
    affected_count integer,
    during_loa_count integer,
    non_loa_count integer
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    normalized_programme text;
BEGIN
    IF NOT mata_rls.context_is_valid()
       OR mata_rls.current_subject_type() <> 'staff'
       OR mata_rls.current_app_role() <> 'admin'
       OR p_reporting_period_id IS NULL
    THEN
        RAISE EXCEPTION 'Verified admin context required'
            USING ERRCODE = '28000';
    END IF;

    IF p_resident_id IS NULL THEN
        IF NOT mata_rls.is_master_admin() THEN
            RAISE EXCEPTION 'Master Admin context required for period-wide reclassification'
                USING ERRCODE = '42501';
        END IF;
    ELSE
        SELECT resident.programme_code
        INTO normalized_programme
        FROM public.residents AS resident
        WHERE resident.id = p_resident_id;
        IF NOT FOUND OR NOT (
            mata_rls.is_master_admin()
            OR mata_rls.has_programme_scope(normalized_programme)
        ) THEN
            RAISE EXCEPTION 'Resident is outside the admin programme scope'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    WITH candidates AS (
        SELECT
            attendance.id AS attendance_id,
            loa.id AS loa_resident_posting_id,
            loa.loa_type
        FROM public.attendance_records AS attendance
        JOIN public.teaching_events AS event
          ON event.id = attendance.teaching_event_id
        JOIN public.reporting_periods AS period
          ON period.id = p_reporting_period_id
         AND event.event_date BETWEEN period.start_date AND period.end_date
        LEFT JOIN LATERAL (
            SELECT posting.id, posting.loa_type
            FROM public.resident_postings AS posting
            WHERE posting.resident_id = attendance.resident_id
              AND posting.reporting_period_id = p_reporting_period_id
              AND posting.status IN ('loa', 'loa_working')
              AND event.event_date BETWEEN posting.start_date AND posting.end_date
              AND event.event_date BETWEEN
                  COALESCE(posting.loa_start_date, posting.start_date)
                  AND COALESCE(posting.loa_end_date, posting.end_date)
            ORDER BY
                CASE posting.status WHEN 'loa' THEN 0 ELSE 1 END,
                posting.start_date DESC,
                posting.id
            LIMIT 1
        ) AS loa ON true
        WHERE p_resident_id IS NULL
           OR attendance.resident_id = p_resident_id
    ), updated AS (
        UPDATE public.attendance_records AS attendance
        SET submitted_during_loa = candidate.loa_resident_posting_id IS NOT NULL,
            loa_resident_posting_id = candidate.loa_resident_posting_id,
            loa_type = candidate.loa_type,
            loa_classified_at = clock_timestamp()
        FROM candidates AS candidate
        WHERE attendance.id = candidate.attendance_id
          AND (
              attendance.submitted_during_loa IS DISTINCT FROM
                  (candidate.loa_resident_posting_id IS NOT NULL)
              OR attendance.loa_resident_posting_id IS DISTINCT FROM
                  candidate.loa_resident_posting_id
              OR attendance.loa_type IS DISTINCT FROM candidate.loa_type
          )
        RETURNING attendance.submitted_during_loa
    )
    SELECT
        count(*)::integer,
        count(*) FILTER (WHERE submitted_during_loa)::integer,
        count(*) FILTER (WHERE NOT submitted_during_loa)::integer
    INTO affected_count, during_loa_count, non_loa_count
    FROM updated;

    RETURN NEXT;
END
$function$;
"""
    )
    _secure_runtime_function(RECLASSIFY_SIGNATURE)


def _replace_loa_visibility_helpers() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_private.can_select_native_loa_event(
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
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT mata_rls.current_subject_type() = 'resident'
       AND NOT COALESCE(p_is_adhoc, false)
       AND p_created_by_resident_id IS NULL
       AND p_created_by_external_resident_id IS NULL
       AND (p_created_by_role IN ('secretary', 'programme_pc') OR p_created_by_role IS NULL)
       AND mata_private.scheduled_event_source_is_valid(
           p_event_date,
           p_teaching_name_id,
           p_global_session_type_id,
           p_source_programme_code,
           p_source_reporting_period_id
       )
       AND (
           p_source_programme_code IS NULL
           OR p_created_for_programme_code IS NULL
           OR p_created_for_programme_code = p_source_programme_code
       )
       AND EXISTS (
           SELECT 1
           FROM public.residents AS resident
           JOIN public.programmes AS programme
             ON programme.code = resident.programme_code
            AND programme.native_teaching_posting_code = p_posting_code
           JOIN public.resident_postings AS posting
             ON posting.resident_id = resident.id
            AND posting.status = 'loa'
            AND posting.posting_code IS NULL
            AND posting.start_date <= p_event_date
            AND posting.end_date >= p_event_date
            AND p_event_date BETWEEN
                COALESCE(posting.loa_start_date, posting.start_date)
                AND COALESCE(posting.loa_end_date, posting.end_date)
           WHERE resident.id = mata_rls.current_subject_id()
             AND resident.status = 'active'
             AND (
                 p_created_for_programme_code IS NULL
                 OR p_created_for_programme_code = resident.programme_code
             )
             AND (
                 p_global_session_type_id IS NOT NULL
                 OR (
                     p_source_programme_code = resident.programme_code
                     AND p_source_reporting_period_id = posting.reporting_period_id
                     AND p_teaching_name_id IS NOT NULL
                 )
                 OR (
                     p_teaching_name_id IS NULL
                     AND p_global_session_type_id IS NULL
                     AND p_source_programme_code IS NULL
                     AND p_source_reporting_period_id IS NULL
                 )
             )
       )
$function$;

REVOKE ALL PRIVILEGES ON FUNCTION mata_private.can_select_native_loa_event(
    uuid,boolean,text,date,text,text,uuid,uuid,uuid,uuid,text,uuid
) FROM PUBLIC, mata_app_runtime, mata_auth_internal;

CREATE OR REPLACE FUNCTION mata_rls.can_select_teaching_event(p_event_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT COALESCE((
        SELECT mata_rls.can_select_teaching_event_row(
            event.id, event.is_adhoc, event.posting_code, event.event_date,
            event.created_for_programme_code, event.created_by_role,
            event.created_by_resident_id,
            event.created_by_external_resident_id,
            event.teaching_name_id, event.global_session_type_id,
            event.source_programme_code, event.source_reporting_period_id
        ) OR mata_private.can_select_cross_programme_secretary_event(
            event.id, event.posting_code, event.event_date,
            event.created_for_programme_code, event.teaching_name_id,
            event.source_programme_code, event.source_reporting_period_id
        ) OR mata_private.can_select_native_loa_event(
            event.id, event.is_adhoc, event.posting_code, event.event_date,
            event.created_for_programme_code, event.created_by_role,
            event.created_by_resident_id,
            event.created_by_external_resident_id,
            event.teaching_name_id, event.global_session_type_id,
            event.source_programme_code, event.source_reporting_period_id
        )
        FROM public.teaching_events AS event
        WHERE event.id = p_event_id
    ), false)
$function$;

CREATE OR REPLACE FUNCTION mata_rls.can_submit_native_attendance(
    p_resident_id uuid,
    p_teaching_event_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT mata_rls.is_native_resident(p_resident_id)
       AND EXISTS (
           SELECT 1 FROM public.teaching_events AS event
           WHERE event.id = p_teaching_event_id
             AND NOT event.is_adhoc
       )
       AND mata_rls.can_select_teaching_event(p_teaching_event_id)
$function$;
"""
    )


def _replace_native_resolver() -> None:
    _execute(
        r"""
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
    v_native_posting text;
    v_phase record;
    v_mapping record;
    v_target record;
BEGIN
    SELECT * INTO v_existing
    FROM mata_rls.resolve_native_teaching_target(p_resident_id, p_event_id);

    IF v_existing.outcome IS NULL AND v_existing.unavailable_reason IS NULL THEN
        RETURN;
    END IF;
    IF v_existing.outcome IS NOT NULL THEN
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
    IF NOT FOUND OR v_event.created_for_programme_code IS NOT NULL
       AND v_event.created_for_programme_code IS DISTINCT FROM (
           SELECT resident.programme_code FROM public.residents AS resident
           WHERE resident.id = p_resident_id
       )
    THEN
        RETURN QUERY SELECT
            NULL::text, COALESCE(v_existing.unavailable_reason, 'event_unavailable'), p_event_id,
            NULL::uuid, NULL::text, NULL::text, NULL::text,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
            NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    IF v_event.is_adhoc OR v_event.teaching_name_id IS NULL THEN
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

    SELECT resident.programme_code, programme.native_teaching_posting_code
    INTO v_resident_programme, v_native_posting
    FROM public.residents AS resident
    JOIN public.programmes AS programme ON programme.code = resident.programme_code
    WHERE resident.id = p_resident_id;

    SELECT
        posting.reporting_period_id,
        COALESCE(posting.posting_code, v_event.posting_code)::text AS posting_code,
        posting.r_year::text AS r_year
    INTO v_phase
    FROM public.resident_postings AS posting
    WHERE posting.resident_id = p_resident_id
      AND posting.reporting_period_id = v_event.source_reporting_period_id
      AND posting.start_date <= v_event.event_date
      AND posting.end_date >= v_event.event_date
      AND (
          (
              posting.status IN ('active', 'loa_working')
              AND posting.posting_code = v_event.posting_code
          )
          OR (
              posting.status = 'loa'
              AND posting.posting_code IS NULL
              AND v_event.posting_code = v_native_posting
              AND v_event.event_date BETWEEN
                  COALESCE(posting.loa_start_date, posting.start_date)
                  AND COALESCE(posting.loa_end_date, posting.end_date)
          )
      )
    ORDER BY CASE WHEN posting.posting_code IS NOT NULL THEN 0 ELSE 1 END,
             posting.start_date DESC, posting.id
    LIMIT 1;
    IF NOT FOUND THEN
        RETURN QUERY SELECT
            NULL::text, 'native_phase_unavailable', v_event.id,
            NULL::uuid, NULL::text, NULL::text, NULL::text,
            NULL::uuid, NULL::uuid, NULL::uuid, NULL::integer,
            NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    IF v_event.global_session_type_id IS NOT NULL THEN
        RETURN QUERY SELECT
            'global_excluded'::text, NULL::text, v_event.id,
            NULL::uuid, NULL::text, NULL::text, NULL::text,
            v_event.global_session_type_id, NULL::uuid, NULL::uuid,
            NULL::integer, NULL::uuid, NULL::uuid;
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
            v_phase.reporting_period_id, v_resident_programme::text,
            v_phase.posting_code::text, v_phase.r_year::text,
            NULL::uuid, v_event.teaching_name_id,
            NULL::uuid, NULL::integer, NULL::uuid, NULL::uuid;
        RETURN;
    END IF;
    IF v_mapping.teaching_target_id IS NULL THEN
        RETURN QUERY SELECT
            'pending_mapping'::text, NULL::text, v_event.id,
            v_phase.reporting_period_id, v_resident_programme::text,
            v_phase.posting_code::text, v_phase.r_year::text,
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
            v_phase.reporting_period_id, v_resident_programme::text,
            v_phase.posting_code::text, v_phase.r_year::text,
            NULL::uuid, v_event.teaching_name_id,
            v_mapping.id, v_mapping.revision, NULL::uuid, NULL::uuid;
        RETURN;
    END IF;
    RETURN QUERY SELECT
        'mapped_target'::text, NULL::text, v_event.id,
        v_phase.reporting_period_id, v_resident_programme::text,
        v_phase.posting_code::text, v_phase.r_year::text,
        NULL::uuid, v_event.teaching_name_id,
        v_mapping.id, v_mapping.revision, v_target.id,
        v_target.session_type_id;
END
$function$;
"""
    )


def _create_native_loa_adhoc_helper() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.create_native_loa_adhoc_attendance(
    p_posting_code text,
    p_teaching_name text,
    p_details_of_session text,
    p_event_date date,
    p_start_time time without time zone,
    p_end_time time without time zone,
    p_duration_hours numeric
)
RETURNS TABLE(event_id uuid, attendance_id uuid)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    subject_id uuid := mata_rls.current_subject_id();
    resolved_period_id uuid;
    resolved_posting_code text;
    matching_count integer;
    new_event_id uuid;
    new_attendance_id uuid;
    candidate_start timestamp without time zone;
    candidate_end timestamp without time zone;
    lock_date date;
BEGIN
    IF NOT mata_rls.context_is_valid()
       OR mata_rls.current_subject_type() <> 'resident'
       OR subject_id IS NULL
    THEN
        RAISE EXCEPTION 'Verified resident context required'
            USING ERRCODE = '28000';
    END IF;
    IF pg_catalog.btrim(COALESCE(p_posting_code, '')) = ''
       OR p_teaching_name <> 'Department/Programme Teaching [1h]'
       OR p_event_date IS NULL
       OR p_start_time IS NULL
       OR p_end_time IS NULL
       OR p_duration_hours <> 1.00::numeric
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

    SELECT COUNT(*), pg_catalog.min(programme.native_teaching_posting_code)
    INTO matching_count, resolved_posting_code
    FROM public.residents AS resident
    JOIN public.programmes AS programme
      ON programme.code = resident.programme_code
    JOIN public.resident_postings AS posting
      ON posting.resident_id = resident.id
     AND posting.reporting_period_id = resolved_period_id
     AND posting.status = 'loa'
     AND posting.posting_code IS NULL
     AND p_event_date BETWEEN posting.start_date AND posting.end_date
     AND p_event_date BETWEEN
         COALESCE(posting.loa_start_date, posting.start_date)
         AND COALESCE(posting.loa_end_date, posting.end_date)
    WHERE resident.id = subject_id
      AND resident.status = 'active'
      AND programme.native_teaching_posting_code IS NOT NULL;
    IF matching_count <> 1
       OR resolved_posting_code IS DISTINCT FROM p_posting_code
    THEN
        RAISE EXCEPTION 'Ad-hoc teaching event is outside the resident LOA scope'
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
                'native-attendance:' || subject_id::text || ':' || lock_date::text,
                0
            )
        );
    END LOOP;

    IF EXISTS (
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

    INSERT INTO public.teaching_events (
        posting_code, teaching_name, details_of_session,
        event_date, start_time, end_time, duration_hours,
        session_type_id, is_adhoc, created_by_role,
        created_by_resident_id, created_by_external_resident_id
    ) VALUES (
        p_posting_code, 'Department/Programme Teaching [1h]', p_details_of_session,
        p_event_date, p_start_time, p_end_time, 1.00::numeric,
        NULL, true, 'resident', subject_id, NULL
    ) RETURNING id INTO new_event_id;

    INSERT INTO public.attendance_records (
        resident_id, teaching_event_id, status, posting_code
    ) VALUES (
        subject_id, new_event_id, 'submitted', p_posting_code
    ) RETURNING id INTO new_attendance_id;

    RETURN QUERY SELECT new_event_id, new_attendance_id;
END
$function$;
"""
    )
    _secure_runtime_function(LOA_ADHOC_SIGNATURE)


def _restore_native_resolver_000041() -> None:
    _execute(
        r"""
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
            v_phase.reporting_period_id, v_resident_programme::text,
            v_phase.posting_code::text, v_phase.r_year::text,
            NULL::uuid, v_event.teaching_name_id,
            NULL::uuid, NULL::integer, NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    IF v_mapping.teaching_target_id IS NULL THEN
        RETURN QUERY SELECT
            'pending_mapping'::text, NULL::text, v_event.id,
            v_phase.reporting_period_id, v_resident_programme::text,
            v_phase.posting_code::text, v_phase.r_year::text,
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
            v_phase.reporting_period_id, v_resident_programme::text,
            v_phase.posting_code::text, v_phase.r_year::text,
            NULL::uuid, v_event.teaching_name_id,
            v_mapping.id, v_mapping.revision, NULL::uuid, NULL::uuid;
        RETURN;
    END IF;

    RETURN QUERY SELECT
        'mapped_target'::text, NULL::text, v_event.id,
        v_phase.reporting_period_id, v_resident_programme::text,
        v_phase.posting_code::text, v_phase.r_year::text,
        NULL::uuid, v_event.teaching_name_id,
        v_mapping.id, v_mapping.revision, v_target.id,
        v_target.session_type_id;
END
$function$;
"""
    )


def _restore_current_helpers() -> None:
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
            event.id, event.is_adhoc, event.posting_code, event.event_date,
            event.created_for_programme_code, event.created_by_role,
            event.created_by_resident_id,
            event.created_by_external_resident_id,
            event.teaching_name_id, event.global_session_type_id,
            event.source_programme_code, event.source_reporting_period_id
        ) OR mata_private.can_select_cross_programme_secretary_event(
            event.id, event.posting_code, event.event_date,
            event.created_for_programme_code, event.teaching_name_id,
            event.source_programme_code, event.source_reporting_period_id
        )
        FROM public.teaching_events AS event
        WHERE event.id = p_event_id
    ), false)
$function$;
"""
    )


def upgrade() -> None:
    _create_classification_contract()
    _replace_loa_visibility_helpers()
    _replace_native_resolver()
    _create_native_loa_adhoc_helper()
    # Existing ad-hoc attendance is otherwise deliberately immutable even to
    # the owner.  Suspend only that exact trigger for this transactional
    # migration backfill; the new classifier trigger remains enabled and
    # recomputes every row from authoritative event-date LOA evidence.
    _execute(
        "ALTER TABLE public.attendance_records "
        "DISABLE TRIGGER mata_enforce_attendance_integrity"
    )
    _execute("UPDATE public.attendance_records SET resident_id = resident_id")
    _execute(
        "ALTER TABLE public.attendance_records "
        "ENABLE TRIGGER mata_enforce_attendance_integrity"
    )


def downgrade() -> None:
    _execute(f"DROP FUNCTION mata_rls.{LOA_ADHOC_SIGNATURE}")
    _restore_current_helpers()
    _restore_native_resolver_000041()
    _execute(
        "DROP FUNCTION mata_private.can_select_native_loa_event("
        "uuid,boolean,text,date,text,text,uuid,uuid,uuid,uuid,text,uuid)"
    )
    _execute("DROP TRIGGER mata_classify_native_attendance_loa ON public.attendance_records")
    _execute("DROP FUNCTION mata_private.classify_native_attendance_loa()")
    _execute(f"DROP FUNCTION mata_rls.{RECLASSIFY_SIGNATURE}")
    _replace_attendance_integrity(allow_loa_reclassification=False)
    op.drop_index("idx_attendance_records_loa_classification", table_name="attendance_records")
    op.drop_constraint(
        "fk_attendance_records_loa_resident_posting",
        "attendance_records",
        type_="foreignkey",
    )
    op.drop_column("attendance_records", "loa_classified_at")
    op.drop_column("attendance_records", "loa_type")
    op.drop_column("attendance_records", "loa_resident_posting_id")
    op.drop_column("attendance_records", "submitted_during_loa")
