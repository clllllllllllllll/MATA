from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import resident
from tests.resident_fakes import FakeResidentSession


def _client(fake_db: FakeResidentSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    async def _db_override():
        yield fake_db

    app.dependency_overrides[resident.get_db_session] = _db_override
    app.include_router(resident.router)
    return TestClient(app)


def test_dashboard_returns_phase_6_placeholder_only() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get(
        "/resident/dashboard",
        headers={
            "X-User-Role": "resident",
            "X-User-Id": fake_db.resident_id,
            "X-User-Programme": "GRM",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["resident"]["id"] == fake_db.resident_id
    assert payload["reporting_period"]["label"] == "Jan - June 2026"
    assert payload["compliance_status"] == "pending_phase_6"
    assert "percentage" not in payload
    assert "surplus" not in payload
