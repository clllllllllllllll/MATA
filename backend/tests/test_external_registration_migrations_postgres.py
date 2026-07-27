from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
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
H_E_DISPOSABLE_DATABASE_NAME = "mata_phase5b_verify_5bhe"
_H_E_QUOTED_DATABASE_NAME = f'"{H_E_DISPOSABLE_DATABASE_NAME}"'
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
    *,
    h_e_restricted: bool,
) -> None:
    database = url.database or ""
    if h_e_restricted:
        if (
            url.drivername not in _SYNC_POSTGRES_DRIVERS
            or (url.host or "").casefold() not in _LOCAL_POSTGRES_HOSTS
            or database != H_E_DISPOSABLE_DATABASE_NAME
            or not url.username
            or bool(url.query)
        ):
            pytest.fail(
                "H-E migration lifecycle tests require the exact named local "
                f"disposable database {H_E_DISPOSABLE_DATABASE_NAME}",
                pytrace=False,
            )
        return

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
                       login_role.rolcreatedb AS login_can_create_database,
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
            or not (
                identity["login_can_create_database"]
                or identity["login_is_superuser"]
            )
        ):
            pytest.fail(
                "H-E lifecycle owner credentials must directly own and be able "
                "to recreate the exact named disposable database",
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


def _assert_h_e_admin_rebuild_boundary(
    connection: Connection,
    *,
    require_target: bool,
) -> bool:
    admin_identity = connection.execute(
        text(
            """
            SELECT current_database() AS database_name,
                   current_user::text AS current_role,
                   session_user::text AS session_role,
                   login_role.rolcreatedb AS login_can_create_database,
                   login_role.rolsuper AS login_is_superuser
            FROM pg_catalog.pg_roles AS login_role
            WHERE login_role.rolname = session_user
            """
        )
    ).mappings().one()
    if (
        admin_identity["database_name"] != "postgres"
        or admin_identity["current_role"] != admin_identity["session_role"]
        or not (
            admin_identity["login_can_create_database"]
            or admin_identity["login_is_superuser"]
        )
    ):
        pytest.fail(
            "H-E lifecycle rebuild requires a direct local administrative "
            "connection that can recreate the disposable database",
            pytrace=False,
        )

    target = connection.execute(
        text(
            """
            SELECT owner_role.rolname AS database_owner
            FROM pg_catalog.pg_database AS db
            JOIN pg_catalog.pg_roles AS owner_role
              ON owner_role.oid = db.datdba
            WHERE db.datname = :database_name
            """
        ),
        {"database_name": H_E_DISPOSABLE_DATABASE_NAME},
    ).mappings().one_or_none()
    if target is None:
        if require_target:
            pytest.fail(
                "The exact named H-E disposable database does not exist",
                pytrace=False,
            )
        return False
    if target["database_owner"] != admin_identity["session_role"]:
        pytest.fail(
            "Refusing to rebuild an H-E disposable database not owned by the "
            "direct migration login",
            pytrace=False,
        )
    return True


def _rebuild_h_e_database(
    admin_engine: Engine,
    *,
    require_existing: bool,
) -> None:
    with admin_engine.connect() as connection:
        target_exists = _assert_h_e_admin_rebuild_boundary(
            connection,
            require_target=require_existing,
        )
        if target_exists:
            connection.execute(
                text(
                    """
                    SELECT pg_catalog.pg_terminate_backend(pid)
                    FROM pg_catalog.pg_stat_activity
                    WHERE datname = :database_name
                      AND pid <> pg_catalog.pg_backend_pid()
                    """
                ),
                {"database_name": H_E_DISPOSABLE_DATABASE_NAME},
            )
            connection.exec_driver_sql(
                f"DROP DATABASE {_H_E_QUOTED_DATABASE_NAME}"
            )
            remaining = connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_catalog.pg_database
                    WHERE datname = :database_name
                    """
                ),
                {"database_name": H_E_DISPOSABLE_DATABASE_NAME},
            )
            assert remaining == 0

        connection.exec_driver_sql(
            f"CREATE DATABASE {_H_E_QUOTED_DATABASE_NAME}"
        )
        recreated_owner = connection.scalar(
            text(
                """
                SELECT owner_role.rolname
                FROM pg_catalog.pg_database AS db
                JOIN pg_catalog.pg_roles AS owner_role
                  ON owner_role.oid = db.datdba
                WHERE db.datname = :database_name
                """
            ),
            {"database_name": H_E_DISPOSABLE_DATABASE_NAME},
        )
        assert recreated_owner == connection.scalar(text("SELECT session_user"))


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
    h_e_restricted = settings.database_rls_enabled
    _assert_local_postgres_source(
        source_url,
        h_e_restricted=h_e_restricted,
    )
    repository_head = (
        _repository_head_revision() if h_e_restricted else None
    )
    if h_e_restricted:
        database_name = H_E_DISPOSABLE_DATABASE_NAME
        assert repository_head is not None
    else:
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
    h_e_rebuild_authorized = False
    quoted_name = (
        _H_E_QUOTED_DATABASE_NAME
        if h_e_restricted
        else f'"{database_name}"'
    )
    environment = os.environ.copy()
    environment["SYNC_DATABASE_URL"] = target_url.render_as_string(
        hide_password=False
    )
    if not h_e_restricted:
        environment["DATABASE_URL"] = target_url.set(
            drivername="postgresql+asyncpg"
        ).render_as_string(hide_password=False)
    environment["ENVIRONMENT"] = "test"
    environment["AUTH_MODE"] = "stub"
    try:
        if h_e_restricted:
            probe_engine = create_engine(target_url, poolclass=NullPool)
            try:
                _assert_h_e_target_ready(
                    probe_engine,
                    repository_head=repository_head,
                )
            finally:
                probe_engine.dispose()
            with admin_engine.connect() as connection:
                _assert_h_e_admin_rebuild_boundary(
                    connection,
                    require_target=True,
                )
            h_e_rebuild_authorized = True
            _rebuild_h_e_database(
                admin_engine,
                require_existing=True,
            )
        else:
            with admin_engine.connect() as connection:
                connection.exec_driver_sql(f"CREATE DATABASE {quoted_name}")
            created = True

        target_engine = create_engine(target_url, poolclass=NullPool)
        yield MigrationHarness(
            database_name=database_name,
            engine=target_engine,
            environment=environment,
        )
    finally:
        if target_engine is not None:
            target_engine.dispose()
        try:
            if h_e_restricted and h_e_rebuild_authorized:
                assert repository_head is not None
                _rebuild_h_e_database(
                    admin_engine,
                    require_existing=False,
                )
                restored_engine = create_engine(target_url, poolclass=NullPool)
                try:
                    restored_harness = MigrationHarness(
                        database_name=database_name,
                        engine=restored_engine,
                        environment=environment,
                    )
                    restore_result = restored_harness.alembic("upgrade", "head")
                    assert restore_result.returncode == 0, (
                        restore_result.stdout + restore_result.stderr
                    )
                    _assert_h_e_target_ready(
                        restored_engine,
                        repository_head=repository_head,
                    )
                finally:
                    restored_engine.dispose()
            elif created:
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
                            "SELECT count(*) FROM pg_database "
                            "WHERE datname = :database_name"
                        ),
                        {"database_name": database_name},
                    )
                    assert remaining == 0
        finally:
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

    if revision == "20260726_000026":
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
