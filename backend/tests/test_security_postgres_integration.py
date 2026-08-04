from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request
from starlette.responses import Response

from app.config import Settings
from app.dependencies.staff_actor import StaffActorContext
from app.errors import ApiError
from app.middleware.auth_stub import AuthIdentity
from app.models.resident import ExternalResident, ResidentPosting
from app.models.session import AppSession
from app.routers import auth as auth_router
from app.services import app_sessions, staff_accounts
from app.schemas.admin import (
    StaffAccountResetPasswordRequest,
    StaffAccountUpdateRequest,
)
from app.services.app_sessions import (
    AppSessionInvalidError,
    CreatedSession,
    SessionState,
    authorization_fingerprint_for_session,
    cleanup_sessions,
    create_session,
    resolve_session,
    revoke_session,
    revoke_session_family_for_logout,
    revoke_subject_sessions,
    rotate_session,
    touch_session,
    validate_csrf,
    validate_session_csrf,
)
from app.services.session_transport import session_cookie_name
from app.services.database_context import (
    AUTH_BOUNDARY_INFO_KEY,
    RLS_ENABLED_INFO_KEY,
    MataSyncSession,
    RlsLockMode,
    clear_request_context,
    configure_request_context,
    prime_request_context,
)
from app.services.persistent_rate_limit import RateLimitPolicy, check_rate_limit
from app.services.staff_accounts import (
    reset_staff_account_password,
    update_staff_account,
)


SESSION_KEY = "postgres-session-integration-key-at-least-32-characters"
RATE_KEY = "postgres-rate-integration-key-at-least-32-characters"
DISPOSABLE_DATABASE_NAME = "mata_evolved_ttf_pre_d_fix_verify"
EXPECTED_ALEMBIC_REVISION = "20260804_000033"
CONCURRENCY_TIMEOUT_SECONDS = 10


@dataclass(frozen=True, slots=True)
class SecurityDatabase:
    owner_engine: AsyncEngine
    runtime_engine: AsyncEngine
    auth_engine: AsyncEngine
    settings: Settings

    def owner_session(self, *, expire_on_commit: bool = False) -> AsyncSession:
        return AsyncSession(
            self.owner_engine,
            expire_on_commit=expire_on_commit,
        )

    def auth_session(self, *, expire_on_commit: bool = False) -> AsyncSession:
        return AsyncSession(
            self.auth_engine,
            expire_on_commit=expire_on_commit,
            info={AUTH_BOUNDARY_INFO_KEY: True},
        )

    def runtime_helper_session(
        self,
        *,
        expire_on_commit: bool = False,
    ) -> AsyncSession:
        return AsyncSession(
            self.runtime_engine,
            expire_on_commit=expire_on_commit,
            info={RLS_ENABLED_INFO_KEY: True},
        )


def _assert_disposable_database(database_url: str) -> None:
    url = make_url(database_url)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or url.database != DISPOSABLE_DATABASE_NAME
        or bool(url.query)
    ):
        pytest.fail(
            "Security integration tests require the explicitly named local "
            f"disposable PostgreSQL database {DISPOSABLE_DATABASE_NAME}",
            pytrace=False,
        )


def _owner_async_database_url(settings: Settings) -> str:
    owner_url = make_url(settings.sync_database_url).set(
        drivername="postgresql+asyncpg"
    )
    _assert_disposable_database(
        owner_url.render_as_string(hide_password=False)
    )
    return owner_url.render_as_string(hide_password=False)


@pytest_asyncio.fixture
async def security_database() -> AsyncIterator[SecurityDatabase]:
    base_settings = Settings(_env_file=None)
    assert base_settings.database_rls_enabled is True
    assert base_settings.auth_database_url is not None
    settings = base_settings.model_copy(
        update={
            "environment": "test",
            "mata_session_hash_key": SESSION_KEY,
            "rate_limit_hash_secret": RATE_KEY,
        }
    )
    _assert_disposable_database(settings.database_url)
    _assert_disposable_database(settings.auth_database_url)
    owner_engine = create_async_engine(
        _owner_async_database_url(settings),
        poolclass=NullPool,
    )
    runtime_engine = create_async_engine(
        settings.database_url,
        pool_size=5,
        max_overflow=0,
    )
    auth_engine = create_async_engine(
        settings.auth_database_url,
        pool_size=12,
        max_overflow=0,
    )
    try:
        async with owner_engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert revision == EXPECTED_ALEMBIC_REVISION
        async with runtime_engine.connect() as connection:
            assert await connection.scalar(
                text(
                    """
                    SELECT pg_has_role(
                        current_user,
                        'mata_app_runtime',
                        'MEMBER'
                    )
                    """
                )
            ) is True
        async with auth_engine.connect() as connection:
            assert await connection.scalar(
                text(
                    """
                    SELECT pg_has_role(
                        current_user,
                        'mata_auth_internal',
                        'MEMBER'
                    )
                    """
                )
            ) is True
        yield SecurityDatabase(
            owner_engine=owner_engine,
            runtime_engine=runtime_engine,
            auth_engine=auth_engine,
            settings=settings,
        )
    finally:
        await auth_engine.dispose()
        await runtime_engine.dispose()
        await owner_engine.dispose()


def _subject_mcr(subject_id: UUID) -> str:
    return f"T{subject_id.hex[:16].upper()}"


@asynccontextmanager
async def _runtime_context_session(
    database: SecurityDatabase,
    app_session: SessionState,
    *,
    lock_mode: RlsLockMode = "exclusive",
) -> AsyncIterator[AsyncSession]:
    fingerprint = authorization_fingerprint_for_session(app_session)
    assert fingerprint is not None
    db = AsyncSession(
        database.runtime_engine,
        expire_on_commit=False,
        sync_session_class=MataSyncSession,
        info={RLS_ENABLED_INFO_KEY: True},
    )
    configure_request_context(
        db,
        token_digest=app_session.token_digest,
        expected_subject_type=app_session.subject_type,
        expected_subject_id=app_session.subject_id,
        expected_app_session_id=app_session.id,
        expected_authorization_fingerprint=fingerprint,
        lock_mode=lock_mode,
    )
    try:
        await prime_request_context(db)
        yield db
    finally:
        clear_request_context(db)
        await db.close()


async def _wait_for_concurrency_checkpoint(
    signal: asyncio.Event,
    *workers: asyncio.Task,
    label: str,
) -> None:
    signal_waiter = asyncio.create_task(signal.wait())
    try:
        done, _pending = await asyncio.wait(
            {signal_waiter, *workers},
            timeout=CONCURRENCY_TIMEOUT_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            raise TimeoutError(f"Timed out waiting for {label}")
        completed_workers = [worker for worker in workers if worker in done]
        if completed_workers:
            for worker in completed_workers:
                await worker
            raise AssertionError(f"Worker completed before {label}")
        assert signal_waiter.result() is True
    finally:
        if not signal_waiter.done():
            signal_waiter.cancel()
        await asyncio.gather(signal_waiter, return_exceptions=True)


async def _wait_until_backend_is_blocked_by(
    db: AsyncSession,
    *,
    blocked_backend_pid: int,
    blocker_backend_pid: int,
    worker: asyncio.Task,
    label: str,
) -> None:
    async def observe_blocker() -> None:
        while True:
            if worker.done():
                await worker
                raise AssertionError(f"Worker completed before {label}")
            is_blocked = await db.scalar(
                text(
                    """
                    SELECT CAST(:blocker_backend_pid AS integer)
                        = ANY(
                            pg_catalog.pg_blocking_pids(
                                CAST(:blocked_backend_pid AS integer)
                            )
                        )
                    """
                ),
                {
                    "blocked_backend_pid": blocked_backend_pid,
                    "blocker_backend_pid": blocker_backend_pid,
                },
            )
            if is_blocked is True:
                return

    await asyncio.wait_for(
        observe_blocker(),
        timeout=CONCURRENCY_TIMEOUT_SECONDS,
    )


async def _delete_subject_sessions(
    database: SecurityDatabase,
    subject_id: UUID,
) -> None:
    async with database.owner_session() as db:
        await db.execute(
            text("DELETE FROM app_sessions WHERE subject_id = :subject_id"),
            {"subject_id": subject_id},
        )
        await db.commit()


async def _insert_test_subject(
    database: SecurityDatabase,
    *,
    subject_type: str,
    subject_id: UUID,
    admin_level: str = "programme",
    supabase_user_id: UUID | None = None,
) -> None:
    async with database.owner_session() as db:
        if subject_type == "staff":
            upstream_subject_id = supabase_user_id or subject_id
            await db.execute(
                text(
                    """
                    INSERT INTO users (
                        id,
                        email,
                        password_hash,
                        role,
                        name,
                        admin_level,
                        is_active,
                        supabase_user_id
                    )
                    VALUES (
                        :subject_id,
                        :email,
                        'integration-only',
                        'admin',
                        'Session Integration Staff',
                        :admin_level,
                        true,
                        :supabase_user_id
                    )
                    """
                ),
                {
                    "subject_id": subject_id,
                    "email": f"{subject_id.hex}@example.invalid",
                    "admin_level": admin_level,
                    "supabase_user_id": upstream_subject_id,
                },
            )
        elif subject_type == "resident":
            await db.execute(
                text(
                    """
                    INSERT INTO residents (
                        id,
                        name,
                        mcr,
                        status
                    )
                    VALUES (
                        :subject_id,
                        'Session Integration Resident',
                        :mcr,
                        'active'
                    )
                    """
                ),
                {
                    "subject_id": subject_id,
                    "mcr": _subject_mcr(subject_id),
                },
            )
        else:
            raise AssertionError(f"Unsupported integration subject type: {subject_type}")
        await db.commit()


async def _delete_test_subject(
    database: SecurityDatabase,
    *,
    subject_type: str,
    subject_id: UUID,
) -> None:
    await _delete_subject_sessions(database, subject_id)
    table_name = "users" if subject_type == "staff" else "residents"
    async with database.owner_session() as db:
        if subject_type == "staff":
            await db.execute(
                text(
                    """
                    DELETE FROM audit_logs
                    WHERE actor_user_id = :subject_id
                       OR entity_id = CAST(:subject_id AS text)
                    """
                ),
                {"subject_id": subject_id},
            )
        await db.execute(
            text(f"DELETE FROM {table_name} WHERE id = :subject_id"),
            {"subject_id": subject_id},
        )
        await db.commit()


async def _create_staff_session(
    database: SecurityDatabase,
    *,
    subject_id: UUID,
    upstream_subject_id: UUID | None = None,
    expected_subject_session_generation: int = 0,
) -> CreatedSession:
    async with database.auth_session() as db:
        created = await create_session(
            db,
            database.settings,
            "staff",
            subject_id,
            "supabase_staff",
            expected_subject_session_generation=(
                expected_subject_session_generation
            ),
            upstream_subject_id=upstream_subject_id or subject_id,
        )
        await db.commit()
        resolved = await resolve_session(
            db,
            database.settings,
            created.session_token,
            touch=False,
        )
        assert resolved is not None
        assert authorization_fingerprint_for_session(resolved) is not None
        return CreatedSession(
            session=resolved,
            session_token=created.session_token,
            csrf_token=created.csrf_token,
        )


async def _set_session_expiry_at_database_clock(
    db: AsyncSession,
    *,
    session_id: UUID,
    expired_deadline: str,
) -> dict[str, datetime]:
    if expired_deadline not in {"idle", "absolute"}:
        raise AssertionError("Unexpected session deadline")

    state = (
        await db.execute(
            text(
                """
                WITH boundary AS MATERIALIZED (
                    SELECT pg_catalog.clock_timestamp() AS expired_at
                )
                UPDATE public.app_sessions AS app_session
                SET
                    last_seen_at = CASE
                        WHEN :expired_deadline = 'absolute'
                        THEN boundary.expired_at
                        ELSE app_session.last_seen_at
                    END,
                    idle_expires_at = boundary.expired_at,
                    absolute_expires_at = CASE
                        WHEN :expired_deadline = 'absolute'
                        THEN boundary.expired_at
                        ELSE app_session.absolute_expires_at
                    END
                FROM boundary
                WHERE app_session.id = :session_id
                RETURNING
                    app_session.last_seen_at,
                    app_session.idle_expires_at,
                    app_session.absolute_expires_at
                """
            ),
            {
                "session_id": session_id,
                "expired_deadline": expired_deadline,
            },
        )
    ).mappings().one()
    return {
        "last_seen_at": state["last_seen_at"],
        "idle_expires_at": state["idle_expires_at"],
        "absolute_expires_at": state["absolute_expires_at"],
    }


async def _expire_session_at_database_clock(
    database: SecurityDatabase,
    *,
    session_id: UUID,
    expired_deadline: str,
) -> dict[str, datetime]:
    async with database.owner_session() as db:
        state = await _set_session_expiry_at_database_clock(
            db,
            session_id=session_id,
            expired_deadline=expired_deadline,
        )
        await db.commit()
        return state


async def _lock_staff_subject_and_stage_session_expiry(
    db: AsyncSession,
    *,
    subject_id: UUID,
    session_id: UUID,
    expired_deadline: str,
) -> tuple[int, dict[str, datetime]]:
    locked_subject_id = await db.scalar(
        text(
            """
            SELECT staff.id
            FROM public.users AS staff
            WHERE staff.id = :subject_id
            FOR UPDATE
            """
        ),
        {"subject_id": subject_id},
    )
    assert locked_subject_id == subject_id
    blocker_backend_pid = int(
        await db.scalar(text("SELECT pg_catalog.pg_backend_pid()"))
    )
    expired_state = await _set_session_expiry_at_database_clock(
        db,
        session_id=session_id,
        expired_deadline=expired_deadline,
    )
    return blocker_backend_pid, expired_state


async def _create_master_actor(
    database: SecurityDatabase,
) -> tuple[UUID, CreatedSession]:
    actor_id = uuid4()
    await _insert_test_subject(
        database,
        subject_type="staff",
        subject_id=actor_id,
        admin_level="master",
    )
    return actor_id, await _create_staff_session(
        database,
        subject_id=actor_id,
    )


@pytest.mark.asyncio
async def test_session_generation_orm_mapping_matches_postgres_schema(
    security_database: SecurityDatabase,
) -> None:
    external_resident_id = uuid4()

    assert "session_generation" in ExternalResident.__table__.c
    assert "session_generation" not in ResidentPosting.__table__.c

    async with security_database.owner_session() as db:
        posting_code = await db.scalar(
            text("SELECT code FROM posting_codes ORDER BY code LIMIT 1")
        )
        assert posting_code is not None
        await db.execute(
            text(
                """
                INSERT INTO external_residents (
                    id,
                    name,
                    mcr,
                    home_cluster,
                    current_nhg_posting_code,
                    status,
                    session_generation
                )
                VALUES (
                    :external_resident_id,
                    'Session Integration External Resident',
                    :mcr,
                    'NUH',
                    :posting_code,
                    'active',
                    7
                )
                """
            ),
            {
                "external_resident_id": external_resident_id,
                "mcr": _subject_mcr(external_resident_id),
                "posting_code": posting_code,
            },
        )
        await db.commit()

    try:
        async with security_database.owner_session() as db:
            external_resident = await db.scalar(
                select(ExternalResident).where(
                    ExternalResident.id == external_resident_id
                )
            )
            assert external_resident is not None
            assert external_resident.session_generation == 7
            await db.execute(select(ResidentPosting).limit(1))
    finally:
        async with security_database.owner_session() as db:
            await db.execute(
                text("DELETE FROM external_residents WHERE id = :external_resident_id"),
                {"external_resident_id": external_resident_id},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_cookie_session_create_resolve_revoke_uses_digest_only_postgres(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    await _insert_test_subject(
        security_database,
        subject_type="resident",
        subject_id=subject_id,
    )
    try:
        async with security_database.auth_session() as db:
            created = await create_session(
                db,
                settings,
                "resident",
                subject_id,
                "mata_resident",
                expected_subject_session_generation=0,
                normalized_mcr=_subject_mcr(subject_id),
                user_agent="PostgreSQL integration browser",
            )
            await db.commit()

        async with security_database.owner_session() as db:
            stored = await db.scalar(
                select(AppSession).where(AppSession.id == created.session.id)
            )
            assert stored is not None
            assert len(stored.token_digest) == 32
            assert len(stored.csrf_token_digest) == 32
            assert created.session_token.encode() not in stored.token_digest
            assert created.csrf_token.encode() not in stored.csrf_token_digest

        async with security_database.auth_session() as db:
            resolved = await resolve_session(
                db,
                settings,
                created.session_token,
                touch=False,
            )
            assert resolved is not None
            assert resolved.subject_id == subject_id
            await revoke_session(db, resolved, reason="integration_logout")
            await db.commit()

        async with security_database.auth_session() as db:
            assert (
                await resolve_session(
                    db,
                    settings,
                    created.session_token,
                    touch=False,
                )
                is None
            )
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="resident",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_postgres_session_expiry_boundary_is_rejected(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    issued_at = datetime(2026, 7, 22, 9, 0, tzinfo=UTC)
    await _insert_test_subject(
        security_database,
        subject_type="resident",
        subject_id=subject_id,
    )
    try:
        async with security_database.owner_session() as db:
            created = await create_session(
                db,
                settings,
                "resident",
                subject_id,
                "mata_resident",
                expected_subject_session_generation=0,
                now=issued_at,
            )
            await db.commit()

        async with security_database.owner_session() as db:
            assert (
                await resolve_session(
                    db,
                    settings,
                    created.session_token,
                    touch=False,
                    now=created.session.idle_expires_at,
                )
                is None
            )
            assert (
                await resolve_session(
                    db,
                    settings,
                    created.session_token,
                    touch=False,
                    now=created.session.absolute_expires_at,
                )
                is None
            )
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="resident",
            subject_id=subject_id,
        )


@pytest.mark.parametrize("expired_deadline", ("idle", "absolute"))
@pytest.mark.asyncio
async def test_restricted_helpers_reject_idle_only_and_absolute_bound_expiry(
    security_database: SecurityDatabase,
    expired_deadline: str,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
    )
    try:
        created = await _create_staff_session(
            security_database,
            subject_id=subject_id,
        )
        session_snapshot = created.session
        expired_state = await _expire_session_at_database_clock(
            security_database,
            session_id=session_snapshot.id,
            expired_deadline=expired_deadline,
        )
        if expired_deadline == "idle":
            assert (
                expired_state["idle_expires_at"]
                < expired_state["absolute_expires_at"]
            )
            assert (
                expired_state["last_seen_at"]
                < expired_state["idle_expires_at"]
            )
        else:
            # The database invariant idle_expires_at <= absolute_expires_at
            # makes an absolute-expired/idle-future row impossible. Refresh
            # last-seen at the absolute boundary and verify activity remains
            # capped to that same immutable family deadline.
            assert expired_state["last_seen_at"] == expired_state[
                "absolute_expires_at"
            ]
            assert expired_state["idle_expires_at"] == expired_state[
                "absolute_expires_at"
            ]

        async with security_database.auth_session() as db:
            assert (
                await resolve_session(
                    db,
                    settings,
                    created.session_token,
                    touch=False,
                )
                is None
            )
            assert (
                await validate_session_csrf(
                    db,
                    session_snapshot,
                    created.csrf_token,
                    settings,
                )
                == "invalid_session"
            )

        async with security_database.runtime_helper_session() as db:
            assert (
                await touch_session(
                    db,
                    settings,
                    session_snapshot,
                    session_token=created.session_token,
                )
                is False
            )
            with pytest.raises(AppSessionInvalidError):
                await rotate_session(
                    db,
                    settings,
                    session_snapshot,
                    session_token=created.session_token,
                )
            await db.rollback()

        async with security_database.owner_session() as db:
            state = (
                await db.execute(
                    text(
                        """
                        SELECT
                            revoked_at,
                            idle_expires_at <= clock_timestamp()
                                AS idle_expired,
                            absolute_expires_at <= clock_timestamp()
                                AS absolute_expired
                        FROM app_sessions
                        WHERE id = :session_id
                        """
                    ),
                    {"session_id": session_snapshot.id},
                )
            ).one()
            child_count = await db.scalar(
                select(AppSession.id)
                .where(
                    AppSession.rotated_from_session_id
                    == session_snapshot.id
                )
                .limit(1)
            )
            assert state.revoked_at is None
            assert state.idle_expired is True
            assert state.absolute_expired is (
                expired_deadline == "absolute"
            )
            assert child_count is None
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.parametrize("operation", ("hydrate", "touch", "logout"))
@pytest.mark.asyncio
async def test_idle_expiry_committed_while_helper_waits_on_subject_lock_wins(
    security_database: SecurityDatabase,
    operation: str,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
    )
    worker: asyncio.Task | None = None
    try:
        created = await _create_staff_session(
            security_database,
            subject_id=subject_id,
        )
        session_snapshot = created.session
        backend_pid_ready: asyncio.Future[int] = (
            asyncio.get_running_loop().create_future()
        )

        async def run_restricted_operation() -> object:
            session_factory = (
                security_database.auth_session
                if operation in {"hydrate", "logout"}
                else security_database.runtime_helper_session
            )
            async with session_factory() as db:
                backend_pid = int(
                    await db.scalar(
                        text("SELECT pg_catalog.pg_backend_pid()")
                    )
                )
                if not backend_pid_ready.done():
                    backend_pid_ready.set_result(backend_pid)

                if operation == "hydrate":
                    outcome: object = await resolve_session(
                        db,
                        settings,
                        created.session_token,
                        touch=False,
                    )
                elif operation == "touch":
                    outcome = await touch_session(
                        db,
                        settings,
                        session_snapshot,
                        session_token=created.session_token,
                    )
                elif operation == "logout":
                    outcome = await revoke_session_family_for_logout(
                        db,
                        settings,
                        session_token=created.session_token,
                        csrf_token=created.csrf_token,
                        reason="integration_expiry_race_logout",
                    )
                else:
                    raise AssertionError("Unexpected expiry-race operation")
                await db.commit()
                return outcome

        async with security_database.owner_session() as lock_db:
            (
                blocker_backend_pid,
                expired_state,
            ) = await _lock_staff_subject_and_stage_session_expiry(
                lock_db,
                subject_id=subject_id,
                session_id=session_snapshot.id,
                expired_deadline="idle",
            )
            worker = asyncio.create_task(run_restricted_operation())
            blocked_backend_pid = await asyncio.wait_for(
                backend_pid_ready,
                timeout=CONCURRENCY_TIMEOUT_SECONDS,
            )
            await _wait_until_backend_is_blocked_by(
                lock_db,
                blocked_backend_pid=blocked_backend_pid,
                blocker_backend_pid=blocker_backend_pid,
                worker=worker,
                label=f"{operation} subject-lock wait",
            )
            # Commit publishes the database-clock deadline and releases the
            # subject lock atomically. The helper must then use its fresh
            # post-lock validity check rather than the pre-lock candidate row.
            await lock_db.commit()

        outcome = await asyncio.wait_for(
            worker,
            timeout=CONCURRENCY_TIMEOUT_SECONDS,
        )
        if operation == "hydrate":
            assert outcome is None
        elif operation == "touch":
            assert outcome is False
        else:
            assert outcome == 0

        async with security_database.owner_session() as db:
            state = (
                await db.execute(
                    text(
                        """
                        SELECT
                            last_seen_at,
                            idle_expires_at,
                            absolute_expires_at,
                            revoked_at,
                            idle_expires_at <= pg_catalog.clock_timestamp()
                                AS idle_expired,
                            absolute_expires_at
                                > pg_catalog.clock_timestamp()
                                AS absolute_active
                        FROM public.app_sessions
                        WHERE id = :session_id
                        """
                    ),
                    {"session_id": session_snapshot.id},
                )
            ).one()
            child_count = await db.scalar(
                select(AppSession.id)
                .where(
                    AppSession.rotated_from_session_id
                    == session_snapshot.id
                )
                .limit(1)
            )
            assert state.last_seen_at == expired_state["last_seen_at"]
            assert state.idle_expires_at == expired_state["idle_expires_at"]
            assert state.absolute_expires_at == expired_state[
                "absolute_expires_at"
            ]
            assert state.revoked_at is None
            assert state.idle_expired is True
            assert state.absolute_active is True
            assert child_count is None
    finally:
        if worker is not None:
            if not worker.done():
                worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_absolute_expiry_racing_refresh_creates_no_child(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
    )
    worker: asyncio.Task | None = None
    try:
        created = await _create_staff_session(
            security_database,
            subject_id=subject_id,
        )
        session_snapshot = created.session
        backend_pid_ready: asyncio.Future[int] = (
            asyncio.get_running_loop().create_future()
        )

        async def refresh_while_blocked() -> CreatedSession | None:
            async with security_database.runtime_helper_session() as db:
                backend_pid = int(
                    await db.scalar(
                        text("SELECT pg_catalog.pg_backend_pid()")
                    )
                )
                if not backend_pid_ready.done():
                    backend_pid_ready.set_result(backend_pid)
                try:
                    rotated = await rotate_session(
                        db,
                        settings,
                        session_snapshot,
                        session_token=created.session_token,
                    )
                except AppSessionInvalidError:
                    await db.rollback()
                    return None
                await db.commit()
                return rotated

        async with security_database.owner_session() as lock_db:
            (
                blocker_backend_pid,
                expired_state,
            ) = await _lock_staff_subject_and_stage_session_expiry(
                lock_db,
                subject_id=subject_id,
                session_id=session_snapshot.id,
                expired_deadline="absolute",
            )
            worker = asyncio.create_task(refresh_while_blocked())
            blocked_backend_pid = await asyncio.wait_for(
                backend_pid_ready,
                timeout=CONCURRENCY_TIMEOUT_SECONDS,
            )
            await _wait_until_backend_is_blocked_by(
                lock_db,
                blocked_backend_pid=blocked_backend_pid,
                blocker_backend_pid=blocker_backend_pid,
                worker=worker,
                label="refresh subject-lock wait",
            )
            # This is the exact absolute-boundary race: recent activity and
            # idle expiry are capped to the newly committed family deadline
            # before the waiting refresh may continue.
            await lock_db.commit()

        assert (
            await asyncio.wait_for(
                worker,
                timeout=CONCURRENCY_TIMEOUT_SECONDS,
            )
            is None
        )

        async with security_database.owner_session() as db:
            family_rows = (
                await db.scalars(
                    select(AppSession)
                    .where(
                        AppSession.session_family_id
                        == session_snapshot.session_family_id
                    )
                    .order_by(AppSession.created_at, AppSession.id)
                )
            ).all()
            assert [row.id for row in family_rows] == [
                session_snapshot.id
            ]
            parent = family_rows[0]
            assert parent.last_seen_at == expired_state["last_seen_at"]
            assert parent.idle_expires_at == expired_state[
                "absolute_expires_at"
            ]
            assert parent.absolute_expires_at == expired_state[
                "absolute_expires_at"
            ]
            assert parent.revoked_at is None
            assert (
                await db.scalar(
                    select(AppSession.id)
                    .where(
                        AppSession.rotated_from_session_id
                        == session_snapshot.id
                    )
                    .limit(1)
                )
                is None
            )
    finally:
        if worker is not None:
            if not worker.done():
                worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_postgres_session_cleanup_is_triggered_bounded_and_skips_locked_rows(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    current_time = datetime.now(UTC)
    old_issue_time = datetime(2000, 1, 1, tzinfo=UTC)
    cleanup_settings = settings.model_copy(
        update={
            "session_cleanup_retention_seconds": 0,
            "session_cleanup_batch_size": 2,
        }
    )
    single_cleanup_settings = cleanup_settings.model_copy(
        update={"session_cleanup_batch_size": 1}
    )
    await _insert_test_subject(
        security_database,
        subject_type="resident",
        subject_id=subject_id,
    )
    try:
        old_sessions: list[CreatedSession] = []
        async with security_database.owner_session() as db:
            for _ in range(4):
                old_sessions.append(
                    await create_session(
                        db,
                        settings,
                        "resident",
                        subject_id,
                        "mata_resident",
                        expected_subject_session_generation=0,
                        now=old_issue_time,
                    )
                )
            await db.execute(
                update(AppSession)
                .where(
                    AppSession.id.in_(
                        [created.session.id for created in old_sessions]
                    )
                )
                .values(
                    revoked_at=old_issue_time + timedelta(hours=1),
                    revoked_reason="cleanup_integration",
                )
                .execution_options(synchronize_session=False)
            )
            await db.commit()

        # Session issuance is the guaranteed serverless-safe cleanup trigger.
        async with security_database.owner_session() as db:
            active = await create_session(
                db,
                cleanup_settings,
                "resident",
                subject_id,
                "mata_resident",
                expected_subject_session_generation=0,
                now=current_time,
            )
            await db.commit()

        old_ids = [created.session.id for created in old_sessions]
        async with security_database.owner_session() as db:
            remaining_old_ids = list(
                (
                    await db.scalars(
                        select(AppSession.id).where(AppSession.id.in_(old_ids))
                    )
                ).all()
            )
            assert len(remaining_old_ids) == 2
            assert (
                await db.scalar(
                    select(AppSession.id).where(AppSession.id == active.session.id)
                )
                == active.session.id
            )

        locked_id = remaining_old_ids[0]
        async with security_database.owner_session() as lock_db:
            locked = await lock_db.scalar(
                select(AppSession)
                .where(AppSession.id == locked_id)
                .with_for_update()
            )
            assert locked is not None
            async with security_database.owner_session() as cleanup_db:
                deleted = await cleanup_sessions(
                    cleanup_db,
                    single_cleanup_settings,
                    now=current_time,
                )
                await cleanup_db.commit()
            assert deleted == 1
            async with security_database.owner_session() as db:
                assert set(
                    (
                        await db.scalars(
                            select(AppSession.id).where(
                                AppSession.id.in_(remaining_old_ids)
                            )
                        )
                    ).all()
                ) == {locked_id}
            await lock_db.rollback()

        async with security_database.owner_session() as db:
            assert (
                await cleanup_sessions(
                    db,
                    single_cleanup_settings,
                    now=current_time,
                )
                == 1
            )
            await db.commit()
            assert (
                await db.scalar(
                    select(AppSession.id).where(AppSession.id == active.session.id)
                )
                == active.session.id
            )
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="resident",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_restricted_refresh_route_reads_identity_before_parent_revocation(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
        admin_level="master",
    )
    try:
        original = await _create_staff_session(
            security_database,
            subject_id=subject_id,
        )
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/auth/session/refresh",
                "headers": [(b"user-agent", b"restricted-refresh-route-test")],
            }
        )
        request.state.app_session = original.session
        request.state.session_token = original.session_token
        response = Response()
        identity = AuthIdentity(
            role="admin",
            subject_id=str(subject_id),
            programme_scope=[],
            admin_level="master",
        )

        async with _runtime_context_session(
            security_database,
            original.session,
            lock_mode="exclusive",
        ) as db:
            route_result = await auth_router.refresh_session(
                request=request,
                response=response,
                identity=identity,
                db=db,
                settings=settings,
            )

        # The parent-bound context becomes invalid as soon as rotation revokes
        # the parent. A protected identity SELECT after rotation would therefore
        # make this actual route call fail instead of returning its response.
        assert route_result.session_refresh_required is False
        assert str(route_result.user["id"]) == str(subject_id)

        cookie = SimpleCookie()
        for header in response.headers.getlist("set-cookie"):
            cookie.load(header)
        rotated_cookie = cookie[session_cookie_name(settings)]
        rotated_token = rotated_cookie.value
        assert rotated_token
        assert rotated_token != original.session_token

        async with security_database.owner_session() as db:
            parent = await db.scalar(
                select(AppSession).where(AppSession.id == original.session.id)
            )
            children = list(
                (
                    await db.scalars(
                        select(AppSession).where(
                            AppSession.rotated_from_session_id
                            == original.session.id
                        )
                    )
                ).all()
            )
            assert parent is not None
            assert parent.revoked_at is not None
            assert parent.revoked_reason == "rotated"
            assert len(children) == 1
            assert children[0].revoked_at is None

        async with security_database.auth_session() as db:
            assert (
                await resolve_session(
                    db,
                    settings,
                    original.session_token,
                    touch=False,
                )
                is None
            )
            rotated = await resolve_session(
                db,
                settings,
                rotated_token,
                touch=False,
            )
            assert rotated is not None
            assert rotated.id == children[0].id
            assert (
                await validate_session_csrf(
                    db,
                    rotated,
                    route_result.csrf_token,
                    settings,
                )
                == "valid"
            )
            await db.commit()
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_refresh_first_logout_without_hydrated_parent_revokes_late_child(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
        admin_level="master",
    )
    try:
        original = await _create_staff_session(
            security_database,
            subject_id=subject_id,
        )
        other_device = await _create_staff_session(
            security_database,
            subject_id=subject_id,
        )

        # Capture the logout request before refresh, but let refresh commit
        # first. Its middleware resolution would now find no active parent, so
        # the route deliberately has no app_session state to depend upon.
        csrf_header = settings.csrf_header_name.lower().encode("ascii")
        logout_request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/auth/logout",
                "headers": [
                    (
                        b"cookie",
                        (
                            f"{session_cookie_name(settings)}="
                            f"{original.session_token}"
                        ).encode("ascii"),
                    ),
                    (csrf_header, original.csrf_token.encode("ascii")),
                ],
            }
        )
        assert getattr(logout_request.state, "app_session", None) is None

        refresh_request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/auth/session/refresh",
                "headers": [(b"user-agent", b"refresh-first-logout-race-test")],
            }
        )
        refresh_request.state.app_session = original.session
        refresh_request.state.session_token = original.session_token
        refresh_response = Response()
        identity = AuthIdentity(
            role="admin",
            subject_id=str(subject_id),
            programme_scope=[],
            admin_level="master",
        )
        async with _runtime_context_session(
            security_database,
            original.session,
            lock_mode="exclusive",
        ) as db:
            refresh_result = await auth_router.refresh_session(
                request=refresh_request,
                response=refresh_response,
                identity=identity,
                db=db,
                settings=settings,
            )

        cookie = SimpleCookie()
        for header in refresh_response.headers.getlist("set-cookie"):
            cookie.load(header)
        late_refresh_token = cookie[session_cookie_name(settings)].value
        assert late_refresh_token

        async with security_database.auth_session() as db:
            late_child_state = await resolve_session(
                db,
                settings,
                late_refresh_token,
                touch=False,
            )
            assert late_child_state is not None

        # A very short cleanup retention must not erase the rotated parent's
        # termination proof while a child extended by qualifying activity can
        # still be active. Backdate the parent's storage age + idle deadline
        # and the child's last activity; no sleep is needed.
        async with security_database.owner_session() as db:
            await db.execute(
                text(
                    """
                    UPDATE public.app_sessions
                    SET revoked_at = (
                        pg_catalog.clock_timestamp()
                        - pg_catalog.make_interval(secs => 2)
                    ),
                        idle_expires_at = (
                            pg_catalog.clock_timestamp()
                            - pg_catalog.make_interval(secs => 1)
                        )
                    WHERE id = :parent_id
                      AND revoked_reason = 'rotated'
                    """
                ),
                {"parent_id": original.session.id},
            )
            await db.execute(
                text(
                    """
                    UPDATE public.app_sessions
                    SET last_seen_at = (
                        pg_catalog.clock_timestamp()
                        - pg_catalog.make_interval(secs => :touch_age)
                    )
                    WHERE id = :child_id
                      AND revoked_at IS NULL
                    """
                ),
                {
                    "child_id": late_child_state.id,
                    "touch_age": (
                        int(settings.session_touch_interval_seconds) + 1
                    ),
                },
            )
            await db.commit()
        async with security_database.auth_session() as db:
            assert await touch_session(
                db,
                settings,
                late_child_state,
                session_token=late_refresh_token,
            )
            await db.commit()
        cleanup_settings = settings.model_copy(
            update={
                "session_cleanup_retention_seconds": 1,
                "session_cleanup_batch_size": 1000,
            }
        )
        async with security_database.auth_session() as db:
            await cleanup_sessions(db, cleanup_settings)
            await db.commit()
        async with security_database.owner_session() as db:
            retained_parent = await db.scalar(
                select(AppSession).where(
                    AppSession.id == original.session.id
                )
            )
            assert retained_parent is not None
            assert retained_parent.revoked_reason == "rotated"
            touched_child = await db.scalar(
                select(AppSession).where(
                    AppSession.id == late_child_state.id
                )
            )
            database_time = await db.scalar(
                text("SELECT pg_catalog.clock_timestamp()")
            )
            assert touched_child is not None
            assert database_time is not None
            assert retained_parent.idle_expires_at <= database_time
            assert database_time < touched_child.idle_expires_at
            assert (
                retained_parent.absolute_expires_at
                == touched_child.absolute_expires_at
            )
        async with security_database.auth_session() as db:
            assert (
                await resolve_session(
                    db,
                    settings,
                    late_refresh_token,
                    touch=False,
                )
                is not None
            )

        logout_response = Response()
        async with security_database.auth_session() as db:
            logout_result = await auth_router.logout(
                request=logout_request,
                response=logout_response,
                db=db,
                settings=settings,
            )

        assert logout_result.success is True
        assert logout_result.server_logout_confirmed is True
        assert any(
            "Max-Age=0" in header
            for header in logout_response.headers.getlist("set-cookie")
        )

        async with security_database.owner_session() as db:
            family_rows = list(
                (
                    await db.scalars(
                        select(AppSession).where(
                            AppSession.session_family_id
                            == original.session.session_family_id
                        )
                    )
                ).all()
            )
            assert len(family_rows) == 2
            assert all(row.revoked_at is not None for row in family_rows)
            assert any(
                row.revoked_reason == "logout"
                and row.rotated_from_session_id == original.session.id
                for row in family_rows
            )
            unrelated = await db.scalar(
                select(AppSession).where(
                    AppSession.id == other_device.session.id
                )
            )
            assert unrelated is not None
            assert unrelated.revoked_at is None

        # Even if the refresh response reaches the browser after the clearing
        # logout response, its newly set opaque credential cannot hydrate.
        async with security_database.auth_session() as db:
            assert (
                await resolve_session(
                    db,
                    settings,
                    late_refresh_token,
                    touch=False,
                )
                is None
            )
            assert (
                await resolve_session(
                    db,
                    settings,
                    other_device.session_token,
                    touch=False,
                )
                is not None
            )
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_local_cleanup_retains_rotated_proof_for_delayed_family_logout(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings.model_copy(
        update={
            "staff_session_idle_timeout_seconds": 5,
            "staff_session_absolute_timeout_seconds": 100,
            "session_touch_interval_seconds": 1,
        }
    )
    cleanup_settings = settings.model_copy(
        update={
            "session_cleanup_retention_seconds": 1,
            "session_cleanup_batch_size": 1000,
        }
    )
    subject_id = uuid4()
    base_time = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)
    rotation_time = base_time + timedelta(seconds=1)
    activity_time = base_time + timedelta(seconds=4)
    delayed_logout_time = base_time + timedelta(seconds=6)
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
    )
    try:
        async with security_database.owner_session() as db:
            original = await create_session(
                db,
                settings,
                "staff",
                subject_id,
                "supabase_staff",
                expected_subject_session_generation=0,
                now=base_time,
            )
            await db.commit()

        async with security_database.owner_session() as db:
            child = await rotate_session(
                db,
                settings,
                original.session,
                session_token=original.session_token,
                now=rotation_time,
            )
            await db.commit()

        async with security_database.owner_session() as db:
            assert await touch_session(
                db,
                settings,
                child.session,
                session_token=child.session_token,
                now=activity_time,
            )
            await db.commit()

        async with security_database.owner_session() as db:
            await cleanup_sessions(
                db,
                cleanup_settings,
                now=delayed_logout_time,
            )
            await db.commit()

        async with security_database.owner_session() as db:
            retained_parent = await db.scalar(
                select(AppSession).where(
                    AppSession.id == original.session.id
                )
            )
            active_child = await db.scalar(
                select(AppSession).where(
                    AppSession.id == child.session.id
                )
            )
            assert retained_parent is not None
            assert retained_parent.revoked_reason == "rotated"
            assert active_child is not None
            assert active_child.revoked_at is None
            assert (
                retained_parent.idle_expires_at
                <= delayed_logout_time
                < active_child.idle_expires_at
            )
            assert (
                retained_parent.absolute_expires_at
                == active_child.absolute_expires_at
            )

        async with security_database.owner_session() as db:
            assert (
                await revoke_session_family_for_logout(
                    db,
                    settings,
                    session_token=original.session_token,
                    csrf_token=original.csrf_token,
                    reason="delayed_local_logout",
                    now=delayed_logout_time,
                )
                == 1
            )
            await db.commit()

        async with security_database.owner_session() as db:
            revoked_child = await db.scalar(
                select(AppSession).where(
                    AppSession.id == child.session.id
                )
            )
            assert revoked_child is not None
            assert revoked_child.revoked_at == delayed_logout_time
            assert revoked_child.revoked_reason == "delayed_local_logout"
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_local_rotated_logout_proof_expires_at_absolute_boundary(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings.model_copy(
        update={
            "staff_session_idle_timeout_seconds": 5,
            "staff_session_absolute_timeout_seconds": 100,
            "session_touch_interval_seconds": 1,
        }
    )
    subject_id = uuid4()
    base_time = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
    )
    try:
        async with security_database.owner_session() as db:
            original = await create_session(
                db,
                settings,
                "staff",
                subject_id,
                "supabase_staff",
                expected_subject_session_generation=0,
                now=base_time,
            )
            await db.commit()

        async with security_database.owner_session() as db:
            child = await rotate_session(
                db,
                settings,
                original.session,
                session_token=original.session_token,
                now=base_time + timedelta(seconds=1),
            )
            await db.commit()

        async with security_database.owner_session() as db:
            assert (
                await revoke_session_family_for_logout(
                    db,
                    settings,
                    session_token=original.session_token,
                    csrf_token=original.csrf_token,
                    reason="absolute_boundary_logout",
                    now=original.session.absolute_expires_at,
                )
                == 0
            )
            await db.commit()

        async with security_database.owner_session() as db:
            unchanged_child = await db.scalar(
                select(AppSession).where(
                    AppSession.id == child.session.id
                )
            )
            assert unchanged_child is not None
            assert unchanged_child.revoked_at is None
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.parametrize("csrf_token", (None, "not-base64url", "A" * 43))
@pytest.mark.asyncio
async def test_rotated_parent_logout_rejects_bad_proof_without_clearing_cookie(
    security_database: SecurityDatabase,
    csrf_token: str | None,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
    )
    try:
        original = await _create_staff_session(
            security_database,
            subject_id=subject_id,
        )
        async with security_database.runtime_helper_session() as db:
            child = await rotate_session(
                db,
                settings,
                original.session,
                session_token=original.session_token,
            )
            await db.commit()

        headers = [
            (
                b"cookie",
                (
                    f"{session_cookie_name(settings)}="
                    f"{original.session_token}"
                ).encode("ascii"),
            )
        ]
        if csrf_token is not None:
            headers.append(
                (
                    settings.csrf_header_name.lower().encode("ascii"),
                    csrf_token.encode("ascii"),
                )
            )
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/auth/logout",
                "headers": headers,
            }
        )
        response = Response()
        async with security_database.auth_session() as db:
            result = await auth_router.logout(
                request=request,
                response=response,
                db=db,
                settings=settings,
            )

        assert result.success is True
        assert result.server_logout_confirmed is False
        assert response.headers.getlist("set-cookie") == []
        async with security_database.auth_session() as db:
            resolved_child = await resolve_session(
                db,
                settings,
                child.session_token,
                touch=False,
            )
            assert resolved_child is not None
            assert resolved_child.id == child.session.id
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_child_cookie_with_rotated_parent_csrf_revokes_only_its_family(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
    )
    try:
        original = await _create_staff_session(
            security_database,
            subject_id=subject_id,
        )
        other_device = await _create_staff_session(
            security_database,
            subject_id=subject_id,
        )
        async with security_database.runtime_helper_session() as db:
            child = await rotate_session(
                db,
                settings,
                original.session,
                session_token=original.session_token,
            )
            await db.commit()

        async with security_database.auth_session() as db:
            revoked_count = await revoke_session_family_for_logout(
                db,
                settings,
                session_token=child.session_token,
                csrf_token=original.csrf_token,
                reason="stale_tab_logout",
            )
            await db.commit()

        assert revoked_count == 1
        async with security_database.auth_session() as db:
            assert (
                await resolve_session(
                    db,
                    settings,
                    child.session_token,
                    touch=False,
                )
                is None
            )
            assert (
                await resolve_session(
                    db,
                    settings,
                    other_device.session_token,
                    touch=False,
                )
                is not None
            )
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_concurrent_postgres_session_rotation_has_one_winner(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    both_loaded = asyncio.Barrier(2)
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
    )
    try:
        async with security_database.auth_session() as db:
            original = await create_session(
                db,
                settings,
                "staff",
                subject_id,
                "supabase_staff",
                expected_subject_session_generation=0,
                upstream_subject_id=subject_id,
            )
            await db.commit()

        loaded_sessions: list[SessionState] = []
        for _ in range(2):
            async with security_database.auth_session() as db:
                loaded = await resolve_session(
                    db,
                    settings,
                    original.session_token,
                    touch=False,
                )
                assert loaded is not None
                loaded_sessions.append(loaded)

        async def rotate_once(loaded: SessionState) -> CreatedSession:
            await both_loaded.wait()
            async with security_database.runtime_helper_session() as db:
                rotated = await rotate_session(
                    db,
                    settings,
                    loaded,
                    session_token=original.session_token,
                )
                await db.commit()
                return rotated

        outcomes = await asyncio.wait_for(
            asyncio.gather(
                *(rotate_once(loaded) for loaded in loaded_sessions),
                return_exceptions=True,
            ),
            timeout=CONCURRENCY_TIMEOUT_SECONDS,
        )
        winners = [item for item in outcomes if isinstance(item, CreatedSession)]
        losers = [item for item in outcomes if isinstance(item, AppSessionInvalidError)]
        outcome_types = [type(item).__name__ for item in outcomes]
        assert len(winners) == 1, outcome_types
        assert len(losers) == 1, outcome_types

        async with security_database.owner_session() as db:
            parent = await db.scalar(
                select(AppSession).where(AppSession.id == original.session.id)
            )
            children = list(
                (
                    await db.scalars(
                        select(AppSession).where(
                            AppSession.rotated_from_session_id == original.session.id
                        )
                    )
                ).all()
            )
            assert parent is not None
            assert parent.revoked_at is not None
            assert parent.revoked_reason == "rotated"
            assert len(children) == 1
            assert children[0].id == winners[0].session.id
            assert children[0].revoked_at is None
            assert not validate_csrf(
                parent,
                original.csrf_token,
                settings,
            )
            assert not validate_csrf(
                children[0],
                original.csrf_token,
                settings,
            )
            assert validate_csrf(
                children[0],
                winners[0].csrf_token,
                settings,
            )

        async with security_database.auth_session() as db:
            assert (
                await resolve_session(
                    db,
                    settings,
                    original.session_token,
                    touch=False,
                )
                is None
            )
            assert (
                await resolve_session(
                    db,
                    settings,
                    winners[0].session_token,
                    touch=False,
                )
                is not None
            )
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_repeated_restricted_rotations_preserve_or_tighten_idle_and_absolute_deadlines(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
    )
    try:
        original = await _create_staff_session(
            security_database,
            subject_id=subject_id,
        )
        async with security_database.owner_session() as db:
            original_deadlines = (
                await db.execute(
                    select(
                        AppSession.last_seen_at,
                        AppSession.idle_expires_at,
                        AppSession.absolute_expires_at,
                    ).where(AppSession.id == original.session.id)
                )
            ).one()
        original_last_seen = original_deadlines.last_seen_at
        original_idle_expiry = original_deadlines.idle_expires_at
        original_absolute_expiry = original_deadlines.absolute_expires_at
        assert isinstance(original_last_seen, datetime)
        assert isinstance(original_idle_expiry, datetime)
        assert isinstance(original_absolute_expiry, datetime)

        async with security_database.runtime_helper_session() as db:
            first_child = await rotate_session(
                db,
                settings,
                original.session,
                session_token=original.session_token,
            )
            await db.commit()

        async with security_database.auth_session() as db:
            first_child_state = await resolve_session(
                db,
                settings,
                first_child.session_token,
                touch=False,
            )
            assert first_child_state is not None

        tightened_idle_seconds = 61
        tightened_settings = settings.model_copy(
            update={
                "staff_session_idle_timeout_seconds": tightened_idle_seconds
            }
        )
        async with security_database.runtime_helper_session() as db:
            second_child = await rotate_session(
                db,
                tightened_settings,
                first_child_state,
                session_token=first_child.session_token,
            )
            await db.commit()

        async with security_database.owner_session() as db:
            rows = (
                await db.scalars(
                    select(AppSession)
                    .where(
                        AppSession.session_family_id
                        == original.session.session_family_id
                    )
                    .order_by(AppSession.created_at, AppSession.id)
                )
            ).all()
            assert [row.id for row in rows] == [
                original.session.id,
                first_child.session.id,
                second_child.session.id,
            ]
            assert all(
                row.absolute_expires_at == original_absolute_expiry
                for row in rows
            )
            assert rows[0].last_seen_at == original_last_seen
            assert rows[1].last_seen_at == original_last_seen
            assert rows[2].last_seen_at == original_last_seen
            assert rows[0].idle_expires_at == original_idle_expiry
            assert rows[1].idle_expires_at == original_idle_expiry
            assert rows[2].idle_expires_at == min(
                original_idle_expiry,
                rows[2].created_at
                + timedelta(seconds=tightened_idle_seconds),
            )
            assert rows[0].revoked_reason == "rotated"
            assert rows[1].revoked_reason == "rotated"
            assert rows[2].revoked_at is None

        async with security_database.auth_session() as db:
            assert (
                await resolve_session(
                    db,
                    settings,
                    original.session_token,
                    touch=False,
                )
                is None
            )
            assert (
                await resolve_session(
                    db,
                    settings,
                    first_child.session_token,
                    touch=False,
                )
                is None
            )
            assert (
                await resolve_session(
                    db,
                    settings,
                    second_child.session_token,
                    touch=False,
                )
                is not None
            )
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_refresh_racing_logout_revokes_the_entire_rotation_family_only(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    both_loaded = asyncio.Barrier(2)
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
    )
    try:
        async with security_database.auth_session() as db:
            original = await create_session(
                db,
                settings,
                "staff",
                subject_id,
                "supabase_staff",
                expected_subject_session_generation=0,
                upstream_subject_id=subject_id,
            )
            other_device = await create_session(
                db,
                settings,
                "staff",
                subject_id,
                "supabase_staff",
                expected_subject_session_generation=0,
                upstream_subject_id=subject_id,
            )
            await db.commit()

        async with security_database.runtime_helper_session() as db:
            loaded_original = await resolve_session(
                db,
                settings,
                original.session_token,
                touch=False,
            )
            assert loaded_original is not None
            first_child = await rotate_session(
                db,
                settings,
                loaded_original,
                session_token=original.session_token,
            )
            await db.commit()

        loaded_sessions: list[SessionState] = []
        for _ in range(2):
            async with security_database.auth_session() as db:
                loaded = await resolve_session(
                    db,
                    settings,
                    first_child.session_token,
                    touch=False,
                )
                assert loaded is not None
                loaded_sessions.append(loaded)

        async def refresh_once(loaded: SessionState) -> CreatedSession:
            await both_loaded.wait()
            async with security_database.runtime_helper_session() as db:
                refreshed = await rotate_session(
                    db,
                    settings,
                    loaded,
                    session_token=first_child.session_token,
                )
                await db.commit()
                return refreshed

        async def logout_once(loaded: SessionState) -> int:
            await both_loaded.wait()
            async with security_database.auth_session() as db:
                revoked = await revoke_session_family_for_logout(
                    db,
                    settings,
                    session_token=first_child.session_token,
                    csrf_token=first_child.csrf_token,
                    reason="integration_logout",
                )
                await db.commit()
                return revoked

        refresh_outcome, logout_outcome = await asyncio.wait_for(
            asyncio.gather(
                refresh_once(loaded_sessions[0]),
                logout_once(loaded_sessions[1]),
                return_exceptions=True,
            ),
            timeout=CONCURRENCY_TIMEOUT_SECONDS,
        )
        assert isinstance(
            refresh_outcome,
            (CreatedSession, AppSessionInvalidError),
        ), type(refresh_outcome).__name__
        assert isinstance(logout_outcome, int), type(logout_outcome).__name__
        assert logout_outcome >= 1

        family_id = first_child.session.session_family_id
        async with security_database.owner_session() as db:
            family_rows = (
                await db.scalars(
                    select(AppSession).where(
                        AppSession.session_family_id == family_id
                    )
                )
            ).all()
            assert len(family_rows) >= 2
            assert all(row.revoked_at is not None for row in family_rows)
            assert all(
                row.session_family_id == original.session.session_family_id
                for row in family_rows
            )
        async with security_database.auth_session() as db:
            assert (
                await resolve_session(
                    db,
                    settings,
                    original.session_token,
                    touch=False,
                )
                is None
            )
            assert (
                await resolve_session(
                    db,
                    settings,
                    first_child.session_token,
                    touch=False,
                )
                is None
            )
            if isinstance(refresh_outcome, CreatedSession):
                assert (
                    await resolve_session(
                        db,
                        settings,
                        refresh_outcome.session_token,
                        touch=False,
                    )
                    is None
                )
            assert (
                await resolve_session(
                    db,
                    settings,
                    other_device.session_token,
                    touch=False,
                )
                is not None
            )
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_family_advisory_lock_releases_on_rollback_and_pool_reuse(
    security_database: SecurityDatabase,
) -> None:
    family_id = uuid4()

    async with security_database.runtime_helper_session() as first_db:
        await app_sessions._lock_session_family(first_db, family_id)
        await first_db.rollback()

    async with security_database.runtime_helper_session() as second_db:
        await asyncio.wait_for(
            app_sessions._lock_session_family(second_db, family_id),
            timeout=2,
        )
        await second_db.rollback()


@pytest.mark.asyncio
async def test_subject_invalidation_serializes_with_rotation_and_leaves_no_active_child(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    start_race = asyncio.Barrier(2)
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
    )
    actor_id, actor_session = await _create_master_actor(security_database)
    try:
        original = await _create_staff_session(
            security_database,
            subject_id=subject_id,
        )

        async def rotate_once() -> CreatedSession:
            async with security_database.runtime_helper_session() as db:
                loaded = await resolve_session(
                    db,
                    settings,
                    original.session_token,
                    touch=False,
                )
                assert loaded is not None
                await start_race.wait()
                rotated = await rotate_session(
                    db,
                    settings,
                    loaded,
                    session_token=original.session_token,
                )
                await db.commit()
                return rotated

        async def invalidate_once() -> int:
            async with _runtime_context_session(
                security_database,
                actor_session.session,
            ) as db:
                await start_race.wait()
                revoked = await revoke_subject_sessions(
                    db,
                    "staff",
                    subject_id,
                    "integration_authorization_change",
                )
                await db.commit()
                return revoked

        rotation_outcome, invalidation_outcome = await asyncio.wait_for(
            asyncio.gather(
                rotate_once(),
                invalidate_once(),
                return_exceptions=True,
            ),
            timeout=CONCURRENCY_TIMEOUT_SECONDS,
        )
        assert isinstance(invalidation_outcome, int), type(invalidation_outcome).__name__
        assert isinstance(
            rotation_outcome,
            (CreatedSession, AppSessionInvalidError),
        ), type(rotation_outcome).__name__

        async with security_database.owner_session() as db:
            generation = await db.scalar(
                text("SELECT session_generation FROM users WHERE id = :subject_id"),
                {"subject_id": subject_id},
            )
            rows = (
                await db.scalars(
                    select(AppSession).where(AppSession.subject_id == subject_id)
                )
            ).all()
            assert generation == 1
            assert rows
            assert all(row.revoked_at is not None for row in rows)

        async with security_database.auth_session() as db:
            assert (
                await resolve_session(
                    db,
                    settings,
                    original.session_token,
                    touch=False,
                )
                is None
            )

        async with security_database.auth_session() as db:
            with pytest.raises(AppSessionInvalidError):
                await create_session(
                    db,
                    settings,
                    "staff",
                    subject_id,
                    "supabase_staff",
                    expected_subject_session_generation=0,
                    upstream_subject_id=subject_id,
                )
            await db.rollback()
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=actor_id,
        )


@pytest.mark.asyncio
async def test_subject_invalidation_and_family_logout_do_not_deadlock(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    start_race = asyncio.Barrier(2)
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
    )
    actor_id, actor_session = await _create_master_actor(security_database)
    try:
        created = await _create_staff_session(
            security_database,
            subject_id=subject_id,
        )

        async def logout_once() -> int:
            async with security_database.auth_session() as db:
                loaded = await resolve_session(
                    db,
                    settings,
                    created.session_token,
                    touch=False,
                )
                assert loaded is not None
                await start_race.wait()
                revoked = await revoke_session_family_for_logout(
                    db,
                    settings,
                    session_token=created.session_token,
                    csrf_token=created.csrf_token,
                    reason="integration_logout",
                )
                await db.commit()
                return revoked

        async def invalidate_once() -> int:
            async with _runtime_context_session(
                security_database,
                actor_session.session,
            ) as db:
                await start_race.wait()
                revoked = await revoke_subject_sessions(
                    db,
                    "staff",
                    subject_id,
                    "integration_authorization_change",
                )
                await db.commit()
                return revoked

        logout_outcome, invalidation_outcome = await asyncio.wait_for(
            asyncio.gather(logout_once(), invalidate_once()),
            timeout=CONCURRENCY_TIMEOUT_SECONDS,
        )
        assert isinstance(logout_outcome, int)
        assert isinstance(invalidation_outcome, int)

        async with security_database.owner_session() as db:
            generation = await db.scalar(
                text("SELECT session_generation FROM users WHERE id = :subject_id"),
                {"subject_id": subject_id},
            )
            rows = (
                await db.scalars(
                    select(AppSession).where(AppSession.subject_id == subject_id)
                )
            ).all()
            assert generation == 1
            assert rows
            assert all(row.revoked_at is not None for row in rows)

        async with security_database.auth_session() as db:
            assert (
                await resolve_session(
                    db,
                    settings,
                    created.session_token,
                    touch=False,
                )
                is None
            )
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=actor_id,
        )


@pytest.mark.asyncio
async def test_password_reset_and_deactivation_invalidate_postgres_sessions(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings.model_copy(
        update={"auth_mode": "stub"}
    )
    subject_id = uuid4()
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
    )
    actor_id, actor_session = await _create_master_actor(security_database)
    actor = StaffActorContext(
        actor_user_id=actor_id,
        actor_role="admin",
        actor_name="Session Integration Actor",
        actor_site=None,
        actor_programme=None,
        actor_admin_level="master",
        raw_scope_metadata={"admin_level": "master"},
    )
    try:
        original = await _create_staff_session(
            security_database,
            subject_id=subject_id,
        )

        async with _runtime_context_session(
            security_database,
            actor_session.session,
        ) as db:
            await reset_staff_account_password(
                db,
                user_id=subject_id,
                payload=StaffAccountResetPasswordRequest(
                    password="integration-reset-password"
                ),
                actor=actor,
                settings=settings,
            )

        async with security_database.owner_session() as db:
            reset_state = (
                await db.execute(
                    text(
                        """
                        SELECT
                            session_generation,
                            session_issuance_blocked
                        FROM users
                        WHERE id = :subject_id
                        """
                    ),
                    {"subject_id": subject_id},
                )
            ).one()
            assert reset_state.session_generation == 2
            assert reset_state.session_issuance_blocked is False

        async with security_database.auth_session() as db:
            assert (
                await resolve_session(
                    db,
                    settings,
                    original.session_token,
                    touch=False,
                )
                is None
            )
        replacement = await _create_staff_session(
            security_database,
            subject_id=subject_id,
            expected_subject_session_generation=2,
        )

        async with _runtime_context_session(
            security_database,
            actor_session.session,
        ) as db:
            await update_staff_account(
                db,
                user_id=subject_id,
                payload=StaffAccountUpdateRequest(
                    account_display_name="Session Integration Staff",
                    account_type="programme_pc",
                    is_active=False,
                    programme_scope=["DR"],
                ),
                actor=actor,
            )

        async with security_database.owner_session() as db:
            deactivated_state = (
                await db.execute(
                    text(
                        """
                        SELECT is_active, session_generation
                        FROM users
                        WHERE id = :subject_id
                        """
                    ),
                    {"subject_id": subject_id},
                )
            ).one()
            assert deactivated_state.is_active is False
            assert deactivated_state.session_generation == 3

        async with security_database.auth_session() as db:
            assert (
                await resolve_session(
                    db,
                    settings,
                    replacement.session_token,
                    touch=False,
                )
                is None
            )
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=actor_id,
        )


@pytest.mark.asyncio
async def test_self_deactivation_audits_before_final_session_invalidation(
    security_database: SecurityDatabase,
) -> None:
    backup_master_id = uuid4()
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=backup_master_id,
        admin_level="master",
    )
    actor_id, actor_session = await _create_master_actor(security_database)
    actor = StaffActorContext(
        actor_user_id=actor_id,
        actor_role="admin",
        actor_name="Self Deactivation Integration Actor",
        actor_site=None,
        actor_programme=None,
        actor_admin_level="master",
        raw_scope_metadata={"admin_level": "master"},
    )
    try:
        async with _runtime_context_session(
            security_database,
            actor_session.session,
            lock_mode="exclusive",
        ) as db:
            response = await update_staff_account(
                db,
                user_id=actor_id,
                payload=StaffAccountUpdateRequest(
                    account_display_name="Inactive Integration Master",
                    account_type="master_admin",
                    is_active=False,
                ),
                actor=actor,
            )
            assert response["is_active"] is False

        async with security_database.owner_session() as db:
            actor_state = (
                await db.execute(
                    text(
                        """
                        SELECT is_active, session_generation
                        FROM public.users
                        WHERE id = :actor_id
                        """
                    ),
                    {"actor_id": actor_id},
                )
            ).one()
            family_rows = (
                await db.scalars(
                    select(AppSession).where(
                        AppSession.session_family_id
                        == actor_session.session.session_family_id
                    )
                )
            ).all()
            audit_row = (
                await db.execute(
                    text(
                        """
                        SELECT before_json, after_json, metadata_json
                        FROM public.audit_logs
                        WHERE action = 'admin.staff_account.update'
                          AND entity_type = 'staff_account'
                          AND entity_id = :entity_id
                        ORDER BY created_at DESC, id DESC
                        LIMIT 1
                        """
                    ),
                    {"entity_id": str(actor_id)},
                )
            ).mappings().one()

            assert actor_state.is_active is False
            assert actor_state.session_generation == 1
            assert family_rows
            assert all(row.revoked_at is not None for row in family_rows)
            assert audit_row["before_json"]["is_active"] is True
            assert audit_row["after_json"]["is_active"] is False
            assert audit_row["metadata_json"]["self_authorization_change"] is True
            assert audit_row["metadata_json"]["revoked_session_count"] is None
            assert (
                audit_row["metadata_json"]["session_revocation_timing"]
                == "final_protected_action_same_transaction"
            )

        async with security_database.auth_session() as db:
            assert (
                await resolve_session(
                    db,
                    security_database.settings,
                    actor_session.session_token,
                    touch=False,
                )
                is None
            )
    finally:
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=actor_id,
        )
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=backup_master_id,
        )


@pytest.mark.asyncio
async def test_concurrent_distinct_master_deactivations_preserve_one_active_master(
    security_database: SecurityDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_id, first_session = await _create_master_actor(security_database)
    second_id, second_session = await _create_master_actor(security_database)
    first_target_locked = asyncio.Event()
    release_first_target = asyncio.Event()
    pid_ready = {first_id: asyncio.Event(), second_id: asyncio.Event()}
    backend_pids: dict[UUID, int] = {}
    workers: list[asyncio.Task] = []
    real_get_staff_account_row = staff_accounts._get_staff_account_row

    async def hold_first_target_lock(
        db: AsyncSession,
        *,
        user_id: UUID,
        for_update: bool = False,
    ) -> dict:
        row = await real_get_staff_account_row(
            db,
            user_id=user_id,
            for_update=for_update,
        )
        if user_id == first_id and for_update:
            first_target_locked.set()
            await release_first_target.wait()
        return row

    monkeypatch.setattr(
        staff_accounts,
        "_get_staff_account_row",
        hold_first_target_lock,
    )

    def actor_for(user_id: UUID, name: str) -> StaffActorContext:
        return StaffActorContext(
            actor_user_id=user_id,
            actor_role="admin",
            actor_name=name,
            actor_site=None,
            actor_programme=None,
            actor_admin_level="master",
            raw_scope_metadata={"admin_level": "master"},
        )

    async def deactivate(
        user_id: UUID,
        actor_session: CreatedSession,
        actor: StaffActorContext,
    ) -> dict | ApiError:
        async with _runtime_context_session(
            security_database,
            actor_session.session,
            lock_mode="exclusive",
        ) as db:
            backend_pids[user_id] = int(
                await db.scalar(text("SELECT pg_catalog.pg_backend_pid()"))
            )
            pid_ready[user_id].set()
            try:
                return await update_staff_account(
                    db,
                    user_id=user_id,
                    payload=StaffAccountUpdateRequest(
                        account_display_name=f"Inactive {actor.actor_name}",
                        account_type="master_admin",
                        is_active=False,
                    ),
                    actor=actor,
                )
            except ApiError as exc:
                return exc

    try:
        async with security_database.owner_session() as db:
            active_master_ids = set(
                await db.scalars(
                    text(
                        """
                        SELECT id
                        FROM public.users
                        WHERE role = 'admin'
                          AND admin_level = 'master'
                          AND is_active = true
                        """
                    )
                )
            )
            assert active_master_ids == {first_id, second_id}

        first_worker = asyncio.create_task(
            deactivate(
                first_id,
                first_session,
                actor_for(first_id, "First Concurrent Master"),
            )
        )
        workers.append(first_worker)
        await _wait_for_concurrency_checkpoint(
            first_target_locked,
            first_worker,
            label="first staff target row lock",
        )

        second_worker = asyncio.create_task(
            deactivate(
                second_id,
                second_session,
                actor_for(second_id, "Second Concurrent Master"),
            )
        )
        workers.append(second_worker)
        await _wait_for_concurrency_checkpoint(
            pid_ready[second_id],
            second_worker,
            label="second staff update backend pid",
        )
        async with security_database.owner_session() as observer:
            await _wait_until_backend_is_blocked_by(
                observer,
                blocked_backend_pid=backend_pids[second_id],
                blocker_backend_pid=backend_pids[first_id],
                worker=second_worker,
                label="cross-account staff update invariant lock",
            )

        release_first_target.set()
        first_outcome, second_outcome = await asyncio.wait_for(
            asyncio.gather(first_worker, second_worker),
            timeout=CONCURRENCY_TIMEOUT_SECONDS,
        )
        assert isinstance(first_outcome, dict)
        assert first_outcome["is_active"] is False
        assert isinstance(second_outcome, ApiError)
        assert second_outcome.status_code == 422
        assert second_outcome.detail == (
            "Cannot deactivate or demote the last active Master Admin"
        )

        async with security_database.owner_session() as db:
            active_master_ids = set(
                await db.scalars(
                    text(
                        """
                        SELECT id
                        FROM public.users
                        WHERE role = 'admin'
                          AND admin_level = 'master'
                          AND is_active = true
                        """
                    )
                )
            )
            assert active_master_ids == {second_id}
    finally:
        release_first_target.set()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=first_id,
        )
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=second_id,
        )


@pytest.mark.asyncio
async def test_display_only_staff_patch_cannot_restore_stale_authorization(
    security_database: SecurityDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_actor_id, first_actor_session = await _create_master_actor(
        security_database
    )
    second_actor_id, second_actor_session = await _create_master_actor(
        security_database
    )
    target_id = uuid4()
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=target_id,
        admin_level="master",
    )
    first_target_locked = asyncio.Event()
    release_first_target = asyncio.Event()
    second_pid_ready = asyncio.Event()
    backend_pids: dict[str, int] = {}
    first_db: AsyncSession | None = None
    workers: list[asyncio.Task] = []
    real_get_staff_account_row = staff_accounts._get_staff_account_row

    async def hold_first_target_lock(
        db: AsyncSession,
        *,
        user_id: UUID,
        for_update: bool = False,
    ) -> dict:
        row = await real_get_staff_account_row(
            db,
            user_id=user_id,
            for_update=for_update,
        )
        if db is first_db and user_id == target_id and for_update:
            first_target_locked.set()
            await release_first_target.wait()
        return row

    monkeypatch.setattr(
        staff_accounts,
        "_get_staff_account_row",
        hold_first_target_lock,
    )
    first_actor = StaffActorContext(
        actor_user_id=first_actor_id,
        actor_role="admin",
        actor_name="Authorization Change Actor",
        actor_site=None,
        actor_programme=None,
        actor_admin_level="master",
        raw_scope_metadata={"admin_level": "master"},
    )
    second_actor = StaffActorContext(
        actor_user_id=second_actor_id,
        actor_role="admin",
        actor_name="Display Change Actor",
        actor_site=None,
        actor_programme=None,
        actor_admin_level="master",
        raw_scope_metadata={"admin_level": "master"},
    )

    async def demote_target() -> dict:
        nonlocal first_db
        async with _runtime_context_session(
            security_database,
            first_actor_session.session,
            lock_mode="exclusive",
        ) as db:
            first_db = db
            backend_pids["first"] = int(
                await db.scalar(text("SELECT pg_catalog.pg_backend_pid()"))
            )
            return await update_staff_account(
                db,
                user_id=target_id,
                payload=StaffAccountUpdateRequest(
                    account_display_name="Demoted Programme PC",
                    account_type="programme_pc",
                    is_active=True,
                    programme_scope=["DR"],
                ),
                actor=first_actor,
            )

    async def rename_target() -> dict:
        async with _runtime_context_session(
            security_database,
            second_actor_session.session,
            lock_mode="exclusive",
        ) as db:
            backend_pids["second"] = int(
                await db.scalar(text("SELECT pg_catalog.pg_backend_pid()"))
            )
            second_pid_ready.set()
            return await update_staff_account(
                db,
                user_id=target_id,
                payload=StaffAccountUpdateRequest(
                    account_display_name="Display-only rename",
                ),
                actor=second_actor,
            )

    try:
        first_worker = asyncio.create_task(demote_target())
        workers.append(first_worker)
        await _wait_for_concurrency_checkpoint(
            first_target_locked,
            first_worker,
            label="authorization-changing target row lock",
        )

        second_worker = asyncio.create_task(rename_target())
        workers.append(second_worker)
        await _wait_for_concurrency_checkpoint(
            second_pid_ready,
            second_worker,
            label="display-only staff update backend pid",
        )
        async with security_database.owner_session() as observer:
            await _wait_until_backend_is_blocked_by(
                observer,
                blocked_backend_pid=backend_pids["second"],
                blocker_backend_pid=backend_pids["first"],
                worker=second_worker,
                label="display-only staff update serialization",
            )

        release_first_target.set()
        demoted, renamed = await asyncio.wait_for(
            asyncio.gather(first_worker, second_worker),
            timeout=CONCURRENCY_TIMEOUT_SECONDS,
        )
        assert demoted["account_type"] == "programme_pc"
        assert renamed["account_display_name"] == "Display-only rename"
        assert renamed["account_type"] == "programme_pc"
        assert renamed["programme_scope"] == ["DR"]

        async with security_database.owner_session() as db:
            target = (
                await db.execute(
                    text(
                        """
                        SELECT
                            name,
                            role,
                            admin_level,
                            programme_scope,
                            is_active,
                            session_generation
                        FROM public.users
                        WHERE id = :target_id
                        """
                    ),
                    {"target_id": target_id},
                )
            ).mappings().one()
            assert target["name"] == "Display-only rename"
            assert target["role"] == "admin"
            assert target["admin_level"] == "programme"
            assert target["programme_scope"] == ["DR"]
            assert target["is_active"] is True
            assert target["session_generation"] == 1
    finally:
        release_first_target.set()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=target_id,
        )
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=first_actor_id,
        )
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=second_actor_id,
        )


@pytest.mark.asyncio
async def test_concurrent_password_resets_serialize_upstream_and_keep_sessions_fenced(
    security_database: SecurityDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = security_database.settings
    subject_id = uuid4()
    supabase_user_id = uuid4()
    first_upstream_entered = asyncio.Event()
    release_first_upstream = asyncio.Event()
    second_fence_started = asyncio.Event()

    class _BlockingSupabaseAdmin:
        def __init__(self) -> None:
            self.active_calls = 0
            self.max_active_calls = 0
            self.passwords: list[str] = []

        async def update_user_password(
            self,
            *,
            supabase_user_id: UUID,
            password: str,
        ) -> None:
            assert supabase_user_id == supabase_user_id_value
            self.passwords.append(password)
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
            try:
                if len(self.passwords) == 1:
                    first_upstream_entered.set()
                    await release_first_upstream.wait()
            finally:
                self.active_calls -= 1

    supabase_user_id_value = supabase_user_id
    fake_admin = _BlockingSupabaseAdmin()
    monkeypatch.setattr(
        staff_accounts,
        "SupabaseAdminClient",
        lambda _settings: fake_admin,
    )
    real_revoke_subject_sessions = staff_accounts.revoke_subject_sessions
    fence_call_count = 0

    async def traced_revoke_subject_sessions(*args, **kwargs):
        nonlocal fence_call_count
        fence_call_count += 1
        if fence_call_count == 2:
            second_fence_started.set()
        return await real_revoke_subject_sessions(*args, **kwargs)

    monkeypatch.setattr(
        staff_accounts,
        "revoke_subject_sessions",
        traced_revoke_subject_sessions,
    )
    supabase_settings = settings.model_copy(update={"auth_mode": "supabase"})
    await _insert_test_subject(
        security_database,
        subject_type="staff",
        subject_id=subject_id,
        supabase_user_id=supabase_user_id,
    )
    first_actor_id, first_actor_session = await _create_master_actor(
        security_database
    )
    second_actor_id, second_actor_session = await _create_master_actor(
        security_database
    )
    first_actor = StaffActorContext(
        actor_user_id=first_actor_id,
        actor_role="admin",
        actor_name="First Session Integration Actor",
        actor_site=None,
        actor_programme=None,
        actor_admin_level="master",
        raw_scope_metadata={"admin_level": "master"},
    )
    second_actor = StaffActorContext(
        actor_user_id=second_actor_id,
        actor_role="admin",
        actor_name="Second Session Integration Actor",
        actor_site=None,
        actor_programme=None,
        actor_admin_level="master",
        raw_scope_metadata={"admin_level": "master"},
    )
    try:
        original = await _create_staff_session(
            security_database,
            subject_id=subject_id,
            upstream_subject_id=supabase_user_id,
        )

        async def reset_once(
            password: str,
            *,
            actor: StaffActorContext,
            actor_session: CreatedSession,
        ) -> dict:
            async with _runtime_context_session(
                security_database,
                actor_session.session,
            ) as db:
                return await reset_staff_account_password(
                    db,
                    user_id=subject_id,
                    payload=StaffAccountResetPasswordRequest(password=password),
                    actor=actor,
                    settings=supabase_settings,
                )

        first_reset: asyncio.Task | None = None
        second_reset: asyncio.Task | None = None
        try:
            first_reset = asyncio.create_task(
                reset_once(
                    "integration-concurrent-reset-one",
                    actor=first_actor,
                    actor_session=first_actor_session,
                )
            )
            await _wait_for_concurrency_checkpoint(
                first_upstream_entered,
                first_reset,
                label="the first password-reset upstream call",
            )
            second_reset = asyncio.create_task(
                reset_once(
                    "integration-concurrent-reset-two",
                    actor=second_actor,
                    actor_session=second_actor_session,
                )
            )
            await _wait_for_concurrency_checkpoint(
                second_fence_started,
                first_reset,
                second_reset,
                label="the second password-reset database fence",
            )

            assert fake_admin.active_calls == 1
            assert len(fake_admin.passwords) == 1
            release_first_upstream.set()
            first_result, second_result = await asyncio.wait_for(
                asyncio.gather(first_reset, second_reset),
                timeout=CONCURRENCY_TIMEOUT_SECONDS,
            )
        finally:
            release_first_upstream.set()
            reset_tasks = [
                task
                for task in (first_reset, second_reset)
                if task is not None
            ]
            for task in reset_tasks:
                if not task.done():
                    task.cancel()
            if reset_tasks:
                await asyncio.gather(*reset_tasks, return_exceptions=True)

        assert first_result["id"] == subject_id
        assert second_result["id"] == subject_id
        assert fake_admin.max_active_calls == 1
        assert fake_admin.passwords == [
            "integration-concurrent-reset-one",
            "integration-concurrent-reset-two",
        ]

        async with security_database.owner_session() as db:
            state = (
                await db.execute(
                    text(
                        """
                        SELECT session_generation, session_issuance_blocked
                        FROM users
                        WHERE id = :subject_id
                        """
                    ),
                    {"subject_id": subject_id},
                )
            ).one()
            rows = (
                await db.scalars(
                    select(AppSession).where(AppSession.subject_id == subject_id)
                )
            ).all()
            assert state.session_generation == 4
            assert state.session_issuance_blocked is False
            assert rows
            assert all(row.revoked_at is not None for row in rows)

        async with security_database.auth_session() as db:
            assert (
                await resolve_session(
                    db,
                    settings,
                    original.session_token,
                    touch=False,
                )
                is None
            )
    finally:
        release_first_upstream.set()
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=subject_id,
        )
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=first_actor_id,
        )
        await _delete_test_subject(
            security_database,
            subject_type="staff",
            subject_id=second_actor_id,
        )


@pytest.mark.asyncio
async def test_concurrent_postgres_rate_limit_is_atomic_and_identifier_is_hmac_only(
    security_database: SecurityDatabase,
) -> None:
    settings = security_database.settings
    scope = f"security_integration_{uuid4().hex}"
    raw_identifier = "resident@example.com|MCR:M12345A"
    policy = RateLimitPolicy(
        scope=scope,
        limit=5,
        window_seconds=60,
        message="Too many requests",
    )

    async def attempt():
        async with security_database.auth_session() as db:
            return await check_rate_limit(
                db,
                settings=settings,
                policy=policy,
                identifier=raw_identifier,
            )

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(attempt() for _ in range(12))),
            timeout=CONCURRENCY_TIMEOUT_SECONDS,
        )
        assert sum(result.allowed for result in results) == 5
        assert sorted(result.request_count for result in results) == list(range(1, 13))

        async with security_database.owner_session() as db:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT key_hash, request_count
                        FROM rate_limit_buckets
                        WHERE scope = :scope
                        """
                    ),
                    {"scope": scope},
                )
            ).mappings().one()
            assert row["request_count"] == 12
            assert raw_identifier.casefold() not in row["key_hash"].casefold()
            assert "resident@example.com" not in row["key_hash"]
            assert "M12345A" not in row["key_hash"]
    finally:
        async with security_database.owner_session() as db:
            await db.execute(
                text("DELETE FROM rate_limit_buckets WHERE scope = :scope"),
                {"scope": scope},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_privilege_hardening_preserves_runtime_and_denies_public_browser_boundary(
    security_database: SecurityDatabase,
) -> None:
    async with security_database.runtime_helper_session() as db:
        runtime_access = await db.scalar(
            text(
                """
                SELECT has_table_privilege(
                    current_user,
                    'public.app_sessions',
                    'SELECT,INSERT,UPDATE,DELETE'
                )
                """
            )
        )
        runtime_helpers = (
            await db.execute(
                text(
                    """
                    SELECT
                        has_function_privilege(
                            current_user,
                            'mata_rls.resolve_app_session_lifecycle(bytea,integer)',
                            'EXECUTE'
                        ) AS resolve_session,
                        has_function_privilege(
                            current_user,
                            'mata_rls.touch_app_session_lifecycle(bytea,uuid,integer,integer)',
                            'EXECUTE'
                        ) AS touch_session,
                        has_function_privilege(
                            current_user,
                            'mata_rls.validate_app_session_csrf(bytea,uuid,bytea)',
                            'EXECUTE'
                        ) AS validate_csrf,
                        has_function_privilege(
                            current_user,
                            'mata_rls.rotate_app_session_lifecycle(bytea,uuid,uuid,bytea,bytea,integer,bytea)',
                            'EXECUTE'
                        ) AS rotate_session,
                        has_function_privilege(
                            current_user,
                            'mata_rls.issue_staff_app_session_lifecycle(uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)',
                            'EXECUTE'
                        ) AS issue_staff_session,
                        has_function_privilege(
                            current_user,
                            'mata_rls.resolve_app_session(bytea,boolean,integer)',
                            'EXECUTE'
                        ) AS retired_resolve_session,
                        has_function_privilege(
                            current_user,
                            'mata_rls.rotate_app_session(bytea,uuid,uuid,bytea,bytea,integer,bytea)',
                            'EXECUTE'
                        ) AS retired_rotate_session,
                        has_function_privilege(
                            current_user,
                            'mata_rls.issue_staff_app_session(uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)',
                            'EXECUTE'
                        ) AS retired_issue_staff_session
                    """
                )
            )
        ).one()

    async with security_database.auth_session() as db:
        auth_access = await db.scalar(
            text(
                """
                SELECT has_table_privilege(
                    current_user,
                    'public.app_sessions',
                    'SELECT,INSERT,UPDATE,DELETE'
                )
                """
            )
        )
        auth_helpers = (
            await db.execute(
                text(
                    """
                    SELECT
                        has_function_privilege(
                            current_user,
                            'mata_rls.resolve_app_session_lifecycle(bytea,integer)',
                            'EXECUTE'
                        ) AS resolve_session,
                        has_function_privilege(
                            current_user,
                            'mata_rls.touch_app_session_lifecycle(bytea,uuid,integer,integer)',
                            'EXECUTE'
                        ) AS touch_session,
                        has_function_privilege(
                            current_user,
                            'mata_rls.validate_app_session_csrf(bytea,uuid,bytea)',
                            'EXECUTE'
                        ) AS validate_csrf,
                        has_function_privilege(
                            current_user,
                            'mata_rls.rotate_app_session_lifecycle(bytea,uuid,uuid,bytea,bytea,integer,bytea)',
                            'EXECUTE'
                        ) AS rotate_session,
                        has_function_privilege(
                            current_user,
                            'mata_rls.issue_staff_app_session_lifecycle(uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)',
                            'EXECUTE'
                        ) AS issue_staff_session,
                        has_function_privilege(
                            current_user,
                            'mata_rls.resolve_app_session(bytea,boolean,integer)',
                            'EXECUTE'
                        ) AS retired_resolve_session,
                        has_function_privilege(
                            current_user,
                            'mata_rls.rotate_app_session(bytea,uuid,uuid,bytea,bytea,integer,bytea)',
                            'EXECUTE'
                        ) AS retired_rotate_session,
                        has_function_privilege(
                            current_user,
                            'mata_rls.issue_staff_app_session(uuid,uuid,bigint,uuid,bytea,bytea,integer,integer,bytea)',
                            'EXECUTE'
                        ) AS retired_issue_staff_session
                    """
                )
            )
        ).one()

    async with security_database.owner_session() as db:
        public_access = await db.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_class AS relation
                    CROSS JOIN LATERAL aclexplode(
                        COALESCE(relation.relacl, acldefault('r', relation.relowner))
                    ) AS privilege
                    WHERE relation.oid = 'public.app_sessions'::regclass
                      AND privilege.grantee = 0
                      AND privilege.privilege_type IN (
                          'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'
                      )
                )
                """
            )
        )
        relation_flags = (
            await db.execute(
                text(
                    """
                    SELECT relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE oid = 'public.app_sessions'::regclass
                    """
                )
            )
        ).one()
        browser_roles = (
            await db.execute(
                text("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
            )
        ).scalars().all()
        for browser_role in browser_roles:
            assert not await db.scalar(
                text(
                    """
                    SELECT has_table_privilege(
                        :role_name,
                        'public.app_sessions',
                        'SELECT,INSERT,UPDATE,DELETE'
                    )
                    """
                ),
                {"role_name": browser_role},
            )

    assert runtime_access is False
    assert auth_access is False
    assert public_access is False
    assert relation_flags.relrowsecurity is True
    assert relation_flags.relforcerowsecurity is False
    assert runtime_helpers.resolve_session is True
    assert runtime_helpers.touch_session is True
    assert runtime_helpers.validate_csrf is True
    assert runtime_helpers.rotate_session is True
    assert runtime_helpers.issue_staff_session is False
    assert runtime_helpers.retired_resolve_session is False
    assert runtime_helpers.retired_rotate_session is False
    assert runtime_helpers.retired_issue_staff_session is False
    assert auth_helpers.resolve_session is True
    assert auth_helpers.touch_session is True
    assert auth_helpers.validate_csrf is True
    assert auth_helpers.rotate_session is False
    assert auth_helpers.issue_staff_session is True
    assert auth_helpers.retired_resolve_session is False
    assert auth_helpers.retired_rotate_session is False
    assert auth_helpers.retired_issue_staff_session is False
