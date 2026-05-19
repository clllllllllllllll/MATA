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


def _headers(fake_db: FakeResidentSession) -> dict[str, str]:
    return {
        "X-User-Role": "resident",
        "X-User-Id": fake_db.resident_id,
        "X-User-Programme": "GRM",
    }


def test_adhoc_teaching_derives_posting_from_submitted_date() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "date": "2026-05-18",
            "start_time": "10:00",
            "teaching_name": "Journal Club",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["event"]["posting_code"] == "TTSHCardio"
    assert payload["event"]["is_adhoc"] is True
    assert payload["attendance"]["posting_code"] == "TTSHCardio"
    assert any(row["is_adhoc"] for row in fake_db.events)


def test_adhoc_teaching_on_public_holiday_returns_422_and_writes_nothing() -> None:
    fake_db = FakeResidentSession()
    before_events = len(fake_db.events)
    before_attendance = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "date": "2026-05-01",
            "start_time": "10:00",
            "teaching_name": "Journal Club",
        },
    )

    assert response.status_code == 422
    assert len(fake_db.events) == before_events
    assert len(fake_db.attendance) == before_attendance


def test_adhoc_teaching_rejects_multiple_matching_postings_without_disambiguation() -> None:
    fake_db = FakeResidentSession()
    fake_db.resident_postings.append(
        {
            "resident_id": fake_db.resident_id,
            "reporting_period_id": fake_db.period_id,
            "posting_code": "TTSHNeuro",
            "r_year": "R2",
            "start_date": date(2026, 5, 1),
            "end_date": date(2026, 5, 31),
            "status": "active",
        }
    )
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "date": "2026-05-18",
            "start_time": "10:00",
            "teaching_name": "Journal Club",
        },
    )

    assert response.status_code == 422
    assert "posting disambiguation" in response.json()["detail"].lower()


def test_adhoc_weekend_non_exception_returns_warning() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "date": "2026-05-16",
            "start_time": "10:00",
            "teaching_name": "Journal Club",
        },
    )

    assert response.status_code == 200
    assert response.json()["compliance_warning"].startswith(
        "1 session(s) submitted on a weekend"
    )
