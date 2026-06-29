from __future__ import annotations

from datetime import date

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


def _external_headers(fake_db: FakeResidentSession) -> dict[str, str]:
    return {
        "X-User-Role": "external_resident",
        "X-User-Id": fake_db.external_resident_id,
    }


def test_external_adhoc_creates_event_and_external_attendance() -> None:
    fake_db = FakeResidentSession()
    before_events = len(fake_db.events)
    before_attendance = len(fake_db.external_attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_external_headers(fake_db),
        json={
            "date": "2026-05-18",
            "start_time": "10:00",
            "teaching_name": "Journal Club",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["event"]["is_adhoc"] is True
    assert "created_by_role" not in payload["event"]
    assert payload["attendance"]["external_resident_id"] == fake_db.external_resident_id
    assert len(fake_db.events) == before_events + 1
    assert len(fake_db.external_attendance) == before_attendance + 1


def test_external_adhoc_does_not_require_teaching_name_catalogue() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_residents[0]["current_nhg_posting_code"] = "KTPHGerMed"
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_external_headers(fake_db),
        json={
            "date": "2026-05-18",
            "start_time": "10:00",
            "teaching_name": "Completely New Topic",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["event"]["teaching_name"] == "Completely New Topic"


def test_external_adhoc_public_holiday_returns_422_and_writes_nothing() -> None:
    fake_db = FakeResidentSession()
    before_events = len(fake_db.events)
    before_attendance = len(fake_db.external_attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_external_headers(fake_db),
        json={
            "date": "2026-05-01",
            "start_time": "10:00",
            "teaching_name": "Journal Club",
        },
    )

    assert response.status_code == 422
    assert len(fake_db.events) == before_events
    assert len(fake_db.external_attendance) == before_attendance


def test_external_adhoc_weekend_non_exception_returns_warning() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_external_headers(fake_db),
        json={
            "date": date(2026, 5, 16).isoformat(),
            "start_time": "10:00",
            "teaching_name": "Journal Club",
        },
    )

    assert response.status_code == 200
    assert response.json()["compliance_warning"].startswith("1 session(s) submitted on a weekend")
