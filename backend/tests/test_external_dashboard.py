from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import resident
from tests.auth_identity_test_helpers import install_stub_header_identity_middleware
from tests.resident_fakes import FakeResidentSession


def _client(fake_db: FakeResidentSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    install_stub_header_identity_middleware(app)

    async def _db_override():
        yield fake_db

    app.dependency_overrides[resident.get_db_session] = _db_override
    app.include_router(resident.router)
    return TestClient(app)


def test_external_dashboard_returns_not_applicable() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get(
        "/resident/dashboard",
        headers={
            "X-User-Role": "external_resident",
            "X-User-Id": fake_db.external_resident_id,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["compliance_status"] == "not_applicable"
    assert payload["reason"] == "external_resident_excluded_from_nhg_compliance"
    assert "NHG compliance and clawback do not apply" in payload["message"]
    assert "percentage" not in payload
    assert "surplus" not in payload
