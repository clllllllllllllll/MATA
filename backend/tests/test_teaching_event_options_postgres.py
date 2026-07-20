from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.services import programme_teaching_events, secretary_events


def _assert_local_postgres(database_url: str) -> None:
    url = make_url(database_url)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1"}
        or not (
            url.database == "mata_db"
            or (url.database or "").startswith("mata_phase5b_verify_")
        )
    ):
        pytest.fail(
            "PostgreSQL teaching-event integration tests require a local MATA test database",
            pytrace=False,
        )


@pytest.mark.asyncio
async def test_programme_and_secretary_options_have_postgres_cardinality_and_scope() -> None:
    settings = Settings(_env_file=None)
    _assert_local_postgres(settings.database_url)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)

    suffix = uuid4().hex[:10]
    programme_code = f"PG{suffix}"[:20]
    secretary_posting = f"PGSec{suffix}"
    second_posting = f"PGAlt{suffix}"
    keyword = f"PG Shared {suffix}"
    period_id = uuid4()
    session_type_one = uuid4()
    session_type_two = uuid4()

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            db = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                await db.execute(
                    text(
                        """
                        INSERT INTO reporting_periods (
                            id, label, start_date, end_date, status
                        )
                        VALUES (
                            :id, :label, :start_date, :end_date, 'active'
                        )
                        """
                    ),
                    {
                        "id": period_id,
                        "label": f"PG opts {suffix}",
                        "start_date": date(2026, 1, 1),
                        "end_date": date(2026, 12, 31),
                    },
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO posting_codes (id, code, institution, department)
                        VALUES
                            (:first_id, :first_code, 'TTSH', NULL),
                            (:second_id, :second_code, NULL, NULL)
                        """
                    ),
                    {
                        "first_id": uuid4(),
                        "first_code": secretary_posting,
                        "second_id": uuid4(),
                        "second_code": second_posting,
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
                        "name": f"PostgreSQL options {suffix}",
                    },
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO session_types (id, name, duration_hours, duration_label)
                        VALUES
                            (:first_id, :first_name, 2.0, '2h'),
                            (:second_id, :second_name, 1.0, '1h')
                        """
                    ),
                    {
                        "first_id": session_type_one,
                        "first_name": f"PG Type A {suffix} [2h]",
                        "second_id": session_type_two,
                        "second_name": f"PG Type B {suffix} [1h]",
                    },
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO secretary_programme_pools (
                            id, posting_code, programme_code, is_active
                        )
                        VALUES (:id, :posting_code, :programme_code, true)
                        """
                    ),
                    {
                        "id": uuid4(),
                        "posting_code": secretary_posting,
                        "programme_code": programme_code,
                    },
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO teaching_name_catalogue (
                            id,
                            keyword,
                            session_type_id,
                            posting_code,
                            programme_code,
                            r_year,
                            reporting_period_id,
                            duration_hours,
                            is_tracked
                        )
                        VALUES
                            (
                                :first_id, :keyword, :first_session_type_id,
                                :first_posting, :programme_code, 'ALL',
                                :reporting_period_id, 2.0, true
                            ),
                            (
                                :second_id, :keyword, :second_session_type_id,
                                :second_posting, :programme_code, 'ALL',
                                :reporting_period_id, 1.0, false
                            )
                        """
                    ),
                    {
                        "first_id": uuid4(),
                        "second_id": uuid4(),
                        "keyword": keyword,
                        "first_session_type_id": session_type_one,
                        "second_session_type_id": session_type_two,
                        "first_posting": secretary_posting,
                        "second_posting": second_posting,
                        "programme_code": programme_code,
                        "reporting_period_id": period_id,
                    },
                )

                pc_options = await programme_teaching_events.teaching_name_options(
                    db,
                    programme_code=programme_code,
                    reporting_period_id=period_id,
                )
                secretary_options = await secretary_events.teaching_name_options(
                    db,
                    posting_code=secretary_posting,
                    reporting_period_id=period_id,
                )

                pc_option = next(row for row in pc_options if row["keyword"] == keyword)
                secretary_option = next(
                    row for row in secretary_options if row["keyword"] == keyword
                )
                expected_postings = sorted([secretary_posting, second_posting])
                assert pc_option["posting_codes"] == expected_postings
                assert secretary_option["posting_codes"] == expected_postings
                assert pc_option["session_type_id"] is None
                assert secretary_option["session_type_id"] is None
                assert secretary_option["is_tracked"] is None
            finally:
                if transaction.is_active:
                    await transaction.rollback()
                await db.close()
    finally:
        await engine.dispose()
