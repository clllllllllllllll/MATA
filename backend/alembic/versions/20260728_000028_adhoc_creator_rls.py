"""bind ad-hoc teaching events to an immutable creator and storage family

Revision ID: 20260728_000028
Revises: 20260727_000027
Create Date: 2026-07-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260728_000028"
down_revision = "20260727_000027"
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

_MOVED_POLICY_HELPERS = (
    (
        "can_select_teaching_event(uuid)",
        "can_select_teaching_event_000027(uuid)",
    ),
    (
        "can_insert_teaching_event(text,text,text,date,boolean,text)",
        "can_insert_teaching_event_000027(text,text,text,date,boolean,text)",
    ),
    (
        "can_submit_native_attendance(uuid,uuid)",
        "can_submit_native_attendance_000027(uuid,uuid)",
    ),
    (
        "can_submit_external_attendance(uuid,uuid)",
        "can_submit_external_attendance_000027(uuid,uuid)",
    ),
)

_DEFINER_SELECT_TABLES = (
    "attendance_records",
    "external_attendance_records",
    "external_resident_postings",
    "external_residents",
    "global_session_types",
    "public_holidays",
    "reporting_periods",
    "resident_postings",
    "residents",
    "session_types",
    "teaching_events",
    "teaching_name_catalogue",
    "teaching_targets",
)


def _execute(statement: str) -> None:
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(statement)


def _assert_atomic_helper_definer_is_hardened() -> None:
    _execute(
        rf"""
DO $migration$
DECLARE
    role_row record;
    helper_schema_owner oid;
BEGIN
    SELECT
        oid,
        rolcanlogin,
        rolinherit,
        rolsuper,
        rolbypassrls,
        rolcreatedb,
        rolcreaterole,
        rolreplication
    INTO STRICT role_row
    FROM pg_catalog.pg_roles
    WHERE rolname = '{DEFINER_ROLE}';

    SELECT nspowner
    INTO STRICT helper_schema_owner
    FROM pg_catalog.pg_namespace
    WHERE nspname = 'mata_rls';

    IF role_row.rolcanlogin
       OR role_row.rolinherit
       OR role_row.rolsuper
       OR NOT role_row.rolbypassrls
       OR role_row.rolcreatedb
       OR role_row.rolcreaterole
       OR role_row.rolreplication
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.pg_auth_members AS membership
           WHERE membership.member = role_row.oid
       )
       OR NOT (
           SELECT
               count(*) = 0
               OR (
                   count(*) = 1
                   AND count(*) FILTER (
                       WHERE member_role.oid = helper_schema_owner
                         AND member_role.rolcreaterole
                         AND member_role.rolbypassrls
                         AND grantor_role.rolsuper
                         AND membership.admin_option
                         AND NOT membership.inherit_option
                         AND NOT membership.set_option
                   ) = 1
               )
           FROM pg_catalog.pg_auth_members AS membership
           LEFT JOIN pg_catalog.pg_roles AS member_role
             ON member_role.oid = membership.member
           LEFT JOIN pg_catalog.pg_roles AS grantor_role
             ON grantor_role.oid = membership.grantor
           WHERE membership.roleid = role_row.oid
       )
    THEN
        RAISE EXCEPTION
            'Unsafe ad-hoc attendance definer role'
            USING ERRCODE = '42501';
    END IF;
END
$migration$
"""
    )


def _prepare_atomic_helper_definer() -> None:
    _execute(
        rf"""
DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles
        WHERE rolname = '{DEFINER_ROLE}'
    ) THEN
        CREATE ROLE {DEFINER_ROLE}
            NOLOGIN NOINHERIT NOSUPERUSER BYPASSRLS
            NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
END
$migration$
"""
    )
    _assert_atomic_helper_definer_is_hardened()
    _execute(
        f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public "
        f"FROM {DEFINER_ROLE}"
    )
    _execute(
        f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public "
        f"FROM {DEFINER_ROLE}"
    )
    _execute(
        f"REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA mata_rls "
        f"FROM {DEFINER_ROLE}"
    )
    _execute(
        "REVOKE EXECUTE ON FUNCTION "
        "mata_rls.current_subject_type(), "
        "mata_rls.current_subject_id() "
        "FROM PUBLIC"
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON FUNCTION public.gen_random_uuid() "
        f"FROM PUBLIC, {DEFINER_ROLE}"
    )
    _execute(
        f"REVOKE ALL PRIVILEGES ON SCHEMA public, mata_rls, mata_private "
        f"FROM {DEFINER_ROLE}"
    )
    _execute(
        f"GRANT USAGE ON SCHEMA public, mata_rls TO {DEFINER_ROLE}"
    )
    _execute(
        "GRANT SELECT ON TABLE "
        + ", ".join(
            f"public.{table_name}" for table_name in _DEFINER_SELECT_TABLES
        )
        + f" TO {DEFINER_ROLE}"
    )
    _execute(
        "GRANT INSERT ON TABLE "
        "public.teaching_events, "
        "public.attendance_records, "
        "public.external_attendance_records "
        f"TO {DEFINER_ROLE}"
    )
    _execute(
        "GRANT EXECUTE ON FUNCTION "
        "mata_rls.current_subject_type(), "
        "mata_rls.current_subject_id() "
        f"TO {DEFINER_ROLE}"
    )
    _execute(
        "GRANT EXECUTE ON FUNCTION public.gen_random_uuid() "
        f"TO {DEFINER_ROLE}"
    )


def _grant_atomic_helper_definer_for_ownership() -> None:
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


def _drop_atomic_helper_as_definer() -> None:
    _execute(f"SET LOCAL ROLE {DEFINER_ROLE}")
    _execute(
        f"DROP FUNCTION mata_rls.{ATOMIC_HELPER_SIGNATURE} RESTRICT"
    )
    _execute("SET LOCAL ROLE NONE")


def _revoke_atomic_helper_definer_ownership() -> None:
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
    _assert_atomic_helper_definer_is_hardened()


def _add_creator_schema_and_backfill() -> None:
    op.add_column(
        "teaching_events",
        sa.Column(
            "created_by_resident_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "teaching_events",
        sa.Column(
            "created_by_external_resident_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    _execute(
        r"""
DO $migration$
DECLARE
    invalid_ids text;
BEGIN
    WITH native_owner AS (
        SELECT
            attendance.teaching_event_id,
            COUNT(DISTINCT attendance.resident_id) AS owner_count
        FROM public.attendance_records AS attendance
        GROUP BY attendance.teaching_event_id
    ),
    external_owner AS (
        SELECT
            attendance.teaching_event_id,
            COUNT(DISTINCT attendance.external_resident_id) AS owner_count
        FROM public.external_attendance_records AS attendance
        GROUP BY attendance.teaching_event_id
    ),
    invalid AS (
        SELECT event.id
        FROM public.teaching_events AS event
        LEFT JOIN native_owner
          ON native_owner.teaching_event_id = event.id
        LEFT JOIN external_owner
          ON external_owner.teaching_event_id = event.id
        WHERE event.is_adhoc
          AND (
              event.created_for_programme_code IS NOT NULL
              OR event.series_id IS NOT NULL
              OR (
                  event.created_by_role = 'resident'
                  AND (
                      COALESCE(native_owner.owner_count, 0) <> 1
                      OR COALESCE(external_owner.owner_count, 0) <> 0
                  )
              )
              OR (
                  event.created_by_role = 'external_resident'
                  AND (
                      COALESCE(native_owner.owner_count, 0) <> 0
                      OR COALESCE(external_owner.owner_count, 0) <> 1
                  )
              )
              OR event.created_by_role IS NULL
              OR event.created_by_role NOT IN (
                  'resident',
                  'external_resident'
              )
          )
        ORDER BY event.id
        LIMIT 20
    )
    SELECT pg_catalog.string_agg(invalid.id::text, ', ')
    INTO invalid_ids
    FROM invalid;

    IF invalid_ids IS NOT NULL THEN
        RAISE EXCEPTION
            'Cannot infer immutable ad-hoc creator for teaching event(s): %',
            invalid_ids
            USING ERRCODE = '23514';
    END IF;

    SELECT pg_catalog.string_agg(invalid.id::text, ', ')
    INTO invalid_ids
    FROM (
        SELECT event.id
        FROM public.teaching_events AS event
        WHERE NOT event.is_adhoc
          AND event.created_by_role IS NOT NULL
          AND event.created_by_role NOT IN ('secretary', 'programme_pc')
        ORDER BY event.id
        LIMIT 20
    ) AS invalid;

    IF invalid_ids IS NOT NULL THEN
        RAISE EXCEPTION
            'Scheduled teaching event has ad-hoc creator role: %',
            invalid_ids
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.attendance_records AS attendance
        WHERE attendance.status NOT IN ('submitted', 'flagged', 'removed')
    ) THEN
        RAISE EXCEPTION
            'attendance_records contains an unsupported status'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.external_attendance_records AS attendance
        WHERE attendance.status NOT IN ('submitted', 'flagged', 'removed')
    ) THEN
        RAISE EXCEPTION
            'external_attendance_records contains an unsupported status'
            USING ERRCODE = '23514';
    END IF;
END
$migration$
"""
    )
    _execute(
        r"""
WITH native_owner AS (
    SELECT
        attendance.teaching_event_id,
        pg_catalog.min(attendance.resident_id::text)::uuid AS resident_id
    FROM public.attendance_records AS attendance
    GROUP BY attendance.teaching_event_id
    HAVING COUNT(DISTINCT attendance.resident_id) = 1
)
UPDATE public.teaching_events AS event
SET created_by_resident_id = native_owner.resident_id
FROM native_owner
WHERE event.id = native_owner.teaching_event_id
  AND event.is_adhoc
  AND event.created_by_role = 'resident'
"""
    )
    _execute(
        r"""
WITH external_owner AS (
    SELECT
        attendance.teaching_event_id,
        pg_catalog.min(attendance.external_resident_id::text)::uuid
            AS external_resident_id
    FROM public.external_attendance_records AS attendance
    GROUP BY attendance.teaching_event_id
    HAVING COUNT(DISTINCT attendance.external_resident_id) = 1
)
UPDATE public.teaching_events AS event
SET created_by_external_resident_id = external_owner.external_resident_id
FROM external_owner
WHERE event.id = external_owner.teaching_event_id
  AND event.is_adhoc
  AND event.created_by_role = 'external_resident'
"""
    )

    op.create_foreign_key(
        "fk_teaching_events_resident_creator",
        "teaching_events",
        "residents",
        ["created_by_resident_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_teaching_events_external_resident_creator",
        "teaching_events",
        "external_residents",
        ["created_by_external_resident_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_teaching_events_adhoc_creator_family",
        "teaching_events",
        """
        (
            NOT is_adhoc
            AND (
                created_by_role IS NULL
                OR created_by_role IN ('secretary', 'programme_pc')
            )
            AND created_by_resident_id IS NULL
            AND created_by_external_resident_id IS NULL
        )
        OR (
            is_adhoc
            AND created_by_role = 'resident'
            AND created_for_programme_code IS NULL
            AND series_id IS NULL
            AND created_by_resident_id IS NOT NULL
            AND created_by_external_resident_id IS NULL
        )
        OR (
            is_adhoc
            AND created_by_role = 'external_resident'
            AND created_for_programme_code IS NULL
            AND series_id IS NULL
            AND created_by_resident_id IS NULL
            AND created_by_external_resident_id IS NOT NULL
        )
        """,
    )
    op.create_index(
        "idx_teaching_events_created_by_resident",
        "teaching_events",
        ["created_by_resident_id"],
        postgresql_where=sa.text("created_by_resident_id IS NOT NULL"),
    )
    op.create_index(
        "idx_teaching_events_created_by_external_resident",
        "teaching_events",
        ["created_by_external_resident_id"],
        postgresql_where=sa.text(
            "created_by_external_resident_id IS NOT NULL"
        ),
    )

    op.drop_constraint(
        "uq_attendance_records_resident_event",
        "attendance_records",
        type_="unique",
    )
    op.drop_index(
        "idx_attendance_records_submitted_resident_event",
        table_name="attendance_records",
    )
    op.create_index(
        "idx_attendance_records_submitted_resident_event",
        "attendance_records",
        ["resident_id", "teaching_event_id"],
        unique=True,
        postgresql_where=sa.text("status = 'submitted'"),
    )
    op.create_check_constraint(
        "ck_attendance_records_status",
        "attendance_records",
        "status IN ('submitted', 'flagged', 'removed')",
    )
    op.create_check_constraint(
        "ck_external_attendance_records_status",
        "external_attendance_records",
        "status IN ('submitted', 'flagged', 'removed')",
    )


def _create_integrity_triggers() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_private.enforce_teaching_event_creator_immutability()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF OLD.is_adhoc IS DISTINCT FROM NEW.is_adhoc
       OR OLD.created_by_role IS DISTINCT FROM NEW.created_by_role
       OR OLD.created_by_resident_id
          IS DISTINCT FROM NEW.created_by_resident_id
       OR OLD.created_by_external_resident_id
          IS DISTINCT FROM NEW.created_by_external_resident_id
    THEN
        RAISE EXCEPTION 'Teaching-event creator ownership is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$
"""
    )
    _execute(
        r"""
CREATE TRIGGER mata_enforce_teaching_event_creator_immutability
BEFORE UPDATE OF
    is_adhoc,
    created_by_role,
    created_by_resident_id,
    created_by_external_resident_id
ON public.teaching_events
FOR EACH ROW
EXECUTE FUNCTION mata_private.enforce_teaching_event_creator_immutability()
"""
    )
    _execute(
        r"""
CREATE FUNCTION mata_private.enforce_attendance_integrity()
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
    runtime_origin boolean := pg_catalog.pg_has_role(
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

    SELECT
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
$function$
"""
    )
    _execute(
        r"""
CREATE TRIGGER mata_enforce_attendance_integrity
BEFORE INSERT OR UPDATE
ON public.attendance_records
FOR EACH ROW
EXECUTE FUNCTION mata_private.enforce_attendance_integrity()
"""
    )
    _execute(
        r"""
CREATE TRIGGER mata_enforce_external_attendance_integrity
BEFORE INSERT OR UPDATE
ON public.external_attendance_records
FOR EACH ROW
EXECUTE FUNCTION mata_private.enforce_attendance_integrity()
"""
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON FUNCTION "
        "mata_private.enforce_teaching_event_creator_immutability() "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON FUNCTION "
        "mata_private.enforce_attendance_integrity() "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )


def _move_old_policy_helpers_to_private() -> None:
    for public_signature, private_signature in _MOVED_POLICY_HELPERS:
        public_name = public_signature.split("(", 1)[0]
        private_name = private_signature.split("(", 1)[0]
        arguments = public_signature.split("(", 1)[1]
        _execute(
            f"ALTER FUNCTION mata_rls.{public_signature} "
            "SET SCHEMA mata_private"
        )
        _execute(
            f"ALTER FUNCTION mata_private.{public_name}({arguments} "
            f"RENAME TO {private_name}"
        )
        _execute(
            f"REVOKE ALL PRIVILEGES ON FUNCTION "
            f"mata_private.{private_signature} "
            f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
        )


def _create_policy_wrappers() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.can_select_teaching_event(p_event_id uuid)
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
                  AND mata_rls.has_programme_scope(
                      resident.programme_code
                  )
            )
        )
        OR (
            event_row.created_by_external_resident_id IS NOT NULL
            AND EXISTS (
                SELECT 1
                FROM public.external_resident_postings AS external_posting
                WHERE external_posting.external_resident_id
                    = event_row.created_by_external_resident_id
                  AND external_posting.posting_code
                    = event_row.posting_code
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
CREATE FUNCTION mata_rls.can_insert_teaching_event(
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
    SELECT
        NOT COALESCE(p_is_adhoc, false)
        AND mata_private.can_insert_teaching_event_000027(
            p_posting_code,
            p_created_for_programme_code,
            p_teaching_name,
            p_event_date,
            p_is_adhoc,
            p_created_by_role
        )
$function$
"""
    )
    _execute(
        r"""
CREATE FUNCTION mata_rls.can_submit_native_attendance(
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
CREATE FUNCTION mata_rls.can_submit_external_attendance(
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

    for signature in (
        "can_select_teaching_event(uuid)",
        "can_insert_teaching_event(text,text,text,date,boolean,text)",
        "can_submit_native_attendance(uuid,uuid)",
        "can_submit_external_attendance(uuid,uuid)",
    ):
        _execute(
            f"REVOKE ALL PRIVILEGES ON FUNCTION mata_rls.{signature} "
            f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
        )
        _execute(
            f"GRANT EXECUTE ON FUNCTION mata_rls.{signature} "
            f"TO {RUNTIME_ROLE}"
        )


def _replace_affected_policies(
    *,
    upgrade: bool,
    drop_existing: bool = True,
) -> None:
    policy_specs = (
        ("teaching_events", "select"),
        ("teaching_events", "insert"),
        ("attendance_records", "select"),
        ("attendance_records", "insert"),
        ("attendance_records", "update"),
        ("external_attendance_records", "insert"),
        ("external_attendance_records", "update"),
    )
    if drop_existing:
        for table_name, action in policy_specs:
            _execute(
                f'DROP POLICY "mata_rls_{table_name}_{action}" '
                f'ON public."{table_name}"'
            )

    _execute(
        r"""
CREATE POLICY "mata_rls_teaching_events_select"
ON public.teaching_events
AS PERMISSIVE
FOR SELECT
TO mata_app_runtime
USING (mata_rls.can_select_teaching_event(id))
"""
    )
    _execute(
        r"""
CREATE POLICY "mata_rls_teaching_events_insert"
ON public.teaching_events
AS PERMISSIVE
FOR INSERT
TO mata_app_runtime
WITH CHECK (
    mata_rls.can_insert_teaching_event(
        posting_code,
        created_for_programme_code,
        teaching_name,
        event_date,
        is_adhoc,
        created_by_role
    )
)
"""
    )
    _execute(
        r"""
CREATE POLICY "mata_rls_attendance_records_select"
ON public.attendance_records
AS PERMISSIVE
FOR SELECT
TO mata_app_runtime
USING (
    CASE
        WHEN mata_rls.current_subject_type() = 'staff'
         AND mata_rls.current_app_role() = 'secretary'
        THEN mata_rls.can_select_teaching_event(teaching_event_id)
        ELSE mata_rls.can_access_resident(resident_id)
    END
)
"""
    )
    _execute(
        r"""
CREATE POLICY "mata_rls_attendance_records_insert"
ON public.attendance_records
AS PERMISSIVE
FOR INSERT
TO mata_app_runtime
WITH CHECK (
    mata_rls.can_submit_native_attendance(
        resident_id,
        teaching_event_id
    )
)
"""
    )
    _execute(
        r"""
CREATE POLICY "mata_rls_external_attendance_records_insert"
ON public.external_attendance_records
AS PERMISSIVE
FOR INSERT
TO mata_app_runtime
WITH CHECK (
    mata_rls.can_submit_external_attendance(
        external_resident_id,
        teaching_event_id
    )
)
"""
    )

    if upgrade:
        native_update = """
            mata_rls.can_submit_native_attendance(
                resident_id,
                teaching_event_id
            )
            OR (
                mata_rls.is_native_resident(resident_id)
                AND mata_rls.can_select_teaching_event(teaching_event_id)
                AND EXISTS (
                    SELECT 1
                    FROM public.teaching_events AS event
                    WHERE event.id = teaching_event_id
                      AND event.is_adhoc
                )
            )
        """
        external_update = """
            mata_rls.can_submit_external_attendance(
                external_resident_id,
                teaching_event_id
            )
            OR (
                mata_rls.is_external_resident(external_resident_id)
                AND mata_rls.can_select_teaching_event(teaching_event_id)
                AND EXISTS (
                    SELECT 1
                    FROM public.teaching_events AS event
                    WHERE event.id = teaching_event_id
                      AND event.is_adhoc
                )
            )
        """
    else:
        native_update = """
            mata_rls.can_submit_native_attendance(
                resident_id,
                teaching_event_id
            )
        """
        external_update = """
            mata_rls.can_submit_external_attendance(
                external_resident_id,
                teaching_event_id
            )
        """

    _execute(
        f"""
CREATE POLICY "mata_rls_attendance_records_update"
ON public.attendance_records
AS PERMISSIVE
FOR UPDATE
TO mata_app_runtime
USING ({native_update})
WITH CHECK ({native_update})
"""
    )
    _execute(
        f"""
CREATE POLICY "mata_rls_external_attendance_records_update"
ON public.external_attendance_records
AS PERMISSIVE
FOR UPDATE
TO mata_app_runtime
USING ({external_update})
WITH CHECK ({external_update})
"""
    )


def _create_atomic_helper() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.create_adhoc_attendance(
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
        f"REVOKE ALL PRIVILEGES ON FUNCTION "
        f"mata_rls.{ATOMIC_HELPER_SIGNATURE} "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        f"GRANT EXECUTE ON FUNCTION "
        f"mata_rls.{ATOMIC_HELPER_SIGNATURE} "
        f"TO {RUNTIME_ROLE}"
    )
    _execute(
        rf"""
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
                'REVOKE ALL PRIVILEGES ON FUNCTION '
                'mata_rls.{ATOMIC_HELPER_SIGNATURE} FROM %I',
                optional_role
            );
        END IF;
    END LOOP;
END
$migration$
"""
    )
    _execute(
        f"GRANT CREATE ON SCHEMA mata_rls TO {DEFINER_ROLE}"
    )
    _grant_atomic_helper_definer_for_ownership()
    _execute(
        f"ALTER FUNCTION mata_rls.{ATOMIC_HELPER_SIGNATURE} "
        f"OWNER TO {DEFINER_ROLE}"
    )
    _execute(
        f"REVOKE CREATE ON SCHEMA mata_rls FROM {DEFINER_ROLE}"
    )
    _revoke_atomic_helper_definer_ownership()


def _restore_old_policy_helpers() -> None:
    for public_signature, private_signature in reversed(_MOVED_POLICY_HELPERS):
        public_name = public_signature.split("(", 1)[0]
        private_name = private_signature.split("(", 1)[0]
        arguments = private_signature.split("(", 1)[1]
        _execute(f"DROP FUNCTION mata_rls.{public_signature}")
        _execute(
            f"ALTER FUNCTION mata_private.{private_signature} "
            f"RENAME TO {public_name}"
        )
        _execute(
            f"ALTER FUNCTION mata_private.{public_name}({arguments} "
            "SET SCHEMA mata_rls"
        )
        _execute(
            f"REVOKE ALL PRIVILEGES ON FUNCTION "
            f"mata_rls.{public_signature} "
            f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
        )
        _execute(
            f"GRANT EXECUTE ON FUNCTION mata_rls.{public_signature} "
            f"TO {RUNTIME_ROLE}"
        )


def _drop_integrity_triggers() -> None:
    _execute(
        "DROP TRIGGER mata_enforce_external_attendance_integrity "
        "ON public.external_attendance_records"
    )
    _execute(
        "DROP TRIGGER mata_enforce_attendance_integrity "
        "ON public.attendance_records"
    )
    _execute(
        "DROP TRIGGER mata_enforce_teaching_event_creator_immutability "
        "ON public.teaching_events"
    )
    _execute(
        "DROP FUNCTION mata_private.enforce_attendance_integrity()"
    )
    _execute(
        "DROP FUNCTION "
        "mata_private.enforce_teaching_event_creator_immutability()"
    )


def _drop_creator_schema() -> None:
    _execute(
        r"""
DO $migration$
DECLARE
    duplicate_scope text;
BEGIN
    SELECT pg_catalog.string_agg(scope_key, ', ')
    INTO duplicate_scope
    FROM (
        SELECT
            attendance.resident_id::text
            || '/'
            || attendance.teaching_event_id::text AS scope_key
        FROM public.attendance_records AS attendance
        GROUP BY
            attendance.resident_id,
            attendance.teaching_event_id
        HAVING COUNT(*) > 1
        ORDER BY scope_key
        LIMIT 20
    ) AS duplicate;

    IF duplicate_scope IS NOT NULL THEN
        RAISE EXCEPTION
            'Cannot downgrade: native attendance history has duplicate scope(s): %',
            duplicate_scope
            USING ERRCODE = '23505';
    END IF;
END
$migration$
"""
    )

    op.drop_constraint(
        "ck_external_attendance_records_status",
        "external_attendance_records",
        type_="check",
    )
    op.drop_constraint(
        "ck_attendance_records_status",
        "attendance_records",
        type_="check",
    )
    op.drop_index(
        "idx_attendance_records_submitted_resident_event",
        table_name="attendance_records",
    )
    op.create_unique_constraint(
        "uq_attendance_records_resident_event",
        "attendance_records",
        ["resident_id", "teaching_event_id"],
    )
    op.create_index(
        "idx_attendance_records_submitted_resident_event",
        "attendance_records",
        ["resident_id", "teaching_event_id"],
        postgresql_where=sa.text("status = 'submitted'"),
    )

    op.drop_index(
        "idx_teaching_events_created_by_external_resident",
        table_name="teaching_events",
    )
    op.drop_index(
        "idx_teaching_events_created_by_resident",
        table_name="teaching_events",
    )
    op.drop_constraint(
        "ck_teaching_events_adhoc_creator_family",
        "teaching_events",
        type_="check",
    )
    op.drop_constraint(
        "fk_teaching_events_external_resident_creator",
        "teaching_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_teaching_events_resident_creator",
        "teaching_events",
        type_="foreignkey",
    )
    op.drop_column(
        "teaching_events",
        "created_by_external_resident_id",
    )
    op.drop_column("teaching_events", "created_by_resident_id")


def upgrade() -> None:
    _add_creator_schema_and_backfill()
    _create_integrity_triggers()
    _move_old_policy_helpers_to_private()
    _create_policy_wrappers()
    _replace_affected_policies(upgrade=True)
    _prepare_atomic_helper_definer()
    _create_atomic_helper()


def downgrade() -> None:
    _grant_atomic_helper_definer_for_ownership()
    _drop_atomic_helper_as_definer()
    _revoke_atomic_helper_definer_ownership()
    _execute(
        "REVOKE ALL PRIVILEGES ON FUNCTION "
        "mata_rls.current_subject_type(), "
        "mata_rls.current_subject_id() "
        f"FROM {DEFINER_ROLE}"
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON FUNCTION public.gen_random_uuid() "
        f"FROM {DEFINER_ROLE}"
    )
    _execute(
        f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public "
        f"FROM {DEFINER_ROLE}"
    )
    _execute(
        f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public "
        f"FROM {DEFINER_ROLE}"
    )
    _execute(
        f"REVOKE ALL PRIVILEGES ON SCHEMA public, mata_rls, mata_private "
        f"FROM {DEFINER_ROLE}"
    )
    for table_name, action in (
        ("teaching_events", "select"),
        ("teaching_events", "insert"),
        ("attendance_records", "select"),
        ("attendance_records", "insert"),
        ("attendance_records", "update"),
        ("external_attendance_records", "insert"),
        ("external_attendance_records", "update"),
    ):
        _execute(
            f'DROP POLICY "mata_rls_{table_name}_{action}" '
            f'ON public."{table_name}"'
        )
    _restore_old_policy_helpers()
    _replace_affected_policies(upgrade=False, drop_existing=False)
    _drop_integrity_triggers()
    _drop_creator_schema()
