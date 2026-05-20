from __future__ import annotations

from datetime import date, timedelta
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


def _headers(fake_db: FakeResidentSession, *, resident_id: str | None = None) -> dict[str, str]:
    return {
        "X-User-Role": "resident",
        "X-User-Id": resident_id or fake_db.resident_id,
        "X-User-Programme": "GRM",
        "X-User-Site": "WrongHeaderSite",
    }


def test_events_returns_posting_schedule_unavailable_when_no_current_posting_exists() -> None:
    fake_db = FakeResidentSession()
    fake_db.resident_postings = []
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    assert response.json() == {"events": [], "reason": "posting_schedule_unavailable"}


def test_events_derive_posting_from_resident_postings_not_header_site() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    events = response.json()["events"]
    ids = {row["id"] for row in events}
    assert fake_db.event_id in ids
    assert fake_db.other_posting_event_id not in ids


def test_events_support_multiple_current_postings_as_union() -> None:
    fake_db = FakeResidentSession()
    fake_db.resident_postings.append(
        {
            "resident_id": fake_db.resident_id,
            "reporting_period_id": fake_db.period_id,
            "posting_code": "TTSHNeuro",
            "r_year": "R2",
            "start_date": fake_db.today - timedelta(days=10),
            "end_date": fake_db.today + timedelta(days=10),
            "status": "active",
        }
    )
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.event_id in ids
    assert fake_db.other_posting_event_id in ids


def test_events_exclude_future_already_submitted_and_unmapped_events() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.future_event_id not in ids
    assert fake_db.second_event_id not in ids
    assert fake_db.invisible_event_id not in ids


def test_events_include_global_session_types_through_normal_posting_rules() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.global_event_id in ids


def test_events_return_empty_reason_when_no_open_reporting_period_exists() -> None:
    fake_db = FakeResidentSession()
    fake_db.reporting_periods = []
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    assert response.json() == {"events": [], "reason": "reporting_period_unavailable"}


def test_events_reject_non_resident_role() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get(
        "/resident/events",
        headers={"X-User-Role": "admin", "X-User-Id": str(uuid4())},
    )

    assert response.status_code == 403
