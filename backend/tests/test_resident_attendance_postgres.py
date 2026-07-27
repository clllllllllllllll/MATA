from __future__ import annotations

import asyncio
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.errors import ApiError
from app.services import app_sessions
from app.services import resident_submission
from app.services.database_context import (
    AUTH_BOUNDARY_INFO_KEY,
    MataSyncSession,
    configure_request_context,
)


DISPOSABLE_DATABASE_NAME = "mata_phase5b_session_lifecycle_verify"
_TEST_SESSION_HASH_KEY = "rls-resident-attendance-test-session-key-32-bytes"


def _assert_disposable_local_postgres(
    database_url: str,
    *,
    async_url: bool,
) -> None:
    url = make_url(database_url)
    allowed_drivers = (
        {"postgresql+asyncpg"}
        if async_url
        else {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
    )
    if (
        url.drivername not in allowed_drivers
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or url.database != DISPOSABLE_DATABASE_NAME
        or not url.username
        or bool(url.query)
    ):
        pytest.fail(
            "PostgreSQL attendance concurrency tests require the exact named local "
            f"disposable database {DISPOSABLE_DATABASE_NAME}",
            pytrace=False,
        )


async def _issue_resident_session(
    auth_engine: AsyncEngine,
    settings: Settings,
    *,
    resident_id: UUID,
    mcr: str,
) -> app_sessions.CreatedSession:
    session_settings = settings.model_copy(
        update={"mata_session_hash_key": _TEST_SESSION_HASH_KEY}
    )
    async with AsyncSession(auth_engine, expire_on_commit=False) as auth_db:
        auth_db.info[AUTH_BOUNDARY_INFO_KEY] = True
        created = await app_sessions.create_session(
            auth_db,
            session_settings,
            "resident",
            resident_id,
            "mata_resident",
            expected_subject_session_generation=0,
            normalized_mcr=mcr,
        )
        await auth_db.commit()
        resolved = await app_sessions.resolve_session(
            auth_db,
            session_settings,
            created.session_token,
            touch=False,
        )
        assert resolved is not None
        assert (
            app_sessions.authorization_fingerprint_for_session(resolved)
            is not None
        )
        return app_sessions.CreatedSession(
            session=resolved,
            session_token=created.session_token,
            csrf_token=created.csrf_token,
        )


def _runtime_session(
    runtime_engine: AsyncEngine,
    *,
    resident_id: UUID,
    created: app_sessions.CreatedSession,
) -> AsyncSession:
    db = AsyncSession(
        runtime_engine,
        expire_on_commit=False,
        sync_session_class=MataSyncSession,
    )
    fingerprint = app_sessions.authorization_fingerprint_for_session(
        created.session
    )
    assert fingerprint is not None
    configure_request_context(
        db,
        token_digest=bytes(created.session.token_digest),
        expected_subject_type="resident",
        expected_subject_id=resident_id,
        expected_app_session_id=created.session.id,
        expected_authorization_fingerprint=fingerprint,
    )
    return db


def _current_repository_alembic_head() -> str:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        pytest.fail("Repository Alembic head could not be resolved", pytrace=False)
    return head


@pytest.mark.asyncio
async def test_concurrent_overlapping_native_submissions_cannot_both_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None)
    assert settings.auth_database_url is not None
    _assert_disposable_local_postgres(settings.database_url, async_url=True)
    _assert_disposable_local_postgres(
        settings.auth_database_url,
        async_url=True,
    )
    _assert_disposable_local_postgres(
        settings.sync_database_url,
        async_url=False,
    )
    configured_users = {
        make_url(settings.database_url).username,
        make_url(settings.auth_database_url).username,
        make_url(settings.sync_database_url).username,
    }
    if not settings.database_rls_enabled or len(configured_users) != 3:
        pytest.fail(
            "Attendance RLS verification requires distinct restricted runtime, "
            "auth, and owner database logins",
            pytrace=False,
        )
    owner_url = make_url(settings.sync_database_url).set(
        drivername="postgresql+asyncpg"
    )
    owner_engine = create_async_engine(owner_url, poolclass=NullPool)
    runtime_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    auth_engine = create_async_engine(settings.auth_database_url, poolclass=NullPool)

    suffix = uuid4().hex[:10]
    programme_code = f"NC{suffix}"[:20]
    posting_code = f"NCPosting{suffix}"
    mcr = f"NC{suffix.upper()}"[:20]
    resident_id = uuid4()
    posting_id = uuid4()
    programme_id = uuid4()
    first_event_id = uuid4()
    second_event_id = uuid4()
    period_id = uuid4()
    session_type_id = uuid4()
    event_date = date(2090, 1, 3)

    events: dict[UUID, dict[str, Any]] = {
        first_event_id: {
            "id": first_event_id,
            "posting_code": posting_code,
            "created_for_programme_code": None,
            "teaching_name": "Synthetic concurrency teaching A",
            "details_of_session": None,
            "event_date": event_date,
            "start_time": time(10, 0),
            "end_time": time(11, 0),
            "duration_hours": Decimal("1.0"),
            "session_type_id": None,
            "series_id": None,
            "cme_points_awarded": False,
            "smc_event_code": None,
            "is_adhoc": False,
            "created_by_role": "secretary",
        },
        second_event_id: {
            "id": second_event_id,
            "posting_code": posting_code,
            "created_for_programme_code": None,
            "teaching_name": "Synthetic concurrency teaching B",
            "details_of_session": None,
            "event_date": event_date,
            "start_time": time(10, 30),
            "end_time": time(11, 30),
            "duration_hours": Decimal("1.0"),
            "session_type_id": None,
            "series_id": None,
            "cme_points_awarded": False,
            "smc_event_code": None,
            "is_adhoc": False,
            "created_by_role": "secretary",
        },
    }
    context = {
        "posting_code": posting_code,
        "r_year": "ALL",
        "start_date": event_date,
        "end_date": event_date,
    }
    resolved = {
        "keyword": "Synthetic concurrency teaching",
        "session_type_id": None,
        "session_type": "Synthetic concurrency teaching [1h]",
        "duration_hours": Decimal("1.0"),
        "is_tracked": True,
        "is_global": False,
    }

    async def _resident(_db: AsyncSession, requested_id: UUID) -> dict[str, Any]:
        assert requested_id == resident_id
        return {
            "id": resident_id,
            "name": "Synthetic Concurrency Resident",
            "mcr": mcr,
            "programme_code": programme_code,
            "status": "active",
        }

    async def _get_event(_db: AsyncSession, event_id: UUID) -> dict[str, Any]:
        return dict(events[event_id])

    async def _active_period(_db: AsyncSession, **_kwargs: Any) -> dict[str, Any]:
        return {
            "id": period_id,
            "label": "Synthetic concurrency period",
            "start_date": event_date,
            "end_date": event_date,
        }

    async def _visibility_contexts(
        _db: AsyncSession,
        **_kwargs: Any,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return [dict(context)], [dict(context)]

    async def _resolve_name(_db: AsyncSession, **_kwargs: Any) -> dict[str, Any]:
        return dict(resolved)

    async def _weekend_accepted(_db: AsyncSession, **_kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(resident_submission, "_resident", _resident)
    monkeypatch.setattr(resident_submission, "_get_event", _get_event)
    monkeypatch.setattr(resident_submission, "_active_reporting_period", _active_period)
    monkeypatch.setattr(
        resident_submission,
        "_resident_visibility_contexts",
        _visibility_contexts,
    )
    monkeypatch.setattr(resident_submission, "_resolve_teaching_name", _resolve_name)
    monkeypatch.setattr(resident_submission, "_weekend_is_accepted", _weekend_accepted)
    monkeypatch.setattr(resident_submission, "invalidate_resident_caches", lambda **_kwargs: None)

    original_acquire_locks = resident_submission._acquire_native_attendance_locks
    both_workers_at_lock = asyncio.Event()
    workers_at_lock = 0

    async def _observed_acquire_locks(
        db: AsyncSession,
        *,
        resident_id: UUID,
        event_dates: set[date],
    ) -> None:
        nonlocal workers_at_lock
        workers_at_lock += 1
        if workers_at_lock == 2:
            both_workers_at_lock.set()
        await original_acquire_locks(
            db,
            resident_id=resident_id,
            event_dates=event_dates,
        )

    monkeypatch.setattr(
        resident_submission,
        "_acquire_native_attendance_locks",
        _observed_acquire_locks,
    )

    tasks: list[asyncio.Task[dict[str, Any] | ApiError]] = []
    try:
        async with owner_engine.connect() as connection:
            database_head = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        assert database_head == _current_repository_alembic_head()

        async with owner_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO posting_codes (
                        id, code, display_name, supports_secretary_events
                    )
                    VALUES (:id, :code, :display_name, true)
                    """
                ),
                {"id": posting_id, "code": posting_code, "display_name": posting_code},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO programmes (
                        id, code, name, ay_date_category, r_year_required
                    )
                    VALUES (
                        :id, :code, :name, 'non_im_subspec', false
                    )
                    """
                ),
                {
                    "id": programme_id,
                    "code": programme_code,
                    "name": f"Synthetic concurrency {suffix}",
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO reporting_periods (
                        id, label, start_date, end_date, status
                    )
                    VALUES (
                        :id, :label, DATE '2090-01-01',
                        DATE '2090-12-31', 'active'
                    )
                    """
                ),
                {
                    "id": period_id,
                    "label": f"Concurrency {suffix}",
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO residents (id, name, mcr, programme_code, status)
                    VALUES (:id, :name, :mcr, :programme_code, 'active')
                    """
                ),
                {
                    "id": resident_id,
                    "name": "Synthetic Concurrency Resident",
                    "mcr": mcr,
                    "programme_code": programme_code,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO resident_postings (
                        id, resident_id, posting_code, reporting_period_id,
                        start_date, end_date, r_year, status
                    )
                    VALUES (
                        :id, :resident_id, :posting_code, :period_id,
                        :event_date, :event_date, 'ALL', 'active'
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "resident_id": resident_id,
                    "posting_code": posting_code,
                    "period_id": period_id,
                    "event_date": event_date,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO session_types (
                        id, name, duration_hours, duration_label
                    )
                    VALUES (:id, :name, 1.0, '1h')
                    """
                ),
                {
                    "id": session_type_id,
                    "name": f"Synthetic concurrency {suffix} [1h]",
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO teaching_name_catalogue (
                        id, keyword, session_type_id, posting_code,
                        programme_code, r_year, reporting_period_id,
                        duration_hours, is_tracked
                    )
                    VALUES
                        (
                            :first_id, :first_keyword, :session_type_id,
                            :posting_code, :programme_code, 'ALL',
                            :period_id, 1.0, true
                        ),
                        (
                            :second_id, :second_keyword, :session_type_id,
                            :posting_code, :programme_code, 'ALL',
                            :period_id, 1.0, true
                        )
                    """
                ),
                {
                    "first_id": uuid4(),
                    "first_keyword": events[first_event_id]["teaching_name"],
                    "second_id": uuid4(),
                    "second_keyword": events[second_event_id]["teaching_name"],
                    "session_type_id": session_type_id,
                    "posting_code": posting_code,
                    "programme_code": programme_code,
                    "period_id": period_id,
                },
            )
            for event in events.values():
                await connection.execute(
                    text(
                        """
                        INSERT INTO teaching_events (
                            id,
                            posting_code,
                            teaching_name,
                            event_date,
                            start_time,
                            end_time,
                            duration_hours,
                            is_adhoc,
                            created_by_role
                        )
                        VALUES (
                            :id,
                            :posting_code,
                            :teaching_name,
                            :event_date,
                            :start_time,
                            :end_time,
                            :duration_hours,
                            false,
                            'secretary'
                        )
                        """
                    ),
                    event,
                )

        created = await _issue_resident_session(
            auth_engine,
            settings,
            resident_id=resident_id,
            mcr=mcr,
        )

        async def _submit(event_id: UUID) -> dict[str, Any] | ApiError:
            async with _runtime_session(
                runtime_engine,
                resident_id=resident_id,
                created=created,
            ) as db:
                try:
                    return await resident_submission.submit_attendance(
                        db,
                        resident_id=resident_id,
                        event_ids=[event_id],
                        today=event_date,
                    )
                except ApiError as exc:
                    await db.rollback()
                    return exc

        key1, key2 = resident_submission._native_attendance_lock_keys(
            resident_id=resident_id,
            event_date=event_date,
        )
        async with AsyncSession(owner_engine, expire_on_commit=False) as blocker:
            await blocker.execute(
                text("SELECT pg_advisory_xact_lock(:key1, :key2)"),
                {"key1": key1, "key2": key2},
            )
            tasks = [
                asyncio.create_task(_submit(first_event_id)),
                asyncio.create_task(_submit(second_event_id)),
            ]
            await asyncio.wait_for(both_workers_at_lock.wait(), timeout=10)
            assert all(not task.done() for task in tasks)
            await blocker.commit()

        outcomes = await asyncio.wait_for(asyncio.gather(*tasks), timeout=20)
        successes = [outcome for outcome in outcomes if isinstance(outcome, dict)]
        conflicts = [outcome for outcome in outcomes if isinstance(outcome, ApiError)]
        assert len(successes) == 1
        assert successes[0]["submitted"] == 1
        assert len(conflicts) == 1
        assert conflicts[0].status_code == 409
        assert conflicts[0].detail == "Attendance overlaps an earlier accepted event"

        async with owner_engine.connect() as connection:
            submitted_count = await connection.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM attendance_records
                    WHERE resident_id = :resident_id
                      AND status = 'submitted'
                      AND teaching_event_id IN (:first_event_id, :second_event_id)
                    """
                ),
                {
                    "resident_id": resident_id,
                    "first_event_id": first_event_id,
                    "second_event_id": second_event_id,
                },
            )
        assert submitted_count == 1
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        async with owner_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM attendance_records WHERE resident_id = :resident_id"),
                {"resident_id": resident_id},
            )
            await connection.execute(
                text("DELETE FROM app_sessions WHERE subject_id = :resident_id"),
                {"resident_id": resident_id},
            )
            await connection.execute(
                text(
                    """
                    DELETE FROM teaching_events
                    WHERE id IN (:first_event_id, :second_event_id)
                    """
                ),
                {
                    "first_event_id": first_event_id,
                    "second_event_id": second_event_id,
                },
            )
            await connection.execute(
                text(
                    "DELETE FROM teaching_name_catalogue "
                    "WHERE reporting_period_id = :period_id"
                ),
                {"period_id": period_id},
            )
            await connection.execute(
                text("DELETE FROM resident_postings WHERE resident_id = :resident_id"),
                {"resident_id": resident_id},
            )
            await connection.execute(
                text("DELETE FROM residents WHERE id = :resident_id"),
                {"resident_id": resident_id},
            )
            await connection.execute(
                text("DELETE FROM session_types WHERE id = :session_type_id"),
                {"session_type_id": session_type_id},
            )
            await connection.execute(
                text("DELETE FROM reporting_periods WHERE id = :period_id"),
                {"period_id": period_id},
            )
            await connection.execute(
                text("DELETE FROM programmes WHERE id = :programme_id"),
                {"programme_id": programme_id},
            )
            await connection.execute(
                text("DELETE FROM posting_codes WHERE id = :posting_id"),
                {"posting_id": posting_id},
            )
        await auth_engine.dispose()
        await runtime_engine.dispose()
        await owner_engine.dispose()
