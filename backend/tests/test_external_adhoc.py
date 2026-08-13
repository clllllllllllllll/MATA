from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import resident
from tests.auth_identity_test_helpers import install_stub_header_identity_middleware
from tests.resident_fakes import FakeResidentSession


def _client(
    fake_db: FakeResidentSession,
    *,
    raise_server_exceptions: bool = True,
    rollback_on_error: bool = False,
) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    install_stub_header_identity_middleware(app)

    async def _db_override():
        try:
            yield fake_db
        except Exception:
            if rollback_on_error:
                await fake_db.rollback()
            raise

    app.dependency_overrides[resident.get_db_session] = _db_override
    app.include_router(resident.router)
    return TestClient(
        app,
        raise_server_exceptions=raise_server_exceptions,
    )


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
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["event"]["is_adhoc"] is True
    assert "created_by_role" not in payload["event"]
    assert payload["attendance"]["external_resident_id"] == fake_db.external_resident_id
    assert len(fake_db.events) == before_events + 1
    assert len(fake_db.external_attendance) == before_attendance + 1
    assert len(fake_db.external_attendance_lock_calls) == 1
    assert len(fake_db.adhoc_helper_calls) == 1
    assert fake_db.adhoc_helper_calls[0]["teaching_name"] == (
        "Department/Programme Teaching [1h]"
    )
    assert str(fake_db.adhoc_helper_calls[0]["duration_hours"]) == "1.00"
    assert fake_db.adhoc_helper_calls[0]["session_type_id"] is None
    assert set(fake_db.adhoc_helper_calls[0]) == {
        "posting_code",
        "attended_posting_code",
        "attended_teaching_name",
        "teaching_name",
        "details_of_session",
        "event_date",
        "start_time",
        "end_time",
        "duration_hours",
        "session_type_id",
    }


def test_external_adhoc_commit_failure_rolls_back_event_and_attendance_and_returns_no_success(
    monkeypatch,
) -> None:
    fake_db = FakeResidentSession(today=date(2026, 5, 18))
    initial = fake_db.transaction_state()
    fake_db.fail_next_commit()
    cache_calls: list[dict] = []
    monkeypatch.setattr(
        "app.services.resident_submission.invalidate_resident_caches",
        lambda **scope: cache_calls.append(scope),
    )
    client = _client(
        fake_db,
        raise_server_exceptions=False,
        rollback_on_error=True,
    )

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_external_headers(fake_db),
        json={
            "date": "2026-05-18",
            "start_time": "14:00",
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"
    assert "event" not in response.json()
    assert "attendance" not in response.json()
    assert fake_db.commits == 1
    assert fake_db.rollbacks == 1
    assert fake_db.transaction_state() == initial
    assert len(fake_db.adhoc_helper_calls) == 1
    assert cache_calls == []


def test_external_adhoc_rejects_overlap_before_calling_atomic_helper() -> None:
    fake_db = FakeResidentSession()
    existing_event = next(
        row for row in fake_db.events if row["id"] == fake_db.second_event_id
    )
    events_before = [dict(row) for row in fake_db.events]
    attendance_before = [dict(row) for row in fake_db.external_attendance]
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_external_headers(fake_db),
        json={
            "date": existing_event["event_date"].isoformat(),
            "start_time": existing_event["start_time"].isoformat(),
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Attendance overlaps an earlier accepted event"
    assert fake_db.events == events_before
    assert fake_db.external_attendance == attendance_before
    assert len(fake_db.external_attendance_lock_calls) == 1
    assert fake_db.adhoc_helper_calls == []


def test_external_adhoc_options_use_date_matched_posting_schedule() -> None:
    fake_db = FakeResidentSession()
    fake_db.teaching_targets = []
    fake_db.external_residents[0]["current_nhg_posting_code"] = "TTSHCardio"
    fake_db.external_resident_postings = [
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "posting_code": "KTPHGerMed",
            "start_date": date(2026, 5, 18),
            "end_date": date(2026, 5, 18),
            "is_current": True,
        }
    ]
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_external_headers(fake_db),
        params={"date": "2026-05-18"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["posting_code"] == "KTPHGerMed"
    assert payload["reporting_period_id"] == fake_db.period_id
    assert payload["r_year"] is None
    assert payload["options"][0]["teaching_name"] == "Department/Programme Teaching [1h]"
    assert payload["options"][0]["session_type_id"] is None


def test_external_adhoc_options_reject_client_selected_non_schedule_posting() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_residents[0]["current_nhg_posting_code"] = "KTPHGerMed"
    fake_db.external_resident_postings = [
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "posting_code": "KTPHGerMed",
            "start_date": date(2026, 5, 18),
            "end_date": date(2026, 5, 18),
            "is_current": True,
        }
    ]
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_external_headers(fake_db),
        params={"date": "2026-05-18", "attended_posting_code": "TTSHCardio"},
    )

    assert response.status_code == 422
    assert "attended_posting_code" in response.json()["detail"]


def test_external_adhoc_options_ignore_future_period() -> None:
    fake_db = FakeResidentSession()
    future_period_id = str(uuid4())
    fake_db.reporting_periods.append(
        {
            "id": future_period_id,
            "label": "Future Test Period",
            "start_date": date(2099, 1, 1),
            "end_date": date(2099, 6, 30),
            "status": "active",
            "activate_on": None,
            "deactivate_on": None,
        }
    )
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_external_headers(fake_db),
        params={"date": "2026-05-18"},
    )

    assert response.status_code == 200
    assert len(response.json()["options"]) == 1
    option = response.json()["options"][0]
    assert option["teaching_name"] == "Department/Programme Teaching [1h]"
    assert option["session_type_id"] is None
    assert str(option["duration_hours"]) == "1.00"


def test_external_adhoc_options_no_schedule_row_returns_unavailable() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_external_headers(fake_db),
        params={"date": "2026-04-15"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["reason"] == "posting_unavailable"
    assert payload["options"] == []


def test_external_adhoc_overlapping_schedule_rows_fail_closed() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings.append(
        {
            **fake_db.external_resident_postings[0],
            "id": str(uuid4()),
            "posting_code": "TTSHNeuro",
        }
    )
    before_events = len(fake_db.events)
    before_external_attendance = len(fake_db.external_attendance)
    client = _client(fake_db)

    options_response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_external_headers(fake_db),
        params={"date": "2026-05-18"},
    )
    submit_response = client.post(
        "/resident/adhoc-teaching",
        headers=_external_headers(fake_db),
        json={"date": "2026-05-18", "start_time": "10:00"},
    )

    assert options_response.status_code == 200
    assert options_response.json()["available"] is False
    assert options_response.json()["reason"] == "posting_unavailable"
    assert submit_response.status_code == 422
    assert "Non-NHG Resident posting" in submit_response.json()["detail"]
    assert len(fake_db.events) == before_events
    assert len(fake_db.external_attendance) == before_external_attendance


def test_external_adhoc_missing_schedule_error_uses_non_nhg_label() -> None:
    fake_db = FakeResidentSession()
    before_events = len(fake_db.events)
    before_external_attendance = len(fake_db.external_attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_external_headers(fake_db),
        json={
            "date": "2026-04-15",
            "start_time": "10:00",
        },
    )

    assert response.status_code == 422
    assert "Non-NHG Resident posting" in response.json()["detail"]
    assert len(fake_db.events) == before_events
    assert len(fake_db.external_attendance) == before_external_attendance


def test_external_adhoc_uses_date_matched_posting_schedule() -> None:
    fake_db = FakeResidentSession()
    fake_db.teaching_targets = []
    fake_db.external_residents[0]["current_nhg_posting_code"] = "TTSHCardio"
    fake_db.external_resident_postings = [
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "posting_code": "KTPHGerMed",
            "start_date": date(2026, 5, 18),
            "end_date": date(2026, 5, 18),
            "is_current": True,
        }
    ]
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_external_headers(fake_db),
        json={
            "date": "2026-05-18",
            "start_time": "10:00",
        },
    )

    assert response.status_code == 200
    assert response.json()["event"]["posting_code"] == "KTPHGerMed"


def test_external_adhoc_rejects_client_selected_non_schedule_posting() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_residents[0]["current_nhg_posting_code"] = "KTPHGerMed"
    fake_db.external_resident_postings = [
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "posting_code": "KTPHGerMed",
            "start_date": date(2026, 5, 18),
            "end_date": date(2026, 5, 18),
            "is_current": True,
        }
    ]
    before_native_attendance = len(fake_db.attendance)
    before_external_attendance = len(fake_db.external_attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_external_headers(fake_db),
        json={
            "date": "2026-05-18",
            "start_time": "10:00",
            "attended_posting_code": "TTSHCardio",
        },
    )

    assert response.status_code == 422
    assert len(fake_db.external_attendance) == before_external_attendance
    assert len(fake_db.attendance) == before_native_attendance


def test_external_adhoc_works_without_teaching_target() -> None:
    fake_db = FakeResidentSession()
    before_events = len(fake_db.events)
    before_attendance = len(fake_db.external_attendance)
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
    fake_db.teaching_targets = []
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_external_headers(fake_db),
        json={
            "date": "2026-05-18",
            "start_time": "10:00",
        },
    )

    assert response.status_code == 200
    assert response.json()["event"]["teaching_name"] == "Department/Programme Teaching [1h]"
    assert len(fake_db.events) == before_events + 1
    assert len(fake_db.external_attendance) == before_attendance + 1


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
        },
    )

    assert response.status_code == 200
    assert response.json()["compliance_warning"].startswith("1 session(s) submitted on a weekend")
