"""complete the final A-J TTF database cutover

Revision ID: 20260805_000036
Revises: 20260804_000035
Create Date: 2026-08-05

The legacy A-K catalogue is intentionally retired as one atomic database
cutover.  D/F/G event source evidence is retained: this revision neither
rewrites events or attendance nor derives identities from catalogue text.

The downgrade is deliberately limited.  It restores an empty legacy catalogue
shape and nullable Column K storage only; deleted catalogue rows and former
Column K text cannot be reconstructed.  It is not an online production
rollback and it does not alter retained events, attendance, Teaching Names,
mappings, targets, warning history, or audit evidence.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260805_000036"
down_revision = "20260804_000035"
branch_labels = None
depends_on = None


RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"
OPTIONAL_BROWSER_ROLES = ("anon", "authenticated", "service_role")

CATALOGUE_TABLE = "teaching_name_catalogue"
CATALOGUE_ACCESS_SIGNATURE = "can_access_teaching_catalogue(text,text,uuid)"
LEGACY_EVENT_INSERT_SIGNATURE = "can_insert_teaching_event(text,text,text,date,boolean,text)"
LEGACY_SCHEDULED_INSERT_SIGNATURE = (
    "can_insert_scheduled_event_source(text,text,uuid,uuid,date,boolean,text)"
)
REPORTING_PERIOD_DEPENDENCY_SIGNATURE = "reporting_period_dependency_counts(uuid)"

_CATALOGUE_POLICY_NAMES = (
    "mata_rls_teaching_name_catalogue_delete",
    "mata_rls_teaching_name_catalogue_insert",
    "mata_rls_teaching_name_catalogue_select",
)
_PRIVATE_LEGACY_HELPERS = (
    "can_select_teaching_event_000027(uuid)",
    "can_insert_teaching_event_000027(text,text,text,date,boolean,text)",
    "can_submit_native_attendance_000027(uuid,uuid)",
    "can_submit_external_attendance_000027(uuid,uuid)",
)

# This is the full current application inventory after the catalogue is
# retired.  Keeping it explicit makes the migration's postcondition independent
# from application-source import timing and catches a partial RLS cutover.
_APPLICATION_TABLES = (
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
    "teaching_name_mappings",
    "teaching_names",
    "teaching_targets",
    "upload_logs",
    "upload_warnings",
    "users",
    "warning_issues",
    "weekend_exceptions",
)
_EXPECTED_APPLICATION_TABLE_COUNT = 35
_EXPECTED_RUNTIME_POLICY_COUNT = 89


def _execute(statement: str) -> None:
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(statement)


def _sql_text_array(values: tuple[str, ...]) -> str:
    return "ARRAY[" + ", ".join(repr(value) for value in values) + "]::text[]"


def _revoke_optional_table_privileges() -> None:
    optional_roles = ", ".join(repr(role) for role in OPTIONAL_BROWSER_ROLES)
    _execute(
        f"""
DO $cutover$
DECLARE
    optional_role text;
BEGIN
    FOREACH optional_role IN ARRAY ARRAY[{optional_roles}]::text[]
    LOOP
        IF pg_catalog.to_regrole(optional_role) IS NOT NULL THEN
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON TABLE public.{CATALOGUE_TABLE} FROM %I',
                optional_role
            );
        END IF;
    END LOOP;
END
$cutover$
"""
    )


def _revoke_optional_function_privileges(function_signature: str) -> None:
    optional_roles = ", ".join(repr(role) for role in OPTIONAL_BROWSER_ROLES)
    _execute(
        f"""
DO $cutover$
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
$cutover$
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


def _assert_upgrade_preflight() -> None:
    expected_policies = _sql_text_array(_CATALOGUE_POLICY_NAMES)
    _execute(
        f"""
DO $cutover$
DECLARE
    catalogue_relation regclass := pg_catalog.to_regclass(
        'public.{CATALOGUE_TABLE}'
    );
    target_relation regclass := pg_catalog.to_regclass('public.teaching_targets');
    details_attnum smallint;
    actual_policy_names text[];
BEGIN
    IF catalogue_relation IS NULL OR target_relation IS NULL THEN
        RAISE EXCEPTION 'Final A-J cutover requires legacy catalogue and targets tables'
            USING ERRCODE = '42P01';
    END IF;

    SELECT attribute.attnum
    INTO details_attnum
    FROM pg_catalog.pg_attribute AS attribute
    WHERE attribute.attrelid = target_relation
      AND attribute.attname = 'details_of_training'
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped;
    IF details_attnum IS NULL THEN
        RAISE EXCEPTION 'Final A-J cutover requires teaching_targets.details_of_training'
            USING ERRCODE = '42703';
    END IF;

    SELECT COALESCE(
        array_agg(policy.polname ORDER BY policy.polname),
        ARRAY[]::text[]
    )
    INTO actual_policy_names
    FROM pg_catalog.pg_policy AS policy
    WHERE policy.polrelid = catalogue_relation;
    IF actual_policy_names IS DISTINCT FROM {expected_policies} THEN
        RAISE EXCEPTION 'Unexpected teaching_name_catalogue RLS policy inventory'
            USING ERRCODE = '42501';
    END IF;

    IF pg_catalog.to_regprocedure(
        'mata_rls.{CATALOGUE_ACCESS_SIGNATURE}'
    ) IS NULL THEN
        RAISE EXCEPTION 'Legacy catalogue access helper is missing'
            USING ERRCODE = '42883';
    END IF;

    -- The catalogue owns outgoing FKs, but no retained relation may reference it.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint AS constraint_row
        WHERE constraint_row.contype = 'f'
          AND constraint_row.confrelid = catalogue_relation
          AND constraint_row.conrelid <> catalogue_relation
    ) THEN
        RAISE EXCEPTION 'Retained foreign key depends on teaching_name_catalogue'
            USING ERRCODE = '2BP01';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_depend AS dependency
        JOIN pg_catalog.pg_class AS sequence_relation
          ON sequence_relation.oid = dependency.objid
        JOIN pg_catalog.pg_namespace AS sequence_namespace
          ON sequence_namespace.oid = sequence_relation.relnamespace
        WHERE dependency.refobjid = catalogue_relation
          AND sequence_relation.relkind = 'S'
          AND sequence_namespace.nspname = 'public'
    ) THEN
        RAISE EXCEPTION 'Unexpected catalogue-owned sequence requires explicit review'
            USING ERRCODE = '2BP01';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_rewrite AS rewrite_rule
        JOIN pg_catalog.pg_class AS view_relation
          ON view_relation.oid = rewrite_rule.ev_class
        JOIN pg_catalog.pg_namespace AS view_namespace
          ON view_namespace.oid = view_relation.relnamespace
        JOIN pg_catalog.pg_depend AS dependency
          ON dependency.classid = 'pg_rewrite'::regclass
         AND dependency.objid = rewrite_rule.oid
        WHERE dependency.refobjid = catalogue_relation
          AND view_namespace.nspname = 'public'
          AND view_relation.relkind IN ('v', 'm')
    ) THEN
        RAISE EXCEPTION 'View or materialized view depends on teaching_name_catalogue'
            USING ERRCODE = '2BP01';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint AS constraint_row
        WHERE (constraint_row.conrelid = target_relation
               AND details_attnum = ANY(constraint_row.conkey))
           OR (constraint_row.confrelid = target_relation
               AND details_attnum = ANY(constraint_row.confkey))
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_index AS index_row
        WHERE index_row.indrelid = target_relation
          AND details_attnum = ANY(index_row.indkey::smallint[])
    ) THEN
        RAISE EXCEPTION 'Constraint or index depends on teaching_targets.details_of_training'
            USING ERRCODE = '2BP01';
    END IF;

    -- pg_get_functiondef rejects aggregates.  Keep it inside CASE rather than
    -- relying on a separate prokind predicate that the planner may reorder.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname IN ('mata_rls', 'mata_private', 'public')
          AND CASE
              WHEN procedure.prokind IN ('f', 'p') THEN
                  pg_catalog.lower(pg_catalog.pg_get_functiondef(procedure.oid))
                      LIKE '%details_of_training%'
              ELSE false
          END
    ) THEN
        RAISE EXCEPTION 'Database helper still depends on details_of_training'
            USING ERRCODE = '2BP01';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policy AS policy
        WHERE pg_catalog.lower(COALESCE(
                  pg_catalog.pg_get_expr(policy.polqual, policy.polrelid), ''
              )) LIKE '%details_of_training%'
           OR pg_catalog.lower(COALESCE(
                  pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid), ''
              )) LIKE '%details_of_training%'
    ) THEN
        RAISE EXCEPTION 'Active RLS policy still depends on details_of_training'
            USING ERRCODE = '2BP01';
    END IF;

    -- All pool-backed events must already carry immutable deterministic source
    -- evidence, including events whose optional Teaching Name was deleted.
    IF EXISTS (
        SELECT 1
        FROM public.teaching_events AS event
        LEFT JOIN public.reporting_periods AS source_period
          ON source_period.id = event.source_reporting_period_id
        LEFT JOIN public.teaching_names AS teaching_name
          ON teaching_name.id = event.teaching_name_id
        WHERE (event.source_programme_code IS NULL)
              <> (event.source_reporting_period_id IS NULL)
           OR (
               (event.teaching_name_id IS NOT NULL
                OR event.source_programme_code IS NOT NULL)
               AND (
                   event.is_adhoc
                   OR event.global_session_type_id IS NOT NULL
                   OR event.source_programme_code IS NULL
                   OR event.source_reporting_period_id IS NULL
                   OR source_period.id IS NULL
                   OR event.event_date NOT BETWEEN source_period.start_date
                                           AND source_period.end_date
                   OR (
                       event.created_for_programme_code IS NOT NULL
                       AND event.created_for_programme_code
                           <> event.source_programme_code
                   )
                   OR (
                       event.teaching_name_id IS NOT NULL
                       AND (
                           teaching_name.id IS NULL
                           OR teaching_name.programme_code
                               <> event.source_programme_code
                           OR teaching_name.reporting_period_id
                               <> event.source_reporting_period_id
                       )
                   )
               )
           )
    ) THEN
        RAISE EXCEPTION 'Teaching-event pool source provenance is incomplete or contradictory'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.teaching_targets AS target
        LEFT JOIN public.reporting_periods AS period
          ON period.id = target.reporting_period_id
        LEFT JOIN public.programmes AS programme
          ON programme.code = target.programme_code
        LEFT JOIN public.posting_codes AS posting
          ON posting.code = target.posting_code
        LEFT JOIN public.session_types AS session_type
          ON session_type.id = target.session_type_id
        WHERE period.id IS NULL
           OR programme.code IS NULL
           OR posting.code IS NULL
           OR session_type.id IS NULL
           OR pg_catalog.btrim(target.r_year) = ''
           OR target.monthly_target < 0
    ) THEN
        RAISE EXCEPTION 'Teaching target scope preflight failed'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.teaching_name_mappings AS mapping
        LEFT JOIN public.teaching_names AS teaching_name
          ON teaching_name.id = mapping.teaching_name_id
        LEFT JOIN public.posting_codes AS posting
          ON posting.code = mapping.posting_code
        LEFT JOIN public.teaching_targets AS target
          ON target.id = mapping.teaching_target_id
        WHERE teaching_name.id IS NULL
           OR posting.code IS NULL
           OR teaching_name.reporting_period_id <> mapping.reporting_period_id
           OR teaching_name.programme_code <> mapping.programme_code
           OR pg_catalog.btrim(mapping.r_year) = ''
           OR (
               mapping.teaching_target_id IS NOT NULL
               AND (
                   target.id IS NULL
                   OR target.reporting_period_id <> mapping.reporting_period_id
                   OR target.programme_code <> mapping.programme_code
                   OR target.posting_code <> mapping.posting_code
                   OR target.r_year <> mapping.r_year
               )
           )
    ) THEN
        RAISE EXCEPTION 'Teaching Name mapping scope preflight failed'
            USING ERRCODE = '23514';
    END IF;

    IF (
        SELECT count(*)
        FROM public.programmes
        WHERE code IN ('SPORTSMED', 'PALLMED')
    ) <> 2 OR EXISTS (
        SELECT 1
        FROM public.programmes
        WHERE code IN ('SPORTSMED', 'PALLMED')
          AND (r_year_required OR NOT is_subspecialty)
    ) THEN
        RAISE EXCEPTION
            'SPORTSMED/PALLMED programme configuration is not at the expected pre-cutover state'
            USING ERRCODE = '23514';
    END IF;
END
$cutover$
"""
    )


def _replace_reporting_period_dependency_helper(*, include_catalogue: bool) -> None:
    catalogue_branch = ""
    if include_catalogue:
        catalogue_branch = """
    UNION ALL
    SELECT 'teaching_name_catalogue', pg_catalog.count(*)
    FROM public.teaching_name_catalogue
    WHERE reporting_period_id = p_reporting_period_id
"""
    _execute(
        f"""
CREATE OR REPLACE FUNCTION mata_rls.reporting_period_dependency_counts(
    p_reporting_period_id uuid
)
RETURNS TABLE (
    dependency_name text,
    dependency_count bigint
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF NOT mata_rls.is_master_admin() THEN
        RAISE EXCEPTION 'Master Admin context required'
            USING ERRCODE = '42501';
    END IF;
    IF p_reporting_period_id IS NULL THEN
        RAISE EXCEPTION 'Reporting period is required'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT 'upload_logs'::text, pg_catalog.count(*)
    FROM public.upload_logs
    WHERE reporting_period_id = p_reporting_period_id
    UNION ALL
    SELECT 'resident_postings', pg_catalog.count(*)
    FROM public.resident_postings
    WHERE reporting_period_id = p_reporting_period_id
    UNION ALL
    SELECT 'teaching_targets', pg_catalog.count(*)
    FROM public.teaching_targets
    WHERE reporting_period_id = p_reporting_period_id
{catalogue_branch}    UNION ALL
    SELECT 'form_f1_records', pg_catalog.count(*)
    FROM public.form_f1_records
    WHERE reporting_period_id = p_reporting_period_id
    UNION ALL
    SELECT 'academic_month_boundaries', pg_catalog.count(*)
    FROM public.academic_month_boundaries AS boundary
    JOIN public.upload_logs AS upload_log
      ON upload_log.id = boundary.upload_id
    WHERE upload_log.reporting_period_id = p_reporting_period_id
    UNION ALL
    SELECT 'period_snapshots', pg_catalog.count(*)
    FROM public.period_snapshots
    WHERE reporting_period_id = p_reporting_period_id
    UNION ALL
    SELECT 'clawback_records', pg_catalog.count(*)
    FROM public.clawback_records
    WHERE reporting_period_id = p_reporting_period_id
    UNION ALL
    SELECT 'surplus_ledger', pg_catalog.count(*)
    FROM public.surplus_ledger
    WHERE reporting_period_id = p_reporting_period_id;
END
$function$
"""
    )
    _secure_runtime_helper(REPORTING_PERIOD_DEPENDENCY_SIGNATURE)


def _replace_legacy_direct_event_insert_helper() -> None:
    # Direct free-text event insertion is not a final A-J source path.  Scheduled
    # source rows use the explicit source helper, while ad-hoc records use the
    # atomic server-owned helper.  Keeping this policy signature fail-closed
    # removes its private legacy catalogue dependency without widening access.
    _execute(
        """
CREATE OR REPLACE FUNCTION mata_rls.can_insert_teaching_event(
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
    SELECT false
$function$
"""
    )
    _secure_runtime_helper(LEGACY_EVENT_INSERT_SIGNATURE)


def _retire_catalogue_policies_and_grants() -> None:
    for policy_name in _CATALOGUE_POLICY_NAMES:
        _execute(f'DROP POLICY "{policy_name}" ON public.{CATALOGUE_TABLE}')
    _execute(
        f"REVOKE ALL PRIVILEGES ON TABLE public.{CATALOGUE_TABLE} "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _revoke_optional_table_privileges()


def _retire_catalogue_helpers() -> None:
    # These are plain RESTRICT drops.  An unexpected policy or helper dependency
    # aborts the migration instead of silently cascading a security boundary.
    _execute(f"DROP FUNCTION mata_rls.{CATALOGUE_ACCESS_SIGNATURE}")
    _execute(f"DROP FUNCTION IF EXISTS mata_rls.{LEGACY_SCHEDULED_INSERT_SIGNATURE}")
    for function_signature in _PRIVATE_LEGACY_HELPERS:
        _execute(f"DROP FUNCTION IF EXISTS mata_private.{function_signature}")


def _assert_removal_preflight() -> None:
    _execute(
        f"""
DO $cutover$
DECLARE
    catalogue_relation regclass := 'public.{CATALOGUE_TABLE}'::regclass;
    target_relation regclass := 'public.teaching_targets'::regclass;
    details_attnum smallint;
    function_signature text;
BEGIN
    SELECT attribute.attnum
    INTO STRICT details_attnum
    FROM pg_catalog.pg_attribute AS attribute
    WHERE attribute.attrelid = target_relation
      AND attribute.attname = 'details_of_training'
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped;

    -- No active policy may remain on, or mention, the retired table/helper.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policy AS policy
        WHERE policy.polrelid = catalogue_relation
           OR pg_catalog.lower(COALESCE(
                  pg_catalog.pg_get_expr(policy.polqual, policy.polrelid), ''
              )) LIKE '%teaching_name_catalogue%'
           OR pg_catalog.lower(COALESCE(
                  pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid), ''
              )) LIKE '%teaching_name_catalogue%'
           OR pg_catalog.lower(COALESCE(
                  pg_catalog.pg_get_expr(policy.polqual, policy.polrelid), ''
              )) LIKE '%can_access_teaching_catalogue%'
           OR pg_catalog.lower(COALESCE(
                  pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid), ''
              )) LIKE '%can_access_teaching_catalogue%'
    ) THEN
        RAISE EXCEPTION 'Active RLS policy depends on retired catalogue state'
            USING ERRCODE = '2BP01';
    END IF;

    -- Runtime and private helper bodies are text-scanned as PostgreSQL does not
    -- record every PL/pgSQL body dependency in pg_depend.  pg_get_functiondef
    -- must remain inside CASE because the planner may reorder WHERE predicates.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname IN ('mata_rls', 'mata_private', 'public')
          AND CASE
              WHEN procedure.prokind IN ('f', 'p') THEN (
                  pg_catalog.lower(pg_catalog.pg_get_functiondef(procedure.oid))
                      LIKE '%teaching_name_catalogue%'
                  OR pg_catalog.lower(pg_catalog.pg_get_functiondef(procedure.oid))
                      LIKE '%details_of_training%'
              )
              ELSE false
          END
    ) THEN
        RAISE EXCEPTION 'Database helper still depends on retired TTF catalogue state'
            USING ERRCODE = '2BP01';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_trigger AS trigger_row
        JOIN pg_catalog.pg_proc AS procedure
          ON procedure.oid = trigger_row.tgfoid
        WHERE NOT trigger_row.tgisinternal
          AND (
              pg_catalog.lower(pg_catalog.pg_get_functiondef(procedure.oid))
                  LIKE '%teaching_name_catalogue%'
              OR pg_catalog.lower(pg_catalog.pg_get_functiondef(procedure.oid))
                  LIKE '%details_of_training%'
          )
    ) THEN
        RAISE EXCEPTION 'Trigger depends on retired TTF catalogue state'
            USING ERRCODE = '2BP01';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_rewrite AS rewrite_rule
        JOIN pg_catalog.pg_class AS view_relation
          ON view_relation.oid = rewrite_rule.ev_class
        JOIN pg_catalog.pg_namespace AS view_namespace
          ON view_namespace.oid = view_relation.relnamespace
        JOIN pg_catalog.pg_depend AS dependency
          ON dependency.classid = 'pg_rewrite'::regclass
         AND dependency.objid = rewrite_rule.oid
        WHERE view_namespace.nspname = 'public'
          AND view_relation.relkind IN ('v', 'm')
          AND (
              (dependency.refobjid = catalogue_relation
               AND dependency.refobjsubid = 0)
              OR (dependency.refobjid = target_relation
                  AND dependency.refobjsubid = details_attnum)
          )
    ) THEN
        RAISE EXCEPTION 'View or materialized view depends on retired TTF state'
            USING ERRCODE = '2BP01';
    END IF;

    FOREACH function_signature IN ARRAY ARRAY[
        'mata_rls.{CATALOGUE_ACCESS_SIGNATURE}',
        'mata_rls.{LEGACY_SCHEDULED_INSERT_SIGNATURE}'
    ]::text[]
    LOOP
        IF pg_catalog.to_regprocedure(function_signature) IS NOT NULL THEN
            RAISE EXCEPTION 'Retired catalogue helper remains: %', function_signature
                USING ERRCODE = '2BP01';
        END IF;
    END LOOP;
    FOREACH function_signature IN ARRAY ARRAY[
        {", ".join(repr(f"mata_private.{signature}") for signature in _PRIVATE_LEGACY_HELPERS)}
    ]::text[]
    LOOP
        IF pg_catalog.to_regprocedure(function_signature) IS NOT NULL THEN
            RAISE EXCEPTION 'Retired private legacy helper remains: %', function_signature
                USING ERRCODE = '2BP01';
        END IF;
    END LOOP;
END
$cutover$
"""
    )


def _drop_legacy_schema() -> None:
    # PostgreSQL defaults both statements to RESTRICT.  They intentionally do
    # not use CASCADE: the preflight above proves retained dependencies are gone.
    _execute("ALTER TABLE public.teaching_targets DROP COLUMN details_of_training")
    _execute(f"DROP TABLE public.{CATALOGUE_TABLE}")


def _correct_special_programme_configuration() -> None:
    _execute(
        """
DO $cutover$
DECLARE
    updated_count integer;
BEGIN
    UPDATE public.programmes
    SET
        r_year_required = true,
        is_subspecialty = false,
        updated_at = pg_catalog.clock_timestamp()
    WHERE code IN ('SPORTSMED', 'PALLMED');
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    IF updated_count <> 2 THEN
        RAISE EXCEPTION 'SPORTSMED/PALLMED programme configuration update was incomplete'
            USING ERRCODE = '23514';
    END IF;
END
$cutover$
"""
    )


def _assert_post_cutover() -> None:
    expected_tables = _sql_text_array(_APPLICATION_TABLES)
    _execute(
        f"""
DO $cutover$
DECLARE
    expected_tables text[] := {expected_tables};
    protected_table_count integer;
    policy_count integer;
BEGIN
    IF pg_catalog.cardinality(expected_tables) <> {_EXPECTED_APPLICATION_TABLE_COUNT}
       OR pg_catalog.to_regclass('public.{CATALOGUE_TABLE}') IS NOT NULL
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.pg_attribute AS attribute
           WHERE attribute.attrelid = 'public.teaching_targets'::regclass
             AND attribute.attname = 'details_of_training'
             AND attribute.attnum > 0
             AND NOT attribute.attisdropped
       )
    THEN
        RAISE EXCEPTION 'Final A-J physical schema assertion failed'
            USING ERRCODE = '23514';
    END IF;

    SELECT count(*)
    INTO protected_table_count
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN ('r', 'p')
      AND relation.relname = ANY(expected_tables)
      AND relation.relrowsecurity;
    IF protected_table_count <> {_EXPECTED_APPLICATION_TABLE_COUNT} THEN
        RAISE EXCEPTION 'Final A-J RLS application-table count is not exact'
            USING ERRCODE = '42501';
    END IF;

    SELECT count(*)
    INTO policy_count
    FROM pg_catalog.pg_policy AS policy
    JOIN pg_catalog.pg_class AS relation
      ON relation.oid = policy.polrelid
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relname = ANY(expected_tables);
    IF policy_count <> {_EXPECTED_RUNTIME_POLICY_COUNT} THEN
        RAISE EXCEPTION 'Final A-J RLS policy count is not exact'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.programmes
        WHERE code IN ('SPORTSMED', 'PALLMED')
          AND (NOT r_year_required OR is_subspecialty)
    ) THEN
        RAISE EXCEPTION 'SPORTSMED/PALLMED final R-year configuration assertion failed'
            USING ERRCODE = '23514';
    END IF;
END
$cutover$
"""
    )


def upgrade() -> None:
    _assert_upgrade_preflight()
    _replace_reporting_period_dependency_helper(include_catalogue=False)
    _replace_legacy_direct_event_insert_helper()
    _retire_catalogue_policies_and_grants()
    _retire_catalogue_helpers()
    _assert_removal_preflight()
    _drop_legacy_schema()
    _correct_special_programme_configuration()
    _assert_post_cutover()


def _restore_legacy_scheduled_insert_helper() -> None:
    """Restore the 000035 signature only so older revisions can downgrade.

    The final A-J runtime deliberately has no catalogue-backed scheduled-event
    helper.  Alembic revision 000035, however, recreates a historical policy
    using this exact seven-argument signature when it is downgraded further.
    Reinstating the old helper here therefore preserves the migration graph
    without reintroducing it into the current head schema.
    """
    _execute(
        r"""
CREATE FUNCTION mata_rls.can_insert_scheduled_event_source(
    p_posting_code text,
    p_created_for_programme_code text,
    p_teaching_name_id uuid,
    p_global_session_type_id uuid,
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
DECLARE
    source_programme_code text;
BEGIN
    IF COALESCE(p_is_adhoc, false)
       OR (p_teaching_name_id IS NULL) = (p_global_session_type_id IS NULL)
    THEN
        RETURN false;
    END IF;

    IF p_teaching_name_id IS NOT NULL THEN
        SELECT teaching_name.programme_code
        INTO source_programme_code
        FROM public.teaching_names AS teaching_name
        JOIN public.reporting_periods AS reporting_period
          ON reporting_period.id = teaching_name.reporting_period_id
        WHERE teaching_name.id = p_teaching_name_id
          AND teaching_name.is_active
          AND p_event_date BETWEEN reporting_period.start_date
                               AND reporting_period.end_date;

        IF NOT FOUND THEN
            RETURN false;
        END IF;

        IF mata_rls.is_master_admin() THEN
            RETURN true;
        END IF;

        IF mata_rls.current_subject_type() = 'staff'
           AND mata_rls.current_app_role() = 'admin'
           AND p_created_by_role = 'programme_pc'
           AND p_created_for_programme_code = source_programme_code
           AND mata_rls.has_programme_scope(source_programme_code)
        THEN
            RETURN true;
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
                 AND pool.programme_code = source_programme_code
                 AND pool.is_active
                 AND pool.can_manage_teaching_names
           );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.global_session_types AS global_type
        WHERE global_type.id = p_global_session_type_id
          AND global_type.is_active
    ) THEN
        RETURN false;
    END IF;

    IF mata_rls.is_master_admin() THEN
        RETURN true;
    END IF;

    IF mata_rls.current_subject_type() = 'staff'
       AND mata_rls.current_app_role() = 'admin'
       AND p_created_by_role = 'programme_pc'
       AND p_created_for_programme_code IS NOT NULL
       AND mata_rls.has_programme_scope(p_created_for_programme_code)
       AND (
           EXISTS (
               SELECT 1
               FROM public.secretary_programme_pools AS pool
               WHERE pool.programme_code = pg_catalog.upper(
                   pg_catalog.btrim(p_created_for_programme_code)
               )
                 AND pool.posting_code = p_posting_code
                 AND pool.is_active
           )
           OR EXISTS (
               SELECT 1
               FROM public.teaching_name_catalogue AS catalogue
               JOIN public.reporting_periods AS reporting_period
                 ON reporting_period.id = catalogue.reporting_period_id
               WHERE catalogue.programme_code = pg_catalog.upper(
                   pg_catalog.btrim(p_created_for_programme_code)
               )
                 AND catalogue.posting_code = p_posting_code
                 AND p_event_date BETWEEN reporting_period.start_date
                                      AND reporting_period.end_date
           )
       )
    THEN
        RETURN true;
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
    _secure_runtime_helper(LEGACY_SCHEDULED_INSERT_SIGNATURE)


def _restore_catalogue_access_helper() -> None:
    _execute(
        """
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
              AND COALESCE(external_posting.end_date, 'infinity'::date)
                  >= reporting_period.start_date
        )
$function$
"""
    )
    _secure_runtime_helper(CATALOGUE_ACCESS_SIGNATURE)


def _restore_empty_catalogue_schema() -> None:
    # No historical catalogue rows or Column K text can be recreated here.
    op.add_column(
        "teaching_targets",
        sa.Column("details_of_training", sa.Text(), nullable=True),
    )
    op.create_table(
        CATALOGUE_TABLE,
        sa.Column("keyword", sa.String(length=200), nullable=False),
        sa.Column(
            "session_type_id",
            sa.Uuid(),
            sa.ForeignKey("session_types.id"),
            nullable=False,
        ),
        sa.Column(
            "posting_code",
            sa.String(length=50),
            sa.ForeignKey("posting_codes.code"),
            nullable=False,
        ),
        sa.Column(
            "programme_code",
            sa.String(length=20),
            sa.ForeignKey("programmes.code"),
            nullable=False,
        ),
        sa.Column("r_year", sa.String(length=10), nullable=False),
        sa.Column(
            "reporting_period_id",
            sa.Uuid(),
            sa.ForeignKey("reporting_periods.id"),
            nullable=False,
        ),
        sa.Column("duration_hours", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column(
            "is_tracked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "keyword",
            "posting_code",
            "programme_code",
            "r_year",
            "reporting_period_id",
            name="uq_teaching_name_catalogue_resolution",
        ),
    )
    op.create_index(
        "idx_teaching_name_catalogue_resolution",
        CATALOGUE_TABLE,
        ["reporting_period_id", "programme_code", "posting_code", "r_year", "keyword"],
    )
    op.create_index(
        "idx_teaching_name_catalogue_session_type",
        CATALOGUE_TABLE,
        ["session_type_id"],
    )
    op.create_index(
        "idx_teaching_name_catalogue_tracked",
        CATALOGUE_TABLE,
        ["reporting_period_id", "programme_code", "posting_code", "r_year", "is_tracked"],
    )


def _restore_catalogue_rls_and_grants() -> None:
    _execute(f"ALTER TABLE public.{CATALOGUE_TABLE} ENABLE ROW LEVEL SECURITY")
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_name_catalogue_select"
ON public.{CATALOGUE_TABLE}
AS PERMISSIVE
FOR SELECT
TO {RUNTIME_ROLE}
USING (
    mata_rls.can_access_teaching_catalogue(
        programme_code,
        posting_code,
        reporting_period_id
    )
)
"""
    )
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_name_catalogue_insert"
ON public.{CATALOGUE_TABLE}
AS PERMISSIVE
FOR INSERT
TO {RUNTIME_ROLE}
WITH CHECK (
    mata_rls.is_master_admin()
    OR mata_rls.has_programme_scope(programme_code)
)
"""
    )
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_name_catalogue_delete"
ON public.{CATALOGUE_TABLE}
AS PERMISSIVE
FOR DELETE
TO {RUNTIME_ROLE}
USING (
    mata_rls.is_master_admin()
    OR mata_rls.has_programme_scope(programme_code)
)
"""
    )
    _execute(
        f"REVOKE ALL PRIVILEGES ON TABLE public.{CATALOGUE_TABLE} "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        f"GRANT SELECT, INSERT, DELETE ON TABLE public.{CATALOGUE_TABLE} "
        f"TO {RUNTIME_ROLE}"
    )
    _revoke_optional_table_privileges()


def _restore_private_downgrade_bridges() -> None:
    # These non-executable fail-closed signatures allow a further historical
    # Alembic downgrade to move its old private helpers back to mata_rls.  They
    # intentionally do not restore display-text or catalogue authorization.
    for function_signature in _PRIVATE_LEGACY_HELPERS:
        function_name, arguments = function_signature.split("(", maxsplit=1)
        _execute(
            f"""
CREATE FUNCTION mata_private.{function_name}({arguments}
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
    SELECT false
$function$
"""
        )
        _execute(
            f"REVOKE ALL PRIVILEGES ON FUNCTION mata_private.{function_signature} "
            f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
        )


def _restore_special_programme_configuration() -> None:
    _execute(
        """
DO $cutover$
DECLARE
    updated_count integer;
BEGIN
    IF (
        SELECT count(*)
        FROM public.programmes
        WHERE code IN ('SPORTSMED', 'PALLMED')
          AND r_year_required
          AND NOT is_subspecialty
    ) <> 2 THEN
        RAISE EXCEPTION
            'Cannot restore historical SPORTSMED/PALLMED configuration after drift'
            USING ERRCODE = '23514';
    END IF;

    UPDATE public.programmes
    SET
        r_year_required = false,
        is_subspecialty = true,
        updated_at = pg_catalog.clock_timestamp()
    WHERE code IN ('SPORTSMED', 'PALLMED');
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    IF updated_count <> 2 THEN
        RAISE EXCEPTION 'SPORTSMED/PALLMED historical configuration restore was incomplete'
            USING ERRCODE = '23514';
    END IF;
END
$cutover$
"""
    )


def downgrade() -> None:
    _restore_special_programme_configuration()
    _restore_empty_catalogue_schema()
    _restore_catalogue_access_helper()
    _restore_catalogue_rls_and_grants()
    _restore_legacy_scheduled_insert_helper()
    _replace_reporting_period_dependency_helper(include_catalogue=True)
    _restore_private_downgrade_bridges()
