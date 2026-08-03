"""add shared Teaching Name pool lifecycle support

Revision ID: 20260803_000031
Revises: 20260803_000030
Create Date: 2026-08-03

Phase C keeps Teaching Name mappings as configuration-only rows.  A narrowly
scoped owner trigger creates pending mappings for the distinct TTF
posting/R-year scopes when a name is created or reactivated.  Deleting a name
cascades only those configuration rows; the prior revision continues to clear
the optional event identity with ``SET NULL`` and preserves event snapshots and
attendance.
"""

from __future__ import annotations

from alembic import op


revision = "20260803_000031"
down_revision = "20260803_000030"
branch_labels = None
depends_on = None


RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"
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


def _replace_mapping_pool_fk(*, ondelete: str) -> None:
    op.drop_constraint(
        "fk_teaching_name_mappings_name_pool",
        "teaching_name_mappings",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_teaching_name_mappings_name_pool",
        "teaching_name_mappings",
        "teaching_names",
        ["teaching_name_id", "reporting_period_id", "programme_code"],
        ["id", "reporting_period_id", "programme_code"],
        ondelete=ondelete,
    )


def _replace_teaching_name_delete_policy(*, master_only: bool) -> None:
    _execute('DROP POLICY "mata_rls_teaching_names_delete" ON public.teaching_names')
    if master_only:
        predicate = "mata_rls.is_master_admin()"
    else:
        predicate = """
mata_rls.is_master_admin()
OR (
    NOT EXISTS (
        SELECT 1
        FROM public.teaching_events AS event
        WHERE event.teaching_name_id = teaching_names.id
    )
    AND (
        mata_rls.has_programme_scope(teaching_names.programme_code)
        OR EXISTS (
            SELECT 1
            FROM public.secretary_programme_pools AS pool
            WHERE pool.programme_code = teaching_names.programme_code
              AND pool.is_active
              AND pool.can_manage_teaching_names
              AND mata_rls.is_secretary_for_posting(pool.posting_code)
        )
    )
)
"""
    _execute(
        f"""
CREATE POLICY "mata_rls_teaching_names_delete"
ON public.teaching_names
AS PERMISSIVE
FOR DELETE
TO {RUNTIME_ROLE}
USING ({predicate})
"""
    )


def _create_pending_mapping_reconciliation_trigger() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_private.reconcile_teaching_name_pending_mappings()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    actor_id uuid;
BEGIN
    IF TG_OP = 'INSERT' AND NEW.is_active THEN
        actor_id := NEW.created_by_user_id;
    ELSIF TG_OP = 'UPDATE' AND NOT OLD.is_active AND NEW.is_active THEN
        actor_id := NEW.updated_by_user_id;
    ELSE
        RETURN NEW;
    END IF;

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
        NEW.id,
        NEW.reporting_period_id,
        NEW.programme_code,
        target_scope.posting_code,
        target_scope.r_year,
        NULL,
        actor_id,
        actor_id
    FROM (
        SELECT DISTINCT target.posting_code, target.r_year
        FROM public.teaching_targets AS target
        WHERE target.reporting_period_id = NEW.reporting_period_id
          AND target.programme_code = NEW.programme_code
    ) AS target_scope
    ON CONFLICT (teaching_name_id, posting_code, r_year) DO NOTHING;

    RETURN NEW;
END
$function$
"""
    )
    _execute(
        r"""
CREATE TRIGGER mata_reconcile_teaching_name_pending_mappings
AFTER INSERT OR UPDATE OF is_active
ON public.teaching_names
FOR EACH ROW
EXECUTE FUNCTION mata_private.reconcile_teaching_name_pending_mappings()
"""
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON FUNCTION "
        "mata_private.reconcile_teaching_name_pending_mappings() "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _revoke_optional_function_privileges(
        "mata_private.reconcile_teaching_name_pending_mappings()"
    )


def _create_used_name_delete_guard() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_private.guard_used_teaching_name_delete()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.teaching_events AS event
        WHERE event.teaching_name_id = OLD.id
    )
    AND NOT mata_rls.is_master_admin()
    AND SESSION_USER <> CURRENT_USER
    THEN
        RAISE EXCEPTION
            'Only a Master Admin may delete a Teaching Name referenced by teaching events'
            USING ERRCODE = '42501';
    END IF;
    RETURN OLD;
END
$function$
"""
    )
    _execute(
        r"""
CREATE TRIGGER mata_guard_used_teaching_name_delete
BEFORE DELETE
ON public.teaching_names
FOR EACH ROW
EXECUTE FUNCTION mata_private.guard_used_teaching_name_delete()
"""
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON FUNCTION "
        "mata_private.guard_used_teaching_name_delete() "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _revoke_optional_function_privileges(
        "mata_private.guard_used_teaching_name_delete()"
    )


def _create_master_delete_lock_helper() -> None:
    _execute(
        r"""
CREATE FUNCTION mata_rls.lock_master_teaching_name_delete(
    p_teaching_name_id uuid
)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF NOT mata_rls.is_master_admin() THEN
        RAISE EXCEPTION
            'Only a Master Admin may lock a Teaching Name for deletion'
            USING ERRCODE = '42501';
    END IF;

    PERFORM 1
    FROM public.teaching_names AS teaching_name
    WHERE teaching_name.id = p_teaching_name_id
    FOR UPDATE;
END
$function$
"""
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON FUNCTION "
        "mata_rls.lock_master_teaching_name_delete(uuid) "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        "GRANT EXECUTE ON FUNCTION "
        "mata_rls.lock_master_teaching_name_delete(uuid) "
        f"TO {RUNTIME_ROLE}"
    )
    _revoke_optional_function_privileges(
        "mata_rls.lock_master_teaching_name_delete(uuid)"
    )


def _assert_phase_c_catalogue() -> None:
    _execute(
        f"""
DO $migration$
DECLARE
    function_name text;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint AS constraint_row
        JOIN pg_catalog.pg_class AS relation
          ON relation.oid = constraint_row.conrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'teaching_name_mappings'
          AND constraint_row.conname = 'fk_teaching_name_mappings_name_pool'
          AND constraint_row.confdeltype = 'c'
    ) THEN
        RAISE EXCEPTION 'Teaching Name mapping pool FK must cascade on delete'
            USING ERRCODE = '23514';
    END IF;

    FOREACH function_name IN ARRAY ARRAY[
        'reconcile_teaching_name_pending_mappings',
        'guard_used_teaching_name_delete'
    ]::text[]
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS procedure
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            WHERE namespace.nspname = 'mata_private'
              AND procedure.proname = function_name
              AND procedure.proowner = pg_catalog.to_regrole(CURRENT_USER)
              AND procedure.prosecdef
              AND procedure.proconfig = ARRAY[
                  'search_path=pg_catalog, pg_temp'
              ]::text[]
        ) THEN
            RAISE EXCEPTION 'Phase C function security assertion failed for %', function_name
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
            WHERE namespace.nspname = 'mata_private'
              AND procedure.proname = function_name
              AND privilege.privilege_type = 'EXECUTE'
              AND privilege.grantee IN (
                  0,
                  pg_catalog.to_regrole('{RUNTIME_ROLE}')::oid,
                  pg_catalog.to_regrole('{AUTH_ROLE}')::oid
              )
        ) THEN
            RAISE EXCEPTION 'Phase C private function remains callable by an application role'
                USING ERRCODE = '42501';
        END IF;
    END LOOP;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        WHERE procedure.oid = pg_catalog.to_regprocedure(
                  'mata_rls.lock_master_teaching_name_delete(uuid)'
              )
          AND namespace.nspname = 'mata_rls'
          AND procedure.proowner = pg_catalog.to_regrole(CURRENT_USER)
          AND procedure.prosecdef
          AND procedure.proconfig = ARRAY[
              'search_path=pg_catalog, pg_temp'
          ]::text[]
          AND pg_catalog.pg_get_function_result(procedure.oid) = 'void'
    ) THEN
        RAISE EXCEPTION 'Phase C Master Teaching Name delete-lock helper assertion failed'
            USING ERRCODE = '42501';
    END IF;

    IF NOT pg_catalog.has_function_privilege(
               '{RUNTIME_ROLE}',
               pg_catalog.to_regprocedure(
                   'mata_rls.lock_master_teaching_name_delete(uuid)'
               ),
               'EXECUTE'
           )
       OR pg_catalog.has_function_privilege(
               '{AUTH_ROLE}',
               pg_catalog.to_regprocedure(
                   'mata_rls.lock_master_teaching_name_delete(uuid)'
               ),
               'EXECUTE'
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
            WHERE procedure.oid = pg_catalog.to_regprocedure(
                      'mata_rls.lock_master_teaching_name_delete(uuid)'
                  )
              AND privilege.grantee = 0
              AND privilege.privilege_type = 'EXECUTE'
       ) THEN
        RAISE EXCEPTION 'Phase C Master Teaching Name delete-lock helper ACL assertion failed'
            USING ERRCODE = '42501';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_trigger AS trigger_row
        JOIN pg_catalog.pg_class AS relation
          ON relation.oid = trigger_row.tgrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_proc AS procedure
          ON procedure.oid = trigger_row.tgfoid
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'teaching_names'
          AND trigger_row.tgname = 'mata_reconcile_teaching_name_pending_mappings'
          AND procedure.proname = 'reconcile_teaching_name_pending_mappings'
          AND NOT trigger_row.tgisinternal
    ) THEN
        RAISE EXCEPTION 'Phase C pending-mapping trigger assertion failed'
            USING ERRCODE = '42501';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_trigger AS trigger_row
        JOIN pg_catalog.pg_class AS relation
          ON relation.oid = trigger_row.tgrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_proc AS procedure
          ON procedure.oid = trigger_row.tgfoid
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'teaching_names'
          AND trigger_row.tgname = 'mata_guard_used_teaching_name_delete'
          AND procedure.proname = 'guard_used_teaching_name_delete'
          AND NOT trigger_row.tgisinternal
    ) THEN
        RAISE EXCEPTION 'Phase C used-name delete guard assertion failed'
            USING ERRCODE = '42501';
    END IF;
END
$migration$
"""
    )


def upgrade() -> None:
    _replace_mapping_pool_fk(ondelete="CASCADE")
    _replace_teaching_name_delete_policy(master_only=False)
    _create_pending_mapping_reconciliation_trigger()
    _create_used_name_delete_guard()
    _create_master_delete_lock_helper()
    _assert_phase_c_catalogue()


def downgrade() -> None:
    _execute(
        "DROP TRIGGER mata_guard_used_teaching_name_delete ON public.teaching_names"
    )
    _execute("DROP FUNCTION mata_private.guard_used_teaching_name_delete()")
    _execute(
        "DROP TRIGGER mata_reconcile_teaching_name_pending_mappings "
        "ON public.teaching_names"
    )
    _execute(
        "DROP FUNCTION mata_private.reconcile_teaching_name_pending_mappings()"
    )
    _execute("DROP FUNCTION IF EXISTS mata_rls.lock_master_teaching_name_delete(uuid)")
    _replace_teaching_name_delete_policy(master_only=True)
    _replace_mapping_pool_fk(ondelete="RESTRICT")
