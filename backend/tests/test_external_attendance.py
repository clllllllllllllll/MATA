from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.auth_stub import AuthIdentity
from app.middleware.errors import install_error_handlers
from app.routers import resident
from tests.auth_identity_test_helpers import install_stub_header_identity_middleware
from tests.resident_fakes import FakeResidentSession


def _client(
    fake_db: FakeResidentSession,
    *,
    identity: AuthIdentity | None = None,
) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    install_stub_header_identity_middleware(app, default_identity=identity)

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


def test_external_events_use_date_matched_posting_schedule() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_residents[0]["current_nhg_posting_code"] = "TTSHCardio"
    fake_db.external_resident_postings = [
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "posting_code": "TTSHNeuro",
            "start_date": fake_db.today - date.resolution,
            "end_date": fake_db.today + date.resolution,
            "is_current": True,
        }
    ]
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_external_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.other_posting_event_id in ids
    assert fake_db.event_id not in ids


def test_external_events_accept_verified_external_identity_without_raw_headers() -> None:
    fake_db = FakeResidentSession()
    client = _client(
        fake_db,
        identity=AuthIdentity(
            role="external_resident",
            subject_id=fake_db.external_resident_id,
            home_cluster="NUH",
        ),
    )

    response = client.get("/resident/events")

    assert response.status_code == 200
    assert fake_db.event_id in {row["id"] for row in response.json()["events"]}


def test_external_events_hidden_when_supports_secretary_events_false() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_residents[0]["current_nhg_posting_code"] = "KTPHGerMed"
    fake_db.external_resident_postings = [
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "posting_code": "KTPHGerMed",
            "start_date": date(2026, 5, 1),
            "end_date": None,
            "is_current": True,
        }
    ]
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
    fake_db.external_resident_postings = [
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "posting_code": "KTPHGerMed",
            "start_date": date(2026, 5, 1),
            "end_date": None,
            "is_current": True,
        }
    ]
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


def test_external_null_role_event_is_hidden_and_cannot_be_submitted() -> None:
    fake_db = FakeResidentSession()
    event_id = str(uuid4())
    event = fake_db._event(  # noqa: SLF001
        event_id,
        "TTSHCardio",
        "Legacy Teaching",
        fake_db.today - date.resolution,
    )
    event["created_by_role"] = None
    fake_db.events.append(event)
    client = _client(fake_db)

    list_response = client.get("/resident/events", headers=_external_headers(fake_db))
    submit_response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [event_id]},
    )

    assert list_response.status_code == 200
    assert event_id not in {row["id"] for row in list_response.json()["events"]}
    assert submit_response.status_code == 422
    assert all(row["teaching_event_id"] != event_id for row in fake_db.external_attendance)


def test_external_programme_owned_event_is_hidden_and_cannot_be_submitted() -> None:
    fake_db = FakeResidentSession()
    event_id = str(uuid4())
    event = fake_db._event(  # noqa: SLF001
        event_id,
        "TTSHCardio",
        "Programme Teaching",
        fake_db.today - date.resolution,
    )
    event["created_for_programme_code"] = "GERI"
    fake_db.events.append(event)
    client = _client(fake_db)

    list_response = client.get("/resident/events", headers=_external_headers(fake_db))
    submit_response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [event_id]},
    )

    assert list_response.status_code == 200
    assert event_id not in {row["id"] for row in list_response.json()["events"]}
    assert submit_response.status_code == 422
    assert all(row["teaching_event_id"] != event_id for row in fake_db.external_attendance)


def test_external_attendance_uses_event_date_matched_posting_schedule() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_residents[0]["current_nhg_posting_code"] = "TTSHCardio"
    event = next(row for row in fake_db.events if row["id"] == fake_db.other_posting_event_id)
    fake_db.external_resident_postings = [
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "posting_code": "TTSHNeuro",
            "start_date": event["event_date"],
            "end_date": event["event_date"],
            "is_current": True,
        }
    ]
    before_external = len(fake_db.external_attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [fake_db.other_posting_event_id]},
    )

    assert response.status_code == 200
    assert len(fake_db.external_attendance) == before_external + 1
    assert fake_db.external_attendance[-1]["posting_code"] == "TTSHNeuro"


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
    fake_db.external_resident_postings = [
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "posting_code": "KTPHGerMed",
            "start_date": date(2026, 5, 1),
            "end_date": None,
            "is_current": True,
        }
    ]
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


def test_external_resident_can_remove_own_external_attendance() -> None:
    fake_db = FakeResidentSession()
    before_native = list(fake_db.attendance)
    client = _client(fake_db)

    response = client.delete(
        f"/resident/attendance/{fake_db.external_existing_attendance_id}",
        headers=_external_headers(fake_db),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "removed"
    assert response.json()["removed_count"] == 1
    assert next(
        row
        for row in fake_db.external_attendance
        if row["id"] == fake_db.external_existing_attendance_id
    )["status"] == "removed"
    assert fake_db.attendance == before_native


def test_external_resident_cannot_remove_another_external_residents_attendance() -> None:
    fake_db = FakeResidentSession()
    other_attendance_id = str(uuid4())
    fake_db.external_attendance.append(
        {
            "id": other_attendance_id,
            "external_resident_id": fake_db.other_external_resident_id,
            "teaching_event_id": fake_db.second_event_id,
            "status": "submitted",
            "posting_code": "TTSHCardio",
            "submitted_at": fake_db.now,
        }
    )
    client = _client(fake_db)

    response = client.delete(
        f"/resident/attendance/{other_attendance_id}",
        headers=_external_headers(fake_db),
    )

    assert response.status_code == 404
    assert next(row for row in fake_db.external_attendance if row["id"] == other_attendance_id)[
        "status"
    ] == "submitted"
