from __future__ import annotations

import os
from pathlib import Path
import secrets
from uuid import uuid4

import psycopg2
from psycopg2 import sql
import pytest
from sqlalchemy.engine import URL, make_url


_PHASE_H_SYNC_DATABASE_URL = "MATA_PHASE_H_SYNC_DATABASE_URL"
_PHASE_H_DATABASE_NAME = "mata_evolved_ttf_hij_verify"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_RUNTIME_GROUP = "mata_app_runtime"
_AUTH_GROUP = "mata_auth_internal"


def _is_phase_h_local_url(url: URL, *, async_url: bool) -> bool:
    expected_drivers = (
        {"postgresql+asyncpg"}
        if async_url
        else {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
    )
    return (
        url.drivername in expected_drivers
        and url.host in _LOCAL_HOSTS
        and url.database == _PHASE_H_DATABASE_NAME
        and bool(url.username)
        and not url.query
    )


def _role_name(kind: str) -> str:
    return f"mata_test_{kind}_{uuid4().hex[:16]}"


def _preflight(connection: psycopg2.extensions.connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT rolname
            FROM pg_roles
            WHERE rolname ~ '^mata_test_(runtime|auth)_[0-9a-f]{16}$'
            """
        )
        if cursor.fetchall():
            raise RuntimeError("Phase H verification found leftover PostgreSQL test roles")
        cursor.execute(
            """
            SELECT count(*)
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
            """
        )
        if cursor.fetchone()[0] != 0:
            raise RuntimeError("Phase H verification requires no competing database sessions")


def _create_role(
    connection: psycopg2.extensions.connection,
    *,
    role_name: str,
    password: str,
    group_name: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {} IN ROLE {}"
            ).format(
                sql.Identifier(role_name),
                sql.Literal(password),
                sql.Identifier(group_name),
            )
        )


def _drop_role(
    connection: psycopg2.extensions.connection,
    *,
    role_name: str,
    group_name: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE usename = %s
              AND pid <> pg_backend_pid()
            """,
            (role_name,),
        )
        cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
        cursor.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(group_name),
                sql.Identifier(role_name),
            )
        )
        cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))


def main() -> int:
    configured_url = os.environ.get(_PHASE_H_SYNC_DATABASE_URL)
    if not configured_url:
        raise SystemExit(
            f"{_PHASE_H_SYNC_DATABASE_URL} is required for Phase H PostgreSQL verification"
        )

    owner_sync_url = make_url(configured_url)
    owner_async_url = owner_sync_url.set(drivername="postgresql+asyncpg")
    if not (
        _is_phase_h_local_url(owner_sync_url, async_url=False)
        and _is_phase_h_local_url(owner_async_url, async_url=True)
    ):
        raise SystemExit(
            "Phase H PostgreSQL verification requires the explicit local database "
            f"{_PHASE_H_DATABASE_NAME}"
        )

    runtime_role = _role_name("runtime")
    auth_role = _role_name("auth")
    runtime_password = secrets.token_hex(32)
    auth_password = secrets.token_hex(32)
    connection = psycopg2.connect(owner_sync_url.render_as_string(hide_password=False))
    connection.autocommit = True
    created_roles: list[tuple[str, str]] = []
    try:
        _preflight(connection)
        _create_role(
            connection,
            role_name=runtime_role,
            password=runtime_password,
            group_name=_RUNTIME_GROUP,
        )
        created_roles.append((runtime_role, _RUNTIME_GROUP))
        _create_role(
            connection,
            role_name=auth_role,
            password=auth_password,
            group_name=_AUTH_GROUP,
        )
        created_roles.append((auth_role, _AUTH_GROUP))
        connection.close()

        os.environ["DATABASE_RLS_ENABLED"] = "true"
        os.environ["SYNC_DATABASE_URL"] = owner_sync_url.render_as_string(
            hide_password=False
        )
        os.environ["DATABASE_URL"] = owner_async_url.set(
            username=runtime_role,
            password=runtime_password,
        ).render_as_string(hide_password=False)
        os.environ["AUTH_DATABASE_URL"] = owner_async_url.set(
            username=auth_role,
            password=auth_password,
        ).render_as_string(hide_password=False)
        os.environ["MATA_PHASE_H_RUNTIME_ROLE"] = runtime_role
        os.environ["MATA_PHASE_H_RUNTIME_PASSWORD"] = runtime_password
        os.environ["MATA_PHASE_H_AUTH_ROLE"] = auth_role
        os.environ["MATA_PHASE_H_AUTH_PASSWORD"] = auth_password

        test_file = Path(__file__).with_name(
            "phase_h_teaching_target_resolution_postgres.py"
        )
        return pytest.main([str(test_file), "-q"])
    finally:
        if not connection.closed:
            connection.close()
        cleanup_errors: list[Exception] = []
        if created_roles:
            cleanup_connection = psycopg2.connect(
                owner_sync_url.render_as_string(hide_password=False)
            )
            cleanup_connection.autocommit = True
            try:
                for role_name, group_name in reversed(created_roles):
                    try:
                        _drop_role(
                            cleanup_connection,
                            role_name=role_name,
                            group_name=group_name,
                        )
                    except Exception as error:
                        cleanup_errors.append(error)
            finally:
                cleanup_connection.close()
        if cleanup_errors:
            raise ExceptionGroup(
                "Failed to remove one or more Phase H PostgreSQL test roles",
                cleanup_errors,
            )


if __name__ == "__main__":
    raise SystemExit(main())
