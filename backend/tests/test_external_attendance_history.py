from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

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


def test_external_attendance_history_returns_only_own_records() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_attendance.append(
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.other_external_resident_id,
            "teaching_event_id": fake_db.event_id,
            "status": "submitted",
            "posting_code": "TTSHNeuro",
            "submitted_at": datetime(2026, 5, 18, 10, 0, tzinfo=timezone.utc),
        }
    )
    client = _client(fake_db)

    response = client.get(
        "/resident/attendance-history",
        headers={
            "X-User-Role": "external_resident",
            "X-User-Id": fake_db.external_resident_id,
        },
    )

    assert response.status_code == 200
    rows = response.json()["attendance"]
    assert rows
    assert all(row["teaching_event_id"] == fake_db.second_event_id for row in rows)
    first = rows[0]
    assert "teaching_name" in first
    assert "event_date" in first
    assert "submitted_at" in first


def test_native_attendance_history_still_uses_native_records() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get(
        "/resident/attendance-history",
        headers={
            "X-User-Role": "resident",
            "X-User-Id": fake_db.resident_id,
            "X-User-Programme": "GRM",
        },
    )

    assert response.status_code == 200
    rows = response.json()["attendance"]
    assert rows
    assert any(row["teaching_event_id"] == fake_db.second_event_id for row in rows)
