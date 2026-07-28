from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
import re
import secrets
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.services.database_context import MataSyncSession


DISPOSABLE_DATABASE_NAME = "mata_phase5b_m05_upload_limits_verify"
RUNTIME_GROUP = "mata_app_runtime"
AUTH_GROUP = "mata_auth_internal"
REQUIRED_REVISION = "20260728_000028"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_TEST_ROLE_RE = re.compile(r"mata_test_(?:runtime|auth)_[0-9a-f]{16}")
_TEST_PASSWORD_RE = re.compile(r"[0-9a-f]{64}")


def _assert_named_local_disposable(url: URL, *, async_url: bool) -> None:
    expected_drivers = (
        {"postgresql+asyncpg"}
        if async_url
        else {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
    )
    if (
        url.drivername not in expected_drivers
        or url.host not in _LOCAL_HOSTS
        or url.database != DISPOSABLE_DATABASE_NAME
        or not url.username
        or bool(url.query)
    ):
        pytest.fail(
            "RLS PostgreSQL tests require the explicitly named local disposable "
            f"database {DISPOSABLE_DATABASE_NAME}",
            pytrace=False,
        )


def _quoted_test_role(role_name: str) -> str:
    if _TEST_ROLE_RE.fullmatch(role_name) is None:
        raise AssertionError("Refusing to use an unexpected PostgreSQL test role")
    return f'"{role_name}"'


def _credentialed_url(owner_url: URL, role_name: str, password: str) -> URL:
    return owner_url.set(username=role_name, password=password)


@dataclass(frozen=True, slots=True)
class RlsPostgresHarness:
    owner_engine: AsyncEngine
    runtime_engine: AsyncEngine
    auth_engine: AsyncEngine
    runtime_role: str
    auth_role: str
    revision: str

    def owner_session(self) -> AsyncSession:
        return AsyncSession(self.owner_engine, expire_on_commit=False)

    def runtime_session(self) -> AsyncSession:
        return AsyncSession(self.runtime_engine, expire_on_commit=False)

    def runtime_context_session(self) -> AsyncSession:
        return AsyncSession(
            self.runtime_engine,
            expire_on_commit=False,
            sync_session_class=MataSyncSession,
        )

    def auth_session(self) -> AsyncSession:
        return AsyncSession(self.auth_engine, expire_on_commit=False)


def _create_login_member(
    admin_engine: Engine,
    *,
    role_name: str,
    password: str,
    group_name: str,
) -> None:
    quoted_role = _quoted_test_role(role_name)
    if group_name not in {RUNTIME_GROUP, AUTH_GROUP}:
        raise AssertionError("Refusing to grant an unexpected PostgreSQL group")
    if _TEST_PASSWORD_RE.fullmatch(password) is None:
        raise AssertionError("Refusing to embed an unexpected test-role password")
    with admin_engine.begin() as connection:
        already_exists = connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role_name)"),
            {"role_name": role_name},
        )
        assert already_exists is False
        # PostgreSQL utility statements do not consistently accept bind
        # parameters. The generated secret is constrained to lowercase hex
        # before embedding and is never returned, printed, or persisted.
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


def _drop_login_member(
    admin_engine: Engine,
    *,
    role_name: str,
    group_name: str,
) -> None:
    quoted_role = _quoted_test_role(role_name)
    if group_name not in {RUNTIME_GROUP, AUTH_GROUP}:
        raise AssertionError("Refusing to revoke an unexpected PostgreSQL group")
    with admin_engine.begin() as connection:
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
        assert remaining == 0


@pytest_asyncio.fixture
async def rls_postgres_harness() -> AsyncIterator[RlsPostgresHarness]:
    settings = Settings(_env_file=None)
    owner_sync_url = make_url(settings.sync_database_url)
    owner_async_url = owner_sync_url.set(drivername="postgresql+asyncpg")
    configured_runtime_url = make_url(settings.database_url)
    _assert_named_local_disposable(owner_async_url, async_url=True)
    _assert_named_local_disposable(owner_sync_url, async_url=False)
    _assert_named_local_disposable(configured_runtime_url, async_url=True)
    if (
        owner_async_url.host != owner_sync_url.host
        or owner_async_url.port != owner_sync_url.port
        or owner_async_url.database != owner_sync_url.database
    ):
        pytest.fail(
            "Derived async and configured sync RLS test owner URLs must identify "
            "the same local database",
            pytrace=False,
        )
    if (
        configured_runtime_url.host != owner_sync_url.host
        or configured_runtime_url.port != owner_sync_url.port
        or configured_runtime_url.database != owner_sync_url.database
    ):
        pytest.fail(
            "Runtime and owner RLS test URLs must identify the same local database",
            pytrace=False,
        )

    admin_engine = create_engine(owner_sync_url, poolclass=NullPool)
    runtime_role = f"mata_test_runtime_{uuid4().hex[:16]}"
    auth_role = f"mata_test_auth_{uuid4().hex[:16]}"
    runtime_password = secrets.token_hex(32)
    auth_password = secrets.token_hex(32)
    created_roles: list[tuple[str, str]] = []
    owner_engine: AsyncEngine | None = None
    runtime_engine: AsyncEngine | None = None
    auth_engine: AsyncEngine | None = None
    try:
        with admin_engine.connect() as connection:
            role_rows = {
                str(row["rolname"]): dict(row)
                for row in connection.execute(
                    text(
                        """
                        SELECT rolname, rolcanlogin, rolsuper, rolcreatedb,
                               rolcreaterole, rolreplication, rolbypassrls
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
            assert set(role_rows) == {RUNTIME_GROUP, AUTH_GROUP}
            for row in role_rows.values():
                assert row["rolcanlogin"] is False
                assert row["rolsuper"] is False
                assert row["rolcreatedb"] is False
                assert row["rolcreaterole"] is False
                assert row["rolreplication"] is False
                assert row["rolbypassrls"] is False

            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            assert revision == REQUIRED_REVISION

        _create_login_member(
            admin_engine,
            role_name=runtime_role,
            password=runtime_password,
            group_name=RUNTIME_GROUP,
        )
        created_roles.append((runtime_role, RUNTIME_GROUP))
        _create_login_member(
            admin_engine,
            role_name=auth_role,
            password=auth_password,
            group_name=AUTH_GROUP,
        )
        created_roles.append((auth_role, AUTH_GROUP))

        owner_engine = create_async_engine(owner_async_url, poolclass=NullPool)
        runtime_engine = create_async_engine(
            _credentialed_url(owner_async_url, runtime_role, runtime_password),
            pool_size=1,
            max_overflow=0,
            pool_timeout=5,
            pool_pre_ping=True,
        )
        auth_engine = create_async_engine(
            _credentialed_url(owner_async_url, auth_role, auth_password),
            pool_size=1,
            max_overflow=0,
            pool_timeout=5,
            pool_pre_ping=True,
        )

        async with runtime_engine.connect() as runtime_connection:
            assert (
                await runtime_connection.scalar(text("SELECT current_user"))
                == runtime_role
            )
        async with auth_engine.connect() as auth_connection:
            assert (
                await auth_connection.scalar(text("SELECT current_user"))
                == auth_role
            )

        yield RlsPostgresHarness(
            owner_engine=owner_engine,
            runtime_engine=runtime_engine,
            auth_engine=auth_engine,
            runtime_role=runtime_role,
            auth_role=auth_role,
            revision=str(revision),
        )
    finally:
        if runtime_engine is not None:
            await runtime_engine.dispose()
        if auth_engine is not None:
            await auth_engine.dispose()
        if owner_engine is not None:
            await owner_engine.dispose()
        cleanup_errors: list[Exception] = []
        for role_name, group_name in reversed(created_roles):
            try:
                _drop_login_member(
                    admin_engine,
                    role_name=role_name,
                    group_name=group_name,
                )
            except Exception as error:
                cleanup_errors.append(error)
        admin_engine.dispose()
        if cleanup_errors:
            raise ExceptionGroup(
                "Failed to remove one or more ephemeral PostgreSQL roles",
                cleanup_errors,
            )
