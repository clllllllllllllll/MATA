from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
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


def _assert_safe_duplicate_conflict(
    response,
    caplog,
    *,
    fake_db: FakeResidentSession,
    duplicate_mcr: str,
) -> None:
    payload = response.json()
    assert payload == {
        "detail": "Conflict",
        "error_code": "CONFLICT",
        "errors": [],
        "warnings": [],
        "metadata": {},
    }
    assert "access_token" not in payload
    assert "user" not in payload

    exposed_text = f"{response.text}\n{caplog.text}"
    exposed_text_lower = exposed_text.lower()
    sensitive_values = (
        duplicate_mcr,
        fake_db.residents[0]["name"],
        fake_db.residents[0]["id"],
        fake_db.external_residents[0]["name"],
        fake_db.external_residents[0]["id"],
        repr(fake_db.residents[0]),
        repr(fake_db.external_residents[0]),
    )
    for value in sensitive_values:
        assert str(value).lower() not in exposed_text_lower

    for unsafe_detail in (
        "external_residents",
        "residents",
        "access_token",
        "stub.",
        "traceback",
        "apierror",
        "select ",
        " inactive",
        " active",
    ):
        assert unsafe_detail not in exposed_text_lower


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
    app.dependency_overrides[auth.get_auth_db_session] = _db_override
    transport_settings = settings or Settings(
        auth_transport="bearer_compat",
        database_rls_enabled=False,
    )
    app.dependency_overrides[auth.get_settings] = lambda: transport_settings
    app.include_router(auth.router)
    return TestClient(app)


def _supabase_settings(*, secret: str | None = RESIDENT_SECRET) -> Settings:
    return Settings(
        auth_mode="supabase",
        auth_transport="bearer_compat",
        database_rls_enabled=False,
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
    assert payload["user"]["current_posting_code"] == "TTSHCardio"
    assert payload["user"]["current_posting_label"] == "TTSH Cardiology"
    assert "current_nhg_posting_code" not in payload["user"]


def test_external_login_falls_back_to_period_posting_when_no_today_row() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings = [
        {
            "id": "period-posting",
            "external_resident_id": fake_db.external_resident_id,
            "posting_code": "TTSHNeuro",
            "start_date": fake_db.reporting_periods[0]["start_date"],
            "end_date": fake_db.today - timedelta(days=1),
            "is_current": False,
        }
    ]
    client = _client(fake_db)

    response = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": "E12345A"},
    )

    assert response.status_code == 200
    assert response.json()["user"]["current_posting_code"] == "TTSHNeuro"
    assert response.json()["user"]["current_posting_label"] == "TTSH Neurology"


def test_external_login_falls_back_to_nearest_future_then_recent_past_posting() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings = [
        {
            "id": "recent-past",
            "external_resident_id": fake_db.external_resident_id,
            "posting_code": "TTSHCardio",
            "start_date": fake_db.today - timedelta(days=20),
            "end_date": fake_db.today - timedelta(days=10),
            "is_current": False,
        },
        {
            "id": "nearest-future",
            "external_resident_id": fake_db.external_resident_id,
            "posting_code": "TTSHNeuro",
            "start_date": fake_db.today + timedelta(days=5),
            "end_date": fake_db.today + timedelta(days=30),
            "is_current": False,
        },
    ]
    client = _client(fake_db)

    response = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": "E12345A"},
    )

    assert response.status_code == 200
    assert response.json()["user"]["current_posting_code"] == "TTSHNeuro"
    assert response.json()["user"]["current_posting_label"] == "TTSH Neurology"

    fake_db.external_resident_postings = [fake_db.external_resident_postings[0]]
    response = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": "E12345A"},
    )

    assert response.status_code == 200
    assert response.json()["user"]["current_posting_code"] == "TTSHCardio"
    assert response.json()["user"]["current_posting_label"] == "TTSH Cardiology"


def test_external_login_omits_current_posting_only_when_no_schedule_rows_exist() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings = []
    client = _client(fake_db)

    response = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": "E12345A"},
    )

    assert response.status_code == 200
    assert "current_posting_code" not in response.json()["user"]
    assert "current_posting_label" not in response.json()["user"]


def test_supabase_mode_shared_resident_login_issues_external_mata_token() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db, settings=_supabase_settings())

    response = client.post(
        "/auth/login",
        json={"role": "resident", "mcr": " e12345a "},
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


def test_supabase_mode_rejects_cross_table_duplicate_mcr_for_resident_login(caplog) -> None:
    fake_db = FakeResidentSession()
    duplicate_mcr = _create_cross_table_mcr_duplicate(fake_db)
    client = _client(fake_db, settings=_supabase_settings())

    response = client.post(
        "/auth/login",
        json={"role": "resident", "mcr": f" {duplicate_mcr.lower()} "},
    )

    assert response.status_code == 409
    _assert_safe_duplicate_conflict(
        response,
        caplog,
        fake_db=fake_db,
        duplicate_mcr=duplicate_mcr,
    )


@pytest.mark.parametrize(
    ("duplicate_mcr", "native_status", "external_status"),
    [
        pytest.param(
            "M90001Z",
            "active",
            "inactive",
            id="native-active-external-inactive",
        ),
        pytest.param(
            "M90002Y",
            "inactive",
            "active",
            id="native-inactive-external-active",
        ),
    ],
)
def test_shared_resident_login_rejects_mixed_status_cross_table_duplicate(
    caplog,
    duplicate_mcr: str,
    native_status: str,
    external_status: str,
) -> None:
    fake_db = FakeResidentSession()
    native_row = fake_db.residents[0]
    external_row = fake_db.external_residents[0]
    native_row.update(
        {
            "name": f"Synthetic Native {native_status.title()}",
            "mcr": duplicate_mcr,
            "status": native_status,
        }
    )
    external_row.update(
        {
            "name": f"Synthetic External {external_status.title()}",
            "mcr": duplicate_mcr,
            "status": external_status,
        }
    )
    assert native_row["mcr"] == external_row["mcr"] == duplicate_mcr
    assert {native_row["status"], external_row["status"]} == {"active", "inactive"}

    client = _client(fake_db, settings=_supabase_settings())
    response = client.post(
        "/auth/login",
        json={"role": "resident", "mcr": f" {duplicate_mcr.lower()} "},
    )

    assert response.status_code == 409
    _assert_safe_duplicate_conflict(
        response,
        caplog,
        fake_db=fake_db,
        duplicate_mcr=duplicate_mcr,
    )


def test_supabase_mode_rejects_cross_table_duplicate_mcr_for_external_login() -> None:
    fake_db = FakeResidentSession()
    duplicate_mcr = _create_cross_table_mcr_duplicate(fake_db)
    client = _client(fake_db, settings=_supabase_settings())

    response = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": duplicate_mcr},
    )

    assert response.status_code == 409
    assert "access_token" not in response.json()


def test_stub_mode_rejects_cross_table_duplicate_mcr_for_resident_login() -> None:
    fake_db = FakeResidentSession()
    duplicate_mcr = _create_cross_table_mcr_duplicate(fake_db)
    client = _client(fake_db)

    response = client.post(
        "/auth/login",
        json={"role": "resident", "mcr": duplicate_mcr},
    )

    assert response.status_code == 409
    assert "access_token" not in response.json()


def test_stub_mode_rejects_cross_table_duplicate_mcr_for_external_login() -> None:
    fake_db = FakeResidentSession()
    duplicate_mcr = _create_cross_table_mcr_duplicate(fake_db)
    client = _client(fake_db)

    response = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": duplicate_mcr},
    )

    assert response.status_code == 409
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


def test_external_role_does_not_authenticate_native_resident_mcr() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": "M12345A"},
    )

    assert response.status_code == 401
    assert "access_token" not in response.json()


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
    assert payload["current_posting_code"] == "TTSHCardio"
    assert "current_nhg_posting_code" not in payload


def test_external_current_posting_uses_resolved_period_and_fails_closed_on_overlap() -> None:
    fake_db = FakeResidentSession()
    fake_db.reporting_periods.append(
        {
            "id": str(uuid4()),
            "label": "Future Test Period",
            "start_date": date(2099, 1, 1),
            "end_date": date(2099, 6, 30),
            "status": "active",
            "activate_on": None,
            "deactivate_on": None,
        }
    )
    client = _client(fake_db)
    current = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": "E12345A"},
    )
    assert current.status_code == 200
    assert current.json()["user"]["current_posting_code"] == "TTSHCardio"

    fake_db.reporting_periods[0]["status"] = "inactive"
    no_period = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": "E12345A"},
    )
    assert no_period.status_code == 200
    assert "current_posting_code" not in no_period.json()["user"]

    fake_db.reporting_periods[0]["status"] = "active"
    fake_db.reporting_periods.append(
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
    conflict = client.post(
        "/auth/login",
        json={"role": "external_resident", "mcr": "E12345A"},
    )
    assert conflict.status_code == 409
