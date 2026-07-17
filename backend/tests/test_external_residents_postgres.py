from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.middleware.errors import install_error_handlers
from app.routers import external_residents


class RollbackOnlyAsyncSession(AsyncSession):
    async def commit(self) -> None:
        await self.flush()


@dataclass
class PostgresExternalRegistrationHarness:
    client: httpx.AsyncClient
    db: AsyncSession


def _assert_local_postgres(database_url: str) -> None:
    url = make_url(database_url)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1"}
        or url.database != "mata_db"
    ):
        pytest.fail(
            "PostgreSQL external-registration tests require the local mata_db test service",
            pytrace=False,
        )


@pytest_asyncio.fixture
async def postgres_external_registration_harness(
) -> AsyncIterator[PostgresExternalRegistrationHarness]:
    settings = Settings(_env_file=None)
    _assert_local_postgres(settings.database_url)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            db = RollbackOnlyAsyncSession(bind=connection, expire_on_commit=False)
            try:
                mapping = await db.execute(
                    text(
                        """
                        SELECT pc.institution
                        FROM secretary_programme_pools spp
                        JOIN posting_codes pc
                          ON pc.code = spp.posting_code
                        WHERE spp.programme_code = 'GERI'
                          AND spp.posting_code = 'TTSHGerMed'
                          AND spp.is_active = true
                        """
                    )
                )
                assert mapping.scalar_one_or_none() == "TTSH"

                await db.execute(
                    text(
                        """
                        DELETE FROM resident_postings
                        WHERE posting_code = 'TTSHGerMed'
                        """
                    )
                )

                app = FastAPI()
                install_error_handlers(app)

                async def _db_override() -> AsyncIterator[AsyncSession]:
                    yield db

                async def _rate_limit_override() -> None:
                    return None

                app.dependency_overrides[external_residents.get_db_session] = _db_override
                app.dependency_overrides[
                    external_residents._persistent_registration_rate_limit
                ] = _rate_limit_override
                app.include_router(external_residents.router)

                transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                ) as client:
                    yield PostgresExternalRegistrationHarness(client=client, db=db)
            finally:
                if transaction.is_active:
                    await transaction.rollback()
                await db.close()
    finally:
        await engine.dispose()


async def _add_native_occupancy(
    harness: PostgresExternalRegistrationHarness,
) -> None:
    resident_id = uuid4()
    reporting_period_id = uuid4()
    await harness.db.execute(
        text(
            """
            INSERT INTO reporting_periods (
                id, label, start_date, end_date, status
            )
            VALUES (
                :id, :label, :start_date, :end_date, 'inactive'
            )
            """
        ),
        {
            "id": reporting_period_id,
            "label": f"PG ext reg {str(reporting_period_id)[:12]}",
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 12, 31),
        },
    )
    await harness.db.execute(
        text(
            """
            INSERT INTO residents (id, name, mcr, programme_code, status)
            VALUES (:id, :name, :mcr, 'GERI', 'active')
            """
        ),
        {
            "id": resident_id,
            "name": "Synthetic Native Occupancy Resident",
            "mcr": f"TSTN{uuid4().hex[:10].upper()}",
        },
    )
    await harness.db.execute(
        text(
            """
            INSERT INTO resident_postings (
                id,
                resident_id,
                posting_code,
                reporting_period_id,
                start_date,
                end_date,
                r_year,
                status
            )
            VALUES (
                :id,
                :resident_id,
                'TTSHGerMed',
                :reporting_period_id,
                :start_date,
                :end_date,
                'ALL',
                'active'
            )
            """
        ),
        {
            "id": uuid4(),
            "resident_id": resident_id,
            "reporting_period_id": reporting_period_id,
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 12, 31),
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("with_native_occupancy", [False, True])
async def test_seeded_registration_mapping_is_independent_of_native_occupancy_on_postgres(
    postgres_external_registration_harness: PostgresExternalRegistrationHarness,
    with_native_occupancy: bool,
) -> None:
    harness = postgres_external_registration_harness
    if with_native_occupancy:
        await _add_native_occupancy(harness)

    target_occupancy_count = await harness.db.scalar(
        text(
            """
            SELECT count(*)
            FROM resident_postings
            WHERE posting_code = 'TTSHGerMed'
            """
        )
    )
    assert target_occupancy_count == int(with_native_occupancy)

    options_response = await harness.client.get(
        "/external-residents/registration-options"
    )
    assert options_response.status_code == 200
    geri_option = next(
        option
        for option in options_response.json()
        if option["programme_code"] == "GERI"
    )
    assert "TTSH" in geri_option["institutions"]

    native_resident_count = await harness.db.scalar(text("SELECT count(*) FROM residents"))
    native_posting_count = await harness.db.scalar(text("SELECT count(*) FROM resident_postings"))
    mcr = f"TSTE{uuid4().hex[:10].upper()}"

    response = await harness.client.post(
        "/external-residents/register",
        json={
            "name": "Synthetic PostgreSQL External Resident",
            "mcr": mcr,
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "programme_code": "GERI",
                    "institution": "TTSH",
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["resident"]["current_nhg_posting_code"] == "TTSHGerMed"
    assert payload["posting_schedule"][0]["posting_code"] == "TTSHGerMed"
    assert await harness.db.scalar(text("SELECT count(*) FROM residents")) == native_resident_count
    assert (
        await harness.db.scalar(text("SELECT count(*) FROM resident_postings"))
        == native_posting_count
    )
    assert await harness.db.scalar(
        text("SELECT count(*) FROM external_residents WHERE mcr = :mcr"),
        {"mcr": mcr},
    ) == 1
    assert await harness.db.scalar(
        text(
            """
            SELECT count(*)
            FROM external_resident_postings erp
            JOIN external_residents er
              ON er.id = erp.external_resident_id
            WHERE er.mcr = :mcr
              AND erp.posting_code = 'TTSHGerMed'
            """
        ),
        {"mcr": mcr},
    ) == 1
