from __future__ import annotations

import pytest

from tests import run_phase_l_e2e_smoke as phase_l_runner
from tests import run_phase_r_postgres_verify as phase_r_runner


def test_phase_l_runner_requires_an_explicit_bootstrap_url() -> None:
    assert phase_l_runner.run([], {}) == 2


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg2://owner:password@db.example.invalid:5432/postgres",
        "postgresql+psycopg2://owner:password@localhost:5432/mata_evolved_ttf_l_verify",
        "postgresql+psycopg2://owner:password@localhost:6543/postgres",
    ],
)
def test_phase_l_bootstrap_url_rejects_non_local_or_target_database(
    database_url: str,
) -> None:
    with pytest.raises(phase_l_runner.PhaseLPostgresRunnerError):
        phase_l_runner._bootstrap_url(
            {phase_l_runner.BOOTSTRAP_DATABASE_URL_ENV: database_url}
        )


def test_phase_l_runner_configuration_is_scoped_and_restored() -> None:
    original_target = phase_r_runner.TARGET_DATABASE_NAME
    original_owner = phase_r_runner.EXPECTED_OWNER_USERNAME

    with phase_l_runner._phase_l_runner_configuration():
        assert phase_r_runner.TARGET_DATABASE_NAME == phase_l_runner.TARGET_DATABASE_NAME
        assert phase_r_runner.EXPECTED_OWNER_USERNAME == phase_l_runner.OWNER_USERNAME
        assert phase_r_runner._generated_role_name("runtime").startswith(
            "mata_phase_l_runtime_"
        )

    assert phase_r_runner.TARGET_DATABASE_NAME == original_target
    assert phase_r_runner.EXPECTED_OWNER_USERNAME == original_owner


@pytest.mark.parametrize(
    ("database_exists", "owner_exists", "role_pattern"),
    [
        (True, False, None),
        (False, True, None),
        (False, False, r"^mata_phase_l_"),
        (False, False, r"^mata_test_"),
        (False, False, r"^mata_e1_"),
    ],
)
def test_phase_l_clean_start_refuses_any_known_generated_resource(
    monkeypatch: pytest.MonkeyPatch,
    database_exists: bool,
    owner_exists: bool,
    role_pattern: str | None,
) -> None:
    connection = object()
    monkeypatch.setattr(
        phase_l_runner._runner,
        "_database_exists",
        lambda received_connection, *, database_name: (
            received_connection is connection
            and database_name == phase_l_runner.TARGET_DATABASE_NAME
            and database_exists
        ),
    )
    monkeypatch.setattr(
        phase_l_runner,
        "_role_exists",
        lambda received_connection, *, role_name: (
            received_connection is connection
            and role_name == phase_l_runner.OWNER_USERNAME
            and owner_exists
        ),
    )
    monkeypatch.setattr(
        phase_l_runner,
        "_named_role_count",
        lambda received_connection, *, pattern: int(
            received_connection is connection and pattern == role_pattern
        ),
    )

    with pytest.raises(phase_l_runner.PhaseLPostgresRunnerError):
        phase_l_runner._assert_clean_start(connection)  # type: ignore[arg-type]
