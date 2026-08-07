from __future__ import annotations

from sqlalchemy.engine import URL

from tests import run_phase_k_postgres_verify as phase_k_runner
from tests import run_phase_r_postgres_verify as phase_r_runner


def test_phase_k_wrapper_applies_and_restores_its_isolated_target(
    monkeypatch,
) -> None:
    original_target = phase_r_runner.TARGET_DATABASE_NAME
    original_owner = phase_r_runner.EXPECTED_OWNER_USERNAME
    observed: dict[str, object] = {}

    def fake_run(pytest_args, environment) -> int:
        observed.update(
            pytest_args=pytest_args,
            environment=environment,
            target=phase_r_runner.TARGET_DATABASE_NAME,
            owner=phase_r_runner.EXPECTED_OWNER_USERNAME,
            generated_role=phase_r_runner._generated_role_name("runtime"),
        )
        return 0

    monkeypatch.setattr(phase_r_runner, "run", fake_run)

    assert phase_k_runner.run(["-q", "tests/test_security_postgres_integration.py"], {}) == 0
    assert observed["target"] == phase_k_runner.TARGET_DATABASE_NAME
    assert observed["owner"] == phase_k_runner.EXPECTED_OWNER_USERNAME
    assert str(observed["generated_role"]).startswith("mata_phase_k_runtime_")
    assert phase_r_runner.TARGET_DATABASE_NAME == original_target
    assert phase_r_runner.EXPECTED_OWNER_USERNAME == original_owner


def test_phase_k_runner_uses_the_explicit_local_sync_owner_variable() -> None:
    assert phase_k_runner.OWNER_DATABASE_URL_ENV == "MATA_PHASE_K_SYNC_DATABASE_URL"


def test_phase_k_targets_require_its_owner_and_allow_a_separate_maintenance_user() -> None:
    owner_url = URL.create(
        "postgresql+psycopg2",
        username=phase_k_runner.EXPECTED_OWNER_USERNAME,
        password="owner-password",
        host="localhost",
        port=5432,
        database=phase_k_runner.TARGET_DATABASE_NAME,
    ).render_as_string(hide_password=False)
    maintenance_url = URL.create(
        "postgresql+psycopg2",
        username="local_maintenance",
        password="maintenance-password",
        host="localhost",
        port=5432,
        database="postgres",
    ).render_as_string(hide_password=False)

    targets = phase_k_runner._phase_k_database_targets(
        {
            phase_k_runner.OWNER_DATABASE_URL_ENV: owner_url,
            phase_k_runner.MAINTENANCE_DATABASE_URL_ENV: maintenance_url,
        }
    )

    assert targets.owner_url.database == phase_k_runner.TARGET_DATABASE_NAME
    assert targets.owner_url.username == phase_k_runner.EXPECTED_OWNER_USERNAME
    assert targets.maintenance_url.username == "local_maintenance"
