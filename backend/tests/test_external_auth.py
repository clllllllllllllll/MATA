from __future__ import annotations

from datetime import UTC, datetime

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.middleware.auth_stub import AuthIdentity
from app.middleware.errors import install_error_handlers
from app.routers import auth
from tests.resident_fakes import FakeResidentSession

RESIDENT_SECRET = "unit-test-resident-session-secret"


def _create_cross_table_mcr_duplicate(fake_db: FakeResidentSession) -> str:
    duplicate_mcr = fake_db.residents[0]["mcr"]
    fake_db.external_residents[0]["mcr"] = duplicate_mcr
    return duplicate_mcr


def _client(
    fake_db: FakeResidentSession,
    identity: AuthIdentity | None = None,
    settings: Settings | None = None,
) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.middleware("http")
    async def inject_identity(request, call_next):
        if identity is not None:
            request.state.identity = identity
        return await call_next(request)

    async def _db_override():
        yield fake_db

    app.dependency_overrides[auth.get_db_session] = _db_override
    if settings is not None:
        app.dependency_overrides[auth.get_settings] = lambda: settings
    app.include_router(auth.router)
    return TestClient(app)


def _supabase_settings(*, secret: str | None = RESIDENT_SECRET) -> Settings:
    return Settings(
        auth_mode="supabase",
        supabase_url="https://mata-test.supabase.co",
        mata_resident_session_secret=secret,
    )


def test_external_login_accepts_mcr_only() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": "E12345A"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["id"] == fake_db.external_resident_id
    assert payload["user"]["role"] == "external_resident"
    assert payload["user"]["mcr"] == "E12345A"
    assert payload["user"]["home_cluster"] == "NUH"
    assert "current_nhg_posting_code" not in payload["user"]


def test_supabase_mode_external_login_issues_backend_signed_mata_token() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db, settings=_supabase_settings())

    response = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": " e12345a "},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    assert not payload["access_token"].startswith("stub.")
    assert payload["user"] == {
        "id": fake_db.external_resident_id,
        "role": "external_resident",
        "name": "External Resident One",
        "mcr": "E12345A",
        "home_cluster": "NUH",
    }

    claims = jwt.decode(
        payload["access_token"],
        RESIDENT_SECRET,
        algorithms=["HS256"],
        audience="mata-resident-session",
        issuer="mata-api",
    )
    assert claims["sub"] == fake_db.external_resident_id
    assert claims["role"] == "external_resident"
    assert claims["app_role"] == "external_resident"
    assert claims["mcr"] == "E12345A"
    assert claims["home_cluster"] == "NUH"
    assert isinstance(claims["exp"], int)
    assert claims["exp"] > int(datetime.now(UTC).timestamp())
    assert "current_nhg_posting_code" not in claims
    assert "current_posting" not in claims
    assert "posting_code" not in claims
    assert "posting_schedule" not in claims
    assert "programme_code" not in claims
    assert "programme_scope" not in claims
    assert "admin_level" not in claims
    assert "current_staff_actor_name" not in claims


def test_supabase_mode_rejects_cross_table_duplicate_mcr_for_resident_login() -> None:
    fake_db = FakeResidentSession()
    duplicate_mcr = _create_cross_table_mcr_duplicate(fake_db)
    client = _client(fake_db, settings=_supabase_settings())

    response = client.post(
        "/auth/login",
        json={"role": "resident", "mcr": f" {duplicate_mcr.lower()} "},
    )

    assert response.status_code == 401
    assert "access_token" not in response.json()


def test_supabase_mode_rejects_cross_table_duplicate_mcr_for_external_login() -> None:
    fake_db = FakeResidentSession()
    duplicate_mcr = _create_cross_table_mcr_duplicate(fake_db)
    client = _client(fake_db, settings=_supabase_settings())

    response = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": duplicate_mcr},
    )

    assert response.status_code == 401
    assert "access_token" not in response.json()


def test_stub_mode_rejects_cross_table_duplicate_mcr_for_resident_login() -> None:
    fake_db = FakeResidentSession()
    duplicate_mcr = _create_cross_table_mcr_duplicate(fake_db)
    client = _client(fake_db)

    response = client.post(
        "/auth/login",
        json={"role": "resident", "mcr": duplicate_mcr},
    )

    assert response.status_code == 401
    assert "access_token" not in response.json()


def test_stub_mode_rejects_cross_table_duplicate_mcr_for_external_login() -> None:
    fake_db = FakeResidentSession()
    duplicate_mcr = _create_cross_table_mcr_duplicate(fake_db)
    client = _client(fake_db)

    response = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": duplicate_mcr},
    )

    assert response.status_code == 401
    assert "access_token" not in response.json()


def test_supabase_mode_external_login_rejects_inactive_external_resident() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_residents[0]["status"] = "inactive"
    client = _client(fake_db, settings=_supabase_settings())

    response = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": "E12345A"},
    )

    assert response.status_code == 401


def test_external_login_rejects_unknown_mcr() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": "UNKNOWN"},
    )

    assert response.status_code == 401


def test_auth_me_returns_external_identity_without_posting_claim() -> None:
    fake_db = FakeResidentSession()
    client = _client(
        fake_db,
        AuthIdentity(
            role="external_resident",
            subject_id=fake_db.external_resident_id,
            mcr="E12345A",
            home_cluster="NUH",
        ),
    )

    response = client.get("/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == fake_db.external_resident_id
    assert payload["role"] == "external_resident"
    assert payload["mcr"] == "E12345A"
    assert payload["home_cluster"] == "NUH"
    assert "current_nhg_posting_code" not in payload
