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


def test_resident_login_accepts_mcr_only_and_does_not_return_posting_code() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post("/auth/login", json={"role": "resident", "mcr": "M12345A"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["user"]["id"] == fake_db.resident_id
    assert payload["user"]["role"] == "resident"
    assert payload["user"]["mcr"] == "M12345A"
    assert payload["user"]["programme_code"] == "GRM"
    assert "posting_code" not in payload["user"]


def test_resident_login_rejects_unknown_mcr() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post("/auth/login", json={"role": "resident", "mcr": "UNKNOWN"})

    assert response.status_code == 401


def test_resident_login_does_not_require_password() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post("/auth/login", json={"role": "resident", "mcr": "M12345A"})

    assert response.status_code == 200


def test_admin_and_secretary_login_still_work() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    admin = client.post(
        "/auth/login",
        json={"role": "admin", "email": "pc@nhg.com.sg", "password": "password"},
    )
    secretary = client.post(
        "/auth/login",
        json={"role": "secretary", "email": "sec@nhg.com.sg", "password": "password"},
    )

    assert admin.status_code == 200
    assert admin.json()["user"]["programme_scope"] == ["GRM", "DR"]
    assert admin.json()["user"]["admin_level"] == "programme"
    assert secretary.status_code == 200
    assert secretary.json()["user"]["posting_code"] == "TTSHCardio"


def test_auth_me_returns_resident_identity_without_posting_code() -> None:
    fake_db = FakeResidentSession()
    client = _client(
        fake_db,
        AuthIdentity(
            role="resident",
            subject_id=fake_db.resident_id,
            programme_code="GRM",
            mcr="M12345A",
        ),
    )

    response = client.get("/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == fake_db.resident_id
    assert payload["role"] == "resident"
    assert payload["mcr"] == "M12345A"
    assert "posting_code" not in payload
