from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import subprocess
import sys
from typing import Any
from uuid import UUID, uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from app.config import Settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
VERSIONS_DIR = BACKEND_ROOT / "alembic" / "versions"
H_E_DISPOSABLE_DATABASE_NAME = "mata_phase5b_final_security_review"
_LOCAL_POSTGRES_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_SYNC_POSTGRES_DRIVERS = frozenset(
    {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
)

EXPECTED_POSTING_CODE_ROWS = (
    ("752081a5-51ce-5d5a-8049-b77f1a98a160", "NSCDermat"),
    ("ae6edcd5-b5ac-5ed1-a723-a68fdcc90e05", "TTSHGenSrg"),
    ("6ac7d953-4db4-58a2-aec5-81e490ee1365", "TTSHInfect"),
    ("f4561637-68c1-581b-b48a-8469f8a69b7f", "TTSHMedOnc"),
    ("85fc721e-68db-5c8a-953c-cbcf5da11297", "TTSHOrtSrg"),
    ("9fb9712f-3d85-50d2-a12b-79f0ded243d9", "TTSHRehabi"),
    ("56bb8cf2-eae0-5a16-bb64-2d2321fd9cad", "TTSHRenal"),
    ("fd559e99-0b30-5d25-a287-572f37befe98", "TTSHRespir"),
    ("e6a4e9c0-679f-53b8-9561-bfdfdb13f99e", "TTSHRheuma"),
    ("48e7fb87-77e1-51da-ba76-2b562d654b2c", "TTSHUrolog"),
)

EXPECTED_ACTIVE_MAPPINGS = (
    ("AIM", "TTSHGenMed"),
    ("ANAES", "TTSHAnaes"),
    ("CARDIO", "TTSHCardio"),
    ("DERM", "NSCDermat"),
    ("DR", "TTSHDiagRd"),
    ("EM", "TTSHEmgMed"),
    ("ENDO", "TTSHEndocr"),
    ("ENT", "TTSHOtolar"),
    ("EYE", "TTSHOphtha"),
    ("GASTRO", "TTSHGas"),
    ("GERI", "TTSHGerMed"),
    ("GS", "TTSHGenSrg"),
    ("ID", "TTSHInfect"),
    ("IM", "TTSHGenMed"),
    ("MEDONCO", "TTSHMedOnc"),
    ("ORTHO", "TTSHOrtSrg"),
    ("PSY", "TTSHPsychi"),
    ("REHAB", "TTSHRehabi"),
    ("RENAL", "TTSHRenal"),
    ("RESPI", "TTSHRespir"),
    ("RHEUM", "TTSHRheuma"),
    ("SIG", "TTSHGenSrg"),
    ("URO", "TTSHUrolog"),
    ("MICROB", "TTSHLabMed"),
)

EXPECTED_INACTIVE_PROGRAMMES = ("FM", "PATH", "SPORTSMED", "PALLMED")


def _load_migration(filename: str, module_name: str) -> Any:
    path = VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POSTING_CODE_MIGRATION = _load_migration(
    "20260721_000020_seed_external_registration_posting_codes.py",
    "external_registration_posting_codes_migration",
)
MAPPING_MIGRATION = _load_migration(
    "20260721_000021_seed_ttsh_external_registration_mappings.py",
    "ttsh_external_registration_mappings_migration",
)
POSTING_PROGRAMME_MIGRATION = _load_migration(
    "20260721_000022_external_resident_posting_programme.py",
    "external_resident_posting_programme_migration",
)


def test_external_registration_migration_chain_and_constants() -> None:
    assert POSTING_CODE_MIGRATION.revision == "20260721_000020"
    assert POSTING_CODE_MIGRATION.down_revision == "20260717_000019"
    assert POSTING_CODE_MIGRATION.POSTING_CODE_ROWS == EXPECTED_POSTING_CODE_ROWS
    assert MAPPING_MIGRATION.revision == "20260721_000021"
    assert MAPPING_MIGRATION.down_revision == "20260721_000020"
    assert MAPPING_MIGRATION.ACTIVE_MAPPINGS == EXPECTED_ACTIVE_MAPPINGS
    assert MAPPING_MIGRATION.INACTIVE_PROGRAMME_CODES == (
        EXPECTED_INACTIVE_PROGRAMMES
    )
    assert POSTING_PROGRAMME_MIGRATION.revision == "20260721_000022"
    assert POSTING_PROGRAMME_MIGRATION.down_revision == "20260721_000021"

    source = (
        VERSIONS_DIR / "20260721_000020_seed_external_registration_posting_codes.py"
    ).read_text(encoding="utf-8")
    assert "ON CONFLICT" not in source.upper()
    assert "WHERE id = :row_id" in source
    assert "AND code = :code" in source

    provenance_source = (
        VERSIONS_DIR / "20260721_000022_external_resident_posting_programme.py"
    ).read_text(encoding="utf-8")
    assert "SELECT DISTINCT posting_code, programme_code" in provenance_source
    assert "WHERE NOT EXISTS" in provenance_source
    assert "status = 'active'" not in provenance_source
    assert "LIMIT 1" not in provenance_source.upper()


def _assert_local_postgres_source(
    url: URL,
) -> None:
    database = url.database or ""
    if (
        url.drivername not in _SYNC_POSTGRES_DRIVERS
        or (url.host or "").casefold() not in _LOCAL_POSTGRES_HOSTS
        or database != H_E_DISPOSABLE_DATABASE_NAME
        or not url.username
        or bool(url.query)
    ):
        pytest.fail(
            "Migration lifecycle tests require the exact named local disposable "
            f"database {H_E_DISPOSABLE_DATABASE_NAME}",
            pytrace=False,
        )


def _repository_head_revision() -> str:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        pytest.fail(
            "Migration lifecycle tests require exactly one Alembic repository head",
            pytrace=False,
        )
    return str(heads[0])


def _h_e_database_identity(connection: Connection) -> dict[str, Any]:
    return dict(
        connection.execute(
            text(
                """
                SELECT db.datname AS database_name,
                       current_user::text AS current_role,
                       session_user::text AS session_role,
                       owner_role.rolname AS database_owner,
                       login_role.rolsuper AS login_is_superuser
                FROM pg_catalog.pg_database AS db
                JOIN pg_catalog.pg_roles AS owner_role
                  ON owner_role.oid = db.datdba
                JOIN pg_catalog.pg_roles AS login_role
                  ON login_role.rolname = session_user
                WHERE db.datname = current_database()
                """
            )
        )
        .mappings()
        .one()
    )


def _assert_h_e_target_ready(
    target_engine: Engine,
    *,
    repository_head: str,
) -> None:
    with target_engine.connect() as connection:
        identity = _h_e_database_identity(connection)
        if (
            identity["database_name"] != H_E_DISPOSABLE_DATABASE_NAME
            or identity["current_role"] != identity["session_role"]
            or identity["session_role"] != identity["database_owner"]
            or not identity["login_is_superuser"]
        ):
            pytest.fail(
                "Migration lifecycle credentials must directly own the exact "
                "named disposable database and be a local migration superuser",
                pytrace=False,
            )

        revisions = list(
            connection.scalars(
                text(
                    """
                    SELECT version_num
                    FROM public.alembic_version
                    ORDER BY version_num
                    """
                )
            )
        )
        if revisions != [repository_head]:
            pytest.fail(
                "H-E lifecycle tests require the exact named disposable database "
                "to start at the single Alembic repository head",
                pytrace=False,
            )


@dataclass
class MigrationHarness:
    database_name: str
    engine: Engine
    environment: dict[str, str]

    def _attest_mutation_target(self) -> None:
        source_url = make_url(self.environment["SYNC_DATABASE_URL"])
        _assert_local_postgres_source(source_url)
        if source_url.database != self.database_name:
            pytest.fail(
                "Migration harness database identity changed before mutation",
                pytrace=False,
            )

        with self.engine.connect() as connection:
            identity = _h_e_database_identity(connection)
            other_connections = connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_catalog.pg_stat_activity
                    WHERE datname = current_database()
                      AND pid <> pg_catalog.pg_backend_pid()
                    """
                )
            )
        if (
            identity["database_name"] != H_E_DISPOSABLE_DATABASE_NAME
            or identity["current_role"] != identity["session_role"]
            or identity["session_role"] != identity["database_owner"]
            or identity["session_role"] != source_url.username
            or not identity["login_is_superuser"]
            or other_connections != 0
        ):
            pytest.fail(
                "Migration mutation requires the exclusive exact named local "
                "disposable database through its direct owner",
                pytrace=False,
            )
        print(
            "PostgreSQL mutation target: "
            f"database={identity['database_name']} "
            f"host={source_url.host}:{source_url.port or 5432}",
            flush=True,
        )

    def alembic(self, action: str, revision: str) -> subprocess.CompletedProcess[str]:
        if action not in {"upgrade", "downgrade"}:
            raise ValueError("Migration harness permits only upgrade or downgrade")
        self._attest_mutation_target()
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "alembic",
                "-c",
                str(ALEMBIC_INI),
                action,
                revision,
            ],
            cwd=BACKEND_ROOT,
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )


def _migration_environment(source_url: URL) -> dict[str, str]:
    owner_sync_url = source_url.render_as_string(hide_password=False)
    owner_async_url = source_url.set(
        drivername="postgresql+asyncpg"
    ).render_as_string(hide_password=False)
    environment = os.environ.copy()
    environment.update(
        {
            "SYNC_DATABASE_URL": owner_sync_url,
            "DATABASE_URL": owner_async_url,
            "AUTH_DATABASE_URL": owner_async_url,
            "MATA_AUTH_DATABASE_URL": owner_async_url,
            "DATABASE_RLS_ENABLED": "false",
            "MATA_DATABASE_RLS_ENABLED": "false",
            "ENVIRONMENT": "test",
            "ENV": "test",
            "AUTH_MODE": "stub",
        }
    )
    return environment


def test_migration_database_guard_accepts_only_final_named_local_owner_url() -> None:
    valid_url = make_url(
        "postgresql://migration_owner:test@localhost:5432/"
        f"{H_E_DISPOSABLE_DATABASE_NAME}"
    )
    _assert_local_postgres_source(valid_url)

    invalid_urls = (
        valid_url.set(drivername="postgresql+asyncpg"),
        valid_url.set(host="db.example.invalid"),
        valid_url.set(database="mata_phase5b_wrong_review"),
        valid_url.set(username=""),
        valid_url.update_query_dict({"sslmode": "require"}),
    )
    for invalid_url in invalid_urls:
        with pytest.raises(pytest.fail.Exception):
            _assert_local_postgres_source(invalid_url)


def test_migration_child_environment_sets_explicit_owner_urls() -> None:
    source_url = make_url(
        "postgresql+psycopg2://migration_owner:test@127.0.0.1:5432/"
        f"{H_E_DISPOSABLE_DATABASE_NAME}"
    )
    environment = _migration_environment(source_url)

    sync_url = make_url(environment["SYNC_DATABASE_URL"])
    async_url = make_url(environment["DATABASE_URL"])
    assert sync_url == source_url
    assert async_url == source_url.set(drivername="postgresql+asyncpg")
    assert environment["AUTH_DATABASE_URL"] == environment["DATABASE_URL"]
    assert environment["MATA_AUTH_DATABASE_URL"] == environment["DATABASE_URL"]
    assert environment["DATABASE_RLS_ENABLED"] == "false"
    assert environment["MATA_DATABASE_RLS_ENABLED"] == "false"
    assert environment["ENVIRONMENT"] == "test"
    assert environment["ENV"] == "test"
    assert environment["AUTH_MODE"] == "stub"


def test_migration_harness_never_manages_a_database_container() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    forbidden_fragments = (
        "CREATE " + "DATABASE",
        "DROP " + "DATABASE",
        "pg_" + "terminate_backend",
        'database=' + '"postgres"',
        "mata_phase5b_" + "verify_mig_",
    )

    for forbidden_fragment in forbidden_fragments:
        assert forbidden_fragment not in source


@pytest.fixture
def clean_migration_database() -> MigrationHarness:
    settings = Settings(_env_file=None)
    source_url = make_url(settings.sync_database_url)
    _assert_local_postgres_source(source_url)
    repository_head = _repository_head_revision()
    target_engine = create_engine(source_url, poolclass=NullPool)
    harness = MigrationHarness(
        database_name=H_E_DISPOSABLE_DATABASE_NAME,
        engine=target_engine,
        environment=_migration_environment(source_url),
    )
    mutation_authorized = False
    try:
        _assert_h_e_target_ready(
            target_engine,
            repository_head=repository_head,
        )
        with target_engine.connect() as connection:
            identity = _h_e_database_identity(connection)
            if identity["session_role"] != source_url.username:
                pytest.fail(
                    "SYNC_DATABASE_URL must use the direct disposable-database "
                    "owner",
                    pytrace=False,
                )

        mutation_authorized = True
        reset_result = harness.alembic("downgrade", "base")
        assert reset_result.returncode == 0, (
            reset_result.stdout + reset_result.stderr
        )
        with target_engine.connect() as connection:
            assert _revision(connection) == "None"

        yield harness
    finally:
        try:
            if mutation_authorized:
                reset_result = harness.alembic("downgrade", "base")
                restore_result = harness.alembic("upgrade", "head")
                assert reset_result.returncode == 0, (
                    reset_result.stdout + reset_result.stderr
                )
                assert restore_result.returncode == 0, (
                    restore_result.stdout + restore_result.stderr
                )
                _assert_h_e_target_ready(
                    target_engine,
                    repository_head=repository_head,
                )
        finally:
            target_engine.dispose()


POSTING_ROW_SQL = """
    SELECT id,
           code,
           display_name,
           institution,
           department,
           billing_dept,
           is_emergency,
           supports_secretary_events,
           created_at,
           updated_at
    FROM posting_codes
    ORDER BY code, id
"""

POSTING_ROW_KEYS = (
    "id",
    "code",
    "display_name",
    "institution",
    "department",
    "billing_dept",
    "is_emergency",
    "supports_secretary_events",
    "created_at",
    "updated_at",
)


def _posting_rows(connection: Connection) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in connection.execute(text(POSTING_ROW_SQL)).all()]


def _target_posting_rows(connection: Connection) -> list[dict[str, Any]]:
    target_codes = tuple(code for _row_id, code in EXPECTED_POSTING_CODE_ROWS)
    return [
        dict(row)
        for row in connection.execute(text(POSTING_ROW_SQL)).mappings().all()
        if row["code"] in target_codes
    ]


def _posting_row_by_id(
    connection: Connection,
    row_id: UUID,
) -> tuple[Any, ...]:
    row = connection.execute(
        text(
            POSTING_ROW_SQL.replace(
                "ORDER BY code, id",
                "WHERE id = :row_id",
            )
        ),
        {"row_id": row_id},
    ).mappings().one()
    return tuple(row[key] for key in POSTING_ROW_KEYS)


def _revision(connection: Connection) -> str:
    return str(connection.scalar(text("SELECT version_num FROM alembic_version")))


def _assert_stage_one_mappings(connection: Connection) -> None:
    counts = connection.execute(
        text(
            """
            SELECT count(*) FILTER (WHERE status = 'pending') AS pending_count,
                   count(*) FILTER (WHERE status = 'active') AS active_count,
                   count(*) FILTER (WHERE status = 'inactive') AS inactive_count,
                   count(posting_code) AS posting_count
            FROM programme_institution_posting_map
            WHERE institution_code = 'TTSH'
            """
        )
    ).one()
    assert tuple(counts) == (28, 0, 0, 0)


def _assert_stage_two_mappings(connection: Connection) -> None:
    rows = connection.execute(
        text(
            """
            SELECT programme_code, posting_code, status
            FROM programme_institution_posting_map
            WHERE institution_code = 'TTSH'
            ORDER BY display_order
            """
        )
    ).mappings().all()
    active = tuple(
        (str(row["programme_code"]), str(row["posting_code"]))
        for row in rows
        if row["status"] == "active"
    )
    inactive = tuple(
        str(row["programme_code"])
        for row in rows
        if row["status"] == "inactive" and row["posting_code"] is None
    )
    assert len(rows) == 28
    assert active == EXPECTED_ACTIVE_MAPPINGS
    assert inactive == EXPECTED_INACTIVE_PROGRAMMES
    assert not any(row["status"] == "pending" for row in rows)
    assert not any(
        row["status"] == "active" and row["posting_code"] is None for row in rows
    )


def _assert_clean_seeded_codes(connection: Connection) -> None:
    rows = _target_posting_rows(connection)
    expected_ids = {code: UUID(row_id) for row_id, code in EXPECTED_POSTING_CODE_ROWS}
    assert len(rows) == 10
    assert {str(row["code"]) for row in rows} == set(expected_ids)
    for row in rows:
        code = str(row["code"])
        assert UUID(str(row["id"])) == expected_ids[code]
        assert row["display_name"] is None
        assert row["institution"] is None
        assert row["department"] is None
        assert row["billing_dept"] is None
        assert row["is_emergency"] is False
        assert row["supports_secretary_events"] is False
        assert row["created_at"] is not None
        assert row["updated_at"] is not None


def _run_success(
    harness: MigrationHarness,
    action: str,
    revision: str,
) -> None:
    result = harness.alembic(action, revision)
    assert result.returncode == 0, result.stdout + result.stderr


def _seed_adhoc_creator_backfill(
    connection: Connection,
    *,
    case: str,
) -> dict[str, UUID]:
    ids = {
        "posting": uuid4(),
        "native_a": uuid4(),
        "native_b": uuid4(),
        "external": uuid4(),
        "native_event": uuid4(),
        "external_event": uuid4(),
    }
    posting_code = f"MIG{uuid4().hex[:20].upper()}"
    connection.execute(
        text("INSERT INTO posting_codes (id, code) VALUES (:id, :code)"),
        {"id": ids["posting"], "code": posting_code},
    )
    connection.execute(
        text(
            """
            INSERT INTO residents (id, name, mcr)
            VALUES (:id, :name, :mcr)
            """
        ),
        [
            {
                "id": ids["native_a"],
                "name": "Migration native A",
                "mcr": f"M{uuid4().hex[:18].upper()}",
            },
            {
                "id": ids["native_b"],
                "name": "Migration native B",
                "mcr": f"M{uuid4().hex[:18].upper()}",
            },
        ],
    )
    connection.execute(
        text(
            """
            INSERT INTO external_residents (
                id, name, mcr, home_cluster, current_nhg_posting_code
            )
            VALUES (
                :id, 'Migration external', :mcr, 'NUH', :posting_code
            )
            """
        ),
        {
            "id": ids["external"],
            "mcr": f"M{uuid4().hex[:18].upper()}",
            "posting_code": posting_code,
        },
    )
    event_rows = [
        {
            "id": ids["native_event"],
            "posting_code": posting_code,
            "teaching_name": "Migration native ad-hoc",
            "created_by_role": "resident",
        }
    ]
    if case == "valid":
        event_rows.append(
            {
                "id": ids["external_event"],
                "posting_code": posting_code,
                "teaching_name": "Migration external ad-hoc",
                "created_by_role": "external_resident",
            }
        )
    connection.execute(
        text(
            """
            INSERT INTO teaching_events (
                id, posting_code, teaching_name, event_date, start_time,
                is_adhoc, created_by_role
            )
            VALUES (
                :id, :posting_code, :teaching_name, DATE '2035-05-01',
                TIME '09:00', true, :created_by_role
            )
            """
        ),
        event_rows,
    )

    if case in {"valid", "ambiguous", "mixed"}:
        native_ids = (
            [ids["native_a"], ids["native_b"]]
            if case == "ambiguous"
            else [ids["native_a"]]
        )
        connection.execute(
            text(
                """
                INSERT INTO attendance_records (
                    resident_id, teaching_event_id, status, posting_code
                )
                VALUES (
                    :resident_id, :event_id, 'submitted', :posting_code
                )
                """
            ),
            [
                {
                    "resident_id": resident_id,
                    "event_id": ids["native_event"],
                    "posting_code": posting_code,
                }
                for resident_id in native_ids
            ],
        )
    if case == "valid":
        connection.execute(
            text(
                """
                INSERT INTO external_attendance_records (
                    external_resident_id, teaching_event_id,
                    status, posting_code
                )
                VALUES (
                    :external_id, :event_id, :status, :posting_code
                )
                """
            ),
            [
                {
                    "external_id": ids["external"],
                    "event_id": ids["external_event"],
                    "status": status,
                    "posting_code": posting_code,
                }
                for status in ("removed", "submitted")
            ],
        )
    elif case == "mixed":
        connection.execute(
            text(
                """
                INSERT INTO external_attendance_records (
                    external_resident_id, teaching_event_id,
                    status, posting_code
                )
                VALUES (
                    :external_id, :event_id, 'submitted', :posting_code
                )
                """
            ),
            {
                "external_id": ids["external"],
                "event_id": ids["native_event"],
                "posting_code": posting_code,
            },
        )
    return ids


def _adhoc_creator_columns(connection: Connection) -> set[str]:
    return {
        str(column)
        for column in connection.scalars(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'teaching_events'
                  AND column_name IN (
                      'created_by_resident_id',
                      'created_by_external_resident_id'
                  )
                """
            )
        )
    }


def _cutover_relation_state(
    connection: Connection,
) -> dict[str, tuple[bool, bool, int]]:
    return {
        str(row["relation_name"]): (
            bool(row["rls_enabled"]),
            bool(row["rls_forced"]),
            int(row["policy_count"]),
        )
        for row in connection.execute(
            text(
                """
                SELECT relation.relname AS relation_name,
                       relation.relrowsecurity AS rls_enabled,
                       relation.relforcerowsecurity AS rls_forced,
                       count(policy.oid) AS policy_count
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                LEFT JOIN pg_catalog.pg_policy AS policy
                  ON policy.polrelid = relation.oid
                WHERE namespace.nspname = 'public'
                  AND relation.relname IN ('users', 'programmes')
                GROUP BY relation.relname,
                         relation.relrowsecurity,
                         relation.relforcerowsecurity
                ORDER BY relation.relname
                """
            )
        ).mappings()
    }


def _assert_cutover_revision_state(
    connection: Connection,
    *,
    revision: str,
) -> None:
    assert _revision(connection) == revision
    relation_state = _cutover_relation_state(connection)
    assert set(relation_state) == {"programmes", "users"}
    assert all(not state[1] for state in relation_state.values())
    helper_exists = connection.scalar(
        text(
            """
            SELECT pg_catalog.to_regprocedure(
                'mata_rls.can_access_resident(uuid)'
            ) IS NOT NULL
            """
        )
    )

    if revision in {
        "20260726_000026",
        "20260727_000027",
        "20260728_000028",
    }:
        assert relation_state["users"][0] is True
        assert relation_state["users"][2] > 0
        assert relation_state["programmes"][0] is True
        assert relation_state["programmes"][2] > 0
        assert helper_exists is True
        return

    assert revision == "20260726_000025"
    assert relation_state["users"] == (False, False, 0)
    # programmes had deny-by-default RLS before the H-E policy cutover and a
    # 000026 downgrade must preserve that earlier hardening.
    assert relation_state["programmes"] == (True, False, 0)
    assert helper_exists is False


def _assert_session_lifecycle_helper_state(
    connection: Connection,
    *,
    revision: str,
) -> None:
    new_helper_access = {
        (
            "issue_staff_app_session_lifecycle("
            "uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)"
        ): (False, True),
        (
            "issue_resident_app_session_lifecycle("
            "text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)"
        ): (False, True),
        (
            "issue_external_resident_app_session_lifecycle("
            "text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)"
        ): (False, True),
        "resolve_app_session_lifecycle(bytea,integer)": (True, True),
        "touch_app_session_lifecycle(bytea,uuid,integer,integer)": (
            True,
            True,
        ),
        "validate_app_session_csrf(bytea,uuid,bytea)": (True, True),
        (
            "rotate_app_session_lifecycle("
            "bytea,uuid,uuid,bytea,bytea,integer,bytea)"
        ): (True, False),
        "revoke_app_session_family_for_logout(bytea,bytea,text)": (
            False,
            True,
        ),
    }
    retired_helper_access = {
        (
            "issue_staff_app_session("
            "uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)"
        ): (False, True),
        (
            "issue_resident_app_session("
            "text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)"
        ): (False, True),
        (
            "issue_external_resident_app_session("
            "text,text,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)"
        ): (False, True),
        "resolve_app_session(bytea,boolean,integer)": (True, True),
        (
            "rotate_app_session("
            "bytea,uuid,uuid,bytea,bytea,integer,bytea)"
        ): (True, False),
    }

    all_signatures = list(new_helper_access | retired_helper_access)
    rows = {
        str(row["signature"]): row
        for row in connection.execute(
            text(
                """
                SELECT
                    requested.signature,
                    procedure.oid IS NOT NULL AS helper_exists,
                    COALESCE(
                        has_function_privilege(
                            'mata_app_runtime',
                            procedure.oid,
                            'EXECUTE'
                        ),
                        false
                    ) AS runtime_execute,
                    COALESCE(
                        has_function_privilege(
                            'mata_auth_internal',
                            procedure.oid,
                            'EXECUTE'
                        ),
                        false
                    ) AS auth_execute
                FROM unnest(CAST(:signatures AS text[]))
                    AS requested(signature)
                LEFT JOIN pg_proc AS procedure
                  ON procedure.oid = to_regprocedure(
                      'mata_rls.' || requested.signature
                  )
                ORDER BY requested.signature
                """
            ),
            {"signatures": all_signatures},
        ).mappings()
    }

    assert revision in {
        "20260726_000026",
        "20260727_000027",
        "20260728_000028",
    }
    for signature, expected_access in retired_helper_access.items():
        row = rows[signature]
        assert row["helper_exists"] is True
        assert (row["runtime_execute"], row["auth_execute"]) == (
            (False, False)
            if revision in {"20260727_000027", "20260728_000028"}
            else expected_access
        )

    for signature, expected_access in new_helper_access.items():
        row = rows[signature]
        if revision in {"20260727_000027", "20260728_000028"}:
            assert row["helper_exists"] is True
            assert (row["runtime_execute"], row["auth_execute"]) == (
                expected_access
            )
        else:
            assert row["helper_exists"] is False
            assert row["runtime_execute"] is False
            assert row["auth_execute"] is False


def _cutover_data_snapshot(
    connection: Connection,
    *,
    programme_id: UUID,
    user_id: UUID,
) -> dict[str, tuple[Any, ...]]:
    programme = connection.execute(
        text(
            """
            SELECT id, code, name, ay_date_category,
                   r_year_required, is_subspecialty
            FROM programmes
            WHERE id = :programme_id
            """
        ),
        {"programme_id": programme_id},
    ).one()
    user = connection.execute(
        text(
            """
            SELECT id, email, role, name, admin_level, is_active,
                   session_generation, session_issuance_blocked
            FROM users
            WHERE id = :user_id
            """
        ),
        {"user_id": user_id},
    ).one()
    return {
        "programme": tuple(programme),
        "user": tuple(user),
    }


def test_full_rls_cutover_clean_populated_downgrade_and_reupgrade_lifecycle(
    clean_migration_database: MigrationHarness,
) -> None:
    harness = clean_migration_database

    # A single clean upgrade exercises the full chain, including 000025, before
    # checking the 000026 catalogue installed on an empty database.
    _run_success(harness, "upgrade", "20260726_000026")
    with harness.engine.connect() as connection:
        _assert_cutover_revision_state(
            connection,
            revision="20260726_000026",
        )

    _run_success(harness, "downgrade", "20260726_000025")
    with harness.engine.connect() as connection:
        _assert_cutover_revision_state(
            connection,
            revision="20260726_000025",
        )

    programme_id = uuid4()
    programme_code = f"LC{uuid4().hex[:12].upper()}"
    user_id = uuid4()
    with harness.engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO programmes (
                    id, code, name, ay_date_category
                )
                VALUES (
                    :programme_id,
                    :programme_code,
                    'H-E lifecycle programme',
                    'non_im_subspec'
                )
                """
            ),
            {
                "programme_id": programme_id,
                "programme_code": programme_code,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO users (
                    id, email, password_hash, role, name, admin_level
                )
                VALUES (
                    :user_id,
                    :email,
                    'migration-lifecycle-only',
                    'admin',
                    'H-E lifecycle Master Admin',
                    'master'
                )
                """
            ),
            {
                "user_id": user_id,
                "email": f"{user_id.hex}@example.invalid",
            },
        )
        populated_snapshot = _cutover_data_snapshot(
            connection,
            programme_id=programme_id,
            user_id=user_id,
        )

    _run_success(harness, "upgrade", "20260726_000026")
    with harness.engine.connect() as connection:
        _assert_cutover_revision_state(
            connection,
            revision="20260726_000026",
        )
        assert _cutover_data_snapshot(
            connection,
            programme_id=programme_id,
            user_id=user_id,
        ) == populated_snapshot
        _assert_session_lifecycle_helper_state(
            connection,
            revision="20260726_000026",
        )

    session_id = uuid4()
    token_digest = uuid4().bytes + uuid4().bytes
    csrf_digest = uuid4().bytes + uuid4().bytes
    with harness.engine.begin() as connection:
        connection.execute(
            text(
                """
                WITH observed AS MATERIALIZED (
                    SELECT clock_timestamp() AS created_at
                )
                INSERT INTO app_sessions (
                    id,
                    token_digest,
                    subject_type,
                    subject_id,
                    subject_session_generation,
                    session_family_id,
                    auth_source,
                    csrf_token_digest,
                    created_at,
                    last_seen_at,
                    idle_expires_at,
                    absolute_expires_at
                )
                SELECT
                    :session_id,
                    :token_digest,
                    'staff',
                    :user_id,
                    0,
                    :session_id,
                    'supabase_staff',
                    :csrf_digest,
                    observed.created_at,
                    observed.created_at,
                    observed.created_at + interval '1 hour',
                    observed.created_at + interval '8 hours'
                FROM observed
                """
            ),
            {
                "session_id": session_id,
                "token_digest": token_digest,
                "user_id": user_id,
                "csrf_digest": csrf_digest,
            },
        )
        session_snapshot = tuple(
            connection.execute(
                text(
                    """
                    SELECT
                        id,
                        token_digest,
                        subject_type,
                        subject_id,
                        subject_session_generation,
                        session_family_id,
                        auth_source,
                        csrf_token_digest,
                        created_at,
                        last_seen_at,
                        idle_expires_at,
                        absolute_expires_at,
                        revoked_at,
                        revoked_reason,
                        rotated_from_session_id,
                        user_agent_hash
                    FROM app_sessions
                    WHERE id = :session_id
                    """
                ),
                {"session_id": session_id},
            ).one()
        )

    _run_success(harness, "upgrade", "20260727_000027")
    with harness.engine.connect() as connection:
        _assert_cutover_revision_state(
            connection,
            revision="20260727_000027",
        )
        _assert_session_lifecycle_helper_state(
            connection,
            revision="20260727_000027",
        )
        assert tuple(
            connection.execute(
                text("SELECT * FROM app_sessions WHERE id = :session_id"),
                {"session_id": session_id},
            ).one()
        ) == session_snapshot

    _run_success(harness, "downgrade", "20260726_000026")
    with harness.engine.connect() as connection:
        _assert_cutover_revision_state(
            connection,
            revision="20260726_000026",
        )
        _assert_session_lifecycle_helper_state(
            connection,
            revision="20260726_000026",
        )
        assert tuple(
            connection.execute(
                text("SELECT * FROM app_sessions WHERE id = :session_id"),
                {"session_id": session_id},
            ).one()
        ) == session_snapshot

    _run_success(harness, "upgrade", "20260727_000027")
    with harness.engine.connect() as connection:
        _assert_cutover_revision_state(
            connection,
            revision="20260727_000027",
        )
        _assert_session_lifecycle_helper_state(
            connection,
            revision="20260727_000027",
        )
        assert tuple(
            connection.execute(
                text("SELECT * FROM app_sessions WHERE id = :session_id"),
                {"session_id": session_id},
            ).one()
        ) == session_snapshot

    _run_success(harness, "downgrade", "20260726_000025")
    with harness.engine.connect() as connection:
        _assert_cutover_revision_state(
            connection,
            revision="20260726_000025",
        )
        assert _cutover_data_snapshot(
            connection,
            programme_id=programme_id,
            user_id=user_id,
        ) == populated_snapshot

    _run_success(harness, "upgrade", "20260726_000026")
    with harness.engine.connect() as connection:
        _assert_cutover_revision_state(
            connection,
            revision="20260726_000026",
        )
        assert _cutover_data_snapshot(
            connection,
            programme_id=programme_id,
            user_id=user_id,
        ) == populated_snapshot

        _assert_session_lifecycle_helper_state(
            connection,
            revision="20260726_000026",
        )

    _run_success(harness, "upgrade", "20260727_000027")
    with harness.engine.connect() as connection:
        _assert_cutover_revision_state(
            connection,
            revision="20260727_000027",
        )
        _assert_session_lifecycle_helper_state(
            connection,
            revision="20260727_000027",
        )
        assert tuple(
            connection.execute(
                text("SELECT * FROM app_sessions WHERE id = :session_id"),
                {"session_id": session_id},
            ).one()
        ) == session_snapshot


def test_adhoc_creator_backfill_populated_downgrade_and_reupgrade(
    clean_migration_database: MigrationHarness,
) -> None:
    harness = clean_migration_database
    _run_success(harness, "upgrade", "20260727_000027")
    with harness.engine.begin() as connection:
        ids = _seed_adhoc_creator_backfill(connection, case="valid")

    for action, revision in (
        ("upgrade", "20260728_000028"),
        ("downgrade", "20260727_000027"),
        ("upgrade", "20260728_000028"),
    ):
        _run_success(harness, action, revision)
        with harness.engine.connect() as connection:
            assert _revision(connection) == revision
            if revision == "20260727_000027":
                assert _adhoc_creator_columns(connection) == set()
                assert connection.scalar(
                    text(
                        """
                        SELECT pg_catalog.to_regprocedure(
                            'mata_rls.create_adhoc_attendance('
                            'text,text,text,text,text,date,time without time zone,'
                            'time without time zone,numeric,uuid)'
                        )
                        """
                    )
                ) is None
                assert connection.scalar(
                    text(
                        """
                        SELECT
                            has_table_privilege(
                                'mata_adhoc_attendance_definer',
                                'public.teaching_events',
                                'INSERT'
                            )
                            OR has_function_privilege(
                                'mata_adhoc_attendance_definer',
                                'public.gen_random_uuid()',
                                'EXECUTE'
                            )
                        """
                    )
                ) is False
                continue

            assert _adhoc_creator_columns(connection) == {
                "created_by_resident_id",
                "created_by_external_resident_id",
            }
            definer = connection.execute(
                text(
                    """
                    SELECT
                        role.rolcanlogin,
                        role.rolinherit,
                        role.rolsuper,
                        role.rolbypassrls,
                        role.rolcreatedb,
                        role.rolcreaterole,
                        role.rolreplication,
                        NOT EXISTS (
                            SELECT 1
                            FROM pg_catalog.pg_auth_members AS membership
                            WHERE membership.member = role.oid
                               OR membership.roleid = role.oid
                        ) AS has_no_memberships,
                        owner.rolname AS function_owner,
                        has_function_privilege(
                            role.oid,
                            'public.gen_random_uuid()',
                            'EXECUTE'
                        ) AS can_generate_uuid,
                        has_function_privilege(
                            role.oid,
                            'mata_rls.current_subject_type()',
                            'EXECUTE'
                        ) AS can_read_subject_type,
                        has_function_privilege(
                            role.oid,
                            'mata_rls.current_subject_id()',
                            'EXECUTE'
                        ) AS can_read_subject_id
                    FROM pg_catalog.pg_roles AS role
                    JOIN pg_catalog.pg_proc AS helper
                      ON helper.oid = pg_catalog.to_regprocedure(
                          'mata_rls.create_adhoc_attendance('
                          'text,text,text,text,text,date,'
                          'time without time zone,'
                          'time without time zone,numeric,uuid)'
                      )
                    JOIN pg_catalog.pg_roles AS owner
                      ON owner.oid = helper.proowner
                    WHERE role.rolname
                        = 'mata_adhoc_attendance_definer'
                    """
                )
            ).mappings().one()
            assert tuple(definer.values()) == (
                False,
                False,
                False,
                True,
                False,
                False,
                False,
                True,
                "mata_adhoc_attendance_definer",
                True,
                True,
                True,
            )
            definer_table_privileges = {
                (
                    str(row["table_name"]),
                    str(row["privilege_type"]),
                )
                for row in connection.execute(
                    text(
                        """
                        SELECT
                            relation.relname AS table_name,
                            privilege.privilege_type
                        FROM pg_catalog.pg_class AS relation
                        JOIN pg_catalog.pg_namespace AS namespace
                          ON namespace.oid = relation.relnamespace
                        CROSS JOIN LATERAL pg_catalog.aclexplode(
                            relation.relacl
                        ) AS privilege
                        WHERE namespace.nspname = 'public'
                          AND relation.relkind IN ('r', 'p')
                          AND privilege.grantee = pg_catalog.to_regrole(
                              'mata_adhoc_attendance_definer'
                          )
                        """
                    )
                ).mappings()
            }
            select_tables = {
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
            assert definer_table_privileges == {
                *((table_name, "SELECT") for table_name in select_tables),
                ("attendance_records", "INSERT"),
                ("external_attendance_records", "INSERT"),
                ("teaching_events", "INSERT"),
            }
            creator_rows = {
                UUID(str(row["id"])): (
                    row["created_by_resident_id"],
                    row["created_by_external_resident_id"],
                )
                for row in connection.execute(
                    text(
                        """
                        SELECT id, created_by_resident_id,
                               created_by_external_resident_id
                        FROM teaching_events
                        WHERE id IN (:native_event, :external_event)
                        """
                    ),
                    {
                        "native_event": ids["native_event"],
                        "external_event": ids["external_event"],
                    },
                ).mappings()
            }
            assert creator_rows[ids["native_event"]] == (
                ids["native_a"],
                None,
            )
            assert creator_rows[ids["external_event"]] == (
                None,
                ids["external"],
            )


@pytest.mark.parametrize("case", ["orphaned", "ambiguous", "mixed"])
def test_adhoc_creator_backfill_rejects_non_deterministic_history(
    clean_migration_database: MigrationHarness,
    case: str,
) -> None:
    harness = clean_migration_database
    _run_success(harness, "upgrade", "20260727_000027")
    with harness.engine.begin() as connection:
        _seed_adhoc_creator_backfill(connection, case=case)

    result = harness.alembic("upgrade", "20260728_000028")
    assert result.returncode != 0
    assert "Cannot infer immutable ad-hoc creator" in (
        result.stdout + result.stderr
    )
    with harness.engine.connect() as connection:
        assert _revision(connection) == "20260727_000027"
        assert _adhoc_creator_columns(connection) == set()


def test_external_registration_migration_lifecycle_on_clean_postgres(
    clean_migration_database: MigrationHarness,
) -> None:
    harness = clean_migration_database
    target_codes = {code for _row_id, code in EXPECTED_POSTING_CODE_ROWS}
    first_owned_id = UUID(EXPECTED_POSTING_CODE_ROWS[0][0])

    _run_success(harness, "upgrade", "20260717_000019")
    with harness.engine.connect() as connection:
        assert _revision(connection) == "20260717_000019"
        _assert_stage_one_mappings(connection)
        assert _target_posting_rows(connection) == []
        baseline_rows = _posting_rows(connection)

    collision_code = f"MigrationCollision{uuid4().hex[:10]}"
    with harness.engine.begin() as connection:
        connection.execute(
            text("INSERT INTO posting_codes (id, code) VALUES (:row_id, :code)"),
            {"row_id": first_owned_id, "code": collision_code},
        )
    with harness.engine.connect() as connection:
        collision_snapshot = _posting_rows(connection)

    collision_result = harness.alembic("upgrade", "20260721_000020")
    assert collision_result.returncode != 0
    assert "Deterministic posting-code UUID collision" in (
        collision_result.stdout + collision_result.stderr
    )
    with harness.engine.connect() as connection:
        assert _revision(connection) == "20260717_000019"
        assert _posting_rows(connection) == collision_snapshot
        assert _target_posting_rows(connection) == []
    with harness.engine.begin() as connection:
        connection.execute(
            text("DELETE FROM posting_codes WHERE id = :row_id AND code = :code"),
            {"row_id": first_owned_id, "code": collision_code},
        )

    preexisting_id = uuid4()
    with harness.engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO posting_codes (
                    id, code, display_name, institution, department,
                    billing_dept, is_emergency, supports_secretary_events
                )
                VALUES (
                    :row_id, 'NSCDermat', 'Existing dermatology', 'NSC',
                    'Dermatology', 'EXISTING', true, true
                )
                """
            ),
            {"row_id": preexisting_id},
        )
        preexisting_before = _posting_row_by_id(connection, preexisting_id)

    _run_success(harness, "upgrade", "20260721_000020")
    with harness.engine.connect() as connection:
        assert _revision(connection) == "20260721_000020"
        _assert_stage_one_mappings(connection)
        preexisting_after = _posting_row_by_id(connection, preexisting_id)
        assert preexisting_after == preexisting_before
        target_rows = _target_posting_rows(connection)
        assert len(target_rows) == 10
        assert sum(UUID(str(row["id"])) == preexisting_id for row in target_rows) == 1
        assert [row for row in _posting_rows(connection) if row[1] not in target_codes] == (
            baseline_rows
        )

    _run_success(harness, "downgrade", "20260717_000019")
    with harness.engine.connect() as connection:
        assert _revision(connection) == "20260717_000019"
        remaining_targets = _target_posting_rows(connection)
        assert len(remaining_targets) == 1
        assert UUID(str(remaining_targets[0]["id"])) == preexisting_id
        assert (
            tuple(remaining_targets[0][key] for key in POSTING_ROW_KEYS)
            == preexisting_before
        )
    with harness.engine.begin() as connection:
        connection.execute(
            text("DELETE FROM posting_codes WHERE id = :row_id AND code = 'NSCDermat'"),
            {"row_id": preexisting_id},
        )

    _run_success(harness, "upgrade", "20260721_000020")
    with harness.engine.connect() as connection:
        assert _revision(connection) == "20260721_000020"
        _assert_stage_one_mappings(connection)
        _assert_clean_seeded_codes(connection)
        assert [row for row in _posting_rows(connection) if row[1] not in target_codes] == (
            baseline_rows
        )

    _run_success(harness, "upgrade", "20260721_000021")
    with harness.engine.connect() as connection:
        assert _revision(connection) == "20260721_000021"
        _assert_stage_two_mappings(connection)

    _run_success(harness, "downgrade", "20260721_000020")
    with harness.engine.connect() as connection:
        assert _revision(connection) == "20260721_000020"
        _assert_stage_one_mappings(connection)
        _assert_clean_seeded_codes(connection)

    with harness.engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE programme_institution_posting_map
                SET posting_code = 'NSCDermat'
                WHERE programme_code = 'FM'
                  AND institution_code = 'TTSH'
                """
            )
        )
    with harness.engine.connect() as connection:
        fk_protected_snapshot = _posting_rows(connection)

    protected_result = harness.alembic("downgrade", "20260717_000019")
    assert protected_result.returncode != 0
    with harness.engine.connect() as connection:
        assert _revision(connection) == "20260721_000020"
        assert _posting_rows(connection) == fk_protected_snapshot
        _assert_clean_seeded_codes(connection)
    with harness.engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE programme_institution_posting_map
                SET posting_code = NULL
                WHERE programme_code = 'FM'
                  AND institution_code = 'TTSH'
                """
            )
        )

    _run_success(harness, "downgrade", "20260717_000019")
    with harness.engine.connect() as connection:
        assert _revision(connection) == "20260717_000019"
        _assert_stage_one_mappings(connection)
        assert _target_posting_rows(connection) == []
        assert _posting_rows(connection) == baseline_rows

    _run_success(harness, "upgrade", "20260721_000021")
    with harness.engine.connect() as connection:
        assert _revision(connection) == "20260721_000021"
        _assert_clean_seeded_codes(connection)
        _assert_stage_two_mappings(connection)


def _external_posting_base_rows(connection: Connection) -> list[tuple[Any, ...]]:
    return [
        tuple(row)
        for row in connection.execute(
            text(
                """
                SELECT id, external_resident_id, posting_code, start_date, end_date,
                       is_current, created_at, updated_at
                FROM external_resident_postings
                ORDER BY id
                """
            )
        ).all()
    ]


def _external_posting_programmes(connection: Connection) -> dict[str, str | None]:
    return {
        str(row["posting_code"]): (
            str(row["programme_code"])
            if row["programme_code"] is not None
            else None
        )
        for row in connection.execute(
            text(
                """
                SELECT posting_code, programme_code
                FROM external_resident_postings
                ORDER BY posting_code
                """
            )
        ).mappings()
    }


def _assert_posting_programme_schema(connection: Connection) -> None:
    column = connection.execute(
        text(
            """
            SELECT data_type, character_maximum_length, is_nullable
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'external_resident_postings'
              AND column_name = 'programme_code'
            """
        )
    ).one()
    assert tuple(column) == ("character varying", 20, "YES")

    foreign_key = connection.execute(
        text(
            """
            SELECT ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_schema = tc.constraint_schema
             AND ccu.constraint_name = tc.constraint_name
            WHERE tc.table_schema = current_schema()
              AND tc.table_name = 'external_resident_postings'
              AND tc.constraint_name =
                  'fk_external_resident_postings_programme_code_programmes'
              AND tc.constraint_type = 'FOREIGN KEY'
            """
        )
    ).one()
    assert tuple(foreign_key) == ("programmes", "code")

    index_definition = connection.scalar(
        text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND tablename = 'external_resident_postings'
              AND indexname = 'idx_external_resident_postings_external_scope_dates'
            """
        )
    )
    assert index_definition is not None
    assert (
        "(external_resident_id, posting_code, programme_code, start_date, end_date)"
        in str(index_definition)
    )


def test_external_posting_programme_migration_backfills_only_unique_mappings(
    clean_migration_database: MigrationHarness,
    request: pytest.FixtureRequest,
) -> None:
    harness = clean_migration_database
    _run_success(harness, "upgrade", "20260721_000021")

    posting_codes = (
        "TTSHGerMed",
        "TTSHGenMed",
        "TTSHGenSrg",
        "KTPHGerMed",
        "TTSHCardio",
    )
    resident_rows = []
    posting_rows = []
    for position, posting_code in enumerate(posting_codes):
        resident_id = uuid4()
        resident_rows.append(
            {
                "id": resident_id,
                "name": f"Legacy migration resident {position}",
                "mcr": f"MIG{uuid4().hex[:12].upper()}",
                "posting_code": posting_code,
            }
        )
        posting_rows.append(
            {
                "id": uuid4(),
                "external_resident_id": resident_id,
                "posting_code": posting_code,
                "start_date": date(2026, position + 1, 1),
                "end_date": date(2026, position + 1, 28),
            }
        )

    def restore_fixture_state() -> None:
        with harness.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    DELETE FROM external_resident_postings
                    WHERE id = ANY(CAST(:ids AS uuid[]))
                    """
                ),
                {"ids": [row["id"] for row in posting_rows]},
            )
            connection.execute(
                text(
                    """
                    DELETE FROM external_residents
                    WHERE id = ANY(CAST(:ids AS uuid[]))
                    """
                ),
                {"ids": [row["id"] for row in resident_rows]},
            )
            connection.execute(
                text(
                    """
                    UPDATE programme_institution_posting_map
                    SET posting_code = NULL
                    WHERE programme_code = 'FM'
                      AND institution_code = 'TTSH'
                      AND status = 'inactive'
                    """
                )
            )

    request.addfinalizer(restore_fixture_state)

    with harness.engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE programme_institution_posting_map
                SET posting_code = 'TTSHCardio'
                WHERE programme_code = 'FM'
                  AND institution_code = 'TTSH'
                  AND status = 'inactive'
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO external_residents (
                    id, name, mcr, home_cluster, current_nhg_posting_code, status
                )
                VALUES (
                    :id, :name, :mcr, 'NUH', :posting_code, 'active'
                )
                """
            ),
            resident_rows,
        )
        connection.execute(
            text(
                """
                INSERT INTO external_resident_postings (
                    id, external_resident_id, posting_code,
                    start_date, end_date, is_current
                )
                VALUES (
                    :id, :external_resident_id, :posting_code,
                    :start_date, :end_date, true
                )
                """
            ),
            posting_rows,
        )

    with harness.engine.connect() as connection:
        base_rows = _external_posting_base_rows(connection)
        resident_snapshot = connection.execute(
            text(
                """
                SELECT id, name, mcr, home_cluster, current_nhg_posting_code,
                       status, created_at, updated_at
                FROM external_residents
                ORDER BY id
                """
            )
        ).all()
        mapping_snapshot = connection.execute(
            text(
                """
                SELECT id, programme_code, institution_code, posting_code, status,
                       display_order, created_at, updated_at
                FROM programme_institution_posting_map
                ORDER BY id
                """
            )
        ).all()

    _run_success(harness, "upgrade", "20260721_000022")
    with harness.engine.connect() as connection:
        assert _revision(connection) == "20260721_000022"
        _assert_posting_programme_schema(connection)
        assert _external_posting_base_rows(connection) == base_rows
        assert _external_posting_programmes(connection) == {
            "KTPHGerMed": None,
            "TTSHCardio": None,
            "TTSHGenMed": None,
            "TTSHGenSrg": None,
            "TTSHGerMed": "GERI",
        }
        assert connection.execute(
            text(
                """
                SELECT id, name, mcr, home_cluster, current_nhg_posting_code,
                       status, created_at, updated_at
                FROM external_residents
                ORDER BY id
                """
            )
        ).all() == resident_snapshot
        assert connection.execute(
            text(
                """
                SELECT id, programme_code, institution_code, posting_code, status,
                       display_order, created_at, updated_at
                FROM programme_institution_posting_map
                ORDER BY id
                """
            )
        ).all() == mapping_snapshot

    with pytest.raises(IntegrityError):
        with harness.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE external_resident_postings
                    SET programme_code = 'NOT_A_PROGRAMME'
                    WHERE posting_code = 'TTSHGenMed'
                    """
                )
            )

    _run_success(harness, "downgrade", "20260721_000021")
    with harness.engine.connect() as connection:
        assert _revision(connection) == "20260721_000021"
        assert not connection.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'external_resident_postings'
                      AND column_name = 'programme_code'
                )
                """
            )
        )
        assert _external_posting_base_rows(connection) == base_rows

    _run_success(harness, "upgrade", "20260721_000022")
    with harness.engine.connect() as connection:
        assert _revision(connection) == "20260721_000022"
        _assert_posting_programme_schema(connection)
        assert _external_posting_base_rows(connection) == base_rows
        assert _external_posting_programmes(connection) == {
            "KTPHGerMed": None,
            "TTSHCardio": None,
            "TTSHGenMed": None,
            "TTSHGenSrg": None,
            "TTSHGerMed": "GERI",
        }
