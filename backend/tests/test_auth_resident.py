from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.middleware.auth_stub import AuthIdentity
from app.middleware.errors import install_error_handlers
from app.routers import auth
from tests.resident_fakes import FakeResidentSession

RESIDENT_SECRET = "unit-test-resident-session-secret"


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
    assert payload["user"]["current_posting_code"] == "TTSHCardio"
    assert payload["user"]["current_posting_label"] == "TTSH Cardiology"
    assert "posting_code" not in payload["user"]


def test_supabase_mode_resident_login_issues_backend_signed_mata_token() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db, settings=_supabase_settings())

    response = client.post("/auth/login", json={"role": "resident", "mcr": " m12345a "})

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    assert not payload["access_token"].startswith("stub.")
    assert payload["user"] == {
        "id": fake_db.resident_id,
        "role": "resident",
        "name": "Resident One",
        "programme_code": "GRM",
        "mcr": "M12345A",
        "current_posting_code": "TTSHCardio",
        "current_posting_label": "TTSH Cardiology",
    }

    claims = jwt.decode(
        payload["access_token"],
        RESIDENT_SECRET,
        algorithms=["HS256"],
        audience="mata-resident-session",
        issuer="mata-api",
    )
    assert claims["sub"] == fake_db.resident_id
    assert claims["role"] == "resident"
    assert claims["app_role"] == "resident"
    assert claims["mcr"] == "M12345A"
    assert claims["programme_code"] == "GRM"
    assert isinstance(claims["exp"], int)
    assert claims["exp"] > int(datetime.now(UTC).timestamp())
    assert "posting_code" not in claims
    assert "current_posting" not in claims
    assert "admin_level" not in claims
    assert "programme_scope" not in claims
    assert "current_staff_actor_name" not in claims


def test_supabase_mode_resident_login_rejects_unknown_mcr() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db, settings=_supabase_settings())

    response = client.post("/auth/login", json={"role": "resident", "mcr": "UNKNOWN"})

    assert response.status_code == 401


def test_supabase_mode_resident_login_rejects_inactive_resident() -> None:
    fake_db = FakeResidentSession()
    fake_db.residents[0]["status"] = "inactive"
    client = _client(fake_db, settings=_supabase_settings())

    response = client.post("/auth/login", json={"role": "resident", "mcr": "M12345A"})

    assert response.status_code == 401


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


def test_staff_login_derives_master_admin_identity_from_email() -> None:
    fake_db = FakeResidentSession()
    fake_db.users.append(
        {
            "id": "00000000-0000-0000-0000-0000000000aa",
            "email": "master@nhg.com.sg",
            "password_hash": "password",
            "role": "admin",
            "name": "Master Admin",
            "posting_code": None,
            "programme_scope": None,
            "admin_level": "master",
            "is_active": True,
        },
    )
    client = _client(fake_db)

    response = client.post(
        "/auth/login",
        json={"role": "staff", "email": "master@nhg.com.sg", "password": "password"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"] == "stub.admin.00000000-0000-0000-0000-0000000000aa"
    assert payload["user"]["role"] == "admin"
    assert payload["user"]["admin_level"] == "master"
    assert payload["user"]["programme_scope"] == []


def test_staff_login_derives_programme_pc_identity_from_email() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/auth/login",
        json={"role": "staff", "email": "pc@nhg.com.sg", "password": "password"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"] == f"stub.admin.{fake_db.admin_id}"
    assert payload["user"]["role"] == "admin"
    assert payload["user"]["admin_level"] == "programme"
    assert payload["user"]["programme_scope"] == ["GRM", "DR"]


def test_staff_login_derives_secretary_identity_from_email() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/auth/login",
        json={"role": "staff", "email": "sec@nhg.com.sg", "password": "password"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"] == f"stub.secretary.{fake_db.secretary_id}"
    assert payload["user"]["role"] == "secretary"
    assert payload["user"]["posting_code"] == "TTSHCardio"


def test_staff_login_wrong_password_returns_401() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/auth/login",
        json={"role": "staff", "email": "sec@nhg.com.sg", "password": "wrong"},
    )

    assert response.status_code == 401


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


def test_resident_current_posting_uses_only_the_resolved_current_period() -> None:
    fake_db = FakeResidentSession()
    future_period_id = str(uuid4())
    fake_db.reporting_periods.append(
        {
            "id": future_period_id,
            "label": "Future Test Period",
            "start_date": date(2099, 1, 1),
            "end_date": date(2099, 6, 30),
            "status": "active",
            "activate_on": None,
            "deactivate_on": None,
        }
    )
    fake_db.resident_postings.append(
        {
            "resident_id": fake_db.resident_id,
            "reporting_period_id": future_period_id,
            "posting_code": "TTSHNeuro",
            "r_year": "R2",
            "start_date": date(2099, 1, 1),
            "end_date": date(2099, 6, 30),
            "status": "active",
        }
    )
    login_client = _client(fake_db)
    me_client = _client(
        fake_db,
        AuthIdentity(role="resident", subject_id=fake_db.resident_id, programme_code="GRM"),
    )

    login = login_client.post("/auth/login", json={"role": "resident", "mcr": "M12345A"})
    current_identity = me_client.get("/auth/me")

    assert login.status_code == 200
    assert login.json()["user"]["current_posting_code"] == "TTSHCardio"
    assert current_identity.status_code == 200
    assert current_identity.json()["current_posting_code"] == "TTSHCardio"


def test_resident_current_posting_is_empty_without_period_and_conflicts_on_overlap() -> None:
    unavailable = FakeResidentSession()
    unavailable.reporting_periods[0]["status"] = "inactive"
    unavailable_client = _client(unavailable)
    no_period = unavailable_client.post(
        "/auth/login",
        json={"role": "resident", "mcr": "M12345A"},
    )

    overlapping = FakeResidentSession()
    overlapping.reporting_periods.append(
        {
            "id": str(uuid4()),
            "label": "Overlapping current period",
            "start_date": date.today() - timedelta(days=1),
            "end_date": date.today() + timedelta(days=1),
            "status": "active",
            "activate_on": None,
            "deactivate_on": None,
        }
    )
    overlap_client = _client(overlapping)
    conflict = overlap_client.post(
        "/auth/login",
        json={"role": "resident", "mcr": "M12345A"},
    )

    assert no_period.status_code == 200
    assert "current_posting_code" not in no_period.json()["user"]
    assert conflict.status_code == 409
