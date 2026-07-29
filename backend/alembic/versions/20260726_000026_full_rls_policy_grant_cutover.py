"""cut over every application table to full RLS and least-privilege grants

Revision ID: 20260726_000026
Revises: 20260726_000025
Create Date: 2026-07-26

The preceding revision establishes hardened capability roles, signed
transaction-local identity context, and narrow service helpers.  This revision
is the authorization cutover: every application table has RLS enabled, normal
runtime access is granted only to ``mata_app_runtime``, and tables that are
reachable solely through reviewed service helpers remain opaque.
"""

from __future__ import annotations

from alembic import op


revision = "20260726_000026"
down_revision = "20260726_000025"
branch_labels = None
depends_on = None


RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"

APPLICATION_TABLES = (
    "academic_month_boundaries",
    "app_sessions",
    "attendance_records",
    "audit_logs",
    "clawback_records",
    "event_series",
    "external_attendance_records",
    "external_resident_postings",
    "external_residents",
    "form_f1_records",
    "global_session_types",
    "loa_types",
    "multi_posting_rules",
    "period_snapshots",
    "posting_codes",
    "posting_groups",
    "programme_institution_posting_map",
    "programmes",
    "public_holidays",
    "rate_limit_buckets",
    "reporting_periods",
    "resident_postings",
    "residents",
    "secretary_programme_pools",
    "session_types",
    "surplus_ledger",
    "teaching_events",
    "teaching_name_catalogue",
    "teaching_targets",
    "upload_logs",
    "upload_warnings",
    "users",
    "warning_issues",
    "weekend_exceptions",
)

# Fourteen tables already had RLS at revision 000024.  ``users`` is normalized
# to the approved deployed RLS baseline at the start of this revision.  A
# downgrade must preserve all fifteen hardened states.
PREEXISTING_RLS_TABLES = (
    "academic_month_boundaries",
    "event_series",
    "global_session_types",
    "loa_types",
    "multi_posting_rules",
    "posting_codes",
    "posting_groups",
    "programmes",
    "public_holidays",
    "rate_limit_buckets",
    "reporting_periods",
    "secretary_programme_pools",
    "session_types",
    "users",
    "weekend_exceptions",
)

NEW_RLS_TABLES = tuple(
    table_name
    for table_name in APPLICATION_TABLES
    if table_name not in PREEXISTING_RLS_TABLES
)

# These six relations are callable only through the narrow SECURITY DEFINER
# helpers created in 000025.  They intentionally receive no table policy and
# no direct runtime table privilege.
NO_DIRECT_RUNTIME_TABLES = (
    "app_sessions",
    "clawback_records",
    "period_snapshots",
    "programme_institution_posting_map",
    "rate_limit_buckets",
    "surplus_ledger",
)

POLICY_HELPER_SIGNATURES = (
    "can_access_resident(uuid)",
    "can_manage_resident(uuid)",
    "can_access_form_f1(text)",
    "native_assignment_matches(text,text,uuid)",
    "can_access_teaching_catalogue(text,text,uuid)",
    "can_select_teaching_event(uuid)",
    "can_insert_teaching_event(text,text,text,date,boolean,text)",
    "can_manage_teaching_event(text,text,text,date,boolean,text)",
    "can_submit_native_attendance(uuid,uuid)",
    "can_access_external_attendance(uuid,uuid)",
    "can_submit_external_attendance(uuid,uuid)",
)


def _policy(
    table_name: str,
    action: str,
    *,
    using: str | None = None,
    check: str | None = None,
) -> tuple[str, str, str, str | None, str | None]:
    policy_name = f"mata_rls_{table_name}_{action.lower()}"
    return table_name, policy_name, action, using, check


AUTHENTICATED = "mata_rls.is_authenticated()"
MASTER = "mata_rls.is_master_admin()"

POLICIES = (
    _policy(
        "users",
        "SELECT",
        using=(
            f"{MASTER} OR ("
            "mata_rls.current_subject_type() = 'staff' "
            "AND id = mata_rls.current_subject_id())"
        ),
    ),
    _policy("users", "INSERT", check=MASTER),
    _policy("users", "UPDATE", using=MASTER, check=MASTER),
    _policy(
        "residents",
        "SELECT",
        using="mata_rls.can_access_resident(id)",
    ),
    _policy(
        "residents",
        "INSERT",
        check=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
    ),
    _policy(
        "residents",
        "UPDATE",
        using=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
        check=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
    ),
    _policy(
        "resident_postings",
        "SELECT",
        using=(
            "CASE WHEN "
            "mata_rls.current_subject_type() = 'staff' "
            "AND mata_rls.current_app_role() = 'secretary' "
            "THEN mata_rls.is_secretary_for_posting(posting_code) "
            "ELSE mata_rls.can_access_resident(resident_id) END"
        ),
    ),
    _policy(
        "resident_postings",
        "INSERT",
        check="mata_rls.can_manage_resident(resident_id)",
    ),
    _policy(
        "resident_postings",
        "UPDATE",
        using="mata_rls.can_manage_resident(resident_id)",
        check="mata_rls.can_manage_resident(resident_id)",
    ),
    _policy(
        "resident_postings",
        "DELETE",
        using="mata_rls.can_manage_resident(resident_id)",
    ),
    _policy(
        "attendance_records",
        "SELECT",
        using=(
            "CASE WHEN "
            "mata_rls.current_subject_type() = 'staff' "
            "AND mata_rls.current_app_role() = 'secretary' "
            "THEN mata_rls.can_select_teaching_event(teaching_event_id) "
            "ELSE mata_rls.can_access_resident(resident_id) END"
        ),
    ),
    _policy(
        "attendance_records",
        "INSERT",
        check=(
            "mata_rls.can_submit_native_attendance("
            "resident_id, teaching_event_id)"
        ),
    ),
    _policy(
        "attendance_records",
        "UPDATE",
        using=(
            "mata_rls.can_submit_native_attendance("
            "resident_id, teaching_event_id)"
        ),
        check=(
            "mata_rls.can_submit_native_attendance("
            "resident_id, teaching_event_id)"
        ),
    ),
    _policy("attendance_records", "DELETE", using=MASTER),
    _policy(
        "external_residents",
        "SELECT",
        using=(
            f"{MASTER} OR mata_rls.is_external_resident(id) OR EXISTS ("
            "SELECT 1 FROM public.external_resident_postings "
            "AS scoped_external_posting "
            "WHERE scoped_external_posting.external_resident_id "
            "= external_residents.id "
            "AND scoped_external_posting.programme_code IS NOT NULL "
            "AND mata_rls.has_programme_scope("
            "scoped_external_posting.programme_code))"
        ),
    ),
    _policy(
        "external_resident_postings",
        "SELECT",
        using=(
            f"{MASTER} "
            "OR mata_rls.is_external_resident(external_resident_id) "
            "OR (programme_code IS NOT NULL "
            "AND mata_rls.has_programme_scope(programme_code))"
        ),
    ),
    _policy(
        "external_attendance_records",
        "SELECT",
        using=(
            "mata_rls.can_access_external_attendance("
            "external_resident_id, teaching_event_id)"
        ),
    ),
    _policy(
        "external_attendance_records",
        "INSERT",
        check=(
            "mata_rls.can_submit_external_attendance("
            "external_resident_id, teaching_event_id)"
        ),
    ),
    _policy(
        "external_attendance_records",
        "UPDATE",
        using=(
            "mata_rls.can_submit_external_attendance("
            "external_resident_id, teaching_event_id)"
        ),
        check=(
            "mata_rls.can_submit_external_attendance("
            "external_resident_id, teaching_event_id)"
        ),
    ),
    _policy("external_attendance_records", "DELETE", using=MASTER),
    _policy(
        "teaching_events",
        "SELECT",
        using="mata_rls.can_select_teaching_event(id)",
    ),
    _policy(
        "teaching_events",
        "INSERT",
        check=(
            "mata_rls.can_insert_teaching_event("
            "posting_code, created_for_programme_code, teaching_name, "
            "event_date, is_adhoc, created_by_role)"
        ),
    ),
    _policy(
        "teaching_events",
        "UPDATE",
        using=(
            "mata_rls.can_manage_teaching_event("
            "posting_code, created_for_programme_code, teaching_name, "
            "event_date, "
            "is_adhoc, created_by_role)"
        ),
        check=(
            "mata_rls.can_manage_teaching_event("
            "posting_code, created_for_programme_code, teaching_name, "
            "event_date, "
            "is_adhoc, created_by_role)"
        ),
    ),
    _policy(
        "teaching_events",
        "DELETE",
        using=(
            "mata_rls.can_manage_teaching_event("
            "posting_code, created_for_programme_code, teaching_name, "
            "event_date, "
            "is_adhoc, created_by_role)"
        ),
    ),
    _policy(
        "event_series",
        "SELECT",
        using=f"{MASTER} OR mata_rls.is_secretary_for_posting(posting_code)",
    ),
    _policy(
        "event_series",
        "INSERT",
        check="mata_rls.is_secretary_for_posting(posting_code)",
    ),
    _policy(
        "event_series",
        "UPDATE",
        using="mata_rls.is_secretary_for_posting(posting_code)",
        check="mata_rls.is_secretary_for_posting(posting_code)",
    ),
    _policy(
        "event_series",
        "DELETE",
        using="mata_rls.is_secretary_for_posting(posting_code)",
    ),
    _policy("session_types", "SELECT", using=AUTHENTICATED),
    _policy(
        "teaching_targets",
        "SELECT",
        using=(
            f"{MASTER} "
            "OR mata_rls.has_programme_scope(programme_code) "
            "OR mata_rls.native_assignment_matches("
            "programme_code, posting_code, reporting_period_id)"
        ),
    ),
    _policy(
        "teaching_targets",
        "INSERT",
        check=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
    ),
    _policy(
        "teaching_targets",
        "UPDATE",
        using=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
        check=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
    ),
    _policy(
        "teaching_targets",
        "DELETE",
        using=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
    ),
    _policy(
        "teaching_name_catalogue",
        "SELECT",
        using=(
            "mata_rls.can_access_teaching_catalogue("
            "programme_code, posting_code, reporting_period_id)"
        ),
    ),
    _policy(
        "teaching_name_catalogue",
        "INSERT",
        check=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
    ),
    _policy(
        "teaching_name_catalogue",
        "DELETE",
        using=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
    ),
    _policy("posting_codes", "SELECT", using=AUTHENTICATED),
    _policy("programmes", "SELECT", using=AUTHENTICATED),
    _policy("programmes", "UPDATE", using=MASTER, check=MASTER),
    _policy("reporting_periods", "SELECT", using=AUTHENTICATED),
    _policy("reporting_periods", "INSERT", check=MASTER),
    _policy("reporting_periods", "UPDATE", using=MASTER, check=MASTER),
    _policy("reporting_periods", "DELETE", using=MASTER),
    _policy(
        "form_f1_records",
        "SELECT",
        using="mata_rls.can_access_form_f1(mcr)",
    ),
    _policy("form_f1_records", "INSERT", check=MASTER),
    _policy(
        "form_f1_records",
        "UPDATE",
        using=f"{MASTER} OR mata_rls.can_access_form_f1(mcr)",
        check=f"{MASTER} OR mata_rls.can_access_form_f1(mcr)",
    ),
    _policy("form_f1_records", "DELETE", using=MASTER),
    _policy("public_holidays", "SELECT", using=AUTHENTICATED),
    _policy("public_holidays", "INSERT", check=MASTER),
    _policy("public_holidays", "UPDATE", using=MASTER, check=MASTER),
    _policy("public_holidays", "DELETE", using=MASTER),
    _policy("academic_month_boundaries", "SELECT", using=AUTHENTICATED),
    _policy("academic_month_boundaries", "INSERT", check=MASTER),
    _policy(
        "academic_month_boundaries",
        "UPDATE",
        using=MASTER,
        check=MASTER,
    ),
    _policy("academic_month_boundaries", "DELETE", using=MASTER),
    _policy(
        "upload_logs",
        "SELECT",
        using=(
            f"{MASTER} OR ("
            "upload_type = 'ttf' "
            "AND programme_code IS NOT NULL "
            "AND mata_rls.has_programme_scope(programme_code))"
        ),
    ),
    _policy(
        "upload_logs",
        "INSERT",
        check=(
            "uploaded_by = mata_rls.current_subject_id() AND ("
            f"{MASTER} OR ("
            "upload_type = 'ttf' "
            "AND programme_code IS NOT NULL "
            "AND mata_rls.has_programme_scope(programme_code)))"
        ),
    ),
    _policy(
        "warning_issues",
        "SELECT",
        using=(
            f"{MASTER} OR ("
            "programme_code IS NOT NULL "
            "AND mata_rls.has_programme_scope(programme_code))"
        ),
    ),
    _policy(
        "warning_issues",
        "INSERT",
        check=(
            f"{MASTER} OR ("
            "programme_code IS NOT NULL "
            "AND mata_rls.has_programme_scope(programme_code))"
        ),
    ),
    _policy(
        "warning_issues",
        "UPDATE",
        using=(
            f"{MASTER} OR ("
            "programme_code IS NOT NULL "
            "AND mata_rls.has_programme_scope(programme_code))"
        ),
        check=(
            f"{MASTER} OR ("
            "programme_code IS NOT NULL "
            "AND mata_rls.has_programme_scope(programme_code))"
        ),
    ),
    _policy(
        "upload_warnings",
        "SELECT",
        using=(
            f"{MASTER} OR ("
            "programme_code IS NOT NULL "
            "AND mata_rls.has_programme_scope(programme_code))"
        ),
    ),
    _policy(
        "upload_warnings",
        "INSERT",
        check=(
            f"{MASTER} OR ("
            "programme_code IS NOT NULL "
            "AND mata_rls.has_programme_scope(programme_code))"
        ),
    ),
    _policy(
        "audit_logs",
        "SELECT",
        using=(
            f"{MASTER} OR ("
            "actor_programme IS NOT NULL "
            "AND mata_rls.has_programme_scope(actor_programme))"
        ),
    ),
    _policy("global_session_types", "SELECT", using=AUTHENTICATED),
    _policy("global_session_types", "INSERT", check=MASTER),
    _policy("global_session_types", "UPDATE", using=MASTER, check=MASTER),
    _policy("global_session_types", "DELETE", using=MASTER),
    _policy(
        "multi_posting_rules",
        "SELECT",
        using=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
    ),
    _policy(
        "multi_posting_rules",
        "INSERT",
        check=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
    ),
    _policy(
        "multi_posting_rules",
        "UPDATE",
        using=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
        check=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
    ),
    _policy(
        "multi_posting_rules",
        "DELETE",
        using=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
    ),
    _policy(
        "posting_groups",
        "SELECT",
        using=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
    ),
    _policy(
        "posting_groups",
        "INSERT",
        check=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
    ),
    _policy(
        "posting_groups",
        "UPDATE",
        using=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
        check=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
    ),
    _policy(
        "posting_groups",
        "DELETE",
        using=f"{MASTER} OR mata_rls.has_programme_scope(programme_code)",
    ),
    _policy("weekend_exceptions", "SELECT", using=AUTHENTICATED),
    _policy("weekend_exceptions", "INSERT", check=MASTER),
    _policy("weekend_exceptions", "UPDATE", using=MASTER, check=MASTER),
    _policy("weekend_exceptions", "DELETE", using=MASTER),
    _policy("loa_types", "SELECT", using=AUTHENTICATED),
    _policy("loa_types", "INSERT", check=MASTER),
    _policy("loa_types", "UPDATE", using=MASTER, check=MASTER),
    _policy("loa_types", "DELETE", using=MASTER),
    _policy(
        "secretary_programme_pools",
        "SELECT",
        using=(
            f"{MASTER} "
            "OR mata_rls.has_programme_scope(programme_code) "
            "OR mata_rls.is_secretary_for_posting(posting_code)"
        ),
    ),
)

# Table-level privileges are paired with the policies above.  Absence from this
# mapping means no direct runtime privilege.
DIRECT_TABLE_GRANTS = {
    "academic_month_boundaries": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "attendance_records": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "audit_logs": ("SELECT",),
    "event_series": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "external_attendance_records": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "external_resident_postings": ("SELECT",),
    "external_residents": ("SELECT",),
    "form_f1_records": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "global_session_types": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "loa_types": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "multi_posting_rules": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "posting_codes": ("SELECT",),
    "posting_groups": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "programmes": ("SELECT", "UPDATE"),
    "public_holidays": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "reporting_periods": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "resident_postings": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "residents": ("SELECT", "INSERT", "UPDATE"),
    "secretary_programme_pools": ("SELECT",),
    "session_types": ("SELECT",),
    "teaching_events": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "teaching_name_catalogue": ("SELECT", "INSERT", "DELETE"),
    "teaching_targets": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "upload_logs": ("SELECT", "INSERT"),
    "upload_warnings": ("SELECT", "INSERT"),
    "warning_issues": ("SELECT", "INSERT", "UPDATE"),
    "weekend_exceptions": ("SELECT", "INSERT", "UPDATE", "DELETE"),
}

# ``password_hash`` is deliberately absent.  Staff password verification is
# confined to the auth helper connection, and normal runtime queries never
# receive a reusable credential verifier.
USERS_SELECT_COLUMNS = (
    "email",
    "role",
    "name",
    "posting_code",
    "programme_scope",
    "is_active",
    "id",
    "created_at",
    "updated_at",
    "admin_level",
    "supabase_user_id",
    "current_staff_actor_name",
    "staff_actor_name_updated_at",
    "staff_actor_name_updated_by_user_id",
    "session_generation",
    "session_issuance_blocked",
)


def _execute(statement: str) -> None:
    # Policy expressions and PL/pgSQL bodies contain PostgreSQL casts.  Driver
    # SQL prevents SQLAlchemy from treating their colon syntax as binds.
    # ``no_parameters`` preserves PL/pgSQL RAISE/format percent tokens when
    # Alembic uses a pyformat DBAPI such as psycopg.
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(statement)


def _sql_text_array(values: tuple[str, ...]) -> str:
    return "ARRAY[" + ", ".join(repr(value) for value in values) + "]::text[]"


def _assert_foundation_catalogue() -> None:
    application_tables = _sql_text_array(APPLICATION_TABLES)
    old_rls_tables = _sql_text_array(PREEXISTING_RLS_TABLES)
    new_rls_tables = _sql_text_array(NEW_RLS_TABLES)
    _execute(
        f"""
DO $migration$
DECLARE
    expected_tables text[] := {application_tables};
    expected_old_rls text[] := {old_rls_tables};
    expected_new_rls text[] := {new_rls_tables};
    table_name text;
    role_row record;
BEGIN
    FOREACH table_name IN ARRAY expected_tables
    LOOP
        IF pg_catalog.to_regclass(
            pg_catalog.format('public.%I', table_name)
        ) IS NULL THEN
            RAISE EXCEPTION 'Required application table is missing: %',
                table_name
                USING ERRCODE = '42P01';
        END IF;
    END LOOP;

    IF pg_catalog.cardinality(expected_tables) <> 34
       OR pg_catalog.cardinality(expected_old_rls) <> 15
       OR pg_catalog.cardinality(expected_new_rls) <> 19
    THEN
        RAISE EXCEPTION 'Reviewed RLS table inventory is inconsistent'
            USING ERRCODE = '22023';
    END IF;

    IF pg_catalog.to_regprocedure(
        'mata_rls.install_request_context(bytea,text,text,uuid,uuid,text)'
    ) IS NULL
       OR pg_catalog.to_regprocedure(
           'mata_rls.context_is_valid()'
       ) IS NULL
       OR pg_catalog.to_regprocedure(
           'mata_rls.is_master_admin()'
       ) IS NULL
    THEN
        RAISE EXCEPTION 'Revision 000025 RLS foundation is incomplete'
            USING ERRCODE = '0A000';
    END IF;

    FOREACH table_name IN ARRAY expected_old_rls
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname = table_name
              AND relation.relkind IN ('r', 'p')
              AND relation.relrowsecurity
              AND NOT relation.relforcerowsecurity
        ) THEN
            RAISE EXCEPTION
                'Pre-existing RLS state drifted for table %',
                table_name
                USING ERRCODE = '42501';
        END IF;
    END LOOP;

    FOREACH table_name IN ARRAY expected_new_rls
    LOOP
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname = table_name
              AND relation.relkind IN ('r', 'p')
              AND (
                  relation.relrowsecurity
                  OR relation.relforcerowsecurity
              )
        ) THEN
            RAISE EXCEPTION
                'Unexpected pre-cutover RLS state for table %',
                table_name
                USING ERRCODE = '42501';
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policy AS policy
        JOIN pg_catalog.pg_class AS relation
          ON relation.oid = policy.polrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = ANY(expected_tables)
    ) THEN
        RAISE EXCEPTION
            'Application-table policies exist before the reviewed cutover'
            USING ERRCODE = '42710';
    END IF;

    FOREACH table_name IN ARRAY ARRAY[
        'mata_app_runtime',
        'mata_auth_internal'
    ]
    LOOP
        SELECT
            rolcanlogin,
            rolsuper,
            rolbypassrls,
            rolcreatedb,
            rolcreaterole,
            rolreplication
        INTO STRICT role_row
        FROM pg_catalog.pg_roles
        WHERE rolname = table_name;
        IF role_row.rolcanlogin
           OR role_row.rolsuper
           OR role_row.rolbypassrls
           OR role_row.rolcreatedb
           OR role_row.rolcreaterole
           OR role_row.rolreplication
        THEN
            RAISE EXCEPTION 'Unsafe role attributes for %', table_name
                USING ERRCODE = '42501';
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_roles AS owner_role
          ON owner_role.oid = relation.relowner
        WHERE namespace.nspname = 'public'
          AND relation.relname = ANY(expected_tables)
          AND owner_role.rolname IN (
              'mata_app_runtime',
              'mata_auth_internal'
          )
    ) THEN
        RAISE EXCEPTION 'A restricted role owns an application table'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS optional_role
        CROSS JOIN pg_catalog.pg_roles AS capability_role
        WHERE optional_role.rolname IN (
            'anon',
            'authenticated',
            'service_role'
        )
          AND capability_role.rolname IN (
              'mata_app_runtime',
              'mata_auth_internal'
          )
          AND pg_catalog.pg_has_role(
              optional_role.oid,
              capability_role.oid,
              'MEMBER'
          )
    ) THEN
        RAISE EXCEPTION
            'Browser/service roles must not inherit H-E capability roles'
            USING ERRCODE = '42501';
    END IF;
END
$migration$
"""
    )


def _create_relationship_predicates() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.can_access_resident(p_resident_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT
        mata_rls.is_master_admin()
        OR mata_rls.is_native_resident(p_resident_id)
        OR (
            mata_rls.current_subject_type() = 'staff'
            AND mata_rls.current_app_role() = 'secretary'
            AND EXISTS (
                SELECT 1
                FROM public.resident_postings AS secretary_posting
                WHERE secretary_posting.resident_id = p_resident_id
                  AND mata_rls.is_secretary_for_posting(
                      secretary_posting.posting_code
                  )
            )
        )
        OR EXISTS (
            SELECT 1
            FROM public.residents AS resident
            WHERE resident.id = p_resident_id
              AND resident.programme_code IS NOT NULL
              AND mata_rls.has_programme_scope(resident.programme_code)
        )
$function$
"""
    )
    _execute(
        r"""
CREATE FUNCTION mata_rls.can_manage_resident(p_resident_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT
        mata_rls.is_master_admin()
        OR EXISTS (
            SELECT 1
            FROM public.residents AS resident
            WHERE resident.id = p_resident_id
              AND resident.programme_code IS NOT NULL
              AND mata_rls.has_programme_scope(resident.programme_code)
        )
$function$
"""
    )
    _execute(
        r"""
CREATE FUNCTION mata_rls.can_access_form_f1(p_mcr text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT
        mata_rls.is_master_admin()
        OR EXISTS (
            SELECT 1
            FROM public.residents AS resident
            WHERE pg_catalog.upper(pg_catalog.btrim(resident.mcr))
                  = pg_catalog.upper(pg_catalog.btrim(p_mcr))
              AND resident.programme_code IS NOT NULL
              AND mata_rls.has_programme_scope(resident.programme_code)
        )
$function$
"""
    )
    _execute(
        r"""
CREATE FUNCTION mata_rls.native_assignment_matches(
    p_programme_code text,
    p_posting_code text,
    p_reporting_period_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.residents AS resident
        JOIN public.resident_postings AS resident_posting
          ON resident_posting.resident_id = resident.id
        WHERE mata_rls.is_native_resident(resident.id)
          AND resident.programme_code
              = pg_catalog.upper(pg_catalog.btrim(p_programme_code))
          AND resident_posting.posting_code = p_posting_code
          AND resident_posting.reporting_period_id = p_reporting_period_id
    )
$function$
"""
    )
    _execute(
        r"""
CREATE FUNCTION mata_rls.can_access_teaching_catalogue(
    p_programme_code text,
    p_posting_code text,
    p_reporting_period_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT
        mata_rls.is_master_admin()
        OR mata_rls.has_programme_scope(p_programme_code)
        OR mata_rls.is_secretary_for_posting(p_posting_code)
        OR EXISTS (
            SELECT 1
            FROM public.secretary_programme_pools AS pool
            WHERE pool.posting_code = mata_rls.current_posting_code()
              AND pool.programme_code
                  = pg_catalog.upper(pg_catalog.btrim(p_programme_code))
              AND pool.is_active
        )
        OR EXISTS (
            SELECT 1
            FROM public.residents AS resident
            JOIN public.programmes AS programme
              ON programme.code = resident.programme_code
            JOIN public.resident_postings AS resident_posting
              ON resident_posting.resident_id = resident.id
             AND resident_posting.reporting_period_id = p_reporting_period_id
            WHERE mata_rls.is_native_resident(resident.id)
              AND resident.programme_code
                  = pg_catalog.upper(pg_catalog.btrim(p_programme_code))
              AND (
                  resident_posting.posting_code = p_posting_code
                  OR programme.native_teaching_posting_code = p_posting_code
              )
        )
        OR EXISTS (
            SELECT 1
            FROM public.external_resident_postings AS external_posting
            JOIN public.reporting_periods AS reporting_period
              ON reporting_period.id = p_reporting_period_id
            WHERE mata_rls.is_external_resident(
                      external_posting.external_resident_id
                  )
              AND external_posting.programme_code
                  = pg_catalog.upper(pg_catalog.btrim(p_programme_code))
              AND external_posting.posting_code = p_posting_code
              AND external_posting.start_date <= reporting_period.end_date
              AND COALESCE(
                      external_posting.end_date,
                      'infinity'::date
                  ) >= reporting_period.start_date
        )
$function$
"""
    )
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
        event.posting_code,
        event.created_for_programme_code,
        event.teaching_name,
        event.event_date,
        event.is_adhoc,
        event.created_by_role
    INTO event_row
    FROM public.teaching_events AS event
    WHERE event.id = p_event_id;
    IF NOT FOUND THEN
        RETURN false;
    END IF;

    IF mata_rls.is_master_admin() THEN
        RETURN true;
    END IF;

    IF subject_type = 'staff' AND app_role = 'admin' THEN
        RETURN (
            NOT event_row.is_adhoc
            AND (
                event_row.created_by_role IN ('secretary', 'programme_pc')
                OR event_row.created_by_role IS NULL
            )
            AND event_row.created_for_programme_code IS NOT NULL
            AND mata_rls.has_programme_scope(
                event_row.created_for_programme_code
            )
        )
        OR (
            NOT event_row.is_adhoc
            AND (
                event_row.created_by_role IN ('secretary', 'programme_pc')
                OR event_row.created_by_role IS NULL
            )
            AND EXISTS (
                SELECT 1
                FROM public.teaching_name_catalogue AS catalogue
                JOIN public.reporting_periods AS reporting_period
                  ON reporting_period.id = catalogue.reporting_period_id
                WHERE catalogue.keyword = event_row.teaching_name
                  AND catalogue.posting_code = event_row.posting_code
                  AND event_row.event_date BETWEEN
                      reporting_period.start_date
                      AND reporting_period.end_date
                  AND mata_rls.has_programme_scope(
                      catalogue.programme_code
                  )
            )
        )
        OR (
            NOT event_row.is_adhoc
            AND (
                event_row.created_by_role IN ('secretary', 'programme_pc')
                OR event_row.created_by_role IS NULL
            )
            AND EXISTS (
                SELECT 1
                FROM public.secretary_programme_pools AS pool
                WHERE pool.posting_code = event_row.posting_code
                  AND pool.is_active
                  AND mata_rls.has_programme_scope(pool.programme_code)
            )
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
            WHERE attendance.teaching_event_id = event_row.id
              AND external_posting.programme_code IS NOT NULL
              AND mata_rls.has_programme_scope(
                  external_posting.programme_code
              )
        );
    END IF;

    IF subject_type = 'staff' AND app_role = 'secretary' THEN
        RETURN mata_rls.is_secretary_for_posting(event_row.posting_code)
           AND NOT event_row.is_adhoc
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
                  EXISTS (
                      SELECT 1
                      FROM public.global_session_types AS global_type
                      WHERE global_type.name = event_row.teaching_name
                        AND global_type.is_active
                  )
                  OR EXISTS (
                      SELECT 1
                      FROM public.teaching_name_catalogue AS catalogue
                      JOIN public.reporting_periods AS reporting_period
                        ON reporting_period.id
                            = catalogue.reporting_period_id
                      WHERE catalogue.keyword = event_row.teaching_name
                        AND catalogue.programme_code
                            = resident.programme_code
                        AND event_row.event_date BETWEEN
                            reporting_period.start_date
                            AND reporting_period.end_date
                        AND catalogue.posting_code IN (
                            resident_posting.posting_code,
                            event_row.posting_code
                        )
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
              AND (
                  (
                      event_row.created_for_programme_code IS NULL
                      AND (
                          event_row.is_adhoc
                          OR posting.supports_secretary_events
                      )
                  )
                  OR (
                      event_row.created_for_programme_code IS NOT NULL
                      AND external_posting.programme_code IS NOT NULL
                      AND external_posting.programme_code
                          = event_row.created_for_programme_code
                  )
              )
              AND (
                  EXISTS (
                      SELECT 1
                      FROM public.global_session_types AS global_type
                      WHERE global_type.name = event_row.teaching_name
                        AND global_type.is_active
                  )
                  OR EXISTS (
                      SELECT 1
                      FROM public.teaching_name_catalogue AS catalogue
                      JOIN public.reporting_periods AS reporting_period
                        ON reporting_period.id
                            = catalogue.reporting_period_id
                      WHERE catalogue.keyword = event_row.teaching_name
                        AND catalogue.programme_code
                            = external_posting.programme_code
                        AND catalogue.posting_code
                            = external_posting.posting_code
                        AND event_row.event_date BETWEEN
                            reporting_period.start_date
                            AND reporting_period.end_date
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
        mata_rls.is_master_admin()
        OR (
            mata_rls.current_subject_type() = 'staff'
            AND mata_rls.current_app_role() = 'admin'
            AND NOT COALESCE(p_is_adhoc, false)
            AND p_created_by_role = 'programme_pc'
            AND p_created_for_programme_code IS NOT NULL
            AND mata_rls.has_programme_scope(
                p_created_for_programme_code
            )
            AND (
                EXISTS (
                    SELECT 1
                    FROM public.teaching_name_catalogue AS catalogue
                    JOIN public.reporting_periods AS reporting_period
                      ON reporting_period.id
                          = catalogue.reporting_period_id
                    WHERE catalogue.keyword = p_teaching_name
                      AND catalogue.programme_code
                          = pg_catalog.upper(
                              pg_catalog.btrim(
                                  p_created_for_programme_code
                              )
                          )
                      AND catalogue.posting_code = p_posting_code
                      AND p_event_date BETWEEN
                          reporting_period.start_date
                          AND reporting_period.end_date
                )
                OR (
                    EXISTS (
                        SELECT 1
                        FROM public.global_session_types AS global_type
                        WHERE global_type.name = p_teaching_name
                          AND global_type.is_active
                    )
                    AND (
                        EXISTS (
                            SELECT 1
                            FROM public.secretary_programme_pools AS pool
                            WHERE pool.programme_code
                                = pg_catalog.upper(
                                    pg_catalog.btrim(
                                        p_created_for_programme_code
                                    )
                                )
                              AND pool.posting_code = p_posting_code
                              AND pool.is_active
                        )
                        OR EXISTS (
                            SELECT 1
                            FROM public.teaching_name_catalogue
                                AS catalogue
                            JOIN public.reporting_periods
                                AS reporting_period
                              ON reporting_period.id
                                  = catalogue.reporting_period_id
                            WHERE catalogue.programme_code
                                = pg_catalog.upper(
                                    pg_catalog.btrim(
                                        p_created_for_programme_code
                                    )
                                )
                              AND catalogue.posting_code
                                  = p_posting_code
                              AND p_event_date BETWEEN
                                  reporting_period.start_date
                                  AND reporting_period.end_date
                        )
                    )
                )
            )
        )
        OR (
            mata_rls.current_subject_type() = 'staff'
            AND mata_rls.current_app_role() = 'secretary'
            AND NOT COALESCE(p_is_adhoc, false)
            AND p_created_by_role = 'secretary'
            AND p_created_for_programme_code IS NULL
            AND mata_rls.is_secretary_for_posting(p_posting_code)
            AND (
                EXISTS (
                    SELECT 1
                    FROM public.global_session_types AS global_type
                    WHERE global_type.name = p_teaching_name
                      AND global_type.is_active
                )
                OR EXISTS (
                    SELECT 1
                    FROM public.teaching_name_catalogue AS catalogue
                    JOIN public.reporting_periods AS reporting_period
                      ON reporting_period.id
                          = catalogue.reporting_period_id
                    WHERE catalogue.keyword = p_teaching_name
                      AND p_event_date BETWEEN
                          reporting_period.start_date
                          AND reporting_period.end_date
                      AND (
                          catalogue.posting_code = p_posting_code
                          OR EXISTS (
                              SELECT 1
                              FROM public.secretary_programme_pools
                                  AS pool
                              WHERE pool.posting_code = p_posting_code
                                AND pool.programme_code
                                    = catalogue.programme_code
                                AND pool.is_active
                          )
                      )
                )
            )
        )
        OR (
            mata_rls.current_subject_type() = 'resident'
            AND COALESCE(p_is_adhoc, false)
            AND p_created_by_role = 'resident'
            AND p_created_for_programme_code IS NULL
            AND EXISTS (
                SELECT 1
                FROM public.residents AS resident
                JOIN public.resident_postings AS resident_posting
                  ON resident_posting.resident_id = resident.id
                WHERE resident_posting.resident_id
                      = mata_rls.current_subject_id()
                  AND resident_posting.posting_code = p_posting_code
                  AND p_event_date BETWEEN
                      resident_posting.start_date
                      AND resident_posting.end_date
                  AND (
                      EXISTS (
                          SELECT 1
                          FROM public.global_session_types AS global_type
                          WHERE global_type.name = p_teaching_name
                            AND global_type.is_active
                      )
                      OR EXISTS (
                          SELECT 1
                          FROM public.teaching_name_catalogue AS catalogue
                          JOIN public.reporting_periods AS reporting_period
                            ON reporting_period.id
                                = catalogue.reporting_period_id
                          WHERE catalogue.keyword = p_teaching_name
                            AND catalogue.programme_code
                                = resident.programme_code
                            AND catalogue.posting_code
                                = resident_posting.posting_code
                            AND p_event_date BETWEEN
                                reporting_period.start_date
                                AND reporting_period.end_date
                      )
                  )
            )
        )
        OR (
            mata_rls.current_subject_type() = 'external_resident'
            AND COALESCE(p_is_adhoc, false)
            AND p_created_by_role = 'external_resident'
            AND p_created_for_programme_code IS NULL
            AND EXISTS (
                SELECT 1
                FROM public.external_resident_postings AS external_posting
                WHERE external_posting.external_resident_id
                      = mata_rls.current_subject_id()
                  AND external_posting.posting_code = p_posting_code
                  AND external_posting.programme_code IS NOT NULL
                  AND external_posting.start_date <= p_event_date
                  AND COALESCE(
                          external_posting.end_date,
                          'infinity'::date
                      ) >= p_event_date
                  AND (
                      EXISTS (
                          SELECT 1
                          FROM public.global_session_types AS global_type
                          WHERE global_type.name = p_teaching_name
                            AND global_type.is_active
                      )
                      OR EXISTS (
                          SELECT 1
                          FROM public.teaching_name_catalogue AS catalogue
                          JOIN public.reporting_periods AS reporting_period
                            ON reporting_period.id
                                = catalogue.reporting_period_id
                          WHERE catalogue.keyword = p_teaching_name
                            AND catalogue.programme_code
                                = external_posting.programme_code
                            AND catalogue.posting_code
                                = external_posting.posting_code
                            AND p_event_date BETWEEN
                                reporting_period.start_date
                                AND reporting_period.end_date
                      )
                  )
            )
        )
$function$
"""
    )
    _execute(
        r"""
CREATE FUNCTION mata_rls.can_manage_teaching_event(
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
        mata_rls.is_master_admin()
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
                    AND (
                        EXISTS (
                            SELECT 1
                            FROM public.secretary_programme_pools AS pool
                            WHERE pool.posting_code = p_posting_code
                              AND pool.is_active
                              AND mata_rls.has_programme_scope(
                                  pool.programme_code
                              )
                        )
                        OR EXISTS (
                            SELECT 1
                            FROM public.teaching_name_catalogue
                                AS catalogue
                            JOIN public.reporting_periods
                                AS reporting_period
                              ON reporting_period.id
                                  = catalogue.reporting_period_id
                            WHERE catalogue.posting_code = p_posting_code
                              AND catalogue.keyword = p_teaching_name
                              AND p_event_date BETWEEN
                                  reporting_period.start_date
                                  AND reporting_period.end_date
                              AND mata_rls.has_programme_scope(
                                  catalogue.programme_code
                              )
                        )
                    )
                )
            )
        )
        OR (
            mata_rls.current_subject_type() = 'staff'
            AND mata_rls.current_app_role() = 'secretary'
            AND NOT COALESCE(p_is_adhoc, false)
            AND (
                p_created_by_role IN ('secretary', 'programme_pc')
                OR p_created_by_role IS NULL
            )
            AND mata_rls.is_secretary_for_posting(p_posting_code)
            AND (
                p_created_for_programme_code IS NULL
                OR EXISTS (
                    SELECT 1
                    FROM public.secretary_programme_pools AS pool
                    WHERE pool.posting_code = p_posting_code
                      AND pool.programme_code
                          = p_created_for_programme_code
                      AND pool.is_active
                )
            )
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
        mata_rls.is_native_resident(p_resident_id)
        AND mata_rls.can_select_teaching_event(p_teaching_event_id)
$function$
"""
    )
    _execute(
        r"""
CREATE FUNCTION mata_rls.can_access_external_attendance(
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
            AND mata_rls.can_select_teaching_event(
                p_teaching_event_id
            )
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
        mata_rls.is_external_resident(p_external_resident_id)
        AND mata_rls.can_select_teaching_event(p_teaching_event_id)
$function$
"""
    )

    _execute(
        "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA mata_rls "
        "FROM PUBLIC"
    )
    for signature in POLICY_HELPER_SIGNATURES:
        _execute(
            f"REVOKE ALL PRIVILEGES ON FUNCTION mata_rls.{signature} "
            f"FROM {RUNTIME_ROLE}, {AUTH_ROLE}"
        )
        _execute(
            f"GRANT EXECUTE ON FUNCTION mata_rls.{signature} "
            f"TO {RUNTIME_ROLE}"
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
                'REVOKE ALL PRIVILEGES ON ALL FUNCTIONS '
                'IN SCHEMA mata_rls FROM %I',
                optional_role
            );
        END IF;
    END LOOP;
END
$migration$;
"""
    )


def _enable_rls_and_create_policies() -> None:
    for table_name in APPLICATION_TABLES:
        _execute(
            f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY'
        )

    for table_name, policy_name, action, using, check in POLICIES:
        clauses = [
            f'CREATE POLICY "{policy_name}"',
            f'ON public."{table_name}"',
            "AS PERMISSIVE",
            f"FOR {action}",
            f"TO {RUNTIME_ROLE}",
        ]
        if using is not None:
            clauses.append(f"USING ({using})")
        if check is not None:
            clauses.append(f"WITH CHECK ({check})")
        _execute("\n".join(clauses))


def _apply_object_privileges() -> None:
    _execute(
        "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public "
        f"FROM {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public "
        f"FROM {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public "
        f"FROM {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    _execute(f"REVOKE CREATE ON SCHEMA public FROM {RUNTIME_ROLE}, {AUTH_ROLE}")
    _execute(f"GRANT USAGE ON SCHEMA public TO {RUNTIME_ROLE}")

    for table_name, privileges in DIRECT_TABLE_GRANTS.items():
        _execute(
            f"GRANT {', '.join(privileges)} "
            f'ON TABLE public."{table_name}" TO {RUNTIME_ROLE}'
        )

    user_columns = ", ".join(f'"{column}"' for column in USERS_SELECT_COLUMNS)
    _execute(
        f"GRANT SELECT ({user_columns}) "
        f'ON TABLE public."users" TO {RUNTIME_ROLE}'
    )
    _execute(
        f"GRANT INSERT, UPDATE ON TABLE public.users TO {RUNTIME_ROLE}"
    )

    # Direct inserts use UUID server defaults whose stored expression resolves
    # to this exact reviewed pgcrypto function.
    _execute(
        f"GRANT EXECUTE ON FUNCTION public.gen_random_uuid() TO {RUNTIME_ROLE}"
    )

    _execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE ALL PRIVILEGES ON TABLES FROM {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE ALL PRIVILEGES ON SEQUENCES FROM {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE ALL PRIVILEGES ON FUNCTIONS FROM {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC"
    )
    _execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC"
    )
    _execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE ALL PRIVILEGES ON FUNCTIONS FROM PUBLIC"
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
                'REVOKE ALL PRIVILEGES ON ALL TABLES '
                'IN SCHEMA public FROM %I',
                optional_role
            );
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON ALL SEQUENCES '
                'IN SCHEMA public FROM %I',
                optional_role
            );
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON ALL FUNCTIONS '
                'IN SCHEMA public FROM %I',
                optional_role
            );
            EXECUTE pg_catalog.format(
                'REVOKE CREATE ON SCHEMA public FROM %I',
                optional_role
            );
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON ALL FUNCTIONS '
                'IN SCHEMA mata_rls FROM %I',
                optional_role
            );
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON ALL FUNCTIONS '
                'IN SCHEMA mata_private FROM %I',
                optional_role
            );
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON SCHEMA mata_rls FROM %I',
                optional_role
            );
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON SCHEMA mata_private FROM %I',
                optional_role
            );
            EXECUTE pg_catalog.format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
                'REVOKE ALL PRIVILEGES ON TABLES FROM %I',
                optional_role
            );
            EXECUTE pg_catalog.format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
                'REVOKE ALL PRIVILEGES ON SEQUENCES FROM %I',
                optional_role
            );
            EXECUTE pg_catalog.format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
                'REVOKE ALL PRIVILEGES ON FUNCTIONS FROM %I',
                optional_role
            );
        END IF;
    END LOOP;
END
$migration$;
"""
    )


def _assert_cutover_catalogue() -> None:
    application_tables = _sql_text_array(APPLICATION_TABLES)
    deny_tables = _sql_text_array(NO_DIRECT_RUNTIME_TABLES)
    helper_names = _sql_text_array(
        tuple(signature.split("(", maxsplit=1)[0] for signature in POLICY_HELPER_SIGNATURES)
    )
    expected_policy_count = len(POLICIES)
    _execute(
        f"""
DO $migration$
DECLARE
    expected_tables text[] := {application_tables};
    deny_tables text[] := {deny_tables};
    helper_names text[] := {helper_names};
    table_name text;
    actual_policy_count integer;
    unsafe_helper text;
BEGIN
    FOREACH table_name IN ARRAY expected_tables
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname = table_name
              AND relation.relkind IN ('r', 'p')
              AND relation.relrowsecurity
              AND NOT relation.relforcerowsecurity
        ) THEN
            RAISE EXCEPTION
                'RLS cutover assertion failed for table %',
                table_name
                USING ERRCODE = '42501';
        END IF;
    END LOOP;

    SELECT pg_catalog.count(*)
    INTO actual_policy_count
    FROM pg_catalog.pg_policy AS policy
    JOIN pg_catalog.pg_class AS relation
      ON relation.oid = policy.polrelid
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relname = ANY(expected_tables);

    IF actual_policy_count <> {expected_policy_count} THEN
        RAISE EXCEPTION
            'Expected {expected_policy_count} H-E policies, found %',
            actual_policy_count
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policy AS policy
        JOIN pg_catalog.pg_class AS relation
          ON relation.oid = policy.polrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = ANY(expected_tables)
          AND policy.polroles
              <> ARRAY[
                  (
                      SELECT role.oid
                      FROM pg_catalog.pg_roles AS role
                      WHERE role.rolname = 'mata_app_runtime'
                  )
              ]::oid[]
    ) THEN
        RAISE EXCEPTION
            'An H-E table policy targets a role other than mata_app_runtime'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace AS public_schema
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                public_schema.nspacl,
                pg_catalog.acldefault('n', public_schema.nspowner)
            )
        ) AS privilege
        WHERE public_schema.nspname = 'public'
          AND privilege.grantee = 0
          AND privilege.privilege_type = 'CREATE'
    ) THEN
        RAISE EXCEPTION
            'PUBLIC retains CREATE on schema public'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS restricted_role
        WHERE restricted_role.rolname IN (
            'mata_app_runtime',
            'mata_auth_internal',
            'anon',
            'authenticated',
            'service_role'
        )
          AND pg_catalog.has_schema_privilege(
              restricted_role.oid,
              'public',
              'CREATE'
          )
    ) THEN
        RAISE EXCEPTION
            'An application or browser/service role retains CREATE on schema public'
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
                pg_catalog.acldefault('r', relation.relowner)
            )
        ) AS privilege
        JOIN pg_catalog.pg_roles AS grantee_role
          ON grantee_role.oid = privilege.grantee
        WHERE namespace.nspname = 'public'
          AND relation.relname = ANY(deny_tables)
          AND grantee_role.rolname = 'mata_app_runtime'
    ) THEN
        RAISE EXCEPTION
            'A helper-only table has a direct runtime privilege'
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
                pg_catalog.acldefault('r', relation.relowner)
            )
        ) AS privilege
        JOIN pg_catalog.pg_roles AS grantee_role
          ON grantee_role.oid = privilege.grantee
        WHERE namespace.nspname = 'public'
          AND (
              relation.relname = 'alembic_version'
              OR relation.relname = ANY(expected_tables)
          )
          AND grantee_role.rolname = 'mata_auth_internal'
    ) THEN
        RAISE EXCEPTION
            'The auth helper role has a direct application-table privilege'
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
                pg_catalog.acldefault('r', relation.relowner)
            )
        ) AS privilege
        JOIN pg_catalog.pg_roles AS grantee_role
          ON grantee_role.oid = privilege.grantee
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'alembic_version'
          AND grantee_role.rolname = 'mata_app_runtime'
    ) THEN
        RAISE EXCEPTION
            'The runtime role must not access alembic_version'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS optional_role
        JOIN pg_catalog.pg_class AS relation
          ON true
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE optional_role.rolname IN (
            'anon',
            'authenticated',
            'service_role'
        )
          AND namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
          AND (
              (
                  relation.relkind <> 'S'
                  AND (
                      pg_catalog.has_table_privilege(
                          optional_role.oid,
                          relation.oid,
                          'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
                      )
                      OR pg_catalog.has_any_column_privilege(
                          optional_role.oid,
                          relation.oid,
                          'SELECT,INSERT,UPDATE,REFERENCES'
                      )
                  )
              )
              OR (
                  relation.relkind = 'S'
                  AND pg_catalog.has_sequence_privilege(
                      optional_role.oid,
                      relation.oid,
                      'USAGE,SELECT,UPDATE'
                  )
              )
          )
    ) THEN
        RAISE EXCEPTION
            'A browser/service role retains public relation access'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS optional_role
        JOIN pg_catalog.pg_proc AS procedure
          ON true
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        WHERE optional_role.rolname IN (
            'anon',
            'authenticated',
            'service_role'
        )
          AND namespace.nspname IN ('mata_rls', 'mata_private')
          AND pg_catalog.has_function_privilege(
              optional_role.oid,
              procedure.oid,
              'EXECUTE'
          )
    ) THEN
        RAISE EXCEPTION
            'A browser/service role retains H-E helper access'
            USING ERRCODE = '42501';
    END IF;

    SELECT pg_catalog.format(
        '%I.%I(%s)',
        namespace.nspname,
        procedure.proname,
        pg_catalog.pg_get_function_identity_arguments(procedure.oid)
    )
    INTO unsafe_helper
    FROM pg_catalog.pg_proc AS procedure
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = procedure.pronamespace
    JOIN pg_catalog.pg_roles AS owner_role
      ON owner_role.oid = procedure.proowner
    WHERE namespace.nspname = 'mata_rls'
      AND procedure.proname = ANY(helper_names)
      AND (
          NOT procedure.prosecdef
          OR owner_role.rolname IN (
              'mata_app_runtime',
              'mata_auth_internal'
          )
          OR NOT (
              COALESCE(procedure.proconfig, ARRAY[]::text[])
              @> ARRAY['search_path=pg_catalog, pg_temp']
          )
      )
    ORDER BY procedure.proname
    LIMIT 1;
    IF unsafe_helper IS NOT NULL THEN
        RAISE EXCEPTION 'Unsafe policy helper definition: %', unsafe_helper
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
        WHERE namespace.nspname = 'mata_rls'
          AND procedure.proname = ANY(helper_names)
          AND privilege.grantee = 0
          AND privilege.privilege_type = 'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'PUBLIC execute remains on a policy helper'
            USING ERRCODE = '42501';
    END IF;
END
$migration$;
"""
    )


def upgrade() -> None:
    # The approved Supabase baseline already protects users with
    # deny-by-default RLS.  Normalize clean databases to that same state
    # transactionally before enforcing the exact reviewed inventory.
    _execute(
        "ALTER TABLE IF EXISTS public.users ENABLE ROW LEVEL SECURITY"
    )
    _assert_foundation_catalogue()
    _create_relationship_predicates()
    _enable_rls_and_create_policies()
    _apply_object_privileges()
    _assert_cutover_catalogue()


def downgrade() -> None:
    # Remove only this revision's policies and application grants. Browser,
    # PUBLIC-schema, and default-ACL hardening are intentionally never undone.
    for table_name, policy_name, _action, _using, _check in reversed(POLICIES):
        _execute(
            f'DROP POLICY IF EXISTS "{policy_name}" '
            f'ON public."{table_name}"'
        )

    _execute(
        "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public "
        f"FROM {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public "
        f"FROM {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(f"REVOKE USAGE ON SCHEMA public FROM {RUNTIME_ROLE}")
    _execute(
        f"REVOKE EXECUTE ON FUNCTION public.gen_random_uuid() "
        f"FROM {RUNTIME_ROLE}"
    )

    for signature in reversed(POLICY_HELPER_SIGNATURES):
        _execute(
            f"REVOKE ALL PRIVILEGES ON FUNCTION mata_rls.{signature} "
            f"FROM {RUNTIME_ROLE}, {AUTH_ROLE}"
        )
        _execute(f"DROP FUNCTION IF EXISTS mata_rls.{signature}")

    for table_name in NEW_RLS_TABLES:
        _execute(
            f'ALTER TABLE public."{table_name}" DISABLE ROW LEVEL SECURITY'
        )
