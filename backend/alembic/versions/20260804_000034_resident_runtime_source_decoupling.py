"""decouple resident runtime attendance from the legacy teaching catalogue

Revision ID: 20260804_000034
Revises: 20260804_000033
Create Date: 2026-08-04

Phase G keeps the physical transitional catalogue and TTF parser intact, but
moves Native Resident, registered Non-NHG Resident, attendance, and ad-hoc
runtime authorization to persisted scheduled-event source identities.  It does
not infer a source from display text or backfill legacy events.
"""

from __future__ import annotations

from alembic import op


revision = "20260804_000034"
down_revision = "20260804_000033"
branch_labels = None
depends_on = None


RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"
DEFINER_ROLE = "mata_adhoc_attendance_definer"
ATOMIC_HELPER_SIGNATURE = (
    "create_adhoc_attendance("
    "text,text,text,text,text,date,time without time zone,"
    "time without time zone,numeric,uuid)"
)
SOURCE_SCOPE_SIGNATURE = "scheduled_event_source_scope(uuid)"
_OPTIONAL_BROWSER_ROLES = ("anon", "authenticated", "service_role")


def _execute(statement: str) -> None:
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(statement)


def _revoke_optional_function_privileges(function_signature: str) -> None:
    optional_roles = ", ".join(repr(role) for role in _OPTIONAL_BROWSER_ROLES)
    _execute(
        f"""
DO $migration$
DECLARE
    optional_role text;
BEGIN
    FOREACH optional_role IN ARRAY ARRAY[{optional_roles}]
    LOOP
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_roles
            WHERE rolname = optional_role
        ) THEN
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


def _grant_definer_ownership() -> None:
    _execute(
        rf"""
DO $migration$
DECLARE
    migration_role_is_superuser boolean;
BEGIN
    IF CURRENT_USER <> SESSION_USER THEN
        RAISE EXCEPTION
            'Migration role must be the direct session role'
            USING ERRCODE = '42501';
    END IF;

    SELECT rolsuper
    INTO STRICT migration_role_is_superuser
    FROM pg_catalog.pg_roles
    WHERE rolname = SESSION_USER;

    IF NOT migration_role_is_superuser THEN
        EXECUTE pg_catalog.format(
            'GRANT %I TO %I WITH INHERIT FALSE GRANTED BY %I',
            '{DEFINER_ROLE}',
            SESSION_USER,
            SESSION_USER
        );
        EXECUTE pg_catalog.format(
            'GRANT %I TO %I WITH SET TRUE GRANTED BY %I',
            '{DEFINER_ROLE}',
            SESSION_USER,
            SESSION_USER
        );
        EXECUTE pg_catalog.format(
            'GRANT %I TO %I WITH ADMIN FALSE GRANTED BY %I',
            '{DEFINER_ROLE}',
            SESSION_USER,
            SESSION_USER
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
    IF CURRENT_USER <> SESSION_USER THEN
        RAISE EXCEPTION
            'Migration role must be the direct session role'
            USING ERRCODE = '42501';
    END IF;

    SELECT rolsuper
    INTO STRICT migration_role_is_superuser
    FROM pg_catalog.pg_roles
    WHERE rolname = SESSION_USER;

    IF NOT migration_role_is_superuser THEN
        EXECUTE pg_catalog.format(
            'REVOKE %I FROM %I GRANTED BY %I RESTRICT',
            '{DEFINER_ROLE}',
            SESSION_USER,
            SESSION_USER
        );
    END IF;
END
$migration$
"""
    )


def _replace_atomic_helper(sql: str) -> None:
    _execute(f"GRANT CREATE ON SCHEMA mata_rls TO {DEFINER_ROLE}")
    _grant_definer_ownership()
    _execute(f"SET LOCAL ROLE {DEFINER_ROLE}")
    _execute(sql)
    _execute("SET LOCAL ROLE NONE")
    _execute(f"REVOKE CREATE ON SCHEMA mata_rls FROM {DEFINER_ROLE}")
    _revoke_definer_ownership()
    _execute(
        f"REVOKE ALL PRIVILEGES ON FUNCTION mata_rls.{ATOMIC_HELPER_SIGNATURE} "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        f"GRANT EXECUTE ON FUNCTION mata_rls.{ATOMIC_HELPER_SIGNATURE} "
        f"TO {RUNTIME_ROLE}"
    )
    _revoke_optional_function_privileges(ATOMIC_HELPER_SIGNATURE)


def _create_scheduled_event_selection_helper() -> None:
    _execute(
        r"""
CREATE OR REPLACE FUNCTION mata_rls.can_select_teaching_event(p_event_id uuid)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    event_row record;
    subject_type text := mata_rls.current_subject_type();
    subject_id uuid := mata_rls.current_subject_id();
    app_role text := mata_rls.current_app_role();
BEGIN
    SELECT
        event.id,
        event.is_adhoc,
        event.posting_code,
        event.event_date,
        event.created_for_programme_code,
        event.created_by_role,
        event.created_by_resident_id,
        event.created_by_external_resident_id,
        event.teaching_name_id,
        event.global_session_type_id
    INTO event_row
    FROM public.teaching_events AS event
    WHERE event.id = p_event_id;

    IF NOT FOUND THEN
        RETURN false;
    END IF;

    IF NOT event_row.is_adhoc THEN
        IF mata_rls.is_master_admin() THEN
            RETURN true;
        END IF;

        IF subject_type = 'staff' AND app_role = 'admin' THEN
            IF NOT (
                event_row.created_by_role IN ('secretary', 'programme_pc')
                OR event_row.created_by_role IS NULL
            ) THEN
                RETURN false;
            END IF;

            -- An explicit pool identity is its sole programme authority.  A
            -- shared posting, attendance provenance, or same display text
            -- must never fan it out to another programme.
            IF event_row.teaching_name_id IS NOT NULL
               AND event_row.global_session_type_id IS NULL
            THEN
                RETURN EXISTS (
                    SELECT 1
                    FROM public.teaching_names AS teaching_name
                    JOIN public.reporting_periods AS reporting_period
                      ON reporting_period.id = teaching_name.reporting_period_id
                    WHERE teaching_name.id = event_row.teaching_name_id
                      AND event_row.event_date BETWEEN
                          reporting_period.start_date AND reporting_period.end_date
                      AND (
                          event_row.created_for_programme_code IS NULL
                          OR event_row.created_for_programme_code
                              = teaching_name.programme_code
                      )
                      AND mata_rls.has_programme_scope(
                          teaching_name.programme_code
                      )
                );
            END IF;

            -- Explicit globals stay global-first.  Legacy rows use only
            -- persisted ownership/posting/attendance evidence below.  Both
            -- cases retain the pre-existing non-text programme evidence.
            IF event_row.teaching_name_id IS NULL
               AND event_row.global_session_type_id IS NOT NULL
            THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM public.global_session_types AS global_type
                    WHERE global_type.id = event_row.global_session_type_id
                      AND global_type.is_active
                ) THEN
                    RETURN false;
                END IF;
            ELSIF event_row.teaching_name_id IS NOT NULL
               OR event_row.global_session_type_id IS NOT NULL
            THEN
                -- A malformed dual-source row is intentionally invisible.
                RETURN false;
            END IF;

            IF event_row.created_for_programme_code IS NOT NULL THEN
                RETURN mata_rls.has_programme_scope(
                    event_row.created_for_programme_code
                );
            END IF;

            RETURN EXISTS (
                SELECT 1
                FROM public.secretary_programme_pools AS pool
                WHERE pool.posting_code = event_row.posting_code
                  AND pool.is_active
                  AND mata_rls.has_programme_scope(pool.programme_code)
            )
            OR EXISTS (
                SELECT 1
                FROM public.attendance_records AS attendance
                JOIN public.residents AS resident
                  ON resident.id = attendance.resident_id
                WHERE attendance.teaching_event_id = event_row.id
                  AND resident.programme_code IS NOT NULL
                  AND mata_rls.has_programme_scope(resident.programme_code)
            )
            OR EXISTS (
                SELECT 1
                FROM public.external_attendance_records AS attendance
                JOIN public.external_resident_postings AS external_posting
                  ON external_posting.external_resident_id
                      = attendance.external_resident_id
                 AND external_posting.posting_code = event_row.posting_code
                 AND external_posting.start_date <= event_row.event_date
                 AND COALESCE(
                         external_posting.end_date,
                         'infinity'::date
                     ) >= event_row.event_date
                 AND NOT EXISTS (
                     SELECT 1
                     FROM public.external_resident_postings AS competing_posting
                     WHERE competing_posting.external_resident_id
                         = attendance.external_resident_id
                       AND competing_posting.start_date <= event_row.event_date
                       AND COALESCE(
                               competing_posting.end_date,
                               'infinity'::date
                           ) >= event_row.event_date
                       AND competing_posting.id <> external_posting.id
                 )
                WHERE attendance.teaching_event_id = event_row.id
                  AND external_posting.programme_code IS NOT NULL
                  AND mata_rls.has_programme_scope(
                      external_posting.programme_code
                  )
            );
        END IF;

        IF subject_type = 'staff' AND app_role = 'secretary' THEN
            RETURN mata_rls.is_secretary_for_posting(event_row.posting_code)
               AND (
                    event_row.created_by_role IN ('secretary', 'programme_pc')
                    OR event_row.created_by_role IS NULL
               )
               AND (
                    event_row.created_for_programme_code IS NULL
                    OR EXISTS (
                        SELECT 1
                        FROM public.secretary_programme_pools AS pool
                        WHERE pool.posting_code = event_row.posting_code
                          AND pool.programme_code
                              = event_row.created_for_programme_code
                          AND pool.is_active
                    )
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
                 AND resident_posting.start_date <= event_row.event_date
                 AND resident_posting.end_date >= event_row.event_date
                 AND resident_posting.status IN ('active', 'loa_working')
                WHERE resident.id = subject_id
                  AND resident.status = 'active'
                  AND (
                      event_row.created_for_programme_code IS NULL
                      OR event_row.created_for_programme_code
                          = resident.programme_code
                  )
                  AND (
                      resident_posting.posting_code = event_row.posting_code
                      OR programme.native_teaching_posting_code
                          = event_row.posting_code
                  )
                  AND (
                      (
                          event_row.global_session_type_id IS NOT NULL
                          AND event_row.teaching_name_id IS NULL
                          AND EXISTS (
                              SELECT 1
                              FROM public.global_session_types AS global_type
                              WHERE global_type.id
                                  = event_row.global_session_type_id
                                AND global_type.is_active
                          )
                      )
                      OR (
                          event_row.teaching_name_id IS NOT NULL
                          AND event_row.global_session_type_id IS NULL
                          AND EXISTS (
                              SELECT 1
                              FROM public.teaching_names AS teaching_name
                              JOIN public.reporting_periods AS reporting_period
                                ON reporting_period.id
                                    = teaching_name.reporting_period_id
                              WHERE teaching_name.id
                                  = event_row.teaching_name_id
                                AND teaching_name.programme_code
                                    = resident.programme_code
                                AND resident_posting.reporting_period_id
                                    = teaching_name.reporting_period_id
                                AND event_row.event_date BETWEEN
                                    reporting_period.start_date
                                    AND reporting_period.end_date
                          )
                      )
                      OR (
                          event_row.teaching_name_id IS NULL
                          AND event_row.global_session_type_id IS NULL
                      )
                  )
            );
        END IF;

        IF subject_type = 'external_resident' THEN
            RETURN EXISTS (
                SELECT 1
                FROM public.external_residents AS external_resident
                JOIN public.external_resident_postings AS external_posting
                  ON external_posting.external_resident_id
                      = external_resident.id
                 AND external_posting.start_date <= event_row.event_date
                 AND COALESCE(
                         external_posting.end_date,
                         'infinity'::date
                     ) >= event_row.event_date
                JOIN public.posting_codes AS posting
                  ON posting.code = external_posting.posting_code
                WHERE external_resident.id = subject_id
                  AND external_resident.status = 'active'
                  AND external_posting.posting_code = event_row.posting_code
                  AND NOT EXISTS (
                      SELECT 1
                      FROM public.external_resident_postings AS competing_posting
                      WHERE competing_posting.external_resident_id
                          = external_resident.id
                        AND competing_posting.start_date <= event_row.event_date
                        AND COALESCE(
                                competing_posting.end_date,
                                'infinity'::date
                            ) >= event_row.event_date
                        AND competing_posting.id <> external_posting.id
                  )
                  AND (
                      (
                          event_row.created_for_programme_code IS NULL
                          AND posting.supports_secretary_events
                      )
                      OR (
                          event_row.created_for_programme_code IS NOT NULL
                          AND external_posting.programme_code IS NOT NULL
                          AND external_posting.programme_code
                              = event_row.created_for_programme_code
                      )
                  )
                  AND (
                      (
                          event_row.global_session_type_id IS NOT NULL
                          AND event_row.teaching_name_id IS NULL
                          AND EXISTS (
                              SELECT 1
                              FROM public.global_session_types AS global_type
                              WHERE global_type.id
                                  = event_row.global_session_type_id
                                AND global_type.is_active
                          )
                      )
                      OR (
                          event_row.teaching_name_id IS NOT NULL
                          AND event_row.global_session_type_id IS NULL
                          AND EXISTS (
                              SELECT 1
                              FROM public.teaching_names AS teaching_name
                              JOIN public.reporting_periods AS reporting_period
                                ON reporting_period.id
                                    = teaching_name.reporting_period_id
                              WHERE teaching_name.id
                                  = event_row.teaching_name_id
                                AND teaching_name.programme_code
                                    = external_posting.programme_code
                                AND event_row.event_date BETWEEN
                                    reporting_period.start_date
                                    AND reporting_period.end_date
                          )
                      )
                      OR (
                          event_row.teaching_name_id IS NULL
                          AND event_row.global_session_type_id IS NULL
                      )
                  )
            );
        END IF;

        RETURN false;
    END IF;

    IF mata_rls.is_master_admin() THEN
        RETURN true;
    END IF;

    IF subject_type = 'resident' THEN
        RETURN event_row.created_by_resident_id = subject_id
           AND event_row.created_by_external_resident_id IS NULL;
    END IF;

    IF subject_type = 'external_resident' THEN
        RETURN event_row.created_by_external_resident_id = subject_id
           AND event_row.created_by_resident_id IS NULL;
    END IF;

    IF subject_type = 'staff' AND app_role = 'admin' THEN
        RETURN (
            event_row.created_by_resident_id IS NOT NULL
            AND EXISTS (
                SELECT 1
                FROM public.residents AS resident
                WHERE resident.id = event_row.created_by_resident_id
                  AND resident.programme_code IS NOT NULL
                  AND mata_rls.has_programme_scope(resident.programme_code)
            )
        )
        OR (
            event_row.created_by_external_resident_id IS NOT NULL
            AND EXISTS (
                SELECT 1
                FROM public.external_resident_postings AS external_posting
                WHERE external_posting.external_resident_id
                    = event_row.created_by_external_resident_id
                  AND external_posting.posting_code = event_row.posting_code
                  AND external_posting.programme_code IS NOT NULL
                  AND external_posting.start_date <= event_row.event_date
                  AND COALESCE(
                          external_posting.end_date,
                          'infinity'::date
                      ) >= event_row.event_date
                  AND NOT EXISTS (
                      SELECT 1
                      FROM public.external_resident_postings AS competing_posting
                      WHERE competing_posting.external_resident_id
                          = event_row.created_by_external_resident_id
                        AND competing_posting.start_date <= event_row.event_date
                        AND COALESCE(
                                competing_posting.end_date,
                                'infinity'::date
                            ) >= event_row.event_date
                        AND competing_posting.id <> external_posting.id
                  )
                  AND mata_rls.has_programme_scope(
                      external_posting.programme_code
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
        "REVOKE ALL PRIVILEGES ON FUNCTION mata_rls.can_select_teaching_event(uuid) "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        "GRANT EXECUTE ON FUNCTION mata_rls.can_select_teaching_event(uuid) "
        f"TO {RUNTIME_ROLE}"
    )
    _revoke_optional_function_privileges("can_select_teaching_event(uuid)")


def _create_attendance_helpers() -> None:
    _execute(
        r"""
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
    SELECT
        mata_rls.is_native_resident(p_resident_id)
        AND EXISTS (
            SELECT 1
            FROM public.teaching_events AS event
            WHERE event.id = p_teaching_event_id
              AND NOT event.is_adhoc
        )
        AND mata_rls.can_select_teaching_event(p_teaching_event_id)
$function$
"""
    )
    _execute(
        r"""
CREATE OR REPLACE FUNCTION mata_rls.can_submit_external_attendance(
    p_external_resident_id uuid,
    p_teaching_event_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT
        mata_rls.is_external_resident(p_external_resident_id)
        AND EXISTS (
            SELECT 1
            FROM public.teaching_events AS event
            WHERE event.id = p_teaching_event_id
              AND NOT event.is_adhoc
        )
        AND mata_rls.can_select_teaching_event(p_teaching_event_id)
$function$
"""
    )
    for signature in (
        "can_submit_native_attendance(uuid,uuid)",
        "can_submit_external_attendance(uuid,uuid)",
        "can_access_external_attendance(uuid,uuid)",
    ):
        _execute(
            f"REVOKE ALL PRIVILEGES ON FUNCTION mata_rls.{signature} "
            f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
        )
        _execute(
            f"GRANT EXECUTE ON FUNCTION mata_rls.{signature} TO {RUNTIME_ROLE}"
        )
        _revoke_optional_function_privileges(signature)

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
    SELECT
        mata_rls.is_master_admin()
        OR mata_rls.is_external_resident(p_external_resident_id)
        OR (
            mata_rls.current_subject_type() = 'staff'
            AND mata_rls.current_app_role() = 'secretary'
            AND EXISTS (
                SELECT 1
                FROM public.teaching_events AS event
                JOIN public.external_resident_postings AS external_posting
                  ON external_posting.external_resident_id
                      = p_external_resident_id
                 AND external_posting.posting_code = event.posting_code
                 AND external_posting.start_date <= event.event_date
                 AND COALESCE(
                         external_posting.end_date,
                         'infinity'::date
                     ) >= event.event_date
                 AND NOT EXISTS (
                     SELECT 1
                     FROM public.external_resident_postings AS competing_posting
                     WHERE competing_posting.external_resident_id
                         = p_external_resident_id
                       AND competing_posting.start_date <= event.event_date
                       AND COALESCE(
                               competing_posting.end_date,
                               'infinity'::date
                           ) >= event.event_date
                       AND competing_posting.id <> external_posting.id
                 )
                WHERE event.id = p_teaching_event_id
                  AND mata_rls.can_select_teaching_event(event.id)
            )
        )
        OR (
            mata_rls.current_subject_type() = 'staff'
            AND mata_rls.current_app_role() = 'admin'
            AND EXISTS (
                SELECT 1
                FROM public.teaching_events AS event
                JOIN public.external_resident_postings AS external_posting
                  ON external_posting.external_resident_id
                      = p_external_resident_id
                 AND external_posting.posting_code = event.posting_code
                 AND external_posting.start_date <= event.event_date
                 AND COALESCE(
                         external_posting.end_date,
                         'infinity'::date
                     ) >= event.event_date
                 AND NOT EXISTS (
                     SELECT 1
                     FROM public.external_resident_postings AS competing_posting
                     WHERE competing_posting.external_resident_id
                         = p_external_resident_id
                       AND competing_posting.start_date <= event.event_date
                       AND COALESCE(
                               competing_posting.end_date,
                               'infinity'::date
                           ) >= event.event_date
                       AND competing_posting.id <> external_posting.id
                 )
                WHERE event.id = p_teaching_event_id
                  AND external_posting.programme_code IS NOT NULL
                  AND mata_rls.has_programme_scope(
                      external_posting.programme_code
                  )
                  AND (
                      event.created_for_programme_code IS NULL
                      OR event.created_for_programme_code
                          = external_posting.programme_code
                  )
                  AND mata_rls.can_select_teaching_event(event.id)
            )
        )
$function$
"""
    )


def _create_scheduled_event_source_scope_helper() -> None:
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
    SELECT
        teaching_name.reporting_period_id,
        teaching_name.programme_code
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
    _execute(
        "REVOKE ALL PRIVILEGES ON FUNCTION "
        f"mata_rls.{SOURCE_SCOPE_SIGNATURE} "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        f"GRANT EXECUTE ON FUNCTION mata_rls.{SOURCE_SCOPE_SIGNATURE} "
        f"TO {RUNTIME_ROLE}"
    )
    _revoke_optional_function_privileges(SOURCE_SCOPE_SIGNATURE)


def _replace_atomic_adhoc_helper() -> None:
    _replace_atomic_helper(
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
    lock_scope text;
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
       OR p_end_time <= p_start_time
       OR p_end_time <> (p_start_time + INTERVAL '1 hour')::time
    THEN
        RAISE EXCEPTION 'Invalid ad-hoc teaching event'
            USING ERRCODE = '22023';
    END IF;

    SELECT
        COUNT(*),
        pg_catalog.min(period.id::text)::uuid
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
        RAISE EXCEPTION
            'Exactly one effective reporting period is required'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.public_holidays AS holiday
        WHERE holiday.holiday_date = p_event_date
    ) THEN
        RAISE EXCEPTION
            'Ad-hoc teaching is unavailable on a public holiday'
            USING ERRCODE = '22023';
    END IF;

    lock_scope := CASE subject_type
        WHEN 'resident' THEN 'native-attendance:'
        ELSE 'external-attendance:'
    END || subject_id::text || ':' || p_event_date::text;
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(lock_scope, 0)
    );

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
        RAISE EXCEPTION
            'Ad-hoc teaching event is outside the resident scope'
            USING ERRCODE = '22023';
    END IF;

    IF (
        subject_type = 'resident'
        AND EXISTS (
            SELECT 1
            FROM public.attendance_records AS attendance
            JOIN public.teaching_events AS existing
              ON existing.id = attendance.teaching_event_id
            WHERE attendance.resident_id = subject_id
              AND attendance.status = 'submitted'
              AND existing.event_date = p_event_date
              AND (
                  existing.start_time = p_start_time
                  OR (
                      p_start_time
                          < COALESCE(existing.end_time, existing.start_time)
                      AND existing.start_time < p_end_time
                  )
              )
        )
    )
    OR (
        subject_type = 'external_resident'
        AND EXISTS (
            SELECT 1
            FROM public.external_attendance_records AS attendance
            JOIN public.teaching_events AS existing
              ON existing.id = attendance.teaching_event_id
            WHERE attendance.external_resident_id = subject_id
              AND attendance.status = 'submitted'
              AND existing.event_date = p_event_date
              AND (
                  existing.start_time = p_start_time
                  OR (
                      p_start_time
                          < COALESCE(existing.end_time, existing.start_time)
                      AND existing.start_time < p_end_time
                  )
              )
        )
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
    )
    VALUES (
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
        CASE
            WHEN subject_type = 'external_resident'
            THEN subject_id
        END
    )
    RETURNING id INTO new_event_id;

    IF subject_type = 'resident' THEN
        INSERT INTO public.attendance_records (
            resident_id,
            teaching_event_id,
            status,
            posting_code
        )
        VALUES (
            subject_id,
            new_event_id,
            'submitted',
            p_posting_code
        )
        RETURNING id INTO new_attendance_id;
    ELSE
        INSERT INTO public.external_attendance_records (
            external_resident_id,
            teaching_event_id,
            status,
            posting_code
        )
        VALUES (
            subject_id,
            new_event_id,
            'submitted',
            p_posting_code
        )
        RETURNING id INTO new_attendance_id;
    END IF;

    RETURN QUERY SELECT new_event_id, new_attendance_id;
END
$function$
"""
    )
    _execute(
        "REVOKE SELECT ON TABLE public.global_session_types, "
        "public.session_types, public.teaching_name_catalogue, "
        f"public.teaching_targets FROM {DEFINER_ROLE}"
    )


def _assert_phase_g_security() -> None:
    _execute(
        rf"""
DO $migration$
DECLARE
    source_scope_oid regprocedure := pg_catalog.to_regprocedure(
        'mata_rls.{SOURCE_SCOPE_SIGNATURE}'
    );
    atomic_oid regprocedure := pg_catalog.to_regprocedure(
        'mata_rls.{ATOMIC_HELPER_SIGNATURE}'
    );
BEGIN
    IF source_scope_oid IS NULL
       OR atomic_oid IS NULL
       OR NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = procedure.pronamespace
           WHERE procedure.oid = source_scope_oid
             AND namespace.nspname = 'mata_rls'
             AND procedure.prosecdef
             AND procedure.proconfig = ARRAY[
                 'search_path=pg_catalog, pg_temp'
             ]::text[]
       )
       OR NOT pg_catalog.has_function_privilege(
           '{RUNTIME_ROLE}', source_scope_oid, 'EXECUTE'
       )
       OR pg_catalog.has_function_privilege(
           '{AUTH_ROLE}', source_scope_oid, 'EXECUTE'
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
           WHERE procedure.oid = source_scope_oid
             AND privilege.grantee = 0
             AND privilege.privilege_type = 'EXECUTE'
       )
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           WHERE namespace.nspname = 'public'
              AND relation.relname IN (
                  'global_session_types',
                  'session_types',
                  'teaching_name_catalogue',
                  'teaching_targets'
             )
             AND pg_catalog.has_table_privilege(
                 '{DEFINER_ROLE}', relation.oid, 'SELECT'
             )
       )
       OR NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           WHERE procedure.oid = atomic_oid
             AND pg_catalog.pg_get_functiondef(procedure.oid)
                 LIKE '%Department/Programme Teaching [1h]%'
             AND pg_catalog.pg_get_functiondef(procedure.oid)
                 NOT LIKE '%teaching_name_catalogue%'
             AND pg_catalog.pg_get_functiondef(procedure.oid)
                 NOT LIKE '%teaching_targets%'
       )
    THEN
        RAISE EXCEPTION 'Phase G resident runtime security assertion failed'
            USING ERRCODE = '42501';
    END IF;
END
$migration$
"""
    )


def _restore_pre_phase_g_selection_helpers() -> None:
    _execute(
        r"""
CREATE OR REPLACE FUNCTION mata_rls.can_select_teaching_event(p_event_id uuid)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    event_row record;
    subject_type text := mata_rls.current_subject_type();
    subject_id uuid := mata_rls.current_subject_id();
    app_role text := mata_rls.current_app_role();
BEGIN
    SELECT
        event.id,
        event.is_adhoc,
        event.posting_code,
        event.event_date,
        event.created_by_resident_id,
        event.created_by_external_resident_id
    INTO event_row
    FROM public.teaching_events AS event
    WHERE event.id = p_event_id;

    IF NOT FOUND THEN
        RETURN false;
    END IF;

    IF NOT event_row.is_adhoc THEN
        RETURN mata_private.can_select_teaching_event_000027(p_event_id);
    END IF;

    IF mata_rls.is_master_admin() THEN
        RETURN true;
    END IF;

    IF subject_type = 'resident' THEN
        RETURN event_row.created_by_resident_id = subject_id
           AND event_row.created_by_external_resident_id IS NULL;
    END IF;

    IF subject_type = 'external_resident' THEN
        RETURN event_row.created_by_external_resident_id = subject_id
           AND event_row.created_by_resident_id IS NULL;
    END IF;

    IF subject_type = 'staff' AND app_role = 'admin' THEN
        RETURN (
            event_row.created_by_resident_id IS NOT NULL
            AND EXISTS (
                SELECT 1
                FROM public.residents AS resident
                WHERE resident.id = event_row.created_by_resident_id
                  AND resident.programme_code IS NOT NULL
                  AND mata_rls.has_programme_scope(resident.programme_code)
            )
        )
        OR (
            event_row.created_by_external_resident_id IS NOT NULL
            AND EXISTS (
                SELECT 1
                FROM public.external_resident_postings AS external_posting
                WHERE external_posting.external_resident_id
                    = event_row.created_by_external_resident_id
                  AND external_posting.posting_code = event_row.posting_code
                  AND external_posting.programme_code IS NOT NULL
                  AND external_posting.start_date <= event_row.event_date
                  AND COALESCE(
                          external_posting.end_date,
                          'infinity'::date
                      ) >= event_row.event_date
                  AND mata_rls.has_programme_scope(
                      external_posting.programme_code
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
    SELECT
        EXISTS (
            SELECT 1
            FROM public.teaching_events AS event
            WHERE event.id = p_teaching_event_id
              AND NOT event.is_adhoc
        )
        AND mata_private.can_submit_native_attendance_000027(
            p_resident_id,
            p_teaching_event_id
        )
$function$
"""
    )
    _execute(
        r"""
CREATE OR REPLACE FUNCTION mata_rls.can_submit_external_attendance(
    p_external_resident_id uuid,
    p_teaching_event_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT
        EXISTS (
            SELECT 1
            FROM public.teaching_events AS event
            WHERE event.id = p_teaching_event_id
              AND NOT event.is_adhoc
        )
        AND mata_private.can_submit_external_attendance_000027(
            p_external_resident_id,
            p_teaching_event_id
        )
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
    SELECT
        mata_rls.is_master_admin()
        OR mata_rls.is_external_resident(p_external_resident_id)
        OR (
            mata_rls.current_subject_type() = 'staff'
            AND mata_rls.current_app_role() = 'secretary'
            AND mata_rls.can_select_teaching_event(p_teaching_event_id)
        )
        OR EXISTS (
            SELECT 1
            FROM public.teaching_events AS event
            JOIN public.external_resident_postings AS external_posting
              ON external_posting.external_resident_id
                  = p_external_resident_id
             AND external_posting.posting_code = event.posting_code
             AND external_posting.start_date <= event.event_date
             AND COALESCE(
                     external_posting.end_date,
                     'infinity'::date
                 ) >= event.event_date
            WHERE event.id = p_teaching_event_id
              AND external_posting.programme_code IS NOT NULL
              AND mata_rls.has_programme_scope(
                  external_posting.programme_code
              )
              AND (
                  event.created_for_programme_code IS NULL
                  OR event.created_for_programme_code
                      = external_posting.programme_code
              )
        )
$function$
"""
    )


def _restore_pre_phase_g_atomic_helper() -> None:
    _replace_atomic_helper(
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
    eligible boolean := false;
    resolved_period_id uuid;
    matching_count integer;
    scope_programme_code text;
    scope_r_year text;
    lock_scope text;
BEGIN
    IF subject_type NOT IN ('resident', 'external_resident')
       OR subject_id IS NULL
    THEN
        RAISE EXCEPTION 'Verified resident context required'
            USING ERRCODE = '28000';
    END IF;

    IF pg_catalog.btrim(COALESCE(p_posting_code, '')) = ''
       OR pg_catalog.btrim(COALESCE(p_attended_posting_code, '')) = ''
       OR pg_catalog.btrim(COALESCE(p_attended_teaching_name, '')) = ''
       OR pg_catalog.btrim(COALESCE(p_teaching_name, '')) = ''
       OR p_event_date IS NULL
       OR p_start_time IS NULL
       OR p_end_time IS NULL
       OR p_duration_hours IS NULL
       OR p_duration_hours <= 0
       OR p_end_time <= p_start_time
       OR p_end_time <> (
           p_start_time
           + (
               INTERVAL '1 minute'
               * pg_catalog.trunc(p_duration_hours * 60)::double precision
           )
       )::time
    THEN
        RAISE EXCEPTION 'Invalid ad-hoc teaching event'
            USING ERRCODE = '22023';
    END IF;

    SELECT
        COUNT(*),
        pg_catalog.min(period.id::text)::uuid
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
        RAISE EXCEPTION
            'Exactly one effective reporting period is required'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.public_holidays AS holiday
        WHERE holiday.holiday_date = p_event_date
    ) THEN
        RAISE EXCEPTION
            'Ad-hoc teaching is unavailable on a public holiday'
            USING ERRCODE = '22023';
    END IF;

    lock_scope := CASE subject_type
        WHEN 'resident' THEN 'native-attendance:'
        ELSE 'external-attendance:'
    END || subject_id::text || ':' || p_event_date::text;
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(lock_scope, 0)
    );

    IF subject_type = 'resident' THEN
        SELECT
            COUNT(*),
            pg_catalog.min(resident.programme_code),
            pg_catalog.min(resident_posting.r_year)
        INTO matching_count, scope_programme_code, scope_r_year
        FROM public.residents AS resident
        JOIN public.resident_postings AS resident_posting
          ON resident_posting.resident_id = resident.id
        WHERE resident.id = subject_id
          AND resident.status = 'active'
          AND resident.programme_code IS NOT NULL
          AND resident_posting.reporting_period_id = resolved_period_id
          AND resident_posting.posting_code = p_posting_code
          AND resident_posting.status IN ('active', 'loa_working')
          AND p_event_date BETWEEN
              resident_posting.start_date AND resident_posting.end_date;

        SELECT matching_count = 1
        AND EXISTS (
            SELECT 1
            FROM public.teaching_targets AS target
            JOIN public.session_types AS session_type
              ON session_type.id = target.session_type_id
            WHERE target.reporting_period_id = resolved_period_id
              AND target.programme_code = scope_programme_code
              AND target.posting_code = p_posting_code
              AND target.r_year IN (scope_r_year, 'ALL')
              AND target.session_type_id = p_session_type_id
              AND session_type.name = p_teaching_name
              AND session_type.duration_hours = p_duration_hours
              AND target.is_tracked
        )
        AND EXISTS (
            SELECT 1
            FROM public.teaching_name_catalogue AS attended
            WHERE attended.reporting_period_id = resolved_period_id
              AND attended.posting_code = p_attended_posting_code
              AND attended.programme_code = scope_programme_code
              AND attended.r_year IN (scope_r_year, 'ALL')
              AND attended.keyword = p_attended_teaching_name
              AND attended.is_tracked
        )
        INTO eligible;
    ELSE
        SELECT
            COUNT(*),
            pg_catalog.min(external_posting.programme_code)
        INTO matching_count, scope_programme_code
        FROM public.external_residents AS external_resident
        JOIN public.external_resident_postings AS external_posting
          ON external_posting.external_resident_id = external_resident.id
        WHERE external_resident.id = subject_id
          AND external_resident.status = 'active'
          AND external_posting.posting_code = p_posting_code
          AND external_posting.start_date <= p_event_date
          AND COALESCE(
                  external_posting.end_date,
                  'infinity'::date
              ) >= p_event_date;

        SELECT matching_count = 1
        AND EXISTS (
            SELECT 1
            FROM public.teaching_name_catalogue AS configured_posting
            WHERE configured_posting.reporting_period_id
                = resolved_period_id
              AND configured_posting.posting_code
                = p_attended_posting_code
        )
        AND (
            EXISTS (
                SELECT 1
                FROM public.global_session_types AS global_type
                WHERE global_type.name = p_attended_teaching_name
                  AND p_teaching_name = p_attended_teaching_name
                  AND global_type.duration_hours = p_duration_hours
                  AND global_type.is_active
                  AND p_session_type_id IS NULL
            )
            OR EXISTS (
                SELECT 1
                FROM public.teaching_name_catalogue AS catalogue
                WHERE catalogue.reporting_period_id = resolved_period_id
                  AND catalogue.posting_code = p_attended_posting_code
                  AND catalogue.keyword = p_attended_teaching_name
                  AND p_teaching_name = p_attended_teaching_name
                  AND catalogue.session_type_id = p_session_type_id
                  AND catalogue.duration_hours = p_duration_hours
            )
        )
        INTO eligible;
    END IF;

    IF NOT eligible THEN
        RAISE EXCEPTION
            'Ad-hoc teaching event is outside the resident scope'
            USING ERRCODE = '22023';
    END IF;

    IF (
        subject_type = 'resident'
        AND EXISTS (
            SELECT 1
            FROM public.attendance_records AS attendance
            JOIN public.teaching_events AS existing
              ON existing.id = attendance.teaching_event_id
            WHERE attendance.resident_id = subject_id
              AND attendance.status = 'submitted'
              AND existing.event_date = p_event_date
              AND (
                  existing.start_time = p_start_time
                  OR (
                      p_start_time
                          < COALESCE(existing.end_time, existing.start_time)
                      AND existing.start_time < p_end_time
                  )
              )
        )
    )
    OR (
        subject_type = 'external_resident'
        AND EXISTS (
            SELECT 1
            FROM public.external_attendance_records AS attendance
            JOIN public.teaching_events AS existing
              ON existing.id = attendance.teaching_event_id
            WHERE attendance.external_resident_id = subject_id
              AND attendance.status = 'submitted'
              AND existing.event_date = p_event_date
              AND (
                  existing.start_time = p_start_time
                  OR (
                      p_start_time
                          < COALESCE(existing.end_time, existing.start_time)
                      AND existing.start_time < p_end_time
                  )
              )
        )
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
    )
    VALUES (
        p_posting_code,
        p_teaching_name,
        p_details_of_session,
        p_event_date,
        p_start_time,
        p_end_time,
        p_duration_hours,
        p_session_type_id,
        true,
        subject_type,
        CASE WHEN subject_type = 'resident' THEN subject_id END,
        CASE
            WHEN subject_type = 'external_resident'
            THEN subject_id
        END
    )
    RETURNING id INTO new_event_id;

    IF subject_type = 'resident' THEN
        INSERT INTO public.attendance_records (
            resident_id,
            teaching_event_id,
            status,
            posting_code
        )
        VALUES (
            subject_id,
            new_event_id,
            'submitted',
            p_posting_code
        )
        RETURNING id INTO new_attendance_id;
    ELSE
        INSERT INTO public.external_attendance_records (
            external_resident_id,
            teaching_event_id,
            status,
            posting_code
        )
        VALUES (
            subject_id,
            new_event_id,
            'submitted',
            p_posting_code
        )
        RETURNING id INTO new_attendance_id;
    END IF;

    RETURN QUERY SELECT new_event_id, new_attendance_id;
END
$function$
"""
    )
    _execute(
        "GRANT SELECT ON TABLE public.global_session_types, "
        "public.session_types, public.teaching_name_catalogue, "
        f"public.teaching_targets TO {DEFINER_ROLE}"
    )


def upgrade() -> None:
    _create_scheduled_event_selection_helper()
    _create_attendance_helpers()
    _create_scheduled_event_source_scope_helper()
    _replace_atomic_adhoc_helper()
    _assert_phase_g_security()


def downgrade() -> None:
    _execute(f"DROP FUNCTION mata_rls.{SOURCE_SCOPE_SIGNATURE}")
    _restore_pre_phase_g_selection_helpers()
    _restore_pre_phase_g_atomic_helper()
