"""Bootstrap ephemeral restricted PostgreSQL logins before pytest collection.

Invoke from ``backend`` with ``SYNC_DATABASE_URL`` explicitly targeting
``mata_evolved_ttf_pre_d_fix_verify``:

``python -B -m tests.run_rls_restricted_pytest <pytest arguments>``
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.pool import NullPool


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DISPOSABLE_DATABASE_NAME = "mata_evolved_ttf_pre_d_fix_verify"
POLICY_REVISION = "20260804_000033"
RUNTIME_GROUP = "mata_app_runtime"
AUTH_GROUP = "mata_auth_internal"
DATABASE_URL_ENV = "DATABASE_URL"
AUTH_DATABASE_URL_ENV = "AUTH_DATABASE_URL"
MATA_AUTH_DATABASE_URL_ENV = "MATA_AUTH_DATABASE_URL"
SYNC_DATABASE_URL_ENV = "SYNC_DATABASE_URL"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_SYNC_DRIVERS = frozenset(
    {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
)
_TEST_ROLE_RE = re.compile(r"mata_test_(?:runtime|auth)_[0-9a-f]{16}")
_TEST_PASSWORD_RE = re.compile(r"[0-9a-f]{64}")


class RestrictedRlsRunnerError(RuntimeError):
    """Raised when the restricted-role runner cannot proceed safely."""


def _owner_sync_url(environment: Mapping[str, str]) -> URL:
    raw_url = environment.get(SYNC_DATABASE_URL_ENV, "").strip()
    if not raw_url:
        raise RestrictedRlsRunnerError(
            "SYNC_DATABASE_URL must explicitly name the disposable owner database"
        )
    try:
        url = make_url(raw_url)
    except ArgumentError as exc:
        raise RestrictedRlsRunnerError(
            "SYNC_DATABASE_URL is not a valid SQLAlchemy database URL"
        ) from exc

    if (
        url.drivername not in _SYNC_DRIVERS
        or (url.host or "").casefold() not in _LOCAL_HOSTS
        or url.database != DISPOSABLE_DATABASE_NAME
        or not url.username
        or bool(url.query)
    ):
        raise RestrictedRlsRunnerError(
            "SYNC_DATABASE_URL must identify the exact named local disposable "
            f"database {DISPOSABLE_DATABASE_NAME}"
        )
    return url


def _owner_async_url(owner_sync_url: URL) -> URL:
    return owner_sync_url.set(drivername="postgresql+asyncpg")


def _quoted_test_role(role_name: str) -> str:
    if _TEST_ROLE_RE.fullmatch(role_name) is None:
        raise RestrictedRlsRunnerError(
            "Refusing to use an unexpected PostgreSQL test role"
        )
    return f'"{role_name}"'


def _assert_test_password(password: str) -> None:
    if _TEST_PASSWORD_RE.fullmatch(password) is None:
        raise RestrictedRlsRunnerError(
            "Refusing to embed an unexpected PostgreSQL test password"
        )


def _credentialed_url(owner_url: URL, role_name: str, password: str) -> URL:
    _quoted_test_role(role_name)
    _assert_test_password(password)
    return owner_url.set(username=role_name, password=password)


def _child_environment(
    base_environment: Mapping[str, str],
    *,
    owner_sync_url: URL,
    runtime_role: str,
    runtime_password: str,
    auth_role: str,
    auth_password: str,
) -> dict[str, str]:
    owner_async_url = _owner_async_url(owner_sync_url)
    runtime_url = _credentialed_url(
        owner_async_url,
        runtime_role,
        runtime_password,
    ).render_as_string(hide_password=False)
    auth_url = _credentialed_url(
        owner_async_url,
        auth_role,
        auth_password,
    ).render_as_string(hide_password=False)

    environment = dict(base_environment)
    environment[DATABASE_URL_ENV] = runtime_url
    environment[AUTH_DATABASE_URL_ENV] = auth_url
    environment[MATA_AUTH_DATABASE_URL_ENV] = auth_url
    environment[SYNC_DATABASE_URL_ENV] = owner_sync_url.render_as_string(
        hide_password=False
    )
    environment.update(
        {
            "DATABASE_RLS_ENABLED": "true",
            "MATA_DATABASE_RLS_ENABLED": "true",
            "DATABASE_RUNTIME_ROLE": RUNTIME_GROUP,
            "MATA_DATABASE_RUNTIME_ROLE": RUNTIME_GROUP,
            "DATABASE_AUTH_ROLE": AUTH_GROUP,
            "MATA_DATABASE_AUTH_ROLE": AUTH_GROUP,
            "ENVIRONMENT": "test",
            "ENV": "test",
            "AUTH_MODE": "stub",
            "AUTH_TRANSPORT": "cookie",
        }
    )
    return environment


def _pytest_command(pytest_args: Sequence[str]) -> list[str]:
    selected_args = list(pytest_args) or [
        "-q",
        "--tb=short",
        "-p",
        "no:cacheprovider",
        "tests",
    ]
    return [sys.executable, "-B", "-m", "pytest", *selected_args]


def _capability_role_is_hardened(role_row: Mapping[str, object]) -> bool:
    return (
        role_row["rolcanlogin"] is False
        and role_row["rolinherit"] is False
        and role_row["rolsuper"] is False
        and role_row["rolcreatedb"] is False
        and role_row["rolcreaterole"] is False
        and role_row["rolreplication"] is False
        and role_row["rolbypassrls"] is False
    )


def _verify_owner_and_groups(admin_engine: Engine) -> None:
    with admin_engine.connect() as connection:
        connection_row = connection.execute(
            text(
                """
                SELECT current_database() AS database_name,
                       current_user AS current_role,
                       session_user AS session_role
                """
            )
        ).mappings().one()
        if connection_row["database_name"] != DISPOSABLE_DATABASE_NAME:
            raise RestrictedRlsRunnerError(
                "Owner connection reached an unexpected database"
            )
        if connection_row["current_role"] != connection_row["session_role"]:
            raise RestrictedRlsRunnerError(
                "Owner connection must not enter through SET ROLE"
            )
        if connection_row["session_role"] in {RUNTIME_GROUP, AUTH_GROUP}:
            raise RestrictedRlsRunnerError(
                "Owner credential must be separate from application roles"
            )

        revision = connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
        if revision != POLICY_REVISION:
            raise RestrictedRlsRunnerError(
                "Restricted-role pytest requires the full H-E policy revision"
            )

        role_rows = {
            str(row["rolname"]): dict(row)
            for row in connection.execute(
                text(
                    """
                    SELECT rolname, rolcanlogin, rolinherit, rolsuper,
                           rolcreatedb, rolcreaterole, rolreplication,
                           rolbypassrls
                    FROM pg_roles
                    WHERE rolname IN (:runtime_group, :auth_group)
                    """
                ),
                {
                    "runtime_group": RUNTIME_GROUP,
                    "auth_group": AUTH_GROUP,
                },
            ).mappings()
        }
        if set(role_rows) != {RUNTIME_GROUP, AUTH_GROUP}:
            raise RestrictedRlsRunnerError(
                "Required H-E capability roles are missing"
            )
        for row in role_rows.values():
            if not _capability_role_is_hardened(row):
                raise RestrictedRlsRunnerError(
                    "H-E capability-role attributes do not match the restricted "
                    "catalogue"
                )
        residual_test_roles = connection.scalar(
            text(
                r"""
                SELECT count(*)
                FROM pg_roles
                WHERE rolname LIKE 'mata\_test\_%' ESCAPE '\'
                """
            )
        )
        if residual_test_roles != 0:
            raise RestrictedRlsRunnerError(
                "Residual mata_test_* roles must be removed before restricted "
                "pytest starts"
            )


def _test_role_count(admin_engine: Engine) -> int:
    with admin_engine.connect() as connection:
        return int(
            connection.scalar(
                text(
                    r"""
                    SELECT count(*)
                    FROM pg_roles
                    WHERE rolname LIKE 'mata\_test\_%' ESCAPE '\'
                    """
                )
            )
            or 0
        )


def _announce_mutation_target(owner_sync_url: URL, *, operation: str) -> None:
    print(
        f"PostgreSQL {operation} target: "
        f"database={owner_sync_url.database} "
        f"host={owner_sync_url.host}:{owner_sync_url.port or 5432}",
        flush=True,
    )


def _create_login_member(
    admin_engine: Engine,
    *,
    role_name: str,
    password: str,
    group_name: str,
    created_roles: list[tuple[str, str]],
) -> None:
    quoted_role = _quoted_test_role(role_name)
    _assert_test_password(password)
    if group_name not in {RUNTIME_GROUP, AUTH_GROUP}:
        raise RestrictedRlsRunnerError(
            "Refusing to grant an unexpected PostgreSQL group"
        )

    with admin_engine.begin() as connection:
        already_exists = connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :name)"),
            {"name": role_name},
        )
        if already_exists:
            raise RestrictedRlsRunnerError(
                "Generated PostgreSQL test role already exists"
            )

        # Utility statements do not consistently accept bind parameters.
        # Both embedded values are generated locally and constrained above.
        connection.exec_driver_sql(
            f"""
            CREATE ROLE {quoted_role}
                LOGIN
                INHERIT
                NOSUPERUSER
                NOCREATEDB
                NOCREATEROLE
                NOREPLICATION
                NOBYPASSRLS
                PASSWORD '{password}'
                IN ROLE {group_name}
            """
        )
        # Record the role before the surrounding transaction commits. If
        # commit or later attestation fails, idempotent cleanup handles either
        # the rolled-back or committed outcome.
        created_roles.append((role_name, group_name))
        role_row = connection.execute(
            text(
                """
                SELECT rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                       rolcreaterole, rolreplication, rolbypassrls,
                       pg_has_role(:role_name, :group_name, 'MEMBER') AS member
                FROM pg_roles
                WHERE rolname = :role_name
                """
            ),
            {"role_name": role_name, "group_name": group_name},
        ).mappings().one()
        if (
            not role_row["rolcanlogin"]
            or not role_row["rolinherit"]
            or role_row["rolsuper"]
            or role_row["rolcreatedb"]
            or role_row["rolcreaterole"]
            or role_row["rolreplication"]
            or role_row["rolbypassrls"]
            or not role_row["member"]
        ):
            raise RestrictedRlsRunnerError(
                "Generated PostgreSQL login is not a restricted group member"
            )


def _drop_login_member(
    admin_engine: Engine,
    *,
    role_name: str,
    group_name: str,
) -> None:
    quoted_role = _quoted_test_role(role_name)
    if group_name not in {RUNTIME_GROUP, AUTH_GROUP}:
        raise RestrictedRlsRunnerError(
            "Refusing to revoke an unexpected PostgreSQL group"
        )
    with admin_engine.begin() as connection:
        role_exists = connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :name)"),
            {"name": role_name},
        )
        if not role_exists:
            return
        connection.execute(
            text(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE usename = :role_name
                  AND pid <> pg_backend_pid()
                """
            ),
            {"role_name": role_name},
        )
        connection.exec_driver_sql(f"DROP OWNED BY {quoted_role}")
        connection.exec_driver_sql(f"REVOKE {group_name} FROM {quoted_role}")
        connection.exec_driver_sql(f"DROP ROLE {quoted_role}")
        remaining = connection.scalar(
            text("SELECT count(*) FROM pg_roles WHERE rolname = :role_name"),
            {"role_name": role_name},
        )
        if remaining != 0:
            raise RestrictedRlsRunnerError(
                "Generated PostgreSQL test role was not removed"
            )


def run(pytest_args: Sequence[str], environment: Mapping[str, str]) -> int:
    try:
        owner_sync_url = _owner_sync_url(environment)
    except RestrictedRlsRunnerError as exc:
        print(f"Restricted RLS pytest aborted: {exc}", file=sys.stderr)
        return 2

    admin_engine: Engine | None = None
    runtime_role = f"mata_test_runtime_{uuid4().hex[:16]}"
    auth_role = f"mata_test_auth_{uuid4().hex[:16]}"
    runtime_password = secrets.token_hex(32)
    auth_password = secrets.token_hex(32)
    created_roles: list[tuple[str, str]] = []
    child_exit_code = 2
    runner_failed = False
    interrupted = False
    cleanup_failed = False
    try:
        admin_engine = create_engine(owner_sync_url, poolclass=NullPool)
        _verify_owner_and_groups(admin_engine)
        _announce_mutation_target(owner_sync_url, operation="role-provisioning")
        _create_login_member(
            admin_engine,
            role_name=runtime_role,
            password=runtime_password,
            group_name=RUNTIME_GROUP,
            created_roles=created_roles,
        )
        _create_login_member(
            admin_engine,
            role_name=auth_role,
            password=auth_password,
            group_name=AUTH_GROUP,
            created_roles=created_roles,
        )

        child_environment = _child_environment(
            environment,
            owner_sync_url=owner_sync_url,
            runtime_role=runtime_role,
            runtime_password=runtime_password,
            auth_role=auth_role,
            auth_password=auth_password,
        )
        print(
            "Restricted RLS pytest roles provisioned; starting pytest.",
            flush=True,
        )
        child_exit_code = subprocess.run(
            _pytest_command(pytest_args),
            cwd=BACKEND_ROOT,
            env=child_environment,
            check=False,
        ).returncode
    except KeyboardInterrupt:
        interrupted = True
        child_exit_code = 130
    except RestrictedRlsRunnerError as exc:
        runner_failed = True
        child_exit_code = 2
        print(
            f"Restricted RLS pytest aborted: {exc}",
            file=sys.stderr,
        )
    except (SQLAlchemyError, OSError) as exc:
        runner_failed = True
        child_exit_code = 2
        print(
            "Restricted RLS pytest aborted due to a setup failure "
            f"({type(exc).__name__}).",
            file=sys.stderr,
        )
    finally:
        if admin_engine is not None:
            if created_roles:
                _announce_mutation_target(owner_sync_url, operation="role-cleanup")
            for role_name, group_name in reversed(created_roles):
                try:
                    _drop_login_member(
                        admin_engine,
                        role_name=role_name,
                        group_name=group_name,
                    )
                except (RestrictedRlsRunnerError, SQLAlchemyError):
                    cleanup_failed = True
            try:
                if _test_role_count(admin_engine) != 0:
                    cleanup_failed = True
            except SQLAlchemyError:
                cleanup_failed = True
            admin_engine.dispose()

    if cleanup_failed:
        print(
            "Restricted RLS pytest cleanup failed; generated-role catalogue "
            "inspection is required.",
            file=sys.stderr,
        )
        return 3
    if interrupted:
        print("Restricted RLS pytest was interrupted; roles were removed.")
    elif not runner_failed:
        print("Restricted RLS pytest finished; roles were removed.")
    return child_exit_code


def main(argv: Sequence[str] | None = None) -> int:
    return run(
        list(sys.argv[1:] if argv is None else argv),
        os.environ,
    )


if __name__ == "__main__":
    raise SystemExit(main())
