from __future__ import annotations

from datetime import date
from decimal import Decimal
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


def _external_headers(fake_db: FakeResidentSession) -> dict[str, str]:
    return {
        "X-User-Role": "external_resident",
        "X-User-Id": fake_db.external_resident_id,
    }


def test_external_events_visible_when_supports_secretary_events_true() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_external_headers(fake_db))

    assert response.status_code == 200
    events = response.json()["events"]
    ids = {row["id"] for row in events}
    assert fake_db.event_id in ids
    assert all("created_by_role" not in row for row in events)


def test_external_events_hidden_when_supports_secretary_events_false() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_residents[0]["current_nhg_posting_code"] = "KTPHGerMed"
    fake_db.events.append(
        fake_db._event(  # noqa: SLF001
            str(uuid4()),
            "KTPHGerMed",
            "Secretary Teaching",
            date(2026, 5, 18),
            duration_hours=Decimal("1.0"),
        )
    )
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_external_headers(fake_db))

    assert response.status_code == 200
    assert response.json() == {"events": [], "reason": "secretary_events_not_supported"}


def test_external_events_exclude_already_submitted_records() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_external_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.second_event_id not in ids


def test_external_event_visibility_does_not_require_teaching_name_catalogue() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_residents[0]["current_nhg_posting_code"] = "KTPHGerMed"
    for row in fake_db.posting_codes:
        if row["code"] == "KTPHGerMed":
            row["supports_secretary_events"] = True
    event_id = str(uuid4())
    event = fake_db._event(event_id, "KTPHGerMed", "Unmapped External Event", date(2026, 5, 18))  # noqa: SLF001
    event["created_by_role"] = "secretary"
    fake_db.events.append(event)
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_external_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert event_id in ids


def test_external_attendance_creates_external_record_only() -> None:
    fake_db = FakeResidentSession()
    before_external = len(fake_db.external_attendance)
    before_native = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [fake_db.event_id]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["submitted"] == 1
    assert all("created_by_role" not in row for row in payload["submitted_events"])
    assert len(fake_db.external_attendance) == before_external + 1
    assert len(fake_db.attendance) == before_native


def test_external_duplicate_attendance_is_rejected() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [fake_db.second_event_id]},
    )

    assert response.status_code == 409


def test_external_cannot_submit_attendance_for_event_outside_current_posting() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [fake_db.other_posting_event_id]},
    )

    assert response.status_code == 422


def test_external_cannot_submit_secretary_event_when_support_disabled() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_residents[0]["current_nhg_posting_code"] = "KTPHGerMed"
    event_id = str(uuid4())
    event = fake_db._event(event_id, "KTPHGerMed", "Secretary Teaching", date(2026, 5, 18))  # noqa: SLF001
    event["created_by_role"] = "secretary"
    fake_db.events.append(event)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [event_id]},
    )

    assert response.status_code == 422


def test_external_weekend_non_exception_stores_and_returns_warning() -> None:
    fake_db = FakeResidentSession()
    before = len(fake_db.external_attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [fake_db.weekend_event_id]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["submitted"] == 1
    assert payload["compliance_warning"].startswith("1 session(s) submitted on a weekend")
    assert len(fake_db.external_attendance) == before + 1
