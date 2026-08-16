from __future__ import annotations

from collections.abc import Iterator
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool

from app.config import Settings
from tests.test_external_registration_migrations_postgres import (
    H_E_DISPOSABLE_DATABASE_NAME,
    MigrationHarness,
    _assert_h_e_target_ready,
    _assert_local_postgres_source,
    _migration_environment,
    _repository_head_revision,
    _revision,
)


PHASE_V_REVISION = "20260812_000040"
CROSS_POSTING_POLICY_REVISION = "20260813_000041"
LOA_CLASSIFICATION_REVISION = "20260813_000042"
CURRENT_HEAD_REVISION = "20260816_000044"

EXPECTED_SECRETARY_POOLS = {
    ("AIM", "TTSHGenMed"),
    ("ANAES", "TTSHAnaes"),
    ("CARDIO", "TTSHCardio"),
    ("DERM", "NSCDermat"),
    ("DR", "TTSHDiagRd"),
    ("EM", "TTSHEmgMed"),
    ("ENDO", "TTSHEndocr"),
    ("ENT", "TTSHOtolar"),
    ("EYE", "TTSHOphtha"),
    ("FM", "NHGPlyNHGPly"),
    ("GASTRO", "TTSHGas"),
    ("GERI", "TTSHGerMed"),
    ("GS", "TTSHGenSrg"),
    ("ID", "TTSHInfect"),
    ("IM", "TTSHGenMed"),
    ("MEDONCO", "TTSHMedOnc"),
    ("ORTHO", "TTSHOrtSrg"),
    ("PATH", "TTSHLabMed"),
    ("PSY", "TTSHPsychi"),
    ("REHAB", "TTSHRehabi"),
    ("RENAL", "TTSHRenal"),
    ("RESPI", "TTSHRespir"),
    ("RHEUM", "TTSHRheuma"),
    ("SPORTSMED", "TTSHOrtSrg(Sports)"),
    ("SIG", "TTSHGenSrg"),
    ("URO", "TTSHUrolog"),
    ("MICROB", "TTSHLabMed"),
    ("PALLMED", "TTSHPallia"),
}


@pytest.fixture
def post_boundary_migration_database(
    request: pytest.FixtureRequest,
) -> Iterator[MigrationHarness]:
    settings = Settings(_env_file=None)
    source_url = make_url(settings.sync_database_url)
    _assert_local_postgres_source(source_url)
    assert _repository_head_revision() == CURRENT_HEAD_REVISION
    engine = create_engine(source_url, poolclass=NullPool)
    harness = MigrationHarness(
        database_name=H_E_DISPOSABLE_DATABASE_NAME,
        engine=engine,
        environment=_migration_environment(source_url),
        request_node=request.node,
    )
    try:
        _assert_h_e_target_ready(
            engine,
            repository_head=CURRENT_HEAD_REVISION,
        )
        yield harness
    finally:
        try:
            restore = harness.alembic("upgrade", CURRENT_HEAD_REVISION)
            assert restore.returncode == 0, restore.stdout + restore.stderr
            _assert_h_e_target_ready(
                engine,
                repository_head=CURRENT_HEAD_REVISION,
            )
        finally:
            engine.dispose()


def _run(
    harness: MigrationHarness,
    action: str,
    revision: str,
) -> None:
    result = harness.alembic(action, revision)
    assert result.returncode == 0, result.stdout + result.stderr


def _attendance_columns(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.scalars(
                text(
                    """
                    SELECT attribute.attname
                    FROM pg_catalog.pg_attribute AS attribute
                    WHERE attribute.attrelid =
                          'public.attendance_records'::pg_catalog.regclass
                      AND attribute.attnum > 0
                      AND NOT attribute.attisdropped
                    """
                )
            )
        )


def _active_secretary_pools(engine: Engine) -> set[tuple[str, str]]:
    with engine.connect() as connection:
        return {
            (str(row["programme_code"]), str(row["posting_code"]))
            for row in connection.execute(
                text(
                    """
                    SELECT programme_code, posting_code
                    FROM secretary_programme_pools
                    WHERE is_active
                      AND can_manage_teaching_names
                    """
                )
            ).mappings()
        }


def _secretary_pool_user_foreign_keys(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_catalog.pg_constraint AS constraint_row
                    WHERE constraint_row.conrelid =
                          'public.secretary_programme_pools'::pg_catalog.regclass
                      AND constraint_row.contype = 'f'
                      AND constraint_row.confrelid =
                          'public.users'::pg_catalog.regclass
                    """
                )
            )
            or 0
        )


@pytest.mark.migration_mutation
@pytest.mark.post_boundary_migration
def test_post_boundary_migrations_downgrade_to_floor_and_reupgrade_to_head(
    post_boundary_migration_database: MigrationHarness,
) -> None:
    harness = post_boundary_migration_database
    loa_columns = {
        "submitted_during_loa",
        "loa_resident_posting_id",
        "loa_type",
        "loa_classified_at",
    }

    with harness.engine.connect() as connection:
        assert _revision(connection) == CURRENT_HEAD_REVISION
    assert loa_columns <= _attendance_columns(harness.engine)
    assert EXPECTED_SECRETARY_POOLS <= _active_secretary_pools(harness.engine)
    assert _secretary_pool_user_foreign_keys(harness.engine) == 0

    _run(harness, "downgrade", CROSS_POSTING_POLICY_REVISION)
    with harness.engine.connect() as connection:
        assert _revision(connection) == CROSS_POSTING_POLICY_REVISION
    assert not loa_columns.intersection(_attendance_columns(harness.engine))
    assert EXPECTED_SECRETARY_POOLS <= _active_secretary_pools(harness.engine)

    _run(harness, "downgrade", PHASE_V_REVISION)
    with harness.engine.connect() as connection:
        assert _revision(connection) == PHASE_V_REVISION
        assert connection.scalar(
            text(
                "SELECT pg_catalog.to_regclass("
                "'public.teaching_name_programme_scopes')"
            )
        ) is not None

    _run(harness, "upgrade", CURRENT_HEAD_REVISION)
    with harness.engine.connect() as connection:
        assert _revision(connection) == CURRENT_HEAD_REVISION
    assert loa_columns <= _attendance_columns(harness.engine)
    assert EXPECTED_SECRETARY_POOLS <= _active_secretary_pools(harness.engine)
