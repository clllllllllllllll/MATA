"""add the additive evolved TTF teaching-name database foundation

Revision ID: 20260802_000029
Revises: 20260728_000028
Create Date: 2026-08-02

The legacy A-K TTF catalogue path remains authoritative through B1.  This
revision adds isolated future-state tables and security boundaries only; it
does not backfill, parse, or switch any current workflow.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260802_000029"
down_revision = "20260728_000028"
branch_labels = None
depends_on = None


RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"
PILOT_POSTING_CODE = "TTSHGerMed"
PILOT_PROGRAMME_CODE = "GERI"

_B1_TABLES = ("teaching_names", "teaching_name_mappings")
_B1_POLICIES = (
    (
        "teaching_names",
        "mata_rls_teaching_names_select",
        "SELECT",
        "mata_rls.is_master_admin() "
        "OR mata_rls.has_programme_scope(programme_code) "
        "OR EXISTS ("
        "SELECT 1 FROM public.secretary_programme_pools AS pool "
        "WHERE pool.programme_code = teaching_names.programme_code "
        "AND pool.is_active "
        "AND pool.can_manage_teaching_names "
        "AND mata_rls.is_secretary_for_posting(pool.posting_code)"
        ")",
        None,
    ),
    (
        "teaching_names",
        "mata_rls_teaching_names_insert",
        "INSERT",
        None,
        "mata_rls.has_programme_scope(programme_code) "
        "OR EXISTS ("
        "SELECT 1 FROM public.secretary_programme_pools AS pool "
        "WHERE pool.programme_code = teaching_names.programme_code "
        "AND pool.is_active "
        "AND pool.can_manage_teaching_names "
        "AND mata_rls.is_secretary_for_posting(pool.posting_code)"
        ")",
    ),
    (
        "teaching_names",
        "mata_rls_teaching_names_update",
        "UPDATE",
        "mata_rls.has_programme_scope(programme_code) "
        "OR EXISTS ("
        "SELECT 1 FROM public.secretary_programme_pools AS pool "
        "WHERE pool.programme_code = teaching_names.programme_code "
        "AND pool.is_active "
        "AND pool.can_manage_teaching_names "
        "AND mata_rls.is_secretary_for_posting(pool.posting_code)"
        ")",
        "mata_rls.has_programme_scope(programme_code) "
        "OR EXISTS ("
        "SELECT 1 FROM public.secretary_programme_pools AS pool "
        "WHERE pool.programme_code = teaching_names.programme_code "
        "AND pool.is_active "
        "AND pool.can_manage_teaching_names "
        "AND mata_rls.is_secretary_for_posting(pool.posting_code)"
        ")",
    ),
    (
        "teaching_names",
        "mata_rls_teaching_names_delete",
        "DELETE",
        "mata_rls.is_master_admin()",
        None,
    ),
    (
        "teaching_name_mappings",
        "mata_rls_teaching_name_mappings_select",
        "SELECT",
        "mata_rls.is_master_admin() "
        "OR mata_rls.has_programme_scope(programme_code)",
        None,
    ),
    (
        "teaching_name_mappings",
        "mata_rls_teaching_name_mappings_insert",
        "INSERT",
        None,
        "mata_rls.has_programme_scope(programme_code)",
    ),
    (
        "teaching_name_mappings",
        "mata_rls_teaching_name_mappings_update",
        "UPDATE",
        "mata_rls.has_programme_scope(programme_code)",
        "mata_rls.has_programme_scope(programme_code)",
    ),
    (
        "teaching_name_mappings",
        "mata_rls_teaching_name_mappings_delete",
        "DELETE",
        "mata_rls.has_programme_scope(programme_code)",
        None,
    ),
)


def _execute(statement: str) -> None:
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(statement)


def _add_schema() -> None:
    op.create_table(
        "teaching_names",
        sa.Column(
            "reporting_period_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("programme_code", sa.String(length=20), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "deactivated_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
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
        sa.ForeignKeyConstraint(
            ["reporting_period_id"],
            ["reporting_periods.id"],
            name="fk_teaching_names_reporting_period",
        ),
        sa.ForeignKeyConstraint(
            ["programme_code"],
            ["programmes.code"],
            name="fk_teaching_names_programme",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_teaching_names_created_by_user",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_teaching_names_updated_by_user",
        ),
        sa.ForeignKeyConstraint(
            ["deactivated_by_user_id"],
            ["users.id"],
            name="fk_teaching_names_deactivated_by_user",
        ),
        sa.UniqueConstraint(
            "reporting_period_id",
            "programme_code",
            "normalized_name",
            name="uq_teaching_names_pool_normalized_name",
        ),
        sa.UniqueConstraint(
            "id",
            "reporting_period_id",
            "programme_code",
            name="uq_teaching_names_id_pool",
        ),
        sa.CheckConstraint(
            "btrim(display_name) <> ''",
            name="ck_teaching_names_display_name_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(normalized_name) <> ''",
            name="ck_teaching_names_normalized_name_nonblank",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_teaching_names_revision_positive",
        ),
    )
    op.create_index(
        "idx_teaching_names_active_pool",
        "teaching_names",
        ["reporting_period_id", "programme_code", "display_name"],
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_index(
        "idx_teaching_names_normalized_lookup",
        "teaching_names",
        ["reporting_period_id", "programme_code", "normalized_name"],
    )

    # The existing legacy unique key remains authoritative.  This candidate key
    # adds the target id to its scope, which lets a mapping prove that its chosen
    # target belongs to that exact scope without forbidding multiple session
    # types in one retained A-K target scope.
    op.create_unique_constraint(
        "uq_teaching_targets_id_mapping_scope",
        "teaching_targets",
        [
            "id",
            "reporting_period_id",
            "programme_code",
            "posting_code",
            "r_year",
        ],
    )

    op.create_table(
        "teaching_name_mappings",
        sa.Column(
            "teaching_name_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "reporting_period_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("programme_code", sa.String(length=20), nullable=False),
        sa.Column("posting_code", sa.String(length=50), nullable=False),
        sa.Column("r_year", sa.String(length=10), nullable=False),
        sa.Column(
            "teaching_target_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
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
        sa.ForeignKeyConstraint(
            ["teaching_name_id", "reporting_period_id", "programme_code"],
            [
                "teaching_names.id",
                "teaching_names.reporting_period_id",
                "teaching_names.programme_code",
            ],
            name="fk_teaching_name_mappings_name_pool",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["posting_code"],
            ["posting_codes.code"],
            name="fk_teaching_name_mappings_posting",
        ),
        sa.ForeignKeyConstraint(
            [
                "teaching_target_id",
                "reporting_period_id",
                "programme_code",
                "posting_code",
                "r_year",
            ],
            [
                "teaching_targets.id",
                "teaching_targets.reporting_period_id",
                "teaching_targets.programme_code",
                "teaching_targets.posting_code",
                "teaching_targets.r_year",
            ],
            name="fk_teaching_name_mappings_target_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_teaching_name_mappings_created_by_user",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_teaching_name_mappings_updated_by_user",
        ),
        sa.UniqueConstraint(
            "teaching_name_id",
            "posting_code",
            "r_year",
            name="uq_teaching_name_mappings_identity",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_teaching_name_mappings_revision_positive",
        ),
    )
    op.create_index(
        "idx_teaching_name_mappings_pending_scope",
        "teaching_name_mappings",
        ["reporting_period_id", "programme_code", "posting_code", "r_year"],
        postgresql_where=sa.text("teaching_target_id IS NULL"),
    )
    op.create_index(
        "idx_teaching_name_mappings_mapped_scope",
        "teaching_name_mappings",
        [
            "reporting_period_id",
            "programme_code",
            "posting_code",
            "r_year",
            "teaching_target_id",
        ],
        postgresql_where=sa.text("teaching_target_id IS NOT NULL"),
    )
    op.create_index(
        "idx_teaching_name_mappings_target_reverse",
        "teaching_name_mappings",
        ["teaching_target_id"],
        postgresql_where=sa.text("teaching_target_id IS NOT NULL"),
    )
    op.create_index(
        "idx_teaching_name_mappings_name",
        "teaching_name_mappings",
        ["teaching_name_id"],
    )

    op.add_column(
        "teaching_events",
        sa.Column(
            "teaching_name_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "teaching_events",
        sa.Column(
            "global_session_type_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_teaching_events_teaching_name",
        "teaching_events",
        "teaching_names",
        ["teaching_name_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_teaching_events_global_session_type",
        "teaching_events",
        "global_session_types",
        ["global_session_type_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_teaching_events_source_identity_exclusive",
        "teaching_events",
        "NOT (teaching_name_id IS NOT NULL AND global_session_type_id IS NOT NULL)",
    )
    op.create_index(
        "idx_teaching_events_teaching_name",
        "teaching_events",
        ["teaching_name_id"],
        postgresql_where=sa.text("teaching_name_id IS NOT NULL"),
    )
    op.create_index(
        "idx_teaching_events_global_session_type",
        "teaching_events",
        ["global_session_type_id"],
        postgresql_where=sa.text("global_session_type_id IS NOT NULL"),
    )

    op.add_column(
        "secretary_programme_pools",
        sa.Column(
            "can_manage_teaching_names",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def _enable_exact_pilot_capability() -> None:
    _execute(
        f"""
DO $migration$
DECLARE
    exact_pilot_count integer;
    enabled_capability_count integer;
BEGIN
    SELECT count(*)
    INTO exact_pilot_count
    FROM public.secretary_programme_pools
    WHERE posting_code = '{PILOT_POSTING_CODE}'
      AND programme_code = '{PILOT_PROGRAMME_CODE}'
      AND is_active;

    IF exact_pilot_count <> 1 THEN
        RAISE EXCEPTION
            'Expected exactly one active approved Teaching Name pilot pool'
            USING ERRCODE = '23514';
    END IF;

    UPDATE public.secretary_programme_pools
    SET can_manage_teaching_names = true
    WHERE posting_code = '{PILOT_POSTING_CODE}'
      AND programme_code = '{PILOT_PROGRAMME_CODE}'
      AND is_active;

    SELECT count(*)
    INTO enabled_capability_count
    FROM public.secretary_programme_pools
    WHERE can_manage_teaching_names;

    IF enabled_capability_count <> 1
       OR NOT EXISTS (
            SELECT 1
            FROM public.secretary_programme_pools
            WHERE posting_code = '{PILOT_POSTING_CODE}'
              AND programme_code = '{PILOT_PROGRAMME_CODE}'
              AND is_active
              AND can_manage_teaching_names
       )
    THEN
        RAISE EXCEPTION
            'Teaching Name capability may be enabled only for the approved pilot'
            USING ERRCODE = '23514';
    END IF;
END
$migration$
"""
    )


def _create_scope_immutability_trigger() -> None:
    # A trigger is the narrowest database-owned way to make the pool identity
    # immutable before future mutation APIs exist.  It is not callable by any
    # application role.
    _execute(
        r"""
CREATE FUNCTION mata_private.enforce_teaching_name_scope_immutability()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF NEW.reporting_period_id IS DISTINCT FROM OLD.reporting_period_id
       OR NEW.programme_code IS DISTINCT FROM OLD.programme_code
    THEN
        RAISE EXCEPTION
            'Teaching Name reporting-period and programme scope are immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$
"""
    )
    _execute(
        r"""
CREATE TRIGGER mata_enforce_teaching_name_scope_immutability
BEFORE UPDATE OF reporting_period_id, programme_code
ON public.teaching_names
FOR EACH ROW
EXECUTE FUNCTION mata_private.enforce_teaching_name_scope_immutability()
"""
    )
    _execute(
        "REVOKE ALL PRIVILEGES ON FUNCTION "
        "mata_private.enforce_teaching_name_scope_immutability() "
        f"FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )


def _create_rls_policies_and_grants() -> None:
    for table_name in _B1_TABLES:
        _execute(f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY')

    for table_name, policy_name, action, using, check in _B1_POLICIES:
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

    table_list = ", ".join(f"public.{table_name}" for table_name in _B1_TABLES)
    _execute(
        "REVOKE ALL PRIVILEGES ON TABLE "
        f"{table_list} FROM PUBLIC, {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
        f"{table_list} TO {RUNTIME_ROLE}"
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
                'REVOKE ALL PRIVILEGES ON TABLE '
                'public.teaching_names, public.teaching_name_mappings FROM %I',
                optional_role
            );
            EXECUTE pg_catalog.format(
                'REVOKE ALL PRIVILEGES ON FUNCTION '
                'mata_private.enforce_teaching_name_scope_immutability() FROM %I',
                optional_role
            );
        END IF;
    END LOOP;
END
$migration$
"""
    )


def _assert_b1_security_catalogue() -> None:
    _execute(
        f"""
DO $migration$
DECLARE
    expected_tables text[] := ARRAY['teaching_names', 'teaching_name_mappings'];
    expected_policies text[] := ARRAY[
        'mata_rls_teaching_names_select',
        'mata_rls_teaching_names_insert',
        'mata_rls_teaching_names_update',
        'mata_rls_teaching_names_delete',
        'mata_rls_teaching_name_mappings_select',
        'mata_rls_teaching_name_mappings_insert',
        'mata_rls_teaching_name_mappings_update',
        'mata_rls_teaching_name_mappings_delete'
    ];
    table_name text;
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
              AND relation.relowner = pg_catalog.to_regrole(CURRENT_USER)
        ) THEN
            RAISE EXCEPTION
                'B1 table ownership or RLS assertion failed for %', table_name
                USING ERRCODE = '42501';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            CROSS JOIN (
                VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'),
                       ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')
            ) AS privilege(action)
            WHERE namespace.nspname = 'public'
              AND relation.relname = table_name
              AND relation.relkind IN ('r', 'p')
              AND (
                  (
                      privilege.action IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
                      AND NOT has_table_privilege(
                          '{RUNTIME_ROLE}', relation.oid, privilege.action
                      )
                  )
                  OR (
                      privilege.action NOT IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
                      AND has_table_privilege(
                          '{RUNTIME_ROLE}', relation.oid, privilege.action
                      )
                  )
              )
        ) THEN
            RAISE EXCEPTION
                'B1 runtime table grants are not exact for %', table_name
                USING ERRCODE = '42501';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            CROSS JOIN (
                VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'),
                       ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')
            ) AS privilege(action)
            WHERE namespace.nspname = 'public'
              AND relation.relname = table_name
              AND relation.relkind IN ('r', 'p')
              AND has_table_privilege('{AUTH_ROLE}', relation.oid, privilege.action)
        ) THEN
            RAISE EXCEPTION
                'Auth helper role has a B1 table privilege'
                USING ERRCODE = '42501';
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS role
        WHERE role.rolname = '{RUNTIME_ROLE}'
          AND role.rolbypassrls
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = ANY(expected_tables)
          AND relation.relowner = pg_catalog.to_regrole('{RUNTIME_ROLE}')
    ) THEN
        RAISE EXCEPTION 'B1 runtime role must remain a non-owner NOBYPASSRLS role'
            USING ERRCODE = '42501';
    END IF;

    IF (
        SELECT count(*)
        FROM pg_catalog.pg_policy AS policy
        JOIN pg_catalog.pg_class AS relation
          ON relation.oid = policy.polrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = ANY(expected_tables)
    ) <> 8
       OR EXISTS (
            SELECT 1
            FROM pg_catalog.pg_policy AS policy
            JOIN pg_catalog.pg_class AS relation
              ON relation.oid = policy.polrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname = ANY(expected_tables)
              AND (
                  policy.polname <> ALL(expected_policies)
                  OR NOT policy.polpermissive
                  OR policy.polroles <> ARRAY[
                      pg_catalog.to_regrole('{RUNTIME_ROLE}')::oid
                  ]::oid[]
              )
       )
    THEN
        RAISE EXCEPTION 'B1 policy catalogue is not exact'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS optional_role
        JOIN pg_catalog.pg_class AS relation ON true
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE optional_role.rolname IN ('anon', 'authenticated', 'service_role')
          AND namespace.nspname = 'public'
          AND relation.relname = ANY(expected_tables)
          AND has_table_privilege(
              optional_role.oid,
              relation.oid,
              'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
          )
    ) THEN
        RAISE EXCEPTION 'A browser/service role has a B1 table privilege'
            USING ERRCODE = '42501';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = 'mata_private'
          AND procedure.proname = 'enforce_teaching_name_scope_immutability'
          AND procedure.proowner = pg_catalog.to_regrole(CURRENT_USER)
          AND procedure.prosecdef
    ) THEN
        RAISE EXCEPTION 'B1 trigger function ownership assertion failed'
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
          AND procedure.proname = 'enforce_teaching_name_scope_immutability'
          AND privilege.privilege_type = 'EXECUTE'
          AND privilege.grantee IN (
              0,
              pg_catalog.to_regrole('{RUNTIME_ROLE}')::oid,
              pg_catalog.to_regrole('{AUTH_ROLE}')::oid
          )
    ) THEN
        RAISE EXCEPTION 'B1 trigger function remains callable by an application role'
            USING ERRCODE = '42501';
    END IF;
END
$migration$
"""
    )


def upgrade() -> None:
    _add_schema()
    _enable_exact_pilot_capability()
    _create_scope_immutability_trigger()
    _create_rls_policies_and_grants()
    _assert_b1_security_catalogue()


def _assert_downgrade_is_drained() -> None:
    _execute(
        f"""
DO $migration$
BEGIN
    IF EXISTS (SELECT 1 FROM public.teaching_name_mappings)
       OR EXISTS (SELECT 1 FROM public.teaching_names)
       OR EXISTS (
            SELECT 1
            FROM public.teaching_events
            WHERE teaching_name_id IS NOT NULL
               OR global_session_type_id IS NOT NULL
       )
       OR EXISTS (
            SELECT 1
            FROM public.secretary_programme_pools
            WHERE can_manage_teaching_names
              AND (
                  posting_code <> '{PILOT_POSTING_CODE}'
                  OR programme_code <> '{PILOT_PROGRAMME_CODE}'
              )
       )
    THEN
        RAISE EXCEPTION
            'B1 downgrade requires drained Teaching Name rows, references, and capability changes'
            USING ERRCODE = '23514';
    END IF;
END
$migration$
"""
    )


def downgrade() -> None:
    # This is an offline/drained rollback only.  It removes only B1 additive
    # objects after the guard above proves no future-state data or references
    # would be discarded; it deliberately leaves all legacy A-K objects intact.
    _assert_downgrade_is_drained()

    for table_name, policy_name, _action, _using, _check in reversed(_B1_POLICIES):
        _execute(f'DROP POLICY IF EXISTS "{policy_name}" ON public."{table_name}"')

    _execute(
        "REVOKE ALL PRIVILEGES ON TABLE public.teaching_names, "
        f"public.teaching_name_mappings FROM {RUNTIME_ROLE}, {AUTH_ROLE}"
    )
    _execute(
        "DROP TRIGGER mata_enforce_teaching_name_scope_immutability "
        "ON public.teaching_names"
    )
    _execute(
        "DROP FUNCTION mata_private.enforce_teaching_name_scope_immutability()"
    )

    op.drop_index(
        "idx_teaching_events_global_session_type",
        table_name="teaching_events",
    )
    op.drop_index(
        "idx_teaching_events_teaching_name",
        table_name="teaching_events",
    )
    op.drop_constraint(
        "ck_teaching_events_source_identity_exclusive",
        "teaching_events",
        type_="check",
    )
    op.drop_constraint(
        "fk_teaching_events_global_session_type",
        "teaching_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_teaching_events_teaching_name",
        "teaching_events",
        type_="foreignkey",
    )
    op.drop_column("teaching_events", "global_session_type_id")
    op.drop_column("teaching_events", "teaching_name_id")

    op.drop_table("teaching_name_mappings")
    op.drop_table("teaching_names")
    op.drop_constraint(
        "uq_teaching_targets_id_mapping_scope",
        "teaching_targets",
        type_="unique",
    )
    op.drop_column("secretary_programme_pools", "can_manage_teaching_names")
