"""Run Phase L smoke checks against a fresh, local disposable PostgreSQL database.

The bootstrap URL is used only to create and remove the dedicated Phase L
owner.  It must name a local maintenance database rather than the disposable
target.  The generated owner credential is held only in this process; child
migrations and tests receive only the owner/runtime/auth URLs they require.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
import os
import re
import secrets
import sys

import psycopg2
from psycopg2 import sql
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from tests import run_phase_r_postgres_verify as _runner


TARGET_DATABASE_NAME = "mata_evolved_ttf_l_verify"
OWNER_USERNAME = "mata_phase_l_owner"
BOOTSTRAP_DATABASE_URL_ENV = "MATA_PHASE_L_BOOTSTRAP_DATABASE_URL"
OWNER_DATABASE_URL_ENV = "MATA_PHASE_L_OWNER_DATABASE_URL"
MAINTENANCE_DATABASE_URL_ENV = "MATA_PHASE_L_MAINTENANCE_DATABASE_URL"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_PHASE_L_ROLE_RE = re.compile(r"mata_phase_l_(?:runtime|auth)_[0-9a-f]{16}")


class PhaseLPostgresRunnerError(RuntimeError):
    """Raised when Phase L's disposable PostgreSQL boundary is unsafe."""


def _bootstrap_url(environment: Mapping[str, str]) -> URL:
    raw_url = environment.get(BOOTSTRAP_DATABASE_URL_ENV, "").strip()
    if not raw_url:
        raise PhaseLPostgresRunnerError(f"{BOOTSTRAP_DATABASE_URL_ENV} is required")
    try:
        url = make_url(raw_url)
    except ArgumentError as exc:
        raise PhaseLPostgresRunnerError(
            f"{BOOTSTRAP_DATABASE_URL_ENV} is not a valid SQLAlchemy database URL"
        ) from exc

    try:
        port = url.port
    except ValueError as exc:
        raise PhaseLPostgresRunnerError(
            f"{BOOTSTRAP_DATABASE_URL_ENV} must include a valid PostgreSQL port"
        ) from exc
    if (
        url.drivername not in {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
        or (url.host or "").casefold() not in _LOCAL_HOSTS
        or port != 5432
        or not url.database
        or url.database == TARGET_DATABASE_NAME
        or not url.username
        or not url.password
        or bool(url.query)
    ):
        raise PhaseLPostgresRunnerError(
            f"{BOOTSTRAP_DATABASE_URL_ENV} must be a credentialed localhost "
            "maintenance PostgreSQL URL on port 5432"
        )
    return url


def _role_exists(connection: psycopg2.extensions.connection, *, role_name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s)",
            (role_name,),
        )
        return bool(cursor.fetchone()[0])


def _named_role_count(
    connection: psycopg2.extensions.connection,
    *,
    pattern: str,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname ~ %s",
            (pattern,),
        )
        return int(cursor.fetchone()[0])


def _assert_clean_start(connection: psycopg2.extensions.connection) -> None:
    if _runner._database_exists(connection, database_name=TARGET_DATABASE_NAME):
        raise PhaseLPostgresRunnerError(
            f"Phase L refuses to reuse existing database {TARGET_DATABASE_NAME}"
        )
    if _role_exists(connection, role_name=OWNER_USERNAME):
        raise PhaseLPostgresRunnerError(
            f"Phase L refuses to reuse existing role {OWNER_USERNAME}"
        )
    if _named_role_count(connection, pattern=r"^mata_phase_l_") != 0:
        raise PhaseLPostgresRunnerError(
            "Phase L refuses to run with existing Phase L runtime/auth roles"
        )
    if _named_role_count(connection, pattern=r"^mata_test_") != 0:
        raise PhaseLPostgresRunnerError(
            "Phase L refuses to run with residual mata_test_* roles"
        )
    if _named_role_count(connection, pattern=r"^mata_e1_") != 0:
        raise PhaseLPostgresRunnerError(
            "Phase L refuses to run with residual mata_e1_* roles"
        )


def _create_owner(
    connection: psycopg2.extensions.connection,
    *,
    password: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN SUPERUSER CREATEDB CREATEROLE REPLICATION "
                "BYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(OWNER_USERNAME), sql.Literal(password))
        )


def _drop_owner(connection: psycopg2.extensions.connection) -> None:
    if not _role_exists(connection, role_name=OWNER_USERNAME):
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_database "
            "WHERE datname = %s",
            (TARGET_DATABASE_NAME,),
        )
        if int(cursor.fetchone()[0]) != 0:
            raise PhaseLPostgresRunnerError(
                "Phase L target database still exists; owner role is retained for safe cleanup"
            )
        cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(OWNER_USERNAME)))


def _assert_complete_cleanup(connection: psycopg2.extensions.connection) -> None:
    if _runner._database_exists(connection, database_name=TARGET_DATABASE_NAME):
        raise PhaseLPostgresRunnerError("Phase L target database was not removed")
    if _role_exists(connection, role_name=OWNER_USERNAME):
        raise PhaseLPostgresRunnerError("Phase L owner role was not removed")
    for pattern in (r"^mata_phase_l_", r"^mata_test_", r"^mata_e1_"):
        if _named_role_count(connection, pattern=pattern) != 0:
            raise PhaseLPostgresRunnerError(
                "Phase L PostgreSQL role cleanup left a generated role behind"
            )


def _phase_l_role_name(kind: str) -> str:
    if kind not in {"runtime", "auth"}:
        raise _runner.PhaseRPostgresRunnerError("Unexpected Phase L role kind")
    return f"mata_phase_l_{kind}_{secrets.token_hex(8)}"


def _phase_l_quoted_role(role_name: str) -> sql.Identifier:
    if _PHASE_L_ROLE_RE.fullmatch(role_name) is None:
        raise _runner.PhaseRPostgresRunnerError("Unexpected Phase L role name")
    return sql.Identifier(role_name)


def _assert_no_phase_l_runtime_roles(connection: psycopg2.extensions.connection) -> None:
    if _named_role_count(
        connection,
        pattern=r"^mata_phase_l_(runtime|auth)_[0-9a-f]{16}$",
    ) != 0:
        raise _runner.PhaseRPostgresRunnerError(
            "Phase L verification found residual generated runtime/auth roles"
        )


@contextmanager
def _phase_l_runner_configuration() -> Iterator[None]:
    originals = {
        "TARGET_DATABASE_NAME": _runner.TARGET_DATABASE_NAME,
        "EXPECTED_OWNER_USERNAME": _runner.EXPECTED_OWNER_USERNAME,
        "OWNER_DATABASE_URL_ENV": _runner.OWNER_DATABASE_URL_ENV,
        "MAINTENANCE_DATABASE_URL_ENV": _runner.MAINTENANCE_DATABASE_URL_ENV,
        "_PHASE_R_ROLE_RE": _runner._PHASE_R_ROLE_RE,
        "_generated_role_name": _runner._generated_role_name,
        "_quoted_generated_role": _runner._quoted_generated_role,
        "_assert_no_residual_generated_roles": _runner._assert_no_residual_generated_roles,
    }
    _runner.TARGET_DATABASE_NAME = TARGET_DATABASE_NAME
    _runner.EXPECTED_OWNER_USERNAME = OWNER_USERNAME
    _runner.OWNER_DATABASE_URL_ENV = OWNER_DATABASE_URL_ENV
    _runner.MAINTENANCE_DATABASE_URL_ENV = MAINTENANCE_DATABASE_URL_ENV
    _runner._PHASE_R_ROLE_RE = _PHASE_L_ROLE_RE
    _runner._generated_role_name = _phase_l_role_name
    _runner._quoted_generated_role = _phase_l_quoted_role
    _runner._assert_no_residual_generated_roles = _assert_no_phase_l_runtime_roles
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(_runner, name, value)


def run(pytest_args: Sequence[str], environment: Mapping[str, str]) -> int:
    """Provision, exercise, and remove the exact Phase L disposable target."""

    bootstrap_connection: psycopg2.extensions.connection | None = None
    owner_created = False
    exit_code = 2
    cleanup_failed = False
    try:
        bootstrap_url = _bootstrap_url(environment)
        bootstrap_connection = _runner._connect(bootstrap_url)
        preflight = _runner._read_preflight(bootstrap_connection)
        _runner._assert_preflight(preflight, url=bootstrap_url, require_superuser=True)
        _assert_clean_start(bootstrap_connection)

        owner_password = secrets.token_hex(32)
        _create_owner(bootstrap_connection, password=owner_password)
        owner_created = True
        owner_target_url = bootstrap_url.set(
            username=OWNER_USERNAME,
            password=owner_password,
            database=TARGET_DATABASE_NAME,
        )
        owner_maintenance_url = owner_target_url.set(database=bootstrap_url.database)
        child_environment = {
            key: value
            for key, value in environment.items()
            if not key.startswith("MATA_PHASE_")
        }
        child_environment.update(
            {
                OWNER_DATABASE_URL_ENV: owner_target_url.render_as_string(
                    hide_password=False
                ),
                MAINTENANCE_DATABASE_URL_ENV: owner_maintenance_url.render_as_string(
                    hide_password=False
                ),
            }
        )
        with _phase_l_runner_configuration():
            exit_code = _runner.run(pytest_args, child_environment)
    except (PhaseLPostgresRunnerError, _runner.PhaseRPostgresRunnerError) as exc:
        print(f"Phase L PostgreSQL verification aborted: {exc}", file=sys.stderr)
        exit_code = 2
    except (psycopg2.Error, OSError) as exc:
        print(
            "Phase L PostgreSQL verification aborted due to a setup failure "
            f"({type(exc).__name__}).",
            file=sys.stderr,
        )
        exit_code = 2
    finally:
        if bootstrap_connection is not None and not bootstrap_connection.closed:
            try:
                if owner_created:
                    _drop_owner(bootstrap_connection)
                _assert_complete_cleanup(bootstrap_connection)
            except (PhaseLPostgresRunnerError, psycopg2.Error) as exc:
                cleanup_failed = True
                print(f"Phase L PostgreSQL cleanup failed: {exc}", file=sys.stderr)
            finally:
                bootstrap_connection.close()

    if cleanup_failed:
        return 3
    if exit_code == 0:
        print("Phase L PostgreSQL verification finished; generated resources were removed.")
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv), os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
