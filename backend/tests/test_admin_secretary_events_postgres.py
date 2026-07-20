from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.dependencies.staff_actor import StaffActorContext
from app.errors import ApiError
from app.services import admin_secretary_events


@dataclass
class PostgresAdminEventHarness:
    db: AsyncSession
    actor: StaffActorContext
    posting_code: str
    programme_code: str
    resident_id: UUID
    external_resident_id: UUID
    series_id: UUID
    suffix: str


def _assert_local_postgres(database_url: str) -> None:
    url = make_url(database_url)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1"}
        or not (url.database or "").startswith(
            ("mata_phase5b_verify_", "mata_admin_events_verify_")
        )
    ):
        pytest.fail(
            "PostgreSQL admin-event integration tests require a local MATA test database",
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


@pytest_asyncio.fixture
async def postgres_admin_event_harness() -> AsyncIterator[PostgresAdminEventHarness]:
    settings = Settings(_env_file=None)
    _assert_local_postgres(settings.database_url)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)

    suffix = uuid4().hex[:10]
    posting_code = f"FDPosting{suffix}"
    programme_code = f"FD{suffix}"[:20]
    actor_user_id = uuid4()
    resident_id = uuid4()
    external_resident_id = uuid4()
    series_id = uuid4()

    try:
        async with engine.connect() as connection:
            outer_transaction = await connection.begin()
            database_head = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            if database_head != _current_repository_alembic_head():
                pytest.fail(
                    "PostgreSQL admin-event integration database is not at current Alembic head",
                    pytrace=False,
                )
            db = AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            try:
                await db.execute(
                    text(
                        """
                        INSERT INTO posting_codes (
                            id, code, display_name, institution,
                            supports_secretary_events
                        )
                        VALUES (
                            :id, :code, :display_name, 'TTSH', true
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "code": posting_code,
                        "display_name": f"Force delete posting {suffix}",
                    },
                )
                await db.execute(
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
                        "id": uuid4(),
                        "code": programme_code,
                        "name": f"Force delete programme {suffix}",
                    },
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO users (
                            id, email, password_hash, role, name,
                            programme_scope, admin_level, is_active,
                            current_staff_actor_name
                        )
                        VALUES (
                            :id, :email, 'not-used', 'admin', :name,
                            ARRAY[]::text[], 'master', true, :actor_name
                        )
                        """
                    ),
                    {
                        "id": actor_user_id,
                        "email": f"force-delete-{suffix}@example.test",
                        "name": "PostgreSQL Master Admin",
                        "actor_name": "PostgreSQL Master Admin",
                    },
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO residents (
                            id, name, mcr, programme_code, status
                        )
                        VALUES (
                            :id, :name, :mcr, :programme_code, 'active'
                        )
                        """
                    ),
                    {
                        "id": resident_id,
                        "name": f"Force delete native resident {suffix}",
                        "mcr": f"FDN{suffix.upper()}",
                        "programme_code": programme_code,
                    },
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO external_residents (
                            id, name, mcr, home_cluster,
                            current_nhg_posting_code, status
                        )
                        VALUES (
                            :id, :name, :mcr, 'NUH', :posting_code, 'active'
                        )
                        """
                    ),
                    {
                        "id": external_resident_id,
                        "name": f"Force delete external resident {suffix}",
                        "mcr": f"FDE{suffix.upper()}",
                        "posting_code": posting_code,
                    },
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO event_series (
                            id, posting_code, recurrence_pattern,
                            recurrence_interval, days_of_week, end_type
                        )
                        VALUES (
                            :id, :posting_code, 'weekly', 1,
                            ARRAY['MON']::text[], 'never'
                        )
                        """
                    ),
                    {"id": series_id, "posting_code": posting_code},
                )
                await db.commit()

                yield PostgresAdminEventHarness(
                    db=db,
                    actor=StaffActorContext(
                        actor_user_id=actor_user_id,
                        actor_role="admin",
                        actor_name="PostgreSQL Master Admin",
                        actor_admin_level="master",
                    ),
                    posting_code=posting_code,
                    programme_code=programme_code,
                    resident_id=resident_id,
                    external_resident_id=external_resident_id,
                    series_id=series_id,
                    suffix=suffix,
                )
            finally:
                await db.close()
                if outer_transaction.is_active:
                    await outer_transaction.rollback()
    finally:
        await engine.dispose()


async def _insert_event(
    harness: PostgresAdminEventHarness,
    *,
    event_id: UUID,
    source_type: Literal["secretary", "programme_pc"],
    event_date: date,
    series_id: UUID | None = None,
) -> None:
    await harness.db.execute(
        text(
            """
            INSERT INTO teaching_events (
                id, posting_code, created_for_programme_code, teaching_name,
                event_date, start_time, end_time, duration_hours,
                series_id, is_adhoc, created_by_role
            )
            VALUES (
                :id, :posting_code, :programme_code, :teaching_name,
                :event_date, :start_time, :end_time, 1.0,
                :series_id, false, :created_by_role
            )
            """
        ),
        {
            "id": event_id,
            "posting_code": harness.posting_code,
            "programme_code": (
                harness.programme_code if source_type == "programme_pc" else None
            ),
            "teaching_name": f"Force delete event {event_id}",
            "event_date": event_date,
            "start_time": time(9, 0),
            "end_time": time(10, 0),
            "series_id": series_id,
            "created_by_role": source_type,
        },
    )


async def _insert_native_attendance(
    harness: PostgresAdminEventHarness,
    *,
    event_id: UUID,
) -> UUID:
    attendance_id = uuid4()
    await harness.db.execute(
        text(
            """
            INSERT INTO attendance_records (
                id, resident_id, teaching_event_id, status, posting_code
            )
            VALUES (
                :id, :resident_id, :event_id, 'submitted', :posting_code
            )
            """
        ),
        {
            "id": attendance_id,
            "resident_id": harness.resident_id,
            "event_id": event_id,
            "posting_code": harness.posting_code,
        },
    )
    return attendance_id


async def _insert_external_attendance(
    harness: PostgresAdminEventHarness,
    *,
    event_id: UUID,
) -> UUID:
    attendance_id = uuid4()
    await harness.db.execute(
        text(
            """
            INSERT INTO external_attendance_records (
                id, external_resident_id, teaching_event_id,
                status, posting_code
            )
            VALUES (
                :id, :external_resident_id, :event_id,
                'submitted', :posting_code
            )
            """
        ),
        {
            "id": attendance_id,
            "external_resident_id": harness.external_resident_id,
            "event_id": event_id,
            "posting_code": harness.posting_code,
        },
    )
    return attendance_id


async def _event_count(harness: PostgresAdminEventHarness, event_id: UUID) -> int:
    return int(
        await harness.db.scalar(
            text("SELECT count(*) FROM teaching_events WHERE id = :event_id"),
            {"event_id": event_id},
        )
        or 0
    )


async def _attendance_count(
    harness: PostgresAdminEventHarness,
    *,
    table_name: Literal["attendance_records", "external_attendance_records"],
    event_id: UUID,
) -> int:
    statement = {
        "attendance_records": text(
            "SELECT count(*) FROM attendance_records WHERE teaching_event_id = :event_id"
        ),
        "external_attendance_records": text(
            """
            SELECT count(*)
            FROM external_attendance_records
            WHERE teaching_event_id = :event_id
            """
        ),
    }[table_name]
    return int(await harness.db.scalar(statement, {"event_id": event_id}) or 0)


async def _assert_no_action_attendance_foreign_keys(
    harness: PostgresAdminEventHarness,
) -> None:
    result = await harness.db.execute(
        text(
            """
            SELECT tc.table_name, rc.delete_rule
            FROM information_schema.table_constraints tc
            JOIN information_schema.referential_constraints rc
              ON rc.constraint_schema = tc.constraint_schema
             AND rc.constraint_name = tc.constraint_name
            JOIN information_schema.key_column_usage kcu
              ON kcu.constraint_schema = tc.constraint_schema
             AND kcu.constraint_name = tc.constraint_name
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_schema = tc.constraint_schema
             AND ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = current_schema()
              AND tc.table_name IN (
                    'attendance_records', 'external_attendance_records'
              )
              AND kcu.column_name = 'teaching_event_id'
              AND ccu.table_name = 'teaching_events'
              AND ccu.column_name = 'id'
            ORDER BY tc.table_name
            """
        )
    )
    assert {
        row["table_name"]: row["delete_rule"]
        for row in result.mappings().all()
    } == {
        "attendance_records": "NO ACTION",
        "external_attendance_records": "NO ACTION",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_name", "source_type", "with_native", "with_external"),
    [
        ("native", "secretary", True, False),
        ("external", "programme_pc", False, True),
        ("mixed", "programme_pc", True, True),
    ],
)
async def test_force_delete_explicitly_removes_attendance_and_persists_audit_on_postgres(
    postgres_admin_event_harness: PostgresAdminEventHarness,
    case_name: str,
    source_type: Literal["secretary", "programme_pc"],
    with_native: bool,
    with_external: bool,
) -> None:
    harness = postgres_admin_event_harness
    event_id = uuid4()
    target_series_id = harness.series_id if case_name == "mixed" else None
    sibling_event_id = uuid4()
    unrelated_event_id = uuid4()

    await _insert_event(
        harness,
        event_id=event_id,
        source_type=source_type,
        event_date=date(2026, 8, 3),
        series_id=target_series_id,
    )
    if with_native:
        await _insert_native_attendance(harness, event_id=event_id)
    if with_external:
        await _insert_external_attendance(harness, event_id=event_id)

    if case_name == "mixed":
        await _insert_event(
            harness,
            event_id=sibling_event_id,
            source_type="programme_pc",
            event_date=date(2026, 8, 10),
            series_id=harness.series_id,
        )
        await _insert_native_attendance(harness, event_id=sibling_event_id)
        await _insert_event(
            harness,
            event_id=unrelated_event_id,
            source_type="secretary",
            event_date=date(2026, 8, 17),
        )
        await _insert_external_attendance(harness, event_id=unrelated_event_id)

    await harness.db.commit()

    if case_name == "mixed":
        await _assert_no_action_attendance_foreign_keys(harness)
        with pytest.raises(IntegrityError):
            async with harness.db.begin_nested():
                await harness.db.execute(
                    text("DELETE FROM teaching_events WHERE id = :event_id"),
                    {"event_id": event_id},
                )
        assert await _event_count(harness, event_id) == 1

    reason = f"PostgreSQL operational deletion test: {case_name}"
    response = await admin_secretary_events.force_delete_event(
        harness.db,
        event_id=event_id,
        reason=reason,
        expected_native_attendance_count=int(with_native),
        expected_external_attendance_count=int(with_external),
        actor=harness.actor,
    )

    expected_native = int(with_native)
    expected_external = int(with_external)
    assert response == {
        "event_id": event_id,
        "deleted": True,
        "source_type": source_type,
        "native_attendance_deleted": expected_native,
        "external_attendance_deleted": expected_external,
        "total_attendance_deleted": expected_native + expected_external,
    }
    assert await _event_count(harness, event_id) == 0
    assert await _attendance_count(
        harness,
        table_name="attendance_records",
        event_id=event_id,
    ) == 0
    assert await _attendance_count(
        harness,
        table_name="external_attendance_records",
        event_id=event_id,
    ) == 0

    audit_result = await harness.db.execute(
        text(
            """
            SELECT
                actor_user_id, actor_role, actor_name, actor_admin_level,
                action, entity_type, entity_id,
                before_json, after_json, metadata_json
            FROM audit_logs
            WHERE action = 'admin.teaching_event.force_delete'
              AND entity_id = :event_id
            """
        ),
        {"event_id": event_id},
    )
    audit = dict(audit_result.mappings().one())
    assert audit["actor_user_id"] == harness.actor.actor_user_id
    assert audit["actor_role"] == "admin"
    assert audit["actor_name"] == "PostgreSQL Master Admin"
    assert audit["actor_admin_level"] == "master"
    assert audit["entity_type"] == "teaching_event"
    assert audit["entity_id"] == event_id
    assert audit["before_json"]["id"] == str(event_id)
    assert audit["before_json"]["posting_code"] == harness.posting_code
    assert audit["before_json"]["created_for_programme_code"] == (
        harness.programme_code if source_type == "programme_pc" else None
    )
    assert audit["before_json"]["teaching_name"] == f"Force delete event {event_id}"
    assert audit["before_json"]["event_date"] == "2026-08-03"
    assert audit["before_json"]["series_id"] == (
        str(target_series_id) if target_series_id else None
    )
    assert audit["after_json"]["deleted"] is True
    assert audit["metadata_json"]["deletion_reason"] == reason
    assert audit["metadata_json"]["event_source_type"] == source_type
    assert audit["metadata_json"]["native_attendance_deleted"] == expected_native
    assert audit["metadata_json"]["external_attendance_deleted"] == expected_external
    assert audit["metadata_json"]["total_attendance_deleted"] == (
        expected_native + expected_external
    )
    assert audit["metadata_json"]["deleted_at"]

    if case_name == "mixed":
        assert await _event_count(harness, sibling_event_id) == 1
        assert await _attendance_count(
            harness,
            table_name="attendance_records",
            event_id=sibling_event_id,
        ) == 1
        assert await _event_count(harness, unrelated_event_id) == 1
        assert await _attendance_count(
            harness,
            table_name="external_attendance_records",
            event_id=unrelated_event_id,
        ) == 1
        assert int(
            await harness.db.scalar(
                text("SELECT count(*) FROM event_series WHERE id = :series_id"),
                {"series_id": harness.series_id},
            )
            or 0
        ) == 1


@pytest.mark.asyncio
async def test_force_delete_stale_impact_rolls_back_before_deletion_on_postgres(
    postgres_admin_event_harness: PostgresAdminEventHarness,
) -> None:
    harness = postgres_admin_event_harness
    event_id = uuid4()
    await _insert_event(
        harness,
        event_id=event_id,
        source_type="programme_pc",
        event_date=date(2026, 8, 24),
    )
    await _insert_native_attendance(harness, event_id=event_id)
    await _insert_external_attendance(harness, event_id=event_id)
    await harness.db.commit()

    with pytest.raises(ApiError) as exc_info:
        await admin_secretary_events.force_delete_event(
            harness.db,
            event_id=event_id,
            reason="Stale confirmation impact",
            expected_native_attendance_count=0,
            expected_external_attendance_count=0,
            actor=harness.actor,
        )

    assert exc_info.value.status_code == 409
    assert await _event_count(harness, event_id) == 1
    assert await _attendance_count(
        harness,
        table_name="attendance_records",
        event_id=event_id,
    ) == 1
    assert await _attendance_count(
        harness,
        table_name="external_attendance_records",
        event_id=event_id,
    ) == 1
    assert int(
        await harness.db.scalar(
            text(
                """
                SELECT count(*)
                FROM audit_logs
                WHERE action = 'admin.teaching_event.force_delete'
                  AND entity_id = :event_id
                """
            ),
            {"event_id": event_id},
        )
        or 0
    ) == 0


@pytest.mark.asyncio
async def test_force_delete_failure_rolls_back_event_attendance_and_audit_on_postgres(
    postgres_admin_event_harness: PostgresAdminEventHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = postgres_admin_event_harness
    event_id = uuid4()
    await _insert_event(
        harness,
        event_id=event_id,
        source_type="programme_pc",
        event_date=date(2026, 9, 7),
        series_id=harness.series_id,
    )
    await _insert_native_attendance(harness, event_id=event_id)
    await _insert_external_attendance(harness, event_id=event_id)
    await harness.db.commit()

    original_write_audit_log = admin_secretary_events.write_audit_log

    async def _write_audit_then_fail(*args: Any, **kwargs: Any) -> dict[str, Any]:
        await original_write_audit_log(*args, **kwargs)
        raise RuntimeError("forced failure after audit insert")

    monkeypatch.setattr(
        admin_secretary_events,
        "write_audit_log",
        _write_audit_then_fail,
    )

    with pytest.raises(RuntimeError, match="forced failure after audit insert"):
        await admin_secretary_events.force_delete_event(
            harness.db,
            event_id=event_id,
            reason="Rollback the destructive operation",
            expected_native_attendance_count=1,
            expected_external_attendance_count=1,
            actor=harness.actor,
        )

    assert await _event_count(harness, event_id) == 1
    assert await _attendance_count(
        harness,
        table_name="attendance_records",
        event_id=event_id,
    ) == 1
    assert await _attendance_count(
        harness,
        table_name="external_attendance_records",
        event_id=event_id,
    ) == 1
    assert int(
        await harness.db.scalar(
            text(
                """
                SELECT count(*)
                FROM audit_logs
                WHERE action = 'admin.teaching_event.force_delete'
                  AND entity_id = :event_id
                """
            ),
            {"event_id": event_id},
        )
        or 0
    ) == 0
