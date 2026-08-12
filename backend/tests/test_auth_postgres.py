from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date
import os
from uuid import UUID, uuid4

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
from app.middleware.errors import install_error_handlers
from app.routers import auth
from app.services import auth as auth_service
from app.services.database_context import AUTH_BOUNDARY_INFO_KEY
from app.services.reporting_period_status import (
    resolve_active_reporting_period_for_date,
)
from app.services.session_transport import session_cookie_name

DEFAULT_DISPOSABLE_DATABASE_NAME = "mata_evolved_ttf_e2b2_verify"
PHASE_R_DISPOSABLE_DATABASE_NAME = "mata_evolved_ttf_r_verify"
PHASE_K_DISPOSABLE_DATABASE_NAME = "mata_evolved_ttf_k_verify"
PHASE_L_DISPOSABLE_DATABASE_NAME = "mata_evolved_ttf_l_verify"
DISPOSABLE_DATABASE_NAME = os.environ.get(
    "MATA_RLS_DISPOSABLE_DATABASE_NAME",
    DEFAULT_DISPOSABLE_DATABASE_NAME,
)
EXPECTED_ALEMBIC_REVISION = "20260813_000042"


@dataclass
class PostgresAuthHarness:
    client: httpx.AsyncClient
    owner_db: AsyncSession
    auth_db: AsyncSession
    settings: Settings
    posting_code: str
    programme_code: str
    posting_id: UUID
    programme_id: UUID
    native_resident_ids: set[UUID] = field(default_factory=set)
    external_resident_ids: set[UUID] = field(default_factory=set)


def _synthetic_mcr() -> str:
    return f"TST{uuid4().hex[:12].upper()}"


def _assert_local_postgres(database_url: str) -> None:
    url = make_url(database_url)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or DISPOSABLE_DATABASE_NAME
        not in {
            DEFAULT_DISPOSABLE_DATABASE_NAME,
            PHASE_R_DISPOSABLE_DATABASE_NAME,
            PHASE_K_DISPOSABLE_DATABASE_NAME,
            PHASE_L_DISPOSABLE_DATABASE_NAME,
        }
        or url.database != DISPOSABLE_DATABASE_NAME
        or bool(url.query)
    ):
        pytest.fail(
            "PostgreSQL auth integration tests require the explicitly named "
            f"local disposable database {DISPOSABLE_DATABASE_NAME}",
            pytrace=False,
        )


def _owner_async_database_url(settings: Settings) -> str:
    owner_url = make_url(settings.sync_database_url).set(
        drivername="postgresql+asyncpg"
    )
    _assert_local_postgres(owner_url.render_as_string(hide_password=False))
    return owner_url.render_as_string(hide_password=False)


@pytest_asyncio.fixture
async def postgres_auth_harness() -> AsyncIterator[PostgresAuthHarness]:
    settings = Settings(_env_file=None)
    assert settings.database_rls_enabled is True
    assert settings.auth_transport == "cookie"
    assert settings.auth_database_url is not None
    _assert_local_postgres(settings.database_url)
    _assert_local_postgres(settings.auth_database_url)
    owner_engine = create_async_engine(
        _owner_async_database_url(settings),
        poolclass=NullPool,
    )
    auth_engine = create_async_engine(
        settings.auth_database_url,
        poolclass=NullPool,
    )
    posting_id = uuid4()
    programme_id = uuid4()
    posting_code = f"PGAuth{uuid4().hex[:12]}"
    programme_code = f"PGT{uuid4().hex[:12]}"
    period_rows: list[dict] = []
    owner_db = AsyncSession(owner_engine, expire_on_commit=False)
    auth_db = AsyncSession(
        auth_engine,
        expire_on_commit=False,
        info={AUTH_BOUNDARY_INFO_KEY: True},
    )
    harness: PostgresAuthHarness | None = None

    try:
        revision = await owner_db.scalar(
            text("SELECT version_num FROM alembic_version")
        )
        assert revision == EXPECTED_ALEMBIC_REVISION
        assert await auth_db.scalar(
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
        assert await auth_db.scalar(
            text(
                """
                SELECT has_table_privilege(
                    current_user,
                    'public.residents',
                    'SELECT,INSERT,UPDATE,DELETE'
                )
                """
            )
        ) is False

        period_rows = [
            dict(row)
            for row in (
                await owner_db.execute(
                    text(
                        """
                        SELECT id, status, activate_on, deactivate_on
                        FROM reporting_periods
                        """
                    )
                )
            ).mappings().all()
        ]
        await owner_db.execute(
            text(
                """
                UPDATE reporting_periods
                SET status = 'inactive',
                    activate_on = NULL,
                    deactivate_on = NULL
                """
            )
        )
        await owner_db.execute(
            text(
                """
                INSERT INTO posting_codes (id, code, display_name)
                VALUES (:id, :code, :display_name)
                """
            ),
            {
                "id": posting_id,
                "code": posting_code,
                "display_name": "Synthetic PostgreSQL Auth Posting",
            },
        )
        await owner_db.execute(
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
                "id": programme_id,
                "code": programme_code,
                "name": "Synthetic PostgreSQL Auth Programme",
                "ay_date_category": "non_im_subspec",
            },
        )
        await owner_db.commit()
        active_period = await resolve_active_reporting_period_for_date(
            owner_db,
            relevant_date=date.today(),
        )
        assert active_period is None

        app = FastAPI()
        install_error_handlers(app)

        async def _auth_db_override() -> AsyncIterator[AsyncSession]:
            yield auth_db

        async def _rate_limit_override() -> None:
            return None

        app.dependency_overrides[auth.get_auth_db_session] = _auth_db_override
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
            harness = PostgresAuthHarness(
                client=client,
                owner_db=owner_db,
                auth_db=auth_db,
                settings=settings,
                posting_code=posting_code,
                programme_code=programme_code,
                posting_id=posting_id,
                programme_id=programme_id,
            )
            yield harness
    finally:
        await auth_db.rollback()
        await auth_db.close()
        await owner_db.rollback()
        if harness is not None:
            subject_ids = list(
                harness.native_resident_ids | harness.external_resident_ids
            )
            if subject_ids:
                await owner_db.execute(
                    text(
                        """
                        DELETE FROM app_sessions
                        WHERE subject_id = ANY(CAST(:subject_ids AS uuid[]))
                        """
                    ),
                    {"subject_ids": subject_ids},
                )
            if harness.external_resident_ids:
                await owner_db.execute(
                    text(
                        """
                        DELETE FROM external_residents
                        WHERE id = ANY(CAST(:subject_ids AS uuid[]))
                        """
                    ),
                    {"subject_ids": list(harness.external_resident_ids)},
                )
            if harness.native_resident_ids:
                await owner_db.execute(
                    text(
                        """
                        DELETE FROM residents
                        WHERE id = ANY(CAST(:subject_ids AS uuid[]))
                        """
                    ),
                    {"subject_ids": list(harness.native_resident_ids)},
                )
        await owner_db.execute(
            text("DELETE FROM programmes WHERE id = :programme_id"),
            {"programme_id": programme_id},
        )
        await owner_db.execute(
            text("DELETE FROM posting_codes WHERE id = :posting_id"),
            {"posting_id": posting_id},
        )
        for period_row in period_rows:
            await owner_db.execute(
                text(
                    """
                    UPDATE reporting_periods
                    SET status = :status,
                        activate_on = :activate_on,
                        deactivate_on = :deactivate_on
                    WHERE id = :id
                    """
                ),
                period_row,
            )
        await owner_db.commit()
        await owner_db.close()
        await auth_engine.dispose()
        await owner_engine.dispose()


async def _insert_native_resident(
    harness: PostgresAuthHarness,
    *,
    mcr: str,
    status: str = "active",
) -> UUID:
    resident_id = uuid4()
    await harness.owner_db.execute(
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
    await harness.owner_db.commit()
    harness.native_resident_ids.add(resident_id)
    return resident_id


async def _insert_external_resident(
    harness: PostgresAuthHarness,
    *,
    mcr: str,
    status: str = "active",
) -> UUID:
    resident_id = uuid4()
    await harness.owner_db.execute(
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
    await harness.owner_db.commit()
    harness.external_resident_ids.add(resident_id)
    return resident_id


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
    assert payload["user"] == {
        "id": str(resident_id),
        "role": "resident",
        "name": "Synthetic Native Resident",
        "programme_code": postgres_auth_harness.programme_code,
        "mcr": mcr,
    }
    assert payload["csrf_token"]
    assert payload["session_refresh_required"] is False
    assert response.cookies.get(
        session_cookie_name(postgres_auth_harness.settings)
    )
    assert "access_token" not in payload
    assert "refresh_token" not in payload
    assert "current_posting_code" not in payload["user"]
    assert "current_posting_label" not in payload["user"]


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
    assert payload["user"] == {
        "id": str(resident_id),
        "role": "external_resident",
        "name": "Synthetic External Resident",
        "mcr": mcr,
        "home_cluster": "NUH",
    }
    assert payload["csrf_token"]
    assert payload["session_refresh_required"] is False
    assert response.cookies.get(
        session_cookie_name(postgres_auth_harness.settings)
    )
    assert "access_token" not in payload
    assert "refresh_token" not in payload
    assert "current_posting_code" not in payload["user"]
    assert "current_posting_label" not in payload["user"]


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
async def test_global_mcr_uniqueness_prevents_ambiguous_shared_login(
    postgres_auth_harness: PostgresAuthHarness,
) -> None:
    mcr = _synthetic_mcr()
    native_id = await _insert_native_resident(postgres_auth_harness, mcr=mcr)

    with pytest.raises(IntegrityError):
        await _insert_external_resident(postgres_auth_harness, mcr=mcr)
    await postgres_auth_harness.owner_db.rollback()

    response = await postgres_auth_harness.client.post(
        "/auth/login",
        json={"role": "resident", "mcr": mcr},
    )

    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(native_id)
    assert response.json()["user"]["role"] == "resident"


@pytest.mark.asyncio
async def test_external_identity_hydration_without_effective_period_executes_on_postgres(
    postgres_auth_harness: PostgresAuthHarness,
) -> None:
    mcr = _synthetic_mcr()
    resident_id = await _insert_external_resident(postgres_auth_harness, mcr=mcr)

    identity = await auth_service.get_current_identity(
        postgres_auth_harness.owner_db,
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
