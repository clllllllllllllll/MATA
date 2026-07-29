"""Attest that the disposable migration database is safe for CI reuse."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
import sys
from time import sleep

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from tests.run_rls_restricted_pytest import (
    DISPOSABLE_DATABASE_NAME,
    POLICY_REVISION,
    RestrictedRlsRunnerError,
    _owner_sync_url,
)


_ATTESTATION_ATTEMPTS = 20
_ATTESTATION_INTERVAL_SECONDS = 0.1


@dataclass(frozen=True, slots=True)
class DatabaseReuseSnapshot:
    database_name: str
    current_role: str
    session_role: str
    database_owner: str
    login_is_superuser: bool
    revision: str
    other_connections: int
    residual_test_roles: int


def _wait_for_database_reuse(
    sample: Callable[[], DatabaseReuseSnapshot],
    *,
    expected_owner: str,
    pause: Callable[[float], None] = sleep,
) -> DatabaseReuseSnapshot:
    for attempt in range(_ATTESTATION_ATTEMPTS):
        snapshot = sample()
        if (
            snapshot.database_name != DISPOSABLE_DATABASE_NAME
            or snapshot.current_role != snapshot.session_role
            or snapshot.session_role != snapshot.database_owner
            or snapshot.session_role != expected_owner
            or not snapshot.login_is_superuser
            or snapshot.revision != POLICY_REVISION
        ):
            raise RestrictedRlsRunnerError(
                "Database-reuse attestation requires the exact local disposable "
                "database at head through its direct owner"
            )
        if (
            snapshot.other_connections == 0
            and snapshot.residual_test_roles == 0
        ):
            return snapshot
        if attempt < _ATTESTATION_ATTEMPTS - 1:
            pause(_ATTESTATION_INTERVAL_SECONDS)

    raise RestrictedRlsRunnerError(
        "Database reuse requires zero competing sessions and zero residual "
        "mata_test_* roles"
    )


def _database_reuse_snapshot(engine: Engine) -> DatabaseReuseSnapshot:
    with engine.connect() as connection:
        identity: Mapping[str, object] = connection.execute(
            text(
                r"""
                SELECT current_database() AS database_name,
                       current_user AS current_role,
                       session_user AS session_role,
                       pg_catalog.pg_get_userbyid(database_row.datdba)
                           AS database_owner,
                       login_role.rolsuper AS login_is_superuser,
                       (
                           SELECT count(*)
                           FROM pg_catalog.pg_stat_activity
                           WHERE datname = current_database()
                             AND pid <> pg_catalog.pg_backend_pid()
                       ) AS other_connections,
                       (
                           SELECT count(*)
                           FROM pg_catalog.pg_roles
                           WHERE rolname LIKE 'mata\_test\_%' ESCAPE '\'
                       ) AS residual_test_roles
                FROM pg_catalog.pg_database AS database_row
                JOIN pg_catalog.pg_roles AS login_role
                  ON login_role.rolname = session_user
                WHERE database_row.datname = current_database()
                """
            )
        ).mappings().one()
        revision = connection.scalar(
            text("SELECT version_num FROM public.alembic_version")
        )

    return DatabaseReuseSnapshot(
        database_name=str(identity["database_name"]),
        current_role=str(identity["current_role"]),
        session_role=str(identity["session_role"]),
        database_owner=str(identity["database_owner"]),
        login_is_superuser=bool(identity["login_is_superuser"]),
        revision=str(revision),
        other_connections=int(identity["other_connections"]),
        residual_test_roles=int(identity["residual_test_roles"]),
    )


def attest_database_reuse(environment: Mapping[str, str]) -> None:
    owner_url = _owner_sync_url(environment)
    engine = create_engine(owner_url, poolclass=NullPool)
    try:
        snapshot = _wait_for_database_reuse(
            lambda: _database_reuse_snapshot(engine),
            expected_owner=str(owner_url.username),
        )
    finally:
        engine.dispose()

    print(
        "PostgreSQL reuse attested: "
        f"database={snapshot.database_name} "
        f"host={owner_url.host}:{owner_url.port or 5432} "
        f"revision={snapshot.revision} "
        "peers=0 residual_test_roles=0",
        flush=True,
    )


def main() -> int:
    try:
        attest_database_reuse(os.environ)
    except RestrictedRlsRunnerError as exc:
        print(f"PostgreSQL reuse attestation aborted: {exc}", file=sys.stderr)
        return 2
    except (SQLAlchemyError, OSError) as exc:
        print(
            "PostgreSQL reuse attestation aborted due to a database failure "
            f"({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
