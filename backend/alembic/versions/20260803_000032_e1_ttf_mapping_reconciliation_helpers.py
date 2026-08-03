"""add narrowly scoped E1 TTF mapping reconciliation helper

Revision ID: 20260803_000032
Revises: 20260803_000031
Create Date: 2026-08-03

TTF target reconciliation may be initiated by a Master Admin, but the normal
mapping policies deliberately do not grant a Master ordinary mapping DML.  This
helper is the sole narrow exception: it can only clear links for verified stale
targets in one TTF scope and create pending rows for verified new target scopes.
"""

from __future__ import annotations

from alembic import op


revision = "20260803_000032"
down_revision = "20260803_000031"
branch_labels = None
depends_on = None


RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"
_OPTIONAL_BROWSER_ROLES = ("anon", "authenticated", "service_role")
_FUNCTION_SIGNATURE = (
    "mata_rls.reconcile_ttf_teaching_name_mappings("
    "uuid,text,uuid[],text[],text[])"
)


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
    FOREACH optional_role IN ARRAY ARRAY[{optional_roles}]::text[]
    LOOP
        IF pg_catalog.to_regrole(optional_role) IS NOT NULL THEN
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON FUNCTION {function_signature} FROM %I',
                optional_role
            );
        END IF;
    END LOOP;
END
$migration$
"""
    )


def _create_ttf_mapping_reconciliation_helper() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.reconcile_ttf_teaching_name_mappings(
    p_reporting_period_id uuid,
    p_programme_code text,
    p_stale_target_ids uuid[],
    p_introduced_posting_codes text[],
    p_introduced_r_years text[]
)
RETURNS TABLE(
    mappings_invalidated integer,
    pending_mappings_created integer
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    normalized_programme text := pg_catalog.upper(
        pg_catalog.btrim(p_programme_code)
    );
    actor_id uuid;
    stale_count integer;
    distinct_stale_count integer;
    introduced_count integer;
    distinct_introduced_count integer;
BEGIN
    IF NOT mata_rls.context_is_valid()
       OR NOT (
           mata_rls.is_master_admin()
           OR mata_rls.has_programme_scope(normalized_programme)
       )
    THEN
        RAISE EXCEPTION 'TTF programme scope required'
            USING ERRCODE = '42501';
    END IF;

    actor_id := mata_rls.current_subject_id();
    IF actor_id IS NULL THEN
        RAISE EXCEPTION 'Verified staff context required'
            USING ERRCODE = '42501';
    END IF;

    IF p_reporting_period_id IS NULL
       OR p_programme_code IS NULL
       OR normalized_programme = ''
       OR pg_catalog.length(normalized_programme) > 20
       OR p_stale_target_ids IS NULL
       OR p_introduced_posting_codes IS NULL
       OR p_introduced_r_years IS NULL
       OR pg_catalog.cardinality(p_stale_target_ids) > 10000
       OR pg_catalog.cardinality(p_introduced_posting_codes) > 10000
       OR pg_catalog.cardinality(p_introduced_posting_codes)
            <> pg_catalog.cardinality(p_introduced_r_years)
    THEN
        RAISE EXCEPTION 'Invalid TTF mapping reconciliation input'
            USING ERRCODE = '22023';
    END IF;

    SELECT
        pg_catalog.count(*),
        pg_catalog.count(DISTINCT stale_target.target_id)
    INTO stale_count, distinct_stale_count
    FROM pg_catalog.unnest(p_stale_target_ids) AS stale_target(target_id);

    IF stale_count <> distinct_stale_count
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.unnest(p_stale_target_ids) AS stale_target(target_id)
           WHERE stale_target.target_id IS NULL
       )
    THEN
        RAISE EXCEPTION 'Invalid stale TTF target identifiers'
            USING ERRCODE = '22023';
    END IF;

    SELECT pg_catalog.count(*)
    INTO introduced_count
    FROM pg_catalog.unnest(p_introduced_posting_codes) WITH ORDINALITY
         AS introduced_posting(posting_code, ordinal_position)
    JOIN pg_catalog.unnest(p_introduced_r_years) WITH ORDINALITY
         AS introduced_r_year(r_year, ordinal_position)
      ON introduced_r_year.ordinal_position
         = introduced_posting.ordinal_position;

    SELECT pg_catalog.count(*)
    INTO distinct_introduced_count
    FROM (
        SELECT DISTINCT
            introduced_posting.posting_code,
            introduced_r_year.r_year
        FROM pg_catalog.unnest(p_introduced_posting_codes) WITH ORDINALITY
             AS introduced_posting(posting_code, ordinal_position)
        JOIN pg_catalog.unnest(p_introduced_r_years) WITH ORDINALITY
             AS introduced_r_year(r_year, ordinal_position)
          ON introduced_r_year.ordinal_position
             = introduced_posting.ordinal_position
    ) AS distinct_scope;

    IF introduced_count <> distinct_introduced_count
       OR EXISTS (
           SELECT 1
            FROM pg_catalog.unnest(p_introduced_posting_codes) WITH ORDINALITY
                 AS introduced_posting(posting_code, ordinal_position)
            JOIN pg_catalog.unnest(p_introduced_r_years) WITH ORDINALITY
                 AS introduced_r_year(r_year, ordinal_position)
              ON introduced_r_year.ordinal_position
                 = introduced_posting.ordinal_position
            WHERE introduced_posting.posting_code IS NULL
               OR introduced_r_year.r_year IS NULL
               OR introduced_posting.posting_code <> pg_catalog.btrim(
                   introduced_posting.posting_code
               )
               OR introduced_r_year.r_year <> pg_catalog.btrim(
                   introduced_r_year.r_year
               )
               OR introduced_posting.posting_code = ''
               OR introduced_r_year.r_year = ''
               OR pg_catalog.length(introduced_posting.posting_code) > 50
               OR pg_catalog.length(introduced_r_year.r_year) > 10
       )
    THEN
        RAISE EXCEPTION 'Invalid introduced TTF target scope'
            USING ERRCODE = '22023';
    END IF;

    IF stale_count <> (
        SELECT pg_catalog.count(*)
        FROM public.teaching_targets AS target
        WHERE target.id = ANY(p_stale_target_ids)
          AND target.reporting_period_id = p_reporting_period_id
          AND target.programme_code = normalized_programme
    ) THEN
        RAISE EXCEPTION 'Stale TTF targets must belong to the requested scope'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.unnest(p_introduced_posting_codes) WITH ORDINALITY
             AS introduced_posting(posting_code, ordinal_position)
        JOIN pg_catalog.unnest(p_introduced_r_years) WITH ORDINALITY
             AS introduced_r_year(r_year, ordinal_position)
          ON introduced_r_year.ordinal_position
             = introduced_posting.ordinal_position
        WHERE NOT EXISTS (
            SELECT 1
            FROM public.teaching_targets AS target
            WHERE target.reporting_period_id = p_reporting_period_id
              AND target.programme_code = normalized_programme
              AND target.posting_code = introduced_posting.posting_code
              AND target.r_year = introduced_r_year.r_year
        )
    ) THEN
        RAISE EXCEPTION 'Introduced TTF scopes must exist in the requested scope'
            USING ERRCODE = '22023';
    END IF;

    mappings_invalidated := 0;
    pending_mappings_created := 0;

    UPDATE public.teaching_name_mappings AS mapping
    SET
        teaching_target_id = NULL,
        revision = mapping.revision + 1,
        updated_at = pg_catalog.clock_timestamp(),
        updated_by_user_id = actor_id
    WHERE mapping.reporting_period_id = p_reporting_period_id
      AND mapping.programme_code = normalized_programme
      AND mapping.teaching_target_id = ANY(p_stale_target_ids);
    GET DIAGNOSTICS mappings_invalidated = ROW_COUNT;

    INSERT INTO public.teaching_name_mappings (
        teaching_name_id,
        reporting_period_id,
        programme_code,
        posting_code,
        r_year,
        teaching_target_id,
        created_by_user_id,
        updated_by_user_id
    )
    SELECT
        teaching_name.id,
        teaching_name.reporting_period_id,
        teaching_name.programme_code,
        introduced_posting.posting_code,
        introduced_r_year.r_year,
        NULL,
        actor_id,
        actor_id
    FROM public.teaching_names AS teaching_name
    CROSS JOIN pg_catalog.unnest(p_introduced_posting_codes) WITH ORDINALITY
         AS introduced_posting(posting_code, ordinal_position)
    JOIN pg_catalog.unnest(p_introduced_r_years) WITH ORDINALITY
         AS introduced_r_year(r_year, ordinal_position)
      ON introduced_r_year.ordinal_position
         = introduced_posting.ordinal_position
    WHERE teaching_name.reporting_period_id = p_reporting_period_id
      AND teaching_name.programme_code = normalized_programme
      AND teaching_name.is_active
    ON CONFLICT (teaching_name_id, posting_code, r_year) DO NOTHING;
    GET DIAGNOSTICS pending_mappings_created = ROW_COUNT;

    RETURN NEXT;
END
$function$
"""
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON FUNCTION "
        f"{_FUNCTION_SIGNATURE} FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        "GRANT EXECUTE ON FUNCTION "
        f"{_FUNCTION_SIGNATURE} TO {RUNTIME_ROLE}"
    )
    _revoke_optional_function_privileges(_FUNCTION_SIGNATURE)


def _assert_e1_helper_security() -> None:
    _execute(
        f"""
DO $migration$
DECLARE
    helper_oid regprocedure := pg_catalog.to_regprocedure(
        '{_FUNCTION_SIGNATURE}'
    );
BEGIN
    IF helper_oid IS NULL
       OR NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = procedure.pronamespace
           WHERE procedure.oid = helper_oid
             AND namespace.nspname = 'mata_rls'
             AND procedure.proowner = pg_catalog.to_regrole(CURRENT_USER)
             AND procedure.prosecdef
             AND procedure.proconfig = ARRAY[
                 'search_path=pg_catalog, pg_temp'
             ]::text[]
             AND pg_catalog.pg_get_function_result(procedure.oid)
                 = 'TABLE(mappings_invalidated integer, pending_mappings_created integer)'
       )
    THEN
        RAISE EXCEPTION 'E1 TTF mapping reconciliation helper security assertion failed'
            USING ERRCODE = '42501';
    END IF;

    IF NOT pg_catalog.has_function_privilege(
               '{RUNTIME_ROLE}', helper_oid, 'EXECUTE'
           )
       OR pg_catalog.has_function_privilege(
               '{AUTH_ROLE}', helper_oid, 'EXECUTE'
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
           WHERE procedure.oid = helper_oid
             AND privilege.grantee = 0
             AND privilege.privilege_type = 'EXECUTE'
       )
    THEN
        RAISE EXCEPTION 'E1 TTF mapping reconciliation helper ACL assertion failed'
            USING ERRCODE = '42501';
    END IF;
END
$migration$
"""
    )


def upgrade() -> None:
    _create_ttf_mapping_reconciliation_helper()
    _assert_e1_helper_security()


def downgrade() -> None:
    _execute(f"DROP FUNCTION IF EXISTS {_FUNCTION_SIGNATURE}")
