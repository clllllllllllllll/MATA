from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.middleware.errors import install_error_handlers
from app.routers import auth
from app.services import auth as auth_service
from app.services.reporting_period_status import (
    resolve_active_reporting_period_for_date,
)

RESIDENT_SECRET = "postgres-test-resident-session-secret"


@dataclass
class PostgresAuthHarness:
    client: httpx.AsyncClient
    db: AsyncSession
    settings: Settings
    posting_code: str
    programme_code: str


def _synthetic_mcr() -> str:
    return f"TST{uuid4().hex[:12].upper()}"


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
            "PostgreSQL auth integration tests require a local MATA test database",
            pytrace=False,
        )


@pytest_asyncio.fixture
async def postgres_auth_harness() -> AsyncIterator[PostgresAuthHarness]:
    settings = Settings(
        _env_file=None,
        auth_mode="supabase",
        auth_transport="bearer_compat",
        supabase_url="https://mata-postgres-test.invalid",
        mata_resident_session_secret=RESIDENT_SECRET,
    )
    _assert_local_postgres(settings.database_url)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            db = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                await db.execute(
                    text(
                        """
                        UPDATE reporting_periods
                        SET status = 'inactive',
                            activate_on = NULL,
                            deactivate_on = NULL
                        """
                    )
                )
                active_period = await resolve_active_reporting_period_for_date(
                    db,
                    relevant_date=date.today(),
                )
                assert active_period is None

                posting_code = f"PGAuth{uuid4().hex[:12]}"
                await db.execute(
                    text(
                        """
                        INSERT INTO posting_codes (id, code, display_name)
                        VALUES (:id, :code, :display_name)
                        """
                    ),
                    {
                        "id": uuid4(),
                        "code": posting_code,
                        "display_name": "Synthetic PostgreSQL Auth Posting",
                    },
                )
                programme_code = f"PGT{uuid4().hex[:12]}"
                await db.execute(
                    text(
                        """
                        INSERT INTO programmes (
                            id,
                            code,
                            name,
                            ay_date_category
                        )
                        VALUES (:id, :code, :name, :ay_date_category)
                        """
                    ),
                    {
                        "id": uuid4(),
                        "code": programme_code,
                        "name": "Synthetic PostgreSQL Auth Programme",
                        "ay_date_category": "non_im_subspec",
                    },
                )

                app = FastAPI()
                install_error_handlers(app)

                async def _db_override() -> AsyncIterator[AsyncSession]:
                    yield db

                async def _rate_limit_override() -> None:
                    # The production limiter commits its bucket update. Bypass only
                    # that route dependency so this database fixture can roll back.
                    return None

                app.dependency_overrides[auth.get_db_session] = _db_override
                app.dependency_overrides[auth.get_settings] = lambda: settings
                app.dependency_overrides[auth._persistent_login_rate_limit] = (
                    _rate_limit_override
                )
                app.include_router(auth.router)

                transport = httpx.ASGITransport(
                    app=app,
                    raise_app_exceptions=False,
                )
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                ) as client:
                    yield PostgresAuthHarness(
                        client=client,
                        db=db,
                        settings=settings,
                        posting_code=posting_code,
                        programme_code=programme_code,
                    )
            finally:
                if transaction.is_active:
                    await transaction.rollback()
                await db.close()
    finally:
        await engine.dispose()


async def _insert_native_resident(
    harness: PostgresAuthHarness,
    *,
    mcr: str,
    status: str = "active",
) -> UUID:
    resident_id = uuid4()
    await harness.db.execute(
        text(
            """
            INSERT INTO residents (id, name, mcr, programme_code, status)
            VALUES (:id, :name, :mcr, :programme_code, :status)
            """
        ),
        {
            "id": resident_id,
            "name": "Synthetic Native Resident",
            "mcr": mcr,
            "programme_code": harness.programme_code,
            "status": status,
        },
    )
    return resident_id


async def _insert_external_resident(
    harness: PostgresAuthHarness,
    *,
    mcr: str,
    status: str = "active",
) -> UUID:
    resident_id = uuid4()
    await harness.db.execute(
        text(
            """
            INSERT INTO external_residents (
                id,
                name,
                mcr,
                home_cluster,
                current_nhg_posting_code,
                status
            )
            VALUES (
                :id,
                :name,
                :mcr,
                :home_cluster,
                :current_nhg_posting_code,
                :status
            )
            """
        ),
        {
            "id": resident_id,
            "name": "Synthetic External Resident",
            "mcr": mcr,
            "home_cluster": "NUH",
            "current_nhg_posting_code": harness.posting_code,
            "status": status,
        },
    )
    return resident_id


def _decode_resident_token(access_token: str) -> dict:
    return jwt.decode(
        access_token,
        RESIDENT_SECRET,
        algorithms=["HS256"],
        audience="mata-resident-session",
        issuer="mata-api",
    )


def _assert_auth_failure(response: httpx.Response, *, status_code: int) -> None:
    assert response.status_code == status_code
    error_code = "CONFLICT" if status_code == 409 else "UNAUTHORIZED"
    detail = "Conflict" if status_code == 409 else "Unauthorized"
    assert response.json() == {
        "detail": detail,
        "error_code": error_code,
        "errors": [],
        "warnings": [],
        "metadata": {},
    }
    assert "access_token" not in response.json()
    assert "user" not in response.json()


@pytest.mark.asyncio
async def test_shared_login_native_without_effective_period_executes_on_postgres(
    postgres_auth_harness: PostgresAuthHarness,
) -> None:
    mcr = _synthetic_mcr()
    resident_id = await _insert_native_resident(postgres_auth_harness, mcr=mcr)

    response = await postgres_auth_harness.client.post(
        "/auth/login",
        json={"role": "resident", "mcr": mcr.lower()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    assert payload["user"] == {
        "id": str(resident_id),
        "role": "resident",
        "name": "Synthetic Native Resident",
        "programme_code": postgres_auth_harness.programme_code,
        "mcr": mcr,
    }
    assert "current_posting_code" not in payload["user"]
    assert "current_posting_label" not in payload["user"]

    claims = _decode_resident_token(payload["access_token"])
    assert claims["sub"] == str(resident_id)
    assert claims["role"] == "resident"
    assert claims["app_role"] == "resident"


@pytest.mark.asyncio
async def test_shared_login_external_without_effective_period_executes_on_postgres(
    postgres_auth_harness: PostgresAuthHarness,
) -> None:
    mcr = _synthetic_mcr()
    resident_id = await _insert_external_resident(postgres_auth_harness, mcr=mcr)

    response = await postgres_auth_harness.client.post(
        "/auth/login",
        json={"role": "resident", "mcr": mcr},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    assert payload["user"] == {
        "id": str(resident_id),
        "role": "external_resident",
        "name": "Synthetic External Resident",
        "mcr": mcr,
        "home_cluster": "NUH",
    }
    assert "current_posting_code" not in payload["user"]
    assert "current_posting_label" not in payload["user"]

    claims = _decode_resident_token(payload["access_token"])
    assert claims["sub"] == str(resident_id)
    assert claims["role"] == "external_resident"
    assert claims["app_role"] == "external_resident"


@pytest.mark.asyncio
async def test_shared_login_missing_identity_without_effective_period_is_generic_401(
    postgres_auth_harness: PostgresAuthHarness,
) -> None:
    response = await postgres_auth_harness.client.post(
        "/auth/login",
        json={"role": "resident", "mcr": _synthetic_mcr()},
    )

    _assert_auth_failure(response, status_code=401)


@pytest.mark.asyncio
async def test_shared_login_duplicate_without_effective_period_is_generic_409(
    postgres_auth_harness: PostgresAuthHarness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mcr = _synthetic_mcr()
    native_id = await _insert_native_resident(postgres_auth_harness, mcr=mcr)
    external_id = await _insert_external_resident(postgres_auth_harness, mcr=mcr)

    response = await postgres_auth_harness.client.post(
        "/auth/login",
        json={"role": "resident", "mcr": mcr},
    )

    _assert_auth_failure(response, status_code=409)
    exposed_text = f"{response.text}\n{caplog.text}".lower()
    for sensitive_value in (
        mcr,
        native_id,
        external_id,
        "Synthetic Native Resident",
        "Synthetic External Resident",
    ):
        assert str(sensitive_value).lower() not in exposed_text


@pytest.mark.asyncio
async def test_external_identity_hydration_without_effective_period_executes_on_postgres(
    postgres_auth_harness: PostgresAuthHarness,
) -> None:
    mcr = _synthetic_mcr()
    resident_id = await _insert_external_resident(postgres_auth_harness, mcr=mcr)

    identity = await auth_service.get_current_identity(
        postgres_auth_harness.db,
        role="external_resident",
        subject_id=resident_id,
    )

    assert identity == {
        "id": resident_id,
        "role": "external_resident",
        "name": "Synthetic External Resident",
        "mcr": mcr,
        "home_cluster": "NUH",
    }
    assert "current_posting_code" not in identity
    assert "current_posting_label" not in identity
