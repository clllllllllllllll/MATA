from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.services import auth as auth_service
from app.services import resident_submission


def _assert_local_postgres(database_url: str) -> None:
    url = make_url(database_url)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1"}
        or url.database != "mata_db"
    ):
        pytest.fail(
            "PostgreSQL resident-event integration tests require the local mata_db test service",
            pytrace=False,
        )


@pytest.mark.asyncio
async def test_resident_event_discovery_merges_active_periods_and_deduplicates_on_postgres() -> None:
    settings = Settings(_env_file=None)
    _assert_local_postgres(settings.database_url)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)

    suffix = uuid4().hex[:10]
    programme_code = f"RV{suffix}"[:20]
    posting_code = f"RVP{suffix}"
    mcr = f"M{suffix.upper()}"
    resident_id = uuid4()
    posting_id = uuid4()
    programme_id = uuid4()
    session_type_id = uuid4()
    first_period_id = uuid4()
    second_period_id = uuid4()
    inactive_period_id = uuid4()
    first_event_id = uuid4()
    second_event_id = uuid4()
    inactive_event_id = uuid4()
    keyword = f"Resident visibility {suffix}"

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            db = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                await db.execute(
                    text(
                        """
                        UPDATE reporting_periods
                        SET status = 'inactive', activate_on = NULL, deactivate_on = NULL
                        """
                    )
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO posting_codes (
                            id, code, display_name, institution, supports_secretary_events
                        )
                        VALUES (:id, :code, :display_name, 'TTSH', true)
                        """
                    ),
                    {"id": posting_id, "code": posting_code, "display_name": posting_code},
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO programmes (
                            id, code, name, ay_date_category, r_year_required,
                            native_teaching_posting_code
                        )
                        VALUES (
                            :id, :code, :name, 'non_im_subspec', false, :posting_code
                        )
                        """
                    ),
                    {
                        "id": programme_id,
                        "code": programme_code,
                        "name": f"Resident visibility {suffix}",
                        "posting_code": posting_code,
                    },
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO residents (id, name, mcr, programme_code, status)
                        VALUES (:id, :name, :mcr, :programme_code, 'active')
                        """
                    ),
                    {
                        "id": resident_id,
                        "name": f"Resident {suffix}",
                        "mcr": mcr,
                        "programme_code": programme_code,
                    },
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO reporting_periods (
                            id, label, start_date, end_date, status, deactivate_on
                        )
                        VALUES
                            (:first_id, :first_label, '2025-07-01', '2025-12-31', 'active', '2099-01-01'),
                            (:second_id, :second_label, '2026-01-01', '2026-06-30', 'active', '2099-01-01'),
                            (:inactive_id, :inactive_label, '2024-07-01', '2024-12-31', 'inactive', NULL)
                        """
                    ),
                    {
                        "first_id": first_period_id,
                        "first_label": f"RV1 {suffix}",
                        "second_id": second_period_id,
                        "second_label": f"RV2 {suffix}",
                        "inactive_id": inactive_period_id,
                        "inactive_label": f"RVI {suffix}",
                    },
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO resident_postings (
                            id, resident_id, posting_code, reporting_period_id,
                            start_date, end_date, r_year, status
                        )
                        VALUES
                            (:first_id, :resident_id, :posting_code, :first_period_id,
                             '2025-07-15', '2025-07-15', 'ALL', 'active'),
                            (:second_id, :resident_id, :posting_code, :second_period_id,
                             '2026-06-01', '2026-06-30', 'ALL', 'loa_working'),
                            (:inactive_id, :resident_id, :posting_code, :inactive_period_id,
                             '2024-07-01', '2024-07-31', 'ALL', 'active')
                        """
                    ),
                    {
                        "first_id": uuid4(),
                        "second_id": uuid4(),
                        "inactive_id": uuid4(),
                        "resident_id": resident_id,
                        "posting_code": posting_code,
                        "first_period_id": first_period_id,
                        "second_period_id": second_period_id,
                        "inactive_period_id": inactive_period_id,
                    },
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO session_types (id, name, duration_hours, duration_label)
                        VALUES (:id, :name, 1.0, '1h')
                        """
                    ),
                    {"id": session_type_id, "name": f"Resident type {suffix} [1h]"},
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO teaching_name_catalogue (
                            id, keyword, session_type_id, posting_code, programme_code,
                            r_year, reporting_period_id, duration_hours, is_tracked
                        )
                        VALUES
                            (:first_id, :keyword, :session_type_id, :posting_code,
                             :programme_code, 'ALL', :first_period_id, 1.0, true),
                            (:second_id, :keyword, :session_type_id, :posting_code,
                             :programme_code, 'ALL', :second_period_id, 1.0, true),
                            (:inactive_id, :keyword, :session_type_id, :posting_code,
                             :programme_code, 'ALL', :inactive_period_id, 1.0, true)
                        """
                    ),
                    {
                        "first_id": uuid4(),
                        "second_id": uuid4(),
                        "inactive_id": uuid4(),
                        "keyword": keyword,
                        "session_type_id": session_type_id,
                        "posting_code": posting_code,
                        "programme_code": programme_code,
                        "first_period_id": first_period_id,
                        "second_period_id": second_period_id,
                        "inactive_period_id": inactive_period_id,
                    },
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO teaching_events (
                            id, posting_code, created_for_programme_code, teaching_name,
                            event_date, start_time, end_time, duration_hours,
                            session_type_id, created_by_role
                        )
                        VALUES
                            (:first_id, :posting_code, NULL, :keyword, '2025-07-15', '10:00',
                             '11:00', 1.0, :session_type_id, 'secretary'),
                            (:second_id, :posting_code, :programme_code, :keyword, '2026-06-30', '10:00',
                             '11:00', 1.0, :session_type_id, 'programme_pc'),
                            (:inactive_id, :posting_code, NULL, :keyword, '2024-07-15', '10:00',
                             '11:00', 1.0, :session_type_id, 'secretary')
                        """
                    ),
                    {
                        "first_id": first_event_id,
                        "second_id": second_event_id,
                        "inactive_id": inactive_event_id,
                        "posting_code": posting_code,
                        "programme_code": programme_code,
                        "keyword": keyword,
                        "session_type_id": session_type_id,
                    },
                )

                payload = await resident_submission.list_available_events(
                    db,
                    resident_id=resident_id,
                    today=date(2026, 7, 17),
                )

                assert [row["id"] for row in payload["events"]] == [
                    first_event_id,
                    second_event_id,
                ]
                assert len({row["id"] for row in payload["events"]}) == 2
                assert inactive_event_id not in {row["id"] for row in payload["events"]}
                assert {row["reporting_period_id"] for row in payload["events"]} == {
                    first_period_id,
                    second_period_id,
                }

                filtered = await resident_submission.list_available_events(
                    db,
                    resident_id=resident_id,
                    today=date(2026, 7, 17),
                    date_from=date(2026, 1, 1),
                    date_to=date(2026, 6, 30),
                )
                assert [row["id"] for row in filtered["events"]] == [second_event_id]

                identity = await auth_service.get_current_identity(
                    db,
                    role="resident",
                    subject_id=resident_id,
                )
                assert identity["mcr"] == mcr
                assert identity["programme_code"] == programme_code
                assert "current_posting_code" not in identity
            finally:
                if transaction.is_active:
                    await transaction.rollback()
                await db.close()
    finally:
        await engine.dispose()
