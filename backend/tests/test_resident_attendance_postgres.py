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
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.errors import ApiError
from app.services import resident_submission


def _assert_disposable_local_postgres(database_url: str) -> None:
    url = make_url(database_url)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1"}
        or not (url.database or "").startswith("mata_phase5b_verify_")
    ):
        pytest.fail(
            "PostgreSQL attendance concurrency tests require a disposable local "
            "mata_phase5b_verify_ database",
            pytrace=False,
        )


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
    _assert_disposable_local_postgres(settings.database_url)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)

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
        async with engine.connect() as connection:
            database_head = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        assert database_head == _current_repository_alembic_head()

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO posting_codes (id, code, display_name)
                    VALUES (:id, :code, :display_name)
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

        async def _submit(event_id: UUID) -> dict[str, Any] | ApiError:
            async with AsyncSession(bind=engine, expire_on_commit=False) as db:
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
        async with AsyncSession(bind=engine, expire_on_commit=False) as blocker:
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

        async with engine.connect() as connection:
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

        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM attendance_records WHERE resident_id = :resident_id"),
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
                text("DELETE FROM residents WHERE id = :resident_id"),
                {"resident_id": resident_id},
            )
            await connection.execute(
                text("DELETE FROM programmes WHERE id = :programme_id"),
                {"programme_id": programme_id},
            )
            await connection.execute(
                text("DELETE FROM posting_codes WHERE id = :posting_id"),
                {"posting_id": posting_id},
            )
        await engine.dispose()
