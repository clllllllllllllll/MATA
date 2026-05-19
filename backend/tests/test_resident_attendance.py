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


def test_attendance_submission_creates_attendance_record() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.event_id]},
    )

    assert response.status_code == 200
    assert response.json()["submitted"] == 1
    assert any(
        row["resident_id"] == fake_db.resident_id
        and row["teaching_event_id"] == fake_db.event_id
        and row["posting_code"] == "TTSHCardio"
        for row in fake_db.attendance
    )


def test_duplicate_attendance_is_rejected() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.second_event_id]},
    )

    assert response.status_code == 409


def test_attendance_outside_posting_window_is_rejected() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.other_posting_event_id]},
    )

    assert response.status_code == 422


def test_weekend_non_exception_attendance_is_stored_with_warning() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.weekend_event_id]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["submitted"] == 1
    assert payload["compliance_warning"].startswith("1 session(s) submitted on a weekend")
    assert any(row["teaching_event_id"] == fake_db.weekend_event_id for row in fake_db.attendance)


def test_resident_cannot_delete_another_residents_attendance() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.delete(
        f"/resident/attendance/{fake_db.other_attendance_id}",
        headers=_headers(fake_db),
    )

    assert response.status_code == 404


def test_deleted_attendance_no_longer_excludes_event_visibility() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    delete_response = client.delete(
        f"/resident/attendance/{fake_db.existing_attendance_id}",
        headers=_headers(fake_db),
    )
    events_response = client.get("/resident/events", headers=_headers(fake_db))

    assert delete_response.status_code == 200
    assert delete_response.json()["removed_count"] == 1
    ids = {row["id"] for row in events_response.json()["events"]}
    assert fake_db.second_event_id in ids


def test_future_event_attendance_is_rejected() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.future_event_id]},
    )

    assert response.status_code == 422


def test_inactive_posting_status_is_rejected_for_attendance() -> None:
    fake_db = FakeResidentSession()
    fake_db.resident_postings[0]["status"] = "loa_non_working"
    fake_db.events[0]["event_date"] = date(2026, 5, 18)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.event_id]},
    )

    assert response.status_code == 422
