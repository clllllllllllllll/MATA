"""Run Phase R checks against one fresh, local disposable PostgreSQL database.

This runner is deliberately opt-in. It never reads the repository-root
environment file and may recreate a pre-existing target only after it verifies
the exact authorized owner. Supply both explicit environment variables from
``backend``:

    ``MATA_PHASE_R_OWNER_DATABASE_URL``
        A local migration-owner URL whose database is exactly
        ``mata_evolved_ttf_r_verify``.  An existing target is recreated only
        after its owner is verified as this exact migration owner.

``MATA_PHASE_R_MAINTENANCE_DATABASE_URL``
    A separate local maintenance-database URL on the same server and port.
    It must be able to create/drop the disposable database and its generated
    restricted login roles.

For example, invoke a focused PostgreSQL test module with:

``python -B -m tests.run_phase_r_postgres_verify -q tests/<phase-r-pg-test>.py``

The runner intentionally requires explicit pytest arguments.  That keeps it
from accidentally treating an arbitrary test collection as destructive local
database verification.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from ipaddress import ip_interface
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
TARGET_DATABASE_NAME = "mata_evolved_ttf_r_verify"
EXPECTED_OWNER_USERNAME = "mata_phase_r_owner"
REQUIRED_POSTGRES_PORT = 5432
OWNER_DATABASE_URL_ENV = "MATA_PHASE_R_OWNER_DATABASE_URL"
MAINTENANCE_DATABASE_URL_ENV = "MATA_PHASE_R_MAINTENANCE_DATABASE_URL"
RUNTIME_GROUP = "mata_app_runtime"
AUTH_GROUP = "mata_auth_internal"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_LOCAL_SERVER_ADDRESSES = frozenset({"127.0.0.1", "::1"})
_SYNC_DRIVERS = frozenset({"postgresql", "postgresql+psycopg2"})
_PHASE_R_ROLE_RE = re.compile(r"mata_phase_r_(?:runtime|auth)_[0-9a-f]{16}")
_PHASE_R_PASSWORD_RE = re.compile(r"[0-9a-f]{64}")


class PhaseRPostgresRunnerError(RuntimeError):
    """Raised when Phase R disposable PostgreSQL verification is unsafe."""


@dataclass(frozen=True, slots=True)
class PhaseRDatabaseTargets:
    """Validated owner and maintenance URLs, never rendered for output."""

    owner_url: URL
    maintenance_url: URL


@dataclass(frozen=True, slots=True)
class PostgresPreflight:
    """Read-only identity observed from a PostgreSQL connection."""

    database_name: str
    current_user: str
    session_user: str
    server_address: str | None
    server_port: int | None
    is_superuser: bool


def _normalise_server_address(address: str | None) -> str | None:
    """Return one exact host address, never a network or malformed value."""

    if address is None:
        return None
    try:
        interface = ip_interface(address)
    except ValueError:
        return None
    if interface.network.prefixlen != interface.max_prefixlen:
        return None
    return str(interface.ip)


def _url_port(url: URL, *, label: str) -> int:
    try:
        port = url.port
    except ValueError as exc:
        raise PhaseRPostgresRunnerError(
            f"{label} must include a valid explicit local PostgreSQL port"
        ) from exc
    if port is None or not 1 <= port <= 65535:
        raise PhaseRPostgresRunnerError(
            f"{label} must include a valid explicit local PostgreSQL port"
        )
    return port


def _configured_local_sync_url(
    environment: Mapping[str, str],
    *,
    env_name: str,
    required_database: str | None = None,
    forbidden_database: str | None = None,
) -> URL:
    raw_url = environment.get(env_name, "").strip()
    if not raw_url:
        raise PhaseRPostgresRunnerError(f"{env_name} is required")
    try:
        url = make_url(raw_url)
    except ArgumentError as exc:
        raise PhaseRPostgresRunnerError(
            f"{env_name} is not a valid SQLAlchemy database URL"
        ) from exc

    host = (url.host or "").casefold()
    _url_port(url, label=env_name)
    if (
        url.drivername not in _SYNC_DRIVERS
        or host not in _LOCAL_HOSTS
        or not url.database
        or not url.username
        or not url.password
        or bool(url.query)
    ):
        raise PhaseRPostgresRunnerError(
            f"{env_name} must be an explicit credentialed local PostgreSQL URL "
            "without query parameters"
        )
    if required_database is not None and url.database != required_database:
        raise PhaseRPostgresRunnerError(
            f"{env_name} must target exactly {required_database}"
        )
    if forbidden_database is not None and url.database == forbidden_database:
        raise PhaseRPostgresRunnerError(
            f"{env_name} must target a separate maintenance database"
        )
    return url


def _phase_r_database_targets(
    environment: Mapping[str, str],
) -> PhaseRDatabaseTargets:
    owner_url = _configured_local_sync_url(
        environment,
        env_name=OWNER_DATABASE_URL_ENV,
        required_database=TARGET_DATABASE_NAME,
    )
    maintenance_url = _configured_local_sync_url(
        environment,
        env_name=MAINTENANCE_DATABASE_URL_ENV,
        forbidden_database=TARGET_DATABASE_NAME,
    )
    if (
        owner_url.username != EXPECTED_OWNER_USERNAME
        or maintenance_url.username != EXPECTED_OWNER_USERNAME
    ):
        raise PhaseRPostgresRunnerError(
            "Phase R owner and maintenance URLs must use the authorized "
            "migration owner"
        )
    if (
        _url_port(owner_url, label=OWNER_DATABASE_URL_ENV) != REQUIRED_POSTGRES_PORT
        or _url_port(maintenance_url, label=MAINTENANCE_DATABASE_URL_ENV)
        != REQUIRED_POSTGRES_PORT
    ):
        raise PhaseRPostgresRunnerError(
            "Phase R owner and maintenance URLs must use the authorized local "
            "PostgreSQL port"
        )
    if (
        (owner_url.host or "").casefold()
        != (maintenance_url.host or "").casefold()
        or _url_port(owner_url, label=OWNER_DATABASE_URL_ENV)
        != _url_port(maintenance_url, label=MAINTENANCE_DATABASE_URL_ENV)
    ):
        raise PhaseRPostgresRunnerError(
            "Phase R owner and maintenance URLs must use the same local host and port"
        )
    return PhaseRDatabaseTargets(
        owner_url=owner_url,
        maintenance_url=maintenance_url,
    )


def _read_preflight(connection: psycopg2.extensions.connection) -> PostgresPreflight:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT current_database() AS database_name,
                   current_user AS current_role,
                   session_user AS session_role,
                   inet_server_addr()::text AS server_address,
                   inet_server_port() AS server_port,
                   (SELECT rolsuper FROM pg_catalog.pg_roles
                    WHERE rolname = current_user) AS is_superuser
            """
        )
        row = cursor.fetchone()
    if row is None:
        raise PhaseRPostgresRunnerError("PostgreSQL preflight returned no identity")
    return PostgresPreflight(
        database_name=str(row[0]),
        current_user=str(row[1]),
        session_user=str(row[2]),
        server_address=_normalise_server_address(
            str(row[3]) if row[3] is not None else None
        ),
        server_port=int(row[4]) if row[4] is not None else None,
        is_superuser=bool(row[5]),
    )


def _assert_preflight(
    preflight: PostgresPreflight,
    *,
    url: URL,
    expected_server: tuple[str, int] | None = None,
    require_superuser: bool = False,
) -> None:
    expected_port = _url_port(url, label="configured PostgreSQL URL")
    if preflight.database_name != url.database:
        raise PhaseRPostgresRunnerError(
            "PostgreSQL preflight reached an unexpected database"
        )
    if (
        preflight.current_user != url.username
        or preflight.session_user != url.username
    ):
        raise PhaseRPostgresRunnerError(
            "PostgreSQL preflight reached an unexpected current user"
        )
    if (
        preflight.server_address not in _LOCAL_SERVER_ADDRESSES
        or preflight.server_port != expected_port
    ):
        raise PhaseRPostgresRunnerError(
            "PostgreSQL preflight did not reach the configured local server address and port"
        )
    if expected_server is not None and (
        preflight.server_address,
        preflight.server_port,
    ) != expected_server:
        raise PhaseRPostgresRunnerError(
            "Owner and maintenance PostgreSQL connections reached different servers"
        )
    if require_superuser and not preflight.is_superuser:
        raise PhaseRPostgresRunnerError(
            "Phase R maintenance PostgreSQL credential must be a local superuser"
        )


def _connect(url: URL) -> psycopg2.extensions.connection:
    # psycopg2 accepts PostgreSQL's base scheme; preserve all validated URL
    # components while avoiding a dialect suffix in its libpq connection string.
    connection = psycopg2.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False)
    )
    connection.autocommit = True
    return connection


def _database_exists(
    connection: psycopg2.extensions.connection,
    *,
    database_name: str,
) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s)",
            (database_name,),
        )
        return bool(cursor.fetchone()[0])


def _assert_target_absent(connection: psycopg2.extensions.connection) -> None:
    if _database_exists(connection, database_name=TARGET_DATABASE_NAME):
        raise PhaseRPostgresRunnerError(
            "Phase R PostgreSQL verification refuses a pre-existing "
            f"database {TARGET_DATABASE_NAME}"
        )


def _create_target_database(
    connection: psycopg2.extensions.connection,
    *,
    owner_username: str,
) -> None:
    _assert_target_absent(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(TARGET_DATABASE_NAME),
                sql.Identifier(owner_username),
            )
        )


def _recreate_target_database(
    connection: psycopg2.extensions.connection,
    *,
    owner_username: str,
) -> None:
    """Recreate only the exact disposable target after an ownership check."""

    if _database_exists(connection, database_name=TARGET_DATABASE_NAME):
        _assert_target_database_owner(
            connection,
            owner_username=owner_username,
        )
        _drop_target_database(
            connection,
            owner_username=owner_username,
        )
    _create_target_database(connection, owner_username=owner_username)


def _target_database_owner(
    connection: psycopg2.extensions.connection,
) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_get_userbyid(datdba)
            FROM pg_catalog.pg_database
            WHERE datname = %s
            """,
            (TARGET_DATABASE_NAME,),
        )
        row = cursor.fetchone()
    return str(row[0]) if row is not None else None


def _assert_target_database_owner(
    connection: psycopg2.extensions.connection,
    *,
    owner_username: str,
) -> None:
    if _target_database_owner(connection) != owner_username:
        raise PhaseRPostgresRunnerError(
            "Phase R disposable database ownership does not match the explicit owner"
        )


def _generated_role_name(kind: str) -> str:
    if kind not in {"runtime", "auth"}:
        raise PhaseRPostgresRunnerError("Refusing to generate an unexpected role kind")
    return f"mata_phase_r_{kind}_{uuid4().hex[:16]}"


def _quoted_generated_role(role_name: str) -> sql.Identifier:
    if _PHASE_R_ROLE_RE.fullmatch(role_name) is None:
        raise PhaseRPostgresRunnerError(
            "Refusing to use an unexpected PostgreSQL Phase R role"
        )
    return sql.Identifier(role_name)


def _assert_generated_password(password: str) -> None:
    if _PHASE_R_PASSWORD_RE.fullmatch(password) is None:
        raise PhaseRPostgresRunnerError(
            "Refusing to use an unexpected PostgreSQL Phase R role password"
        )


def _verify_capability_groups(connection: psycopg2.extensions.connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT rolname, rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                   rolcreaterole, rolreplication, rolbypassrls
            FROM pg_catalog.pg_roles
            WHERE rolname IN (%s, %s)
            """,
            (RUNTIME_GROUP, AUTH_GROUP),
        )
        rows = {str(row[0]): row[1:] for row in cursor.fetchall()}
    if set(rows) != {RUNTIME_GROUP, AUTH_GROUP}:
        raise PhaseRPostgresRunnerError(
            "Required restricted PostgreSQL capability roles are missing"
        )
    for attributes in rows.values():
        if attributes != (False, False, False, False, False, False, False):
            raise PhaseRPostgresRunnerError(
                "Restricted PostgreSQL capability-role attributes are unexpected"
            )


def _residual_generated_role_count(
    connection: psycopg2.extensions.connection,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM pg_catalog.pg_roles
            WHERE rolname ~ %s
            """,
            (r"^mata_phase_r_(runtime|auth)_[0-9a-f]{16}$",),
        )
        return int(cursor.fetchone()[0])


def _assert_no_residual_generated_roles(
    connection: psycopg2.extensions.connection,
) -> None:
    if _residual_generated_role_count(connection) != 0:
        raise PhaseRPostgresRunnerError(
            "Phase R verification found pre-existing generated PostgreSQL roles"
        )


def _create_restricted_login(
    connection: psycopg2.extensions.connection,
    *,
    role_name: str,
    password: str,
    group_name: str,
) -> None:
    quoted_role = _quoted_generated_role(role_name)
    _assert_generated_password(password)
    if group_name not in {RUNTIME_GROUP, AUTH_GROUP}:
        raise PhaseRPostgresRunnerError(
            "Refusing to grant an unexpected PostgreSQL capability role"
        )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s)",
            (role_name,),
        )
        if cursor.fetchone()[0]:
            raise PhaseRPostgresRunnerError(
                "Generated Phase R PostgreSQL role already exists"
            )
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {} IN ROLE {}"
            ).format(
                quoted_role,
                sql.Literal(password),
                sql.Identifier(group_name),
            )
        )


def _drop_generated_role(
    connection: psycopg2.extensions.connection,
    *,
    role_name: str,
    group_name: str,
) -> None:
    quoted_role = _quoted_generated_role(role_name)
    if group_name not in {RUNTIME_GROUP, AUTH_GROUP}:
        raise PhaseRPostgresRunnerError(
            "Refusing to revoke an unexpected PostgreSQL capability role"
        )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s)",
            (role_name,),
        )
        if not cursor.fetchone()[0]:
            return
        cursor.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(group_name),
                quoted_role,
            )
        )
        cursor.execute(sql.SQL("DROP ROLE {}").format(quoted_role))


def _owner_environment(
    base_environment: Mapping[str, str],
    *,
    owner_url: URL,
) -> dict[str, str]:
    owner_sync_url = owner_url.render_as_string(hide_password=False)
    owner_async_url = owner_url.set(
        drivername="postgresql+asyncpg"
    ).render_as_string(hide_password=False)
    environment = dict(base_environment)
    # Do not pass the maintenance credential to migrations or tests.
    environment.pop(MAINTENANCE_DATABASE_URL_ENV, None)
    environment.pop(OWNER_DATABASE_URL_ENV, None)
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
            "AUTH_TRANSPORT": "cookie",
        }
    )
    return environment


def _restricted_test_environment(
    owner_environment: Mapping[str, str],
    *,
    owner_url: URL,
    runtime_role: str,
    runtime_password: str,
    auth_role: str,
    auth_password: str,
) -> dict[str, str]:
    _quoted_generated_role(runtime_role)
    _quoted_generated_role(auth_role)
    _assert_generated_password(runtime_password)
    _assert_generated_password(auth_password)
    owner_async_url = owner_url.set(drivername="postgresql+asyncpg")
    runtime_url = owner_async_url.set(
        username=runtime_role,
        password=runtime_password,
    ).render_as_string(hide_password=False)
    auth_url = owner_async_url.set(
        username=auth_role,
        password=auth_password,
    ).render_as_string(hide_password=False)
    environment = dict(owner_environment)
    environment.update(
        {
            "DATABASE_URL": runtime_url,
            "AUTH_DATABASE_URL": auth_url,
            "MATA_AUTH_DATABASE_URL": auth_url,
            "DATABASE_RLS_ENABLED": "true",
            "MATA_DATABASE_RLS_ENABLED": "true",
            "DATABASE_RUNTIME_ROLE": RUNTIME_GROUP,
            "MATA_DATABASE_RUNTIME_ROLE": RUNTIME_GROUP,
            "DATABASE_AUTH_ROLE": AUTH_GROUP,
            "MATA_DATABASE_AUTH_ROLE": AUTH_GROUP,
            "MATA_PHASE_R_RUNTIME_ROLE": runtime_role,
            "MATA_PHASE_R_RUNTIME_PASSWORD": runtime_password,
            "MATA_PHASE_R_AUTH_ROLE": auth_role,
            "MATA_PHASE_R_AUTH_PASSWORD": auth_password,
            "MATA_RLS_DISPOSABLE_DATABASE_NAME": TARGET_DATABASE_NAME,
            "MATA_RLS_RUNTIME_ROLE": runtime_role,
            "MATA_RLS_RUNTIME_PASSWORD": runtime_password,
            "MATA_RLS_AUTH_ROLE": auth_role,
            "MATA_RLS_AUTH_PASSWORD": auth_password,
        }
    )
    return environment


def _alembic_command(*args: str) -> list[str]:
    return [sys.executable, "-B", "-m", "alembic", *args]


def _pytest_command(pytest_args: Sequence[str]) -> list[str]:
    if not pytest_args:
        raise PhaseRPostgresRunnerError(
            "Phase R PostgreSQL verification requires explicit pytest arguments"
        )
    return [sys.executable, "-B", "-m", "pytest", *pytest_args]


def _run_command(command: Sequence[str], *, environment: Mapping[str, str]) -> int:
    return subprocess.run(
        list(command),
        cwd=BACKEND_ROOT,
        env=dict(environment),
        check=False,
    ).returncode


def _drop_target_database(
    connection: psycopg2.extensions.connection,
    *,
    owner_username: str,
) -> None:
    database_owner = _target_database_owner(connection)
    if database_owner is None:
        return
    if database_owner != owner_username:
        raise PhaseRPostgresRunnerError(
            "Refusing to drop a Phase R database with unexpected ownership"
        )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_catalog.pg_stat_activity
            WHERE datname = %s
              AND pid <> pg_backend_pid()
            """,
            (TARGET_DATABASE_NAME,),
        )
        cursor.execute(
            sql.SQL("DROP DATABASE {}").format(sql.Identifier(TARGET_DATABASE_NAME))
        )
    if _database_exists(connection, database_name=TARGET_DATABASE_NAME):
        raise PhaseRPostgresRunnerError(
            "Phase R disposable PostgreSQL database was not removed"
        )


def _cleanup(
    targets: PhaseRDatabaseTargets,
    *,
    expected_maintenance_server: tuple[str, int] | None,
    target_created: bool,
    created_roles: Sequence[tuple[str, str]],
) -> bool:
    """Remove only this run's roles and the tracked exact disposable database."""

    cleanup_failed = False
    try:
        connection = _connect(targets.maintenance_url)
    except psycopg2.Error:
        return True
    try:
        try:
            maintenance_preflight = _read_preflight(connection)
            _assert_preflight(
                maintenance_preflight,
                url=targets.maintenance_url,
                expected_server=expected_maintenance_server,
                require_superuser=True,
            )
        except (PhaseRPostgresRunnerError, psycopg2.Error):
            return True

        database_removed = not target_created
        if target_created:
            try:
                _drop_target_database(
                    connection,
                    owner_username=str(targets.owner_url.username),
                )
                database_removed = True
            except (PhaseRPostgresRunnerError, psycopg2.Error):
                cleanup_failed = True

        if database_removed:
            for role_name, group_name in reversed(created_roles):
                try:
                    _drop_generated_role(
                        connection,
                        role_name=role_name,
                        group_name=group_name,
                    )
                except (PhaseRPostgresRunnerError, psycopg2.Error):
                    cleanup_failed = True
            try:
                _assert_no_residual_generated_roles(connection)
            except (PhaseRPostgresRunnerError, psycopg2.Error):
                cleanup_failed = True
    finally:
        connection.close()
    return cleanup_failed


def run(pytest_args: Sequence[str], environment: Mapping[str, str]) -> int:
    """Provision, verify, and remove a fresh Phase R local PostgreSQL target."""

    try:
        targets = _phase_r_database_targets(environment)
        pytest_command = _pytest_command(pytest_args)
    except PhaseRPostgresRunnerError as exc:
        print(f"Phase R PostgreSQL verification aborted: {exc}", file=sys.stderr)
        return 2

    maintenance_connection: psycopg2.extensions.connection | None = None
    owner_connection: psycopg2.extensions.connection | None = None
    expected_maintenance_server: tuple[str, int] | None = None
    target_created = False
    created_roles: list[tuple[str, str]] = []
    exit_code = 2
    runner_failed = False
    interrupted = False
    try:
        maintenance_connection = _connect(targets.maintenance_url)
        maintenance_preflight = _read_preflight(maintenance_connection)
        _assert_preflight(
            maintenance_preflight,
            url=targets.maintenance_url,
            require_superuser=True,
        )
        expected_maintenance_server = (
            str(maintenance_preflight.server_address),
            int(maintenance_preflight.server_port),
        )
        print(
            "Phase R PostgreSQL target preflight passed: "
            f"database={TARGET_DATABASE_NAME} "
            f"server={maintenance_preflight.server_address}:{maintenance_preflight.server_port}",
            flush=True,
        )
        _recreate_target_database(
            maintenance_connection,
            owner_username=str(targets.owner_url.username),
        )
        target_created = True
        _assert_target_database_owner(
            maintenance_connection,
            owner_username=str(targets.owner_url.username),
        )

        owner_connection = _connect(targets.owner_url)
        owner_preflight = _read_preflight(owner_connection)
        _assert_preflight(
            owner_preflight,
            url=targets.owner_url,
            expected_server=expected_maintenance_server,
        )
        owner_connection.close()
        owner_connection = None

        owner_environment = _owner_environment(
            environment,
            owner_url=targets.owner_url,
        )
        if _run_command(
            _alembic_command("upgrade", "head"),
            environment=owner_environment,
        ) != 0:
            runner_failed = True
            exit_code = 1
            print(
                "Phase R PostgreSQL verification aborted: clean migration failed.",
                file=sys.stderr,
            )
        elif _run_command(
            _alembic_command("current", "--check-heads"),
            environment=owner_environment,
        ) != 0:
            runner_failed = True
            exit_code = 1
            print(
                "Phase R PostgreSQL verification aborted: migration head attestation failed.",
                file=sys.stderr,
            )
        if not runner_failed:
            owner_connection = _connect(targets.owner_url)
            owner_preflight = _read_preflight(owner_connection)
            _assert_preflight(
                owner_preflight,
                url=targets.owner_url,
                expected_server=expected_maintenance_server,
            )
            _verify_capability_groups(owner_connection)
            _assert_no_residual_generated_roles(owner_connection)

            runtime_role = _generated_role_name("runtime")
            auth_role = _generated_role_name("auth")
            runtime_password = secrets.token_hex(32)
            auth_password = secrets.token_hex(32)
            _create_restricted_login(
                owner_connection,
                role_name=runtime_role,
                password=runtime_password,
                group_name=RUNTIME_GROUP,
            )
            created_roles.append((runtime_role, RUNTIME_GROUP))
            _create_restricted_login(
                owner_connection,
                role_name=auth_role,
                password=auth_password,
                group_name=AUTH_GROUP,
            )
            created_roles.append((auth_role, AUTH_GROUP))
            owner_connection.close()
            owner_connection = None

            restricted_environment = _restricted_test_environment(
                owner_environment,
                owner_url=targets.owner_url,
                runtime_role=runtime_role,
                runtime_password=runtime_password,
                auth_role=auth_role,
                auth_password=auth_password,
            )
            print(
                "Phase R restricted roles provisioned; starting explicit pytest command.",
                flush=True,
            )
            exit_code = _run_command(pytest_command, environment=restricted_environment)
    except KeyboardInterrupt:
        interrupted = True
        exit_code = 130
    except PhaseRPostgresRunnerError as exc:
        runner_failed = True
        exit_code = 2
        print(f"Phase R PostgreSQL verification aborted: {exc}", file=sys.stderr)
    except (psycopg2.Error, OSError) as exc:
        runner_failed = True
        exit_code = 2
        print(
            "Phase R PostgreSQL verification aborted due to a setup failure "
            f"({type(exc).__name__}).",
            file=sys.stderr,
        )
    finally:
        if owner_connection is not None and not owner_connection.closed:
            owner_connection.close()
        if maintenance_connection is not None and not maintenance_connection.closed:
            maintenance_connection.close()
        cleanup_failed = _cleanup(
            targets,
            expected_maintenance_server=expected_maintenance_server,
            target_created=target_created,
            created_roles=created_roles,
        )

    if cleanup_failed:
        print(
            "Phase R PostgreSQL cleanup failed; inspect only the exact disposable "
            "database and generated Phase R roles.",
            file=sys.stderr,
        )
        return 3
    if interrupted:
        print("Phase R PostgreSQL verification was interrupted; generated resources were removed.")
    elif not runner_failed and exit_code == 0:
        print("Phase R PostgreSQL verification finished; generated resources were removed.")
    elif not runner_failed:
        print("Phase R PostgreSQL tests failed; generated resources were removed.")
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    return run(
        list(sys.argv[1:] if argv is None else argv),
        os.environ,
    )


if __name__ == "__main__":
    raise SystemExit(main())
