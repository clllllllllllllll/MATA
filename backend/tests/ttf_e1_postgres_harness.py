"""E1 PostgreSQL guards for explicitly prepared local disposable databases.

The standard owner fixture never provisions a database, runs migrations, or
creates roles.  The E1-only restricted fixture creates disposable login roles
solely to prove real runtime/auth capability boundaries, then removes them.
"""

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
from tests.postgres_disposable_database import configured_disposable_database_name


E1_DISPOSABLE_DATABASE_NAME = configured_disposable_database_name()
E1_REQUIRED_REVISION = "20260806_000038"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_RUNTIME_GROUP = "mata_app_runtime"
_AUTH_GROUP = "mata_auth_internal"
_E1_TEST_ROLE_RE = re.compile(r"mata_e1_(?:runtime|auth)_[0-9a-f]{16}")
_E1_TEST_PASSWORD_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class E1RestrictedRuntimeHarness:
    """Fresh owner/runtime/auth connections for E1-only RLS checks."""

    owner_engine: AsyncEngine
    runtime_engine: AsyncEngine
    auth_engine: AsyncEngine
    runtime_role: str
    auth_role: str

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


def _assert_e1_local_database(url: URL, *, async_url: bool) -> None:
    expected_drivers = (
        {"postgresql+asyncpg"}
        if async_url
        else {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
    )
    if (
        url.drivername not in expected_drivers
        or (url.host or "").casefold() not in _LOCAL_HOSTS
        or url.database != E1_DISPOSABLE_DATABASE_NAME
        or not url.username
        or bool(url.query)
    ):
        pytest.fail(
            "E1 PostgreSQL verification requires the exact named local disposable "
            f"database {E1_DISPOSABLE_DATABASE_NAME}",
            pytrace=False,
        )


def _quoted_e1_test_role(role_name: str) -> str:
    if _E1_TEST_ROLE_RE.fullmatch(role_name) is None:
        raise AssertionError("Refusing to use an unexpected E1 PostgreSQL test role")
    return f'"{role_name}"'


def _credentialed_url(owner_url: URL, role_name: str, password: str) -> URL:
    return owner_url.set(username=role_name, password=password)


def _create_login_member(
    admin_engine: Engine,
    *,
    role_name: str,
    password: str,
    group_name: str,
) -> None:
    quoted_role = _quoted_e1_test_role(role_name)
    if group_name not in {_RUNTIME_GROUP, _AUTH_GROUP}:
        raise AssertionError("Refusing to grant an unexpected PostgreSQL group")
    if _E1_TEST_PASSWORD_RE.fullmatch(password) is None:
        raise AssertionError("Refusing to embed an unexpected E1 test-role password")
    with admin_engine.begin() as connection:
        assert (
            connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role_name)"),
                {"role_name": role_name},
            )
            is False
        )
        # PostgreSQL utility statements do not reliably bind identifiers or
        # passwords. Both generated values are narrowly validated before use.
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
    quoted_role = _quoted_e1_test_role(role_name)
    if group_name not in {_RUNTIME_GROUP, _AUTH_GROUP}:
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
        assert (
            connection.scalar(
                text("SELECT count(*) FROM pg_roles WHERE rolname = :role_name"),
                {"role_name": role_name},
            )
            == 0
        )


@pytest_asyncio.fixture
async def ttf_e1_postgres_engine() -> AsyncIterator[AsyncEngine]:
    """Yield an engine only after attesting the pre-provisioned E1 database.

    The caller owns all fixture rows inside an uncommitted transaction.  This
    owner-only fixture intentionally performs no database or role setup/cleanup;
    ``ttf_e1_restricted_runtime_harness`` supplies the isolated login roles.
    """
    settings = Settings(_env_file=None)
    owner_sync_url = make_url(settings.sync_database_url)
    owner_async_url = owner_sync_url.set(drivername="postgresql+asyncpg")
    runtime_async_url = make_url(settings.database_url)
    _assert_e1_local_database(owner_sync_url, async_url=False)
    _assert_e1_local_database(owner_async_url, async_url=True)
    _assert_e1_local_database(runtime_async_url, async_url=True)
    if settings.auth_database_url is not None:
        _assert_e1_local_database(
            make_url(settings.auth_database_url),
            async_url=True,
        )

    engine = create_async_engine(owner_async_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            database_name = await connection.scalar(text("SELECT current_database()"))
            if database_name != E1_DISPOSABLE_DATABASE_NAME:
                pytest.fail(
                    "E1 PostgreSQL verification connected to an unexpected database",
                    pytrace=False,
                )
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != E1_REQUIRED_REVISION:
                pytest.fail(
                    "E1 PostgreSQL verification requires the E1 schema revision "
                    f"{E1_REQUIRED_REVISION}",
                    pytrace=False,
                )
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def ttf_e1_restricted_runtime_harness() -> AsyncIterator[E1RestrictedRuntimeHarness]:
    """Provision only disposable login capabilities for the E1 RLS test.

    This never creates a database or runs migrations.  The fresh login URLs are
    deliberately isolated with ``NullPool`` and every ephemeral role is
    terminated, dropped, and checked for residual catalogue state in ``finally``.
    """

    settings = Settings(_env_file=None)
    owner_sync_url = make_url(settings.sync_database_url)
    owner_async_url = owner_sync_url.set(drivername="postgresql+asyncpg")
    runtime_async_url = make_url(settings.database_url)
    auth_async_url = (
        make_url(settings.auth_database_url)
        if settings.auth_database_url is not None
        else owner_async_url
    )
    _assert_e1_local_database(owner_sync_url, async_url=False)
    _assert_e1_local_database(owner_async_url, async_url=True)
    _assert_e1_local_database(runtime_async_url, async_url=True)
    _assert_e1_local_database(auth_async_url, async_url=True)
    for candidate_url in (runtime_async_url, auth_async_url):
        if (
            candidate_url.host != owner_sync_url.host
            or candidate_url.port != owner_sync_url.port
            or candidate_url.database != owner_sync_url.database
        ):
            pytest.fail(
                "E1 owner/runtime/auth URLs must identify the same local disposable database",
                pytrace=False,
            )

    admin_engine = create_engine(owner_sync_url, poolclass=NullPool)
    runtime_role = f"mata_e1_runtime_{uuid4().hex[:16]}"
    auth_role = f"mata_e1_auth_{uuid4().hex[:16]}"
    runtime_password = secrets.token_hex(32)
    auth_password = secrets.token_hex(32)
    created_roles: list[tuple[str, str]] = []
    owner_engine: AsyncEngine | None = None
    runtime_engine: AsyncEngine | None = None
    auth_engine: AsyncEngine | None = None
    try:
        with admin_engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert revision == E1_REQUIRED_REVISION
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
                    {"runtime_group": _RUNTIME_GROUP, "auth_group": _AUTH_GROUP},
                ).mappings()
            }
            assert set(role_rows) == {_RUNTIME_GROUP, _AUTH_GROUP}
            for row in role_rows.values():
                assert row["rolcanlogin"] is False
                assert row["rolsuper"] is False
                assert row["rolcreatedb"] is False
                assert row["rolcreaterole"] is False
                assert row["rolreplication"] is False
                assert row["rolbypassrls"] is False

        _create_login_member(
            admin_engine,
            role_name=runtime_role,
            password=runtime_password,
            group_name=_RUNTIME_GROUP,
        )
        created_roles.append((runtime_role, _RUNTIME_GROUP))
        _create_login_member(
            admin_engine,
            role_name=auth_role,
            password=auth_password,
            group_name=_AUTH_GROUP,
        )
        created_roles.append((auth_role, _AUTH_GROUP))

        owner_engine = create_async_engine(owner_async_url, poolclass=NullPool)
        runtime_engine = create_async_engine(
            _credentialed_url(runtime_async_url, runtime_role, runtime_password),
            poolclass=NullPool,
        )
        auth_engine = create_async_engine(
            _credentialed_url(auth_async_url, auth_role, auth_password),
            poolclass=NullPool,
        )
        async with runtime_engine.connect() as connection:
            assert await connection.scalar(text("SELECT current_user")) == runtime_role
            assert await connection.scalar(text("SELECT session_user")) == runtime_role
        async with auth_engine.connect() as connection:
            assert await connection.scalar(text("SELECT current_user")) == auth_role
            assert await connection.scalar(text("SELECT session_user")) == auth_role

        yield E1RestrictedRuntimeHarness(
            owner_engine=owner_engine,
            runtime_engine=runtime_engine,
            auth_engine=auth_engine,
            runtime_role=runtime_role,
            auth_role=auth_role,
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
                "Failed to remove one or more E1 ephemeral PostgreSQL roles",
                cleanup_errors,
            )
