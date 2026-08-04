from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date, time
import os
import re
from time import sleep
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.models import Base
from tests.test_external_registration_migrations_postgres import (
    ALEMBIC_INI,
    BACKEND_ROOT,
    H_E_DISPOSABLE_DATABASE_NAME,
    MigrationHarness,
    _adhoc_creator_columns,
    _assert_local_postgres_source,
    _h_e_database_identity,
    _migration_environment,
    _repository_head_revision,
    _revision,
)


PREVIOUS_REVISION = "20260727_000027"
ADHOC_REVISION = "20260728_000028"
REPOSITORY_HEAD_REVISION = "20260804_000034"
PHASE_G_PREVIOUS_REVISION = "20260804_000033"
RUNTIME_ROLE = "mata_app_runtime"
AUTH_ROLE = "mata_auth_internal"
DEFINER_ROLE = "mata_adhoc_attendance_definer"
ATOMIC_HELPER = (
    "mata_rls.create_adhoc_attendance("
    "text,text,text,text,text,date,time without time zone,"
    "time without time zone,numeric,uuid)"
)
SOURCE_SCOPE_HELPER = "mata_rls.scheduled_event_source_scope(uuid)"
EXTERNAL_ACCESS_HELPER = "mata_rls.can_access_external_attendance(uuid,uuid)"
_SAFE_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")
_EPHEMERAL_ROLE = re.compile(r"mata_test_(?:runtime|auth)_[0-9a-f]{16}")

# Every other current model table must be empty before this deliberately
# in-place schema lifecycle starts.
MIGRATION_SEED_COUNTS = {
    "global_session_types": 1,
    "loa_types": 14,
    "multi_posting_rules": 27,
    "posting_codes": 62,
    "programme_institution_posting_map": 28,
    "programmes": 28,
    "secretary_programme_pools": 1,
    "session_types": 2,
    "weekend_exceptions": 4,
}

DEFINER_SELECT_TABLES = {
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
}
PHASE_G_DEFINER_SELECT_TABLES = DEFINER_SELECT_TABLES - {
    "global_session_types",
    "session_types",
    "teaching_name_catalogue",
    "teaching_targets",
}

IDS = {
    "sentinel_programme": UUID("5b000028-0000-4000-8000-000000000001"),
    "posting": UUID("5b000028-0000-4000-8000-000000000002"),
    "native_a": UUID("5b000028-0000-4000-8000-000000000003"),
    "native_b": UUID("5b000028-0000-4000-8000-000000000004"),
    "external": UUID("5b000028-0000-4000-8000-000000000005"),
    "native_event": UUID("5b000028-0000-4000-8000-000000000006"),
    "external_event": UUID("5b000028-0000-4000-8000-000000000007"),
    "native_attendance": UUID("5b000028-0000-4000-8000-000000000008"),
    "external_removed": UUID("5b000028-0000-4000-8000-000000000009"),
    "external_submitted": UUID("5b000028-0000-4000-8000-00000000000a"),
    "ambiguous_event": UUID("5b000028-0000-4000-8000-00000000000b"),
    "ambiguous_a": UUID("5b000028-0000-4000-8000-00000000000c"),
    "ambiguous_b": UUID("5b000028-0000-4000-8000-00000000000d"),
}


@dataclass(frozen=True, slots=True)
class InPlaceHarness:
    migration: MigrationHarness
    owner: str

    @property
    def engine(self) -> Engine:
        return self.migration.engine


def _assert_exclusive(engine: Engine) -> None:
    other_connections = -1
    for attempt in range(20):
        with engine.connect() as connection:
            identity = _h_e_database_identity(connection)
            assert identity["database_name"] == H_E_DISPOSABLE_DATABASE_NAME
            assert identity["current_role"] == identity["session_role"]
            assert identity["session_role"] == identity["database_owner"]
            other_connections = int(
                connection.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM pg_catalog.pg_stat_activity
                        WHERE datname = current_database()
                          AND pid <> pg_catalog.pg_backend_pid()
                        """
                    )
                )
                or 0
            )
        if other_connections == 0:
            return
        if attempt < 19:
            sleep(0.1)
    pytest.fail(
        "Migration mutation requires an exclusive disposable-database connection",
        pytrace=False,
    )


def _migrate(
    harness: InPlaceHarness,
    action: str,
    revision: str,
    *,
    succeeds: bool = True,
) -> str:
    _assert_exclusive(harness.engine)
    result = harness.migration.alembic(action, revision)
    output = result.stdout + result.stderr
    assert (result.returncode == 0) is succeeds, output
    return output


def _public_tables(connection: Connection) -> set[str]:
    return {
        str(name)
        for name in connection.scalars(
            text(
                """
                SELECT relation.relname
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relkind IN ('r', 'p')
                """
            )
        )
    }


def _expected_restricted_runner_roles() -> set[str]:
    expected: set[str] = set()
    for variable_name in ("DATABASE_URL", "MATA_AUTH_DATABASE_URL"):
        raw_url = os.environ.get(variable_name, "").strip()
        if not raw_url:
            continue
        username = make_url(raw_url).username
        if username and _EPHEMERAL_ROLE.fullmatch(username):
            expected.add(username)
    return expected


def _assert_seed_only_head(connection: Connection) -> None:
    assert _revision(connection) == REPOSITORY_HEAD_REVISION
    model_tables = {table.name for table in Base.metadata.tables.values()}
    assert _public_tables(connection) == {*model_tables, "alembic_version"}
    for table_name in sorted(model_tables):
        assert _SAFE_IDENTIFIER.fullmatch(table_name)
        count = connection.scalar(
            text(f'SELECT count(*) FROM public."{table_name}"')
        )
        assert count == MIGRATION_SEED_COUNTS.get(table_name, 0)
    assert connection.scalar(
        text("SELECT count(*) FROM mata_private.context_signing_key")
    ) == 1
    ephemeral_roles = set(
        connection.scalars(
            text(
                r"""
                SELECT rolname
                FROM pg_catalog.pg_roles
                WHERE rolname LIKE 'mata\_test\_%' ESCAPE '\'
                """
            )
        )
    )
    assert ephemeral_roles == _expected_restricted_runner_roles()


def _assert_base(connection: Connection) -> None:
    assert _revision(connection) == "None"
    assert _public_tables(connection) <= {"alembic_version"}
    assert connection.scalar(
        text(
            """
            SELECT count(*)
            FROM pg_catalog.pg_namespace
            WHERE nspname IN ('mata_rls', 'mata_private')
            """
        )
    ) == 0


def _catalogue(connection: Connection) -> dict[str, tuple[Any, ...]]:
    function_names = [
        "create_adhoc_attendance",
        "can_select_teaching_event",
        "can_select_teaching_event_000027",
        "can_insert_teaching_event",
        "can_insert_teaching_event_000027",
        "can_submit_native_attendance",
        "can_submit_native_attendance_000027",
        "can_submit_external_attendance",
        "can_submit_external_attendance_000027",
        "enforce_teaching_event_creator_immutability",
        "enforce_attendance_integrity",
    ]
    return {
        "columns": tuple(
            connection.execute(
                text(
                    """
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'teaching_events'
                      AND column_name LIKE 'created_by_%resident_id'
                    ORDER BY column_name
                    """
                )
            )
        ),
        "constraints": tuple(
            connection.execute(
                text(
                    """
                    SELECT constraint_row.conname,
                           pg_catalog.pg_get_constraintdef(
                               constraint_row.oid, true
                           )
                    FROM pg_catalog.pg_constraint AS constraint_row
                    JOIN pg_catalog.pg_class AS relation
                      ON relation.oid = constraint_row.conrelid
                    WHERE relation.relname IN (
                        'teaching_events',
                        'attendance_records',
                        'external_attendance_records'
                    )
                      AND (
                          constraint_row.conname LIKE '%creator%'
                          OR constraint_row.conname LIKE '%status'
                          OR constraint_row.conname
                              = 'uq_attendance_records_resident_event'
                      )
                    ORDER BY constraint_row.conname
                    """
                )
            )
        ),
        "indexes": tuple(
            connection.execute(
                text(
                    """
                    SELECT indexname, indexdef
                    FROM pg_catalog.pg_indexes
                    WHERE schemaname = 'public'
                      AND indexname IN (
                          'idx_teaching_events_created_by_resident',
                          'idx_teaching_events_created_by_external_resident',
                          'idx_attendance_records_submitted_resident_event'
                      )
                    ORDER BY indexname
                    """
                )
            )
        ),
        "triggers": tuple(
            connection.execute(
                text(
                    """
                    SELECT trigger_row.tgname,
                           pg_catalog.pg_get_triggerdef(
                               trigger_row.oid, true
                           )
                    FROM pg_catalog.pg_trigger AS trigger_row
                    WHERE trigger_row.tgname LIKE 'mata_enforce_%integrity'
                       OR trigger_row.tgname
                          = 'mata_enforce_teaching_event_creator_immutability'
                    ORDER BY trigger_row.tgname
                    """
                )
            )
        ),
        "functions": tuple(
            connection.execute(
                text(
                    """
                    SELECT
                        pg_catalog.format(
                            '%I.%I(%s)',
                            namespace.nspname,
                            procedure.proname,
                            pg_catalog.replace(
                                pg_catalog.oidvectortypes(
                                    procedure.proargtypes
                                ),
                                ', ', ','
                            )
                        ),
                        owner_role.rolname,
                        procedure.prosecdef,
                        procedure.proconfig,
                        pg_catalog.has_function_privilege(
                            :runtime_role, procedure.oid, 'EXECUTE'
                        ),
                        pg_catalog.has_function_privilege(
                            :auth_role, procedure.oid, 'EXECUTE'
                        ),
                        COALESCE(
                            pg_catalog.has_function_privilege(
                                pg_catalog.to_regrole('anon'),
                                procedure.oid,
                                'EXECUTE'
                            ),
                            false
                        ),
                        COALESCE(
                            pg_catalog.has_function_privilege(
                                pg_catalog.to_regrole('authenticated'),
                                procedure.oid,
                                'EXECUTE'
                            ),
                            false
                        ),
                        COALESCE(
                            pg_catalog.has_function_privilege(
                                pg_catalog.to_regrole('service_role'),
                                procedure.oid,
                                'EXECUTE'
                            ),
                            false
                        ),
                        NOT EXISTS (
                            SELECT 1
                            FROM pg_catalog.aclexplode(
                                COALESCE(
                                    procedure.proacl,
                                    pg_catalog.acldefault(
                                        'f', procedure.proowner
                                    )
                                )
                            ) AS privilege
                            WHERE privilege.grantee = 0
                              AND privilege.privilege_type = 'EXECUTE'
                        ),
                        pg_catalog.pg_get_functiondef(procedure.oid)
                    FROM pg_catalog.pg_proc AS procedure
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = procedure.pronamespace
                    JOIN pg_catalog.pg_roles AS owner_role
                      ON owner_role.oid = procedure.proowner
                    WHERE namespace.nspname IN ('mata_rls', 'mata_private')
                      AND procedure.proname
                          = ANY(CAST(:function_names AS text[]))
                    ORDER BY 1
                    """
                ),
                {
                    "runtime_role": RUNTIME_ROLE,
                    "auth_role": AUTH_ROLE,
                    "function_names": function_names,
                },
            )
        ),
        "policies": tuple(
            connection.execute(
                text(
                    """
                    SELECT tablename, policyname, cmd, roles::text,
                           qual, with_check
                    FROM pg_catalog.pg_policies
                    WHERE schemaname = 'public'
                      AND policyname IN (
                          'mata_rls_teaching_events_select',
                          'mata_rls_teaching_events_insert',
                          'mata_rls_attendance_records_select',
                          'mata_rls_attendance_records_insert',
                          'mata_rls_attendance_records_update',
                          'mata_rls_external_attendance_records_insert',
                          'mata_rls_external_attendance_records_update'
                      )
                    ORDER BY tablename, policyname
                    """
                )
            )
        ),
        "role": tuple(
            connection.execute(
                text(
                    """
                    SELECT rolcanlogin, rolinherit, rolsuper, rolbypassrls,
                           rolcreatedb, rolcreaterole, rolreplication,
                           NOT EXISTS (
                               SELECT 1
                               FROM pg_catalog.pg_auth_members AS membership
                               WHERE membership.member = role.oid
                                  OR membership.roleid = role.oid
                           )
                    FROM pg_catalog.pg_roles AS role
                    WHERE role.rolname = :definer_role
                    """
                ),
                {"definer_role": DEFINER_ROLE},
            )
        ),
        "table_acl": tuple(
            connection.execute(
                text(
                    """
                    SELECT relation.relname, privilege.privilege_type
                    FROM pg_catalog.pg_class AS relation
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        relation.relacl
                    ) AS privilege
                    WHERE namespace.nspname = 'public'
                      AND relation.relkind IN ('r', 'p')
                      AND privilege.grantee
                          = pg_catalog.to_regrole(:definer_role)
                    ORDER BY relation.relname, privilege.privilege_type
                    """
                ),
                {"definer_role": DEFINER_ROLE},
            )
        ),
        "boundary": tuple(
            connection.execute(
                text(
                    """
                    SELECT
                        pg_catalog.to_regprocedure(
                            'mata_rls.create_adhoc_attendance('
                            'text,text,text,text,text,date,'
                            'time without time zone,'
                            'time without time zone,numeric,uuid)'
                        ) IS NOT NULL,
                        pg_catalog.has_schema_privilege(
                            :definer_role, 'mata_rls', 'USAGE'
                        ),
                        pg_catalog.has_schema_privilege(
                            :definer_role, 'mata_private', 'USAGE'
                        ),
                        pg_catalog.has_schema_privilege(
                            :definer_role, 'mata_rls', 'CREATE'
                        ),
                        pg_catalog.has_function_privilege(
                            :definer_role,
                            'public.gen_random_uuid()', 'EXECUTE'
                        ),
                        pg_catalog.has_function_privilege(
                            :definer_role,
                            'mata_rls.current_subject_type()', 'EXECUTE'
                        ),
                        pg_catalog.has_function_privilege(
                            :definer_role,
                            'mata_rls.current_subject_id()', 'EXECUTE'
                        )
                    """
                ),
                {"definer_role": DEFINER_ROLE},
            )
        ),
    }


def _assert_000027(connection: Connection) -> None:
    assert _revision(connection) == PREVIOUS_REVISION
    assert _adhoc_creator_columns(connection) == set()
    state = _catalogue(connection)
    assert state["triggers"] == ()
    assert state["boundary"] == ((False, False, False, False, False, False, False),)
    assert state["role"] == (
        (False, False, False, True, False, False, False, True),
    )
    assert state["table_acl"] == ()


def _assert_000028(connection: Connection, *, owner: str) -> None:
    assert _revision(connection) == ADHOC_REVISION
    assert _adhoc_creator_columns(connection) == {
        "created_by_resident_id",
        "created_by_external_resident_id",
    }
    state = _catalogue(connection)
    constraint_names = {str(row[0]) for row in state["constraints"]}
    assert {
        "fk_teaching_events_resident_creator",
        "fk_teaching_events_external_resident_creator",
        "ck_teaching_events_adhoc_creator_family",
        "ck_attendance_records_status",
        "ck_external_attendance_records_status",
    } <= constraint_names
    assert "uq_attendance_records_resident_event" not in constraint_names
    index_rows = {str(row[0]): str(row[1]) for row in state["indexes"]}
    assert set(index_rows) == {
        "idx_teaching_events_created_by_resident",
        "idx_teaching_events_created_by_external_resident",
        "idx_attendance_records_submitted_resident_event",
    }
    assert "UNIQUE" in index_rows[
        "idx_attendance_records_submitted_resident_event"
    ]
    assert len(state["triggers"]) == 3

    functions = {str(row[0]): row for row in state["functions"]}
    public_wrappers = {
        "mata_rls.can_select_teaching_event(uuid)",
        "mata_rls.can_insert_teaching_event(text,text,text,date,boolean,text)",
        "mata_rls.can_submit_native_attendance(uuid,uuid)",
        "mata_rls.can_submit_external_attendance(uuid,uuid)",
    }
    private_helpers = {
        "mata_private.can_select_teaching_event_000027(uuid)",
        (
            "mata_private.can_insert_teaching_event_000027("
            "text,text,text,date,boolean,text)"
        ),
        "mata_private.can_submit_native_attendance_000027(uuid,uuid)",
        "mata_private.can_submit_external_attendance_000027(uuid,uuid)",
        "mata_private.enforce_teaching_event_creator_immutability()",
        "mata_private.enforce_attendance_integrity()",
    }
    assert {*public_wrappers, *private_helpers, ATOMIC_HELPER} <= set(functions)
    for signature in {*public_wrappers, *private_helpers, ATOMIC_HELPER}:
        row = functions[signature]
        assert row[1] == (DEFINER_ROLE if signature == ATOMIC_HELPER else owner)
        assert row[2] is True
        assert list(row[3] or []) == ["search_path=pg_catalog, pg_temp"]
        assert row[4] is (signature in public_wrappers or signature == ATOMIC_HELPER)
        assert row[5] is False
        assert row[6] is False
        assert row[7] is False
        assert row[8] is False
        assert row[9] is True

    assert state["role"] == (
        (False, False, False, True, False, False, False, True),
    )
    assert set(state["table_acl"]) == {
        *((table_name, "SELECT") for table_name in DEFINER_SELECT_TABLES),
        ("attendance_records", "INSERT"),
        ("external_attendance_records", "INSERT"),
        ("teaching_events", "INSERT"),
    }
    assert state["boundary"] == (
        (True, True, False, False, True, True, True),
    )
    assert len(state["policies"]) == 7
    assert all(row[3] == "{mata_app_runtime}" for row in state["policies"])


DATA_IDS = {
    "programmes": [IDS["sentinel_programme"]],
    "posting_codes": [IDS["posting"]],
    "residents": [IDS["native_a"], IDS["native_b"]],
    "external_residents": [IDS["external"]],
    "teaching_events": [
        IDS["native_event"],
        IDS["external_event"],
        IDS["ambiguous_event"],
    ],
    "attendance_records": [
        IDS["native_attendance"],
        IDS["ambiguous_a"],
        IDS["ambiguous_b"],
    ],
    "external_attendance_records": [
        IDS["external_removed"],
        IDS["external_submitted"],
    ],
}


def _data_snapshot(connection: Connection) -> dict[str, tuple[Any, ...]]:
    snapshot: dict[str, tuple[Any, ...]] = {}
    for table_name, row_ids in DATA_IDS.items():
        assert _SAFE_IDENTIFIER.fullmatch(table_name)
        stripped = (
            [
                "created_by_resident_id",
                "created_by_external_resident_id",
            ]
            if table_name == "teaching_events"
            else []
        )
        snapshot[table_name] = tuple(
            connection.execute(
                text(
                    f"""
                    SELECT id::text,
                           (
                               pg_catalog.to_jsonb(source)
                               - CAST(:stripped AS text[])
                           )::text
                    FROM public."{table_name}" AS source
                    WHERE id = ANY(CAST(:ids AS uuid[]))
                    ORDER BY id
                    """
                ),
                {"ids": row_ids, "stripped": stripped},
            )
        )
    return snapshot


def _seed_valid(connection: Connection) -> None:
    tables = Base.metadata.tables
    connection.execute(
        tables["programmes"].insert(),
        {
            "id": IDS["sentinel_programme"],
            "code": "MIG28SENTINEL",
            "name": "Migration sentinel",
            "ay_date_category": "non_im_subspec",
        },
    )
    connection.execute(
        tables["posting_codes"].insert(),
        {"id": IDS["posting"], "code": "MIG28VERIFY"},
    )
    connection.execute(
        tables["residents"].insert(),
        [
            {"id": IDS["native_a"], "name": "Migration A", "mcr": "MIG28A"},
            {"id": IDS["native_b"], "name": "Migration B", "mcr": "MIG28B"},
        ],
    )
    connection.execute(
        tables["external_residents"].insert(),
        {
            "id": IDS["external"],
            "name": "Migration external",
            "mcr": "MIG28EXT",
            "home_cluster": "NUH",
            "current_nhg_posting_code": "MIG28VERIFY",
        },
    )
    connection.execute(
        tables["teaching_events"].insert(),
        [
            {
                "id": IDS["native_event"],
                "posting_code": "MIG28VERIFY",
                "teaching_name": "Migration native ad-hoc",
                "event_date": date(2035, 5, 1),
                "start_time": time(9),
                "is_adhoc": True,
                "created_by_role": "resident",
            },
            {
                "id": IDS["external_event"],
                "posting_code": "MIG28VERIFY",
                "teaching_name": "Migration external ad-hoc",
                "event_date": date(2035, 5, 1),
                "start_time": time(10),
                "is_adhoc": True,
                "created_by_role": "external_resident",
            },
        ],
    )
    connection.execute(
        tables["attendance_records"].insert(),
        {
            "id": IDS["native_attendance"],
            "resident_id": IDS["native_a"],
            "teaching_event_id": IDS["native_event"],
            "status": "submitted",
            "posting_code": "MIG28VERIFY",
        },
    )
    connection.execute(
        tables["external_attendance_records"].insert(),
        [
            {
                "id": IDS["external_removed"],
                "external_resident_id": IDS["external"],
                "teaching_event_id": IDS["external_event"],
                "status": "removed",
                "posting_code": "MIG28VERIFY",
            },
            {
                "id": IDS["external_submitted"],
                "external_resident_id": IDS["external"],
                "teaching_event_id": IDS["external_event"],
                "status": "submitted",
                "posting_code": "MIG28VERIFY",
            },
        ],
    )


def _seed_ambiguous(connection: Connection) -> None:
    tables = Base.metadata.tables
    connection.execute(
        tables["teaching_events"].insert(),
        {
            "id": IDS["ambiguous_event"],
            "posting_code": "MIG28VERIFY",
            "teaching_name": "Migration ambiguous ad-hoc",
            "event_date": date(2035, 5, 2),
            "start_time": time(9),
            "is_adhoc": True,
            "created_by_role": "resident",
        },
    )
    connection.execute(
        tables["attendance_records"].insert(),
        [
            {
                "id": IDS["ambiguous_a"],
                "resident_id": IDS["native_a"],
                "teaching_event_id": IDS["ambiguous_event"],
                "status": "submitted",
                "posting_code": "MIG28VERIFY",
            },
            {
                "id": IDS["ambiguous_b"],
                "resident_id": IDS["native_b"],
                "teaching_event_id": IDS["ambiguous_event"],
                "status": "submitted",
                "posting_code": "MIG28VERIFY",
            },
        ],
    )


def _assert_creators(connection: Connection) -> None:
    assert {
        UUID(str(row[0])): (row[1], row[2])
        for row in connection.execute(
            text(
                """
                SELECT id, created_by_resident_id,
                       created_by_external_resident_id
                FROM teaching_events
                WHERE id = ANY(CAST(:ids AS uuid[]))
                """
            ),
            {"ids": [IDS["native_event"], IDS["external_event"]]},
        )
    } == {
        IDS["native_event"]: (IDS["native_a"], None),
        IDS["external_event"]: (None, IDS["external"]),
    }


def _cleanup(engine: Engine) -> None:
    order = (
        "attendance_records",
        "external_attendance_records",
        "teaching_events",
        "external_residents",
        "residents",
        "posting_codes",
        "programmes",
    )
    with engine.begin() as connection:
        for table_name in order:
            if connection.scalar(
                text("SELECT pg_catalog.to_regclass(:name)"),
                {"name": f"public.{table_name}"},
            ) is None:
                continue
            connection.execute(
                text(
                    f'DELETE FROM public."{table_name}" '
                    "WHERE id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": DATA_IDS[table_name]},
            )


def _recover_head(harness: InPlaceHarness) -> None:
    _cleanup(harness.engine)
    _migrate(harness, "upgrade", "head")
    _cleanup(harness.engine)
    with harness.engine.connect() as connection:
        _assert_seed_only_head(connection)


@pytest.fixture
def in_place_migration_database(
    request: pytest.FixtureRequest,
) -> Iterator[InPlaceHarness]:
    if request.node.get_closest_marker("migration_mutation") is None:
        pytest.fail(
            "Direct-owner migration fixtures require the migration_mutation marker",
            pytrace=False,
        )
    settings = Settings(_env_file=None)
    source_url = make_url(settings.sync_database_url)
    _assert_local_postgres_source(source_url)
    assert _repository_head_revision() == REPOSITORY_HEAD_REVISION
    environment = _migration_environment(source_url)
    engine = create_engine(source_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            identity: Mapping[str, Any] = _h_e_database_identity(connection)
            assert identity["database_name"] == H_E_DISPOSABLE_DATABASE_NAME
            assert identity["current_role"] == identity["session_role"]
            assert identity["session_role"] == identity["database_owner"]
            assert identity["session_role"] == source_url.username
            assert identity["login_is_superuser"] is True
            _assert_seed_only_head(connection)
        _assert_exclusive(engine)
        migration = MigrationHarness(
            database_name=H_E_DISPOSABLE_DATABASE_NAME,
            engine=engine,
            environment=environment,
            request_node=request.node,
        )
        yield InPlaceHarness(
            migration=migration,
            owner=str(identity["database_owner"]),
        )
    finally:
        engine.dispose()


@pytest.mark.migration_mutation
def test_phase_g_runtime_source_decoupling_migration_lifecycle_in_place(
    in_place_migration_database: InPlaceHarness,
) -> None:
    harness = in_place_migration_database
    try:
        _migrate(harness, "downgrade", PHASE_G_PREVIOUS_REVISION)
        with harness.engine.connect() as connection:
            assert _revision(connection) == PHASE_G_PREVIOUS_REVISION
            assert connection.scalar(
                text("SELECT pg_catalog.to_regprocedure(:signature)"),
                {"signature": SOURCE_SCOPE_HELPER},
            ) is None
            assert set(_catalogue(connection)["table_acl"]) == {
                *((table_name, "SELECT") for table_name in DEFINER_SELECT_TABLES),
                ("attendance_records", "INSERT"),
                ("external_attendance_records", "INSERT"),
                ("teaching_events", "INSERT"),
            }
            pre_phase_g_external_access = str(
                connection.scalar(
                    text(
                        "SELECT pg_catalog.pg_get_functiondef("
                        "pg_catalog.to_regprocedure(:signature))"
                    ),
                    {"signature": EXTERNAL_ACCESS_HELPER},
                )
            )

        _migrate(harness, "upgrade", REPOSITORY_HEAD_REVISION)
        with harness.engine.connect() as connection:
            assert _revision(connection) == REPOSITORY_HEAD_REVISION
            source_scope = connection.execute(
                text(
                    """
                    SELECT owner_role.rolname,
                           procedure.prosecdef,
                           procedure.proconfig,
                           pg_catalog.has_function_privilege(
                               :runtime_role, procedure.oid, 'EXECUTE'
                           ),
                           pg_catalog.has_function_privilege(
                               :auth_role, procedure.oid, 'EXECUTE'
                           ),
                           NOT EXISTS (
                               SELECT 1
                               FROM pg_catalog.aclexplode(
                                   COALESCE(
                                       procedure.proacl,
                                       pg_catalog.acldefault(
                                           'f', procedure.proowner
                                       )
                                   )
                               ) AS privilege
                               WHERE privilege.grantee = 0
                                 AND privilege.privilege_type = 'EXECUTE'
                           )
                    FROM pg_catalog.pg_proc AS procedure
                    JOIN pg_catalog.pg_roles AS owner_role
                      ON owner_role.oid = procedure.proowner
                    WHERE procedure.oid = pg_catalog.to_regprocedure(:signature)
                    """
                ),
                {
                    "signature": SOURCE_SCOPE_HELPER,
                    "runtime_role": RUNTIME_ROLE,
                    "auth_role": AUTH_ROLE,
                },
            ).one()
            assert source_scope[0] == harness.owner
            assert source_scope[1] is True
            assert list(source_scope[2] or []) == ["search_path=pg_catalog, pg_temp"]
            assert source_scope[3:] == (True, False, True)

            phase_g_acl = set(_catalogue(connection)["table_acl"])
            assert phase_g_acl == {
                *(
                    (table_name, "SELECT")
                    for table_name in PHASE_G_DEFINER_SELECT_TABLES
                ),
                ("attendance_records", "INSERT"),
                ("external_attendance_records", "INSERT"),
                ("teaching_events", "INSERT"),
            }
            atomic_definition = str(
                connection.scalar(
                    text(
                        "SELECT pg_catalog.pg_get_functiondef("
                        "pg_catalog.to_regprocedure(:signature))"
                    ),
                    {"signature": ATOMIC_HELPER},
                )
            )
            assert "Department/Programme Teaching [1h]" in atomic_definition
            assert "teaching_name_catalogue" not in atomic_definition
            assert "teaching_targets" not in atomic_definition
            phase_g_external_access = str(
                connection.scalar(
                    text(
                        "SELECT pg_catalog.pg_get_functiondef("
                        "pg_catalog.to_regprocedure(:signature))"
                    ),
                    {"signature": EXTERNAL_ACCESS_HELPER},
                )
            )
            assert phase_g_external_access != pre_phase_g_external_access
            assert "current_app_role() = 'secretary'" in phase_g_external_access
            assert "current_app_role() = 'admin'" in phase_g_external_access
            assert "competing_posting" in phase_g_external_access

        _migrate(harness, "downgrade", PHASE_G_PREVIOUS_REVISION)
        with harness.engine.connect() as connection:
            assert connection.scalar(
                text("SELECT pg_catalog.to_regprocedure(:signature)"),
                {"signature": SOURCE_SCOPE_HELPER},
            ) is None
            assert set(_catalogue(connection)["table_acl"]) == {
                *((table_name, "SELECT") for table_name in DEFINER_SELECT_TABLES),
                ("attendance_records", "INSERT"),
                ("external_attendance_records", "INSERT"),
                ("teaching_events", "INSERT"),
            }
            assert str(
                connection.scalar(
                    text(
                        "SELECT pg_catalog.pg_get_functiondef("
                        "pg_catalog.to_regprocedure(:signature))"
                    ),
                    {"signature": EXTERNAL_ACCESS_HELPER},
                )
            ) == pre_phase_g_external_access
    finally:
        _recover_head(harness)


@pytest.mark.migration_mutation
def test_adhoc_creator_migration_lifecycle_in_place(
    in_place_migration_database: InPlaceHarness,
) -> None:
    harness = in_place_migration_database
    try:
        _migrate(harness, "downgrade", "base")
        with harness.engine.connect() as connection:
            _assert_base(connection)
        _migrate(harness, "upgrade", ADHOC_REVISION)
        with harness.engine.connect() as connection:
            _assert_000028(connection, owner=harness.owner)
            head_catalogue = _catalogue(connection)

        _migrate(harness, "downgrade", PREVIOUS_REVISION)
        with harness.engine.begin() as connection:
            _assert_000027(connection)
            _seed_valid(connection)
            valid_data = _data_snapshot(connection)
            previous_catalogue = _catalogue(connection)

        for action, revision in (
            ("upgrade", ADHOC_REVISION),
            ("downgrade", PREVIOUS_REVISION),
            ("upgrade", ADHOC_REVISION),
        ):
            _migrate(harness, action, revision)
            with harness.engine.connect() as connection:
                assert _data_snapshot(connection) == valid_data
                if revision == ADHOC_REVISION:
                    _assert_000028(connection, owner=harness.owner)
                    assert _catalogue(connection) == head_catalogue
                    _assert_creators(connection)
                else:
                    _assert_000027(connection)
                    assert _catalogue(connection) == previous_catalogue

        _migrate(harness, "downgrade", PREVIOUS_REVISION)
        with harness.engine.begin() as connection:
            _assert_000027(connection)
            assert _catalogue(connection) == previous_catalogue
            _seed_ambiguous(connection)
            ambiguous_data = _data_snapshot(connection)
            rollback_catalogue = _catalogue(connection)

        output = _migrate(
            harness,
            "upgrade",
            ADHOC_REVISION,
            succeeds=False,
        )
        assert "Cannot infer immutable ad-hoc creator" in output
        with harness.engine.connect() as connection:
            _assert_000027(connection)
            assert _catalogue(connection) == rollback_catalogue
            assert _catalogue(connection) == previous_catalogue
            assert _data_snapshot(connection) == ambiguous_data
    finally:
        _recover_head(harness)
