from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.config import Settings
from app.dependencies.staff_actor import StaffActorContext
from app.models.resident import ExternalResident, ResidentPosting
from app.models.session import AppSession
from app.services import app_sessions, staff_accounts
from app.schemas.admin import (
    StaffAccountResetPasswordRequest,
    StaffAccountUpdateRequest,
)
from app.services.app_sessions import (
    AppSessionInvalidError,
    CreatedSession,
    cleanup_sessions,
    create_session,
    resolve_session,
    revoke_session,
    revoke_session_family,
    revoke_subject_sessions,
    rotate_session,
    validate_csrf,
)
from app.services.persistent_rate_limit import RateLimitPolicy, check_rate_limit
from app.services.staff_accounts import (
    reset_staff_account_password,
    update_staff_account,
)


SESSION_KEY = "postgres-session-integration-key-at-least-32-characters"
RATE_KEY = "postgres-rate-integration-key-at-least-32-characters"


def _assert_disposable_database(database_url: str) -> None:
    url = make_url(database_url)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1"}
        or not (url.database or "").startswith("mata_phase5b_verify_")
    ):
        pytest.fail(
            "Security integration tests require a named disposable local PostgreSQL database",
            pytrace=False,
        )


@pytest_asyncio.fixture
async def security_database() -> AsyncIterator[tuple[AsyncEngine, Settings]]:
    settings = Settings(
        _env_file=None,
        environment="test",
        mata_session_hash_key=SESSION_KEY,
        rate_limit_hash_secret=RATE_KEY,
    )
    _assert_disposable_database(settings.database_url)
    engine = create_async_engine(
        settings.database_url,
        pool_size=5,
        max_overflow=0,
    )
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert revision == "20260722_000024"
        yield engine, settings
    finally:
        await engine.dispose()


async def _delete_subject_sessions(engine: AsyncEngine, subject_id: UUID) -> None:
    async with AsyncSession(engine) as db:
        await db.execute(
            text("DELETE FROM app_sessions WHERE subject_id = :subject_id"),
            {"subject_id": subject_id},
        )
        await db.commit()


async def _insert_test_subject(
    engine: AsyncEngine,
    *,
    subject_type: str,
    subject_id: UUID,
) -> None:
    async with AsyncSession(engine) as db:
        if subject_type == "staff":
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
                        is_active
                    )
                    VALUES (
                        :subject_id,
                        :email,
                        'integration-only',
                        'admin',
                        'Session Integration Staff',
                        'programme',
                        true
                    )
                    """
                ),
                {
                    "subject_id": subject_id,
                    "email": f"{subject_id.hex}@example.invalid",
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
                    "mcr": f"T{subject_id.hex[:16].upper()}",
                },
            )
        else:
            raise AssertionError(f"Unsupported integration subject type: {subject_type}")
        await db.commit()


async def _delete_test_subject(
    engine: AsyncEngine,
    *,
    subject_type: str,
    subject_id: UUID,
) -> None:
    await _delete_subject_sessions(engine, subject_id)
    table_name = "users" if subject_type == "staff" else "residents"
    async with AsyncSession(engine) as db:
        if subject_type == "staff":
            await db.execute(
                text(
                    """
                    DELETE FROM audit_logs
                    WHERE actor_user_id = :subject_id
                       OR entity_id = :subject_id
                    """
                ),
                {"subject_id": subject_id},
            )
        await db.execute(
            text(f"DELETE FROM {table_name} WHERE id = :subject_id"),
            {"subject_id": subject_id},
        )
        await db.commit()


@pytest.mark.asyncio
async def test_session_generation_orm_mapping_matches_postgres_schema(
    security_database: tuple[AsyncEngine, Settings],
) -> None:
    engine, _ = security_database
    external_resident_id = uuid4()

    assert "session_generation" in ExternalResident.__table__.c
    assert "session_generation" not in ResidentPosting.__table__.c

    async with AsyncSession(engine) as db:
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
                "mcr": f"T{external_resident_id.hex[:16].upper()}",
                "posting_code": posting_code,
            },
        )
        await db.commit()

    try:
        async with AsyncSession(engine) as db:
            external_resident = await db.scalar(
                select(ExternalResident).where(
                    ExternalResident.id == external_resident_id
                )
            )
            assert external_resident is not None
            assert external_resident.session_generation == 7
            await db.execute(select(ResidentPosting).limit(1))
    finally:
        async with AsyncSession(engine) as db:
            await db.execute(
                text("DELETE FROM external_residents WHERE id = :external_resident_id"),
                {"external_resident_id": external_resident_id},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_cookie_session_create_resolve_revoke_uses_digest_only_postgres(
    security_database: tuple[AsyncEngine, Settings],
) -> None:
    engine, settings = security_database
    subject_id = uuid4()
    await _insert_test_subject(
        engine,
        subject_type="resident",
        subject_id=subject_id,
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            created = await create_session(
                db,
                settings,
                "resident",
                subject_id,
                "mata_resident",
                expected_subject_session_generation=0,
                user_agent="PostgreSQL integration browser",
            )
            await db.commit()

        async with AsyncSession(engine, expire_on_commit=False) as db:
            stored = await db.scalar(
                select(AppSession).where(AppSession.id == created.session.id)
            )
            assert stored is not None
            assert len(stored.token_digest) == 32
            assert len(stored.csrf_token_digest) == 32
            assert created.session_token.encode() not in stored.token_digest
            assert created.csrf_token.encode() not in stored.csrf_token_digest

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

        async with AsyncSession(engine) as db:
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
            engine,
            subject_type="resident",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_postgres_session_expiry_boundary_is_rejected(
    security_database: tuple[AsyncEngine, Settings],
) -> None:
    engine, settings = security_database
    subject_id = uuid4()
    issued_at = datetime(2026, 7, 22, 9, 0, tzinfo=UTC)
    await _insert_test_subject(
        engine,
        subject_type="resident",
        subject_id=subject_id,
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
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

        async with AsyncSession(engine) as db:
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
            engine,
            subject_type="resident",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_postgres_session_cleanup_is_triggered_bounded_and_skips_locked_rows(
    security_database: tuple[AsyncEngine, Settings],
) -> None:
    engine, settings = security_database
    subject_id = uuid4()
    current_time = datetime.now(UTC)
    old_issue_time = current_time - timedelta(hours=2)
    cleanup_settings = settings.model_copy(
        update={
            "session_cleanup_retention_seconds": 0,
            "session_cleanup_batch_size": 2,
        }
    )
    await _insert_test_subject(
        engine,
        subject_type="resident",
        subject_id=subject_id,
    )
    try:
        old_sessions: list[CreatedSession] = []
        async with AsyncSession(engine, expire_on_commit=False) as db:
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
        async with AsyncSession(engine, expire_on_commit=False) as db:
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
        async with AsyncSession(engine) as db:
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
        async with AsyncSession(engine) as lock_db:
            locked = await lock_db.scalar(
                select(AppSession)
                .where(AppSession.id == locked_id)
                .with_for_update()
            )
            assert locked is not None
            async with AsyncSession(engine) as cleanup_db:
                deleted = await cleanup_sessions(
                    cleanup_db,
                    cleanup_settings,
                    now=current_time,
                )
                await cleanup_db.commit()
            assert deleted == 1
            await lock_db.rollback()

        async with AsyncSession(engine) as db:
            assert (
                await cleanup_sessions(db, cleanup_settings, now=current_time)
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
            engine,
            subject_type="resident",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_concurrent_postgres_session_rotation_has_one_winner(
    security_database: tuple[AsyncEngine, Settings],
) -> None:
    engine, settings = security_database
    subject_id = uuid4()
    both_loaded = asyncio.Barrier(2)
    await _insert_test_subject(
        engine,
        subject_type="staff",
        subject_id=subject_id,
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            original = await create_session(
                db,
                settings,
                "staff",
                subject_id,
                "supabase_staff",
                expected_subject_session_generation=0,
            )
            await db.commit()

        async def rotate_once() -> CreatedSession:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                loaded = await resolve_session(
                    db,
                    settings,
                    original.session_token,
                    touch=False,
                )
                await both_loaded.wait()
                assert loaded is not None
                rotated = await rotate_session(
                    db,
                    settings,
                    loaded,
                    session_token=original.session_token,
                )
                await db.commit()
                return rotated

        outcomes = await asyncio.gather(
            rotate_once(),
            rotate_once(),
            return_exceptions=True,
        )
        winners = [item for item in outcomes if isinstance(item, CreatedSession)]
        losers = [item for item in outcomes if isinstance(item, AppSessionInvalidError)]
        outcome_types = [type(item).__name__ for item in outcomes]
        assert len(winners) == 1, outcome_types
        assert len(losers) == 1, outcome_types

        async with AsyncSession(engine) as db:
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
    finally:
        await _delete_test_subject(
            engine,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_refresh_racing_logout_revokes_the_entire_rotation_family_only(
    security_database: tuple[AsyncEngine, Settings],
) -> None:
    engine, settings = security_database
    subject_id = uuid4()
    both_loaded = asyncio.Barrier(2)
    await _insert_test_subject(
        engine,
        subject_type="staff",
        subject_id=subject_id,
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            original = await create_session(
                db,
                settings,
                "staff",
                subject_id,
                "supabase_staff",
                expected_subject_session_generation=0,
            )
            other_device = await create_session(
                db,
                settings,
                "staff",
                subject_id,
                "supabase_staff",
                expected_subject_session_generation=0,
            )
            await db.commit()

        async with AsyncSession(engine, expire_on_commit=False) as db:
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

        async def refresh_once() -> CreatedSession:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                loaded = await resolve_session(
                    db,
                    settings,
                    first_child.session_token,
                    touch=False,
                )
                assert loaded is not None
                await both_loaded.wait()
                refreshed = await rotate_session(
                    db,
                    settings,
                    loaded,
                    session_token=first_child.session_token,
                )
                await db.commit()
                return refreshed

        async def logout_once() -> int:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                loaded = await resolve_session(
                    db,
                    settings,
                    first_child.session_token,
                    touch=False,
                )
                assert loaded is not None
                await both_loaded.wait()
                revoked = await revoke_session_family(
                    db,
                    loaded,
                    reason="integration_logout",
                )
                await db.commit()
                return revoked

        refresh_outcome, logout_outcome = await asyncio.gather(
            refresh_once(),
            logout_once(),
            return_exceptions=True,
        )
        assert isinstance(
            refresh_outcome,
            (CreatedSession, AppSessionInvalidError),
        ), type(refresh_outcome).__name__
        assert isinstance(logout_outcome, int), type(logout_outcome).__name__
        assert logout_outcome >= 1

        family_id = first_child.session.session_family_id
        async with AsyncSession(engine) as db:
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
            engine,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_family_advisory_lock_releases_on_rollback_and_pool_reuse(
    security_database: tuple[AsyncEngine, Settings],
) -> None:
    engine, _ = security_database
    family_id = uuid4()

    async with AsyncSession(engine) as first_db:
        await app_sessions._lock_session_family(first_db, family_id)
        await first_db.rollback()

    async with AsyncSession(engine) as second_db:
        await asyncio.wait_for(
            app_sessions._lock_session_family(second_db, family_id),
            timeout=2,
        )
        await second_db.rollback()


@pytest.mark.asyncio
async def test_subject_invalidation_serializes_with_rotation_and_leaves_no_active_child(
    security_database: tuple[AsyncEngine, Settings],
) -> None:
    engine, settings = security_database
    subject_id = uuid4()
    start_race = asyncio.Barrier(2)
    await _insert_test_subject(
        engine,
        subject_type="staff",
        subject_id=subject_id,
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            original = await create_session(
                db,
                settings,
                "staff",
                subject_id,
                "supabase_staff",
                expected_subject_session_generation=0,
            )
            await db.commit()

        async def rotate_once() -> CreatedSession:
            async with AsyncSession(engine, expire_on_commit=False) as db:
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
            async with AsyncSession(engine) as db:
                await start_race.wait()
                revoked = await revoke_subject_sessions(
                    db,
                    "staff",
                    subject_id,
                    "integration_authorization_change",
                )
                await db.commit()
                return revoked

        rotation_outcome, invalidation_outcome = await asyncio.gather(
            rotate_once(),
            invalidate_once(),
            return_exceptions=True,
        )
        assert isinstance(invalidation_outcome, int), type(invalidation_outcome).__name__
        assert isinstance(
            rotation_outcome,
            (CreatedSession, AppSessionInvalidError),
        ), type(rotation_outcome).__name__

        async with AsyncSession(engine) as db:
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
            assert (
                await resolve_session(
                    db,
                    settings,
                    original.session_token,
                    touch=False,
                )
                is None
            )

        async with AsyncSession(engine) as db:
            with pytest.raises(AppSessionInvalidError):
                await create_session(
                    db,
                    settings,
                    "staff",
                    subject_id,
                    "supabase_staff",
                    expected_subject_session_generation=0,
                )
            await db.rollback()
    finally:
        await _delete_test_subject(
            engine,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_subject_invalidation_and_family_logout_do_not_deadlock(
    security_database: tuple[AsyncEngine, Settings],
) -> None:
    engine, settings = security_database
    subject_id = uuid4()
    start_race = asyncio.Barrier(2)
    await _insert_test_subject(
        engine,
        subject_type="staff",
        subject_id=subject_id,
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            created = await create_session(
                db,
                settings,
                "staff",
                subject_id,
                "supabase_staff",
                expected_subject_session_generation=0,
            )
            await db.commit()

        async def logout_once() -> int:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                loaded = await resolve_session(
                    db,
                    settings,
                    created.session_token,
                    touch=False,
                )
                assert loaded is not None
                await start_race.wait()
                revoked = await revoke_session_family(
                    db,
                    loaded,
                    reason="integration_logout",
                )
                await db.commit()
                return revoked

        async def invalidate_once() -> int:
            async with AsyncSession(engine) as db:
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
            timeout=5,
        )
        assert isinstance(logout_outcome, int)
        assert isinstance(invalidation_outcome, int)

        async with AsyncSession(engine) as db:
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
            engine,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_password_reset_and_deactivation_invalidate_postgres_sessions(
    security_database: tuple[AsyncEngine, Settings],
) -> None:
    engine, settings = security_database
    subject_id = uuid4()
    actor = StaffActorContext(
        actor_user_id=subject_id,
        actor_role="admin",
        actor_name="Session Integration Actor",
        actor_site=None,
        actor_programme=None,
        actor_admin_level="master",
        raw_scope_metadata={"admin_level": "master"},
    )
    await _insert_test_subject(
        engine,
        subject_type="staff",
        subject_id=subject_id,
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            original = await create_session(
                db,
                settings,
                "staff",
                subject_id,
                "supabase_staff",
                expected_subject_session_generation=0,
            )
            await db.commit()

        async with AsyncSession(engine, expire_on_commit=False) as db:
            await reset_staff_account_password(
                db,
                user_id=subject_id,
                payload=StaffAccountResetPasswordRequest(
                    password="integration-reset-password"
                ),
                actor=actor,
                settings=settings,
            )

        async with AsyncSession(engine, expire_on_commit=False) as db:
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
            assert (
                await resolve_session(
                    db,
                    settings,
                    original.session_token,
                    touch=False,
                )
                is None
            )
            replacement = await create_session(
                db,
                settings,
                "staff",
                subject_id,
                "supabase_staff",
                expected_subject_session_generation=2,
            )
            await db.commit()

        async with AsyncSession(engine, expire_on_commit=False) as db:
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

        async with AsyncSession(engine) as db:
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
            engine,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_concurrent_password_resets_serialize_upstream_and_keep_sessions_fenced(
    security_database: tuple[AsyncEngine, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, settings = security_database
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
    actor = StaffActorContext(
        actor_user_id=subject_id,
        actor_role="admin",
        actor_name="Session Integration Actor",
        actor_site=None,
        actor_programme=None,
        actor_admin_level="master",
        raw_scope_metadata={"admin_level": "master"},
    )

    await _insert_test_subject(
        engine,
        subject_type="staff",
        subject_id=subject_id,
    )
    try:
        async with AsyncSession(engine) as db:
            await db.execute(
                text(
                    """
                    UPDATE users
                    SET supabase_user_id = :supabase_user_id
                    WHERE id = :subject_id
                    """
                ),
                {
                    "supabase_user_id": supabase_user_id,
                    "subject_id": subject_id,
                },
            )
            await db.commit()

        async with AsyncSession(engine, expire_on_commit=False) as db:
            original = await create_session(
                db,
                settings,
                "staff",
                subject_id,
                "supabase_staff",
                expected_subject_session_generation=0,
            )
            await db.commit()

        async def reset_once(password: str) -> dict:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                return await reset_staff_account_password(
                    db,
                    user_id=subject_id,
                    payload=StaffAccountResetPasswordRequest(password=password),
                    actor=actor,
                    settings=supabase_settings,
                )

        first_reset = asyncio.create_task(
            reset_once("integration-concurrent-reset-one")
        )
        await first_upstream_entered.wait()
        second_reset = asyncio.create_task(
            reset_once("integration-concurrent-reset-two")
        )
        await second_fence_started.wait()

        assert fake_admin.active_calls == 1
        assert len(fake_admin.passwords) == 1
        release_first_upstream.set()
        first_result, second_result = await asyncio.wait_for(
            asyncio.gather(first_reset, second_reset),
            timeout=10,
        )

        assert first_result["id"] == subject_id
        assert second_result["id"] == subject_id
        assert fake_admin.max_active_calls == 1
        assert fake_admin.passwords == [
            "integration-concurrent-reset-one",
            "integration-concurrent-reset-two",
        ]

        async with AsyncSession(engine) as db:
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
            engine,
            subject_type="staff",
            subject_id=subject_id,
        )


@pytest.mark.asyncio
async def test_concurrent_postgres_rate_limit_is_atomic_and_identifier_is_hmac_only(
    security_database: tuple[AsyncEngine, Settings],
) -> None:
    engine, settings = security_database
    scope = f"security_integration_{uuid4().hex}"
    raw_identifier = "resident@example.com|MCR:M12345A"
    policy = RateLimitPolicy(
        scope=scope,
        limit=5,
        window_seconds=60,
        message="Too many requests",
    )

    async def attempt():
        async with AsyncSession(engine) as db:
            return await check_rate_limit(
                db,
                settings=settings,
                policy=policy,
                identifier=raw_identifier,
            )

    try:
        results = await asyncio.gather(*(attempt() for _ in range(12)))
        assert sum(result.allowed for result in results) == 5
        assert sorted(result.request_count for result in results) == list(range(1, 13))

        async with AsyncSession(engine) as db:
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
        async with AsyncSession(engine) as db:
            await db.execute(
                text("DELETE FROM rate_limit_buckets WHERE scope = :scope"),
                {"scope": scope},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_privilege_hardening_preserves_runtime_and_denies_public_browser_boundary(
    security_database: tuple[AsyncEngine, Settings],
) -> None:
    engine, _settings = security_database
    async with AsyncSession(engine) as db:
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

    assert runtime_access is True
    assert public_access is False
    assert relation_flags.relrowsecurity is False
    assert relation_flags.relforcerowsecurity is False
