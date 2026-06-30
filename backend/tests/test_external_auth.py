from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.auth_stub import AuthIdentity
from app.middleware.errors import install_error_handlers
from app.routers import auth
from tests.resident_fakes import FakeResidentSession


def _client(
    fake_db: FakeResidentSession,
    identity: AuthIdentity | None = None,
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
    app.include_router(auth.router)
    return TestClient(app)


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
