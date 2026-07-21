from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, URL, make_url
from sqlalchemy.pool import NullPool

from app.config import Settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
VERSIONS_DIR = BACKEND_ROOT / "alembic" / "versions"

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

    source = (
        VERSIONS_DIR / "20260721_000020_seed_external_registration_posting_codes.py"
    ).read_text(encoding="utf-8")
    assert "ON CONFLICT" not in source.upper()
    assert "WHERE id = :row_id" in source
    assert "AND code = :code" in source


def _assert_local_postgres_source(url: URL) -> None:
    database = url.database or ""
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"localhost", "127.0.0.1"}
        or not (
            database == "mata_db"
            or database.startswith("mata_phase5b_verify_")
        )
    ):
        pytest.fail(
            "Migration lifecycle tests require an approved local MATA database",
            pytrace=False,
        )


@dataclass
class MigrationHarness:
    database_name: str
    engine: Engine
    environment: dict[str, str]

    def alembic(self, action: str, revision: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
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


@pytest.fixture
def clean_migration_database() -> MigrationHarness:
    settings = Settings(_env_file=None)
    source_url = make_url(settings.sync_database_url)
    _assert_local_postgres_source(source_url)
    database_name = f"mata_phase5b_verify_mig_{uuid4().hex[:20]}"
    assert re.fullmatch(r"mata_phase5b_verify_[a-z0-9_]+", database_name)
    assert len(database_name) < 64

    admin_url = source_url.set(database="postgres")
    target_url = source_url.set(database=database_name)
    admin_engine = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    target_engine: Engine | None = None
    created = False
    quoted_name = f'"{database_name}"'
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f"CREATE DATABASE {quoted_name}")
        created = True

        target_engine = create_engine(target_url, poolclass=NullPool)
        environment = os.environ.copy()
        environment["SYNC_DATABASE_URL"] = target_url.render_as_string(
            hide_password=False
        )
        environment["DATABASE_URL"] = target_url.set(
            drivername="postgresql+asyncpg"
        ).render_as_string(hide_password=False)
        environment["ENVIRONMENT"] = "test"
        environment["AUTH_MODE"] = "stub"
        yield MigrationHarness(
            database_name=database_name,
            engine=target_engine,
            environment=environment,
        )
    finally:
        if target_engine is not None:
            target_engine.dispose()
        if created:
            with admin_engine.connect() as connection:
                connection.execute(
                    text(
                        """
                        SELECT pg_terminate_backend(pid)
                        FROM pg_stat_activity
                        WHERE datname = :database_name
                          AND pid <> pg_backend_pid()
                        """
                    ),
                    {"database_name": database_name},
                )
                connection.exec_driver_sql(f"DROP DATABASE {quoted_name}")
                remaining = connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_database WHERE datname = :database_name"
                    ),
                    {"database_name": database_name},
                )
                assert remaining == 0
        admin_engine.dispose()


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
