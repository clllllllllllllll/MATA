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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.errors import ApiError
from app.middleware.errors import install_error_handlers
from app.routers import external_residents
from app.schemas.external_resident import ExternalResidentPostingScheduleRow
from app.services import external_residents as external_resident_service
from app.services import programme_institution_posting


APPROVED_TTSH_MAPPINGS = (
    ("AIM", "TTSHGenMed"),
    ("ANAES", "TTSHAnaes"),
    ("CARDIO", "TTSHCardio"),
    ("DERM", "NSCDermat"),
    ("DR", "TTSHDiagRd"),
    ("EM", "TTSHEmgMed"),
    ("ENDO", "TTSHEndocr"),
    ("ENT", "TTSHOtolar"),
    ("EYE", "TTSHOphtha"),
    ("GASTRO", "TTSHGas"),
    ("GERI", "TTSHGerMed"),
    ("GS", "TTSHGenSrg"),
    ("ID", "TTSHInfect"),
    ("IM", "TTSHGenMed"),
    ("MEDONCO", "TTSHMedOnc"),
    ("ORTHO", "TTSHOrtSrg"),
    ("PSY", "TTSHPsychi"),
    ("REHAB", "TTSHRehabi"),
    ("RENAL", "TTSHRenal"),
    ("RESPI", "TTSHRespir"),
    ("RHEUM", "TTSHRheuma"),
    ("SIG", "TTSHGenSrg"),
    ("URO", "TTSHUrolog"),
    ("MICROB", "TTSHLabMed"),
)
INACTIVE_TTSH_PROGRAMMES = ("FM", "PATH", "SPORTSMED", "PALLMED")


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
        or not (
            url.database == "mata_db"
            or (url.database or "").startswith("mata_phase5b_verify_")
        )
    ):
        pytest.fail(
            "PostgreSQL external-registration tests require a local MATA test database",
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
                mapping_rows = await db.execute(
                    text(
                        """
                        SELECT programme_code, posting_code, status
                        FROM programme_institution_posting_map
                        WHERE institution_code = 'TTSH'
                        ORDER BY display_order
                        """
                    )
                )
                rows = mapping_rows.mappings().all()
                active_rows = [
                    (row["programme_code"], row["posting_code"])
                    for row in rows
                    if row["status"] == "active"
                ]
                inactive_rows = [
                    (row["programme_code"], row["posting_code"])
                    for row in rows
                    if row["status"] == "inactive"
                ]
                assert len(rows) == 28
                assert len(active_rows) == 24
                assert len(inactive_rows) == 4
                assert active_rows == list(APPROVED_TTSH_MAPPINGS)
                assert inactive_rows == [
                    (programme_code, None)
                    for programme_code in INACTIVE_TTSH_PROGRAMMES
                ]
                assert not any(row["status"] == "pending" for row in rows)
                assert dict(active_rows)["AIM"] == dict(active_rows)["IM"]
                assert dict(active_rows)["GS"] == dict(active_rows)["SIG"]

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
    options_payload = options_response.json()
    assert options_payload["institutions"] == [{"code": "TTSH", "name": "TTSH"}]
    assert [
        option["programme_code"] for option in options_payload["programmes"]
    ] == [programme_code for programme_code, _posting_code in APPROVED_TTSH_MAPPINGS]
    assert all(
        option["institutions"]
        == [
            {
                "institution_code": "TTSH",
                "available": True,
                "status": "active",
            }
        ]
        for option in options_payload["programmes"]
    )
    assert "posting_code" not in options_response.text
    geri_option = next(
        option
        for option in options_payload["programmes"]
        if option["programme_code"] == "GERI"
    )
    assert geri_option["programme_name"] == "Geriatric Medicine"
    assert geri_option["institutions"] == [
        {
            "institution_code": "TTSH",
            "available": True,
            "status": "active",
        }
    ]

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("programme_code", "expected_posting_code"),
    APPROVED_TTSH_MAPPINGS,
)
async def test_each_approved_ttsh_pair_resolves_exactly_on_postgres(
    postgres_external_registration_harness: PostgresExternalRegistrationHarness,
    programme_code: str,
    expected_posting_code: str,
) -> None:
    resolved = await programme_institution_posting.resolve_programme_institution_posting(
        postgres_external_registration_harness.db,
        programme_code=f" {programme_code.lower()} ",
        institution_code=" ttsh ",
    )

    assert resolved == expected_posting_code


@pytest.mark.asyncio
async def test_mapping_constraints_are_enforced_on_postgres(
    postgres_external_registration_harness: PostgresExternalRegistrationHarness,
) -> None:
    db = postgres_external_registration_harness.db

    statements = [
        (
            """
            INSERT INTO programme_institution_posting_map (
                programme_code, institution_code, posting_code, status
            ) VALUES ('GERI', 'TTSH', NULL, 'pending')
            """,
            "unique programme/institution",
        ),
        (
            """
            INSERT INTO programme_institution_posting_map (
                programme_code, institution_code, posting_code, status
            ) VALUES ('GERI', 'NULLCHECK', NULL, 'active')
            """,
            "active mapping posting check",
        ),
        (
            """
            INSERT INTO programme_institution_posting_map (
                programme_code, institution_code, posting_code, status
            ) VALUES ('UNKNOWN', 'FKPROGRAMME', NULL, 'pending')
            """,
            "programme foreign key",
        ),
        (
            """
            INSERT INTO programme_institution_posting_map (
                programme_code, institution_code, posting_code, status
            ) VALUES ('GERI', 'FKPOSTING', 'UNKNOWN', 'pending')
            """,
            "posting foreign key",
        ),
    ]

    for statement, label in statements:
        with pytest.raises(IntegrityError) as error:
            async with db.begin_nested():
                await db.execute(text(statement))
        assert error.value is not None, label


@pytest.mark.asyncio
@pytest.mark.parametrize("programme_code", INACTIVE_TTSH_PROGRAMMES)
async def test_inactive_registration_is_transactional_on_postgres(
    postgres_external_registration_harness: PostgresExternalRegistrationHarness,
    programme_code: str,
) -> None:
    harness = postgres_external_registration_harness
    mcr = f"TSTI{uuid4().hex[:9].upper()}"
    residents_before = await harness.db.scalar(
        text("SELECT count(*) FROM external_residents")
    )
    postings_before = await harness.db.scalar(
        text("SELECT count(*) FROM external_resident_postings")
    )

    response = await harness.client.post(
        "/external-residents/register",
        json={
            "name": "Inactive PostgreSQL Resident",
            "mcr": mcr,
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "programme_code": programme_code,
                    "institution": "TTSH",
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Posting configuration for this programme is unavailable."
    )
    assert await harness.db.scalar(
        text("SELECT count(*) FROM external_residents")
    ) == residents_before
    assert await harness.db.scalar(
        text("SELECT count(*) FROM external_resident_postings")
    ) == postings_before


@pytest.mark.asyncio
async def test_schedule_replacement_mixed_mapping_rolls_back_on_postgres(
    postgres_external_registration_harness: PostgresExternalRegistrationHarness,
) -> None:
    harness = postgres_external_registration_harness
    mcr = f"TSTR{uuid4().hex[:10].upper()}"
    registration = await harness.client.post(
        "/external-residents/register",
        json={
            "name": "Replacement PostgreSQL Resident",
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
    assert registration.status_code == 200
    resident_id = registration.json()["resident"]["id"]
    prior_rows = (
        await harness.db.execute(
            text(
                """
                SELECT posting_code, start_date, end_date
                FROM external_resident_postings
                WHERE external_resident_id = :resident_id
                ORDER BY start_date
                """
            ),
            {"resident_id": resident_id},
        )
    ).mappings().all()

    with pytest.raises(ApiError) as error:
        await external_resident_service.replace_my_posting_schedule(
            harness.db,
            external_resident_id=resident_id,
            posting_schedule=[
                ExternalResidentPostingScheduleRow(
                    start_date=date(2026, 10, 1),
                    end_date=date(2026, 10, 31),
                    programme_code="GERI",
                    institution="TTSH",
                ),
                ExternalResidentPostingScheduleRow(
                    start_date=date(2026, 11, 1),
                    end_date=date(2026, 11, 30),
                    programme_code="FM",
                    institution="TTSH",
                ),
            ],
        )
    assert error.value.status_code == 422
    assert error.value.detail == "Posting configuration for this programme is unavailable."
    current_rows = (
        await harness.db.execute(
            text(
                """
                SELECT posting_code, start_date, end_date
                FROM external_resident_postings
                WHERE external_resident_id = :resident_id
                ORDER BY start_date
                """
            ),
            {"resident_id": resident_id},
        )
    ).mappings().all()
    assert current_rows == prior_rows


@pytest.mark.asyncio
async def test_future_institution_discovery_is_data_driven_on_postgres(
    postgres_external_registration_harness: PostgresExternalRegistrationHarness,
) -> None:
    harness = postgres_external_registration_harness
    await harness.db.execute(
        text(
            """
            INSERT INTO programme_institution_posting_map (
                programme_code,
                institution_code,
                posting_code,
                status,
                display_order
            ) VALUES ('GERI', 'KTPH', 'KTPHGerMed', 'active', 11)
            """
        )
    )

    response = await harness.client.get(
        "/external-residents/registration-options"
    )

    assert response.status_code == 200
    assert {row["code"] for row in response.json()["institutions"]} == {
        "TTSH",
        "KTPH",
    }
    geri = next(
        row
        for row in response.json()["programmes"]
        if row["programme_code"] == "GERI"
    )
    assert any(
        row["institution_code"] == "KTPH" and row["available"] is True
        for row in geri["institutions"]
    )
