"""Run Phase K checks against one fresh, local disposable PostgreSQL database.

This wrapper reuses the tested Phase R provisioning flow with an isolated Phase
K target and generated-role namespace. It requires explicit local owner and
maintenance URLs and removes only resources created for this verification.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
import os
import re
import sys
from uuid import uuid4

from tests import run_phase_r_postgres_verify as _runner


TARGET_DATABASE_NAME = "mata_evolved_ttf_k_verify"
EXPECTED_OWNER_USERNAME = "mata_phase_k_owner"
OWNER_DATABASE_URL_ENV = "MATA_PHASE_K_SYNC_DATABASE_URL"
MAINTENANCE_DATABASE_URL_ENV = "MATA_PHASE_K_MAINTENANCE_DATABASE_URL"
_PHASE_K_ROLE_RE = re.compile(r"^mata_phase_k_(runtime|auth)_[0-9a-f]{16}$")


def _generated_role_name(kind: str) -> str:
    if kind not in {"runtime", "auth"}:
        raise _runner.PhaseRPostgresRunnerError("Unexpected Phase K role kind")
    return f"mata_phase_k_{kind}_{uuid4().hex[:16]}"


def _phase_k_database_targets(
    environment: Mapping[str, str],
) -> _runner.PhaseRDatabaseTargets:
    owner_url = _runner._configured_local_sync_url(
        environment,
        env_name=OWNER_DATABASE_URL_ENV,
        required_database=TARGET_DATABASE_NAME,
    )
    maintenance_url = _runner._configured_local_sync_url(
        environment,
        env_name=MAINTENANCE_DATABASE_URL_ENV,
        forbidden_database=TARGET_DATABASE_NAME,
    )
    if owner_url.username != EXPECTED_OWNER_USERNAME:
        raise _runner.PhaseRPostgresRunnerError(
            "Phase K owner URL must use the dedicated local migration owner"
        )
    if (
        (owner_url.host or "").casefold() != (maintenance_url.host or "").casefold()
        or _runner._url_port(owner_url, label=OWNER_DATABASE_URL_ENV)
        != _runner._url_port(maintenance_url, label=MAINTENANCE_DATABASE_URL_ENV)
    ):
        raise _runner.PhaseRPostgresRunnerError(
            "Phase K owner and maintenance URLs must use the same local server"
        )
    return _runner.PhaseRDatabaseTargets(
        owner_url=owner_url,
        maintenance_url=maintenance_url,
    )


def _residual_generated_role_count(connection: object) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname ~ %s",
            (_PHASE_K_ROLE_RE.pattern,),
        )
        row = cursor.fetchone()
    return int(row[0])


@contextmanager
def _phase_k_runner_configuration() -> Iterator[None]:
    overrides = {
        "TARGET_DATABASE_NAME": TARGET_DATABASE_NAME,
        "EXPECTED_OWNER_USERNAME": EXPECTED_OWNER_USERNAME,
        "OWNER_DATABASE_URL_ENV": OWNER_DATABASE_URL_ENV,
        "MAINTENANCE_DATABASE_URL_ENV": MAINTENANCE_DATABASE_URL_ENV,
        "_PHASE_R_ROLE_RE": re.compile(r"mata_phase_k_(?:runtime|auth)_[0-9a-f]{16}"),
        "_phase_r_database_targets": _phase_k_database_targets,
        "_generated_role_name": _generated_role_name,
        "_residual_generated_role_count": _residual_generated_role_count,
    }
    originals = {name: getattr(_runner, name) for name in overrides}
    try:
        for name, value in overrides.items():
            setattr(_runner, name, value)
        yield
    finally:
        for name, value in originals.items():
            setattr(_runner, name, value)


def run(pytest_args: Sequence[str], environment: Mapping[str, str]) -> int:
    with _phase_k_runner_configuration():
        return _runner.run(pytest_args, environment)


def main(argv: Sequence[str] | None = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv), os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
