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
    }


def test_events_returns_posting_schedule_unavailable_when_no_current_posting_exists() -> None:
    fake_db = FakeResidentSession()
    fake_db.resident_postings = []
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"] == []
    assert payload["reason"] == "posting_schedule_unavailable"
    assert payload["ad_hoc_allowed"] is False


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
    payload = response.json()
    ids = {row["id"] for row in payload["events"]}
    assert fake_db.global_event_id in ids
    global_event = next(row for row in payload["events"] if row["id"] == fake_db.global_event_id)
    assert global_event["is_global"] is True


def test_events_return_empty_reason_when_no_open_reporting_period_exists() -> None:
    fake_db = FakeResidentSession()
    fake_db.reporting_periods = []
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"] == []
    assert payload["reason"] == "reporting_period_unavailable"
    assert payload["ad_hoc_allowed"] is False


def test_events_return_empty_and_allow_adhoc_when_no_eligible_scheduled_events_exist() -> None:
    fake_db = FakeResidentSession()
    fake_db.events = []
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"] == []
    assert payload["reason"] == "no_eligible_scheduled_events"
    assert payload["ad_hoc_allowed"] is True


def test_events_do_not_clamp_on_supports_secretary_events_flag_for_native_resident() -> None:
    fake_db = FakeResidentSession()
    fake_db.resident_postings[0]["posting_code"] = "KTPHGerMed"
    fake_db.catalogue.append(
        {
            "keyword": "KTPH Teaching",
            "posting_code": "KTPHGerMed",
            "programme_code": "GRM",
            "r_year": "R2",
            "reporting_period_id": fake_db.period_id,
            "session_type_id": fake_db.session_type_id,
            "session_type": "KTPH Teaching [1.0h]",
            "duration_hours": 1.0,
            "is_tracked": True,
        }
    )
    fake_db.events.append(
        fake_db._event(str(uuid4()), "KTPHGerMed", "KTPH Teaching", fake_db.today - timedelta(days=1))  # noqa: SLF001
    )
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    payload = response.json()
    assert any(row["posting_code"] == "KTPHGerMed" for row in payload["events"])
    posting_capabilities = {
        row["posting_code"]: row["supports_secretary_events"]
        for row in payload["posting_capabilities"]
    }
    assert posting_capabilities["KTPHGerMed"] is False


def test_events_reject_non_resident_role() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get(
        "/resident/events",
        headers={"X-User-Role": "admin", "X-User-Id": str(uuid4())},
    )

    assert response.status_code == 403


def test_events_use_open_period_event_window_not_today_posting_only() -> None:
    fake_db = FakeResidentSession()
    fake_db.reporting_periods = [
        {
            "id": fake_db.period_id,
            "label": "Jul-Dec 2025",
            "start_date": date(2025, 7, 1),
            "end_date": date(2025, 12, 31),
            "status": "open",
        }
    ]
    fake_db.resident_postings = [
        {
            "resident_id": fake_db.resident_id,
            "reporting_period_id": fake_db.period_id,
            "posting_code": "TTSHGerMed",
            "r_year": "ALL",
            "start_date": date(2025, 7, 8),
            "end_date": date(2025, 7, 31),
            "status": "active",
        }
    ]
    fake_db.residents[0]["programme_code"] = "GERI"
    fake_db.posting_codes.append({"code": "TTSHGerMed", "supports_secretary_events": False})
    fake_db.catalogue = [
        {
            "keyword": "GERI Demo Row 22",
            "posting_code": "TTSHGerMed",
            "programme_code": "GERI",
            "r_year": "ALL",
            "reporting_period_id": fake_db.period_id,
            "session_type_id": fake_db.session_type_id,
            "session_type": "GERI Session [1.0h]",
            "duration_hours": 1.0,
            "is_tracked": True,
        }
    ]
    fake_db.attendance = []
    valid_event_id = str(uuid4())
    outside_window_id = str(uuid4())
    fake_db.events = [
        fake_db._event(valid_event_id, "TTSHGerMed", "GERI Demo Row 22", date(2025, 7, 15)),  # noqa: SLF001
        fake_db._event(outside_window_id, "TTSHGerMed", "GERI Demo Row 22", date(2025, 7, 5)),  # noqa: SLF001
    ]
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    payload = response.json()
    returned_ids = {row["id"] for row in payload["events"]}
    assert valid_event_id in returned_ids
    assert outside_window_id not in returned_ids
    posting_capabilities = {
        row["posting_code"]: row["supports_secretary_events"]
        for row in payload["posting_capabilities"]
    }
    assert "TTSHGerMed" in posting_capabilities
    assert all("(from " not in row["posting_code"] for row in payload["posting_capabilities"])


def test_events_exclude_submitted_event_in_open_period_window() -> None:
    fake_db = FakeResidentSession()
    fake_db.reporting_periods = [
        {
            "id": fake_db.period_id,
            "label": "Jul-Dec 2025",
            "start_date": date(2025, 7, 1),
            "end_date": date(2025, 12, 31),
            "status": "open",
        }
    ]
    fake_db.resident_postings = [
        {
            "resident_id": fake_db.resident_id,
            "reporting_period_id": fake_db.period_id,
            "posting_code": "TTSHGerMed",
            "r_year": "ALL",
            "start_date": date(2025, 7, 8),
            "end_date": date(2025, 7, 31),
            "status": "active",
        }
    ]
    fake_db.residents[0]["programme_code"] = "GERI"
    fake_db.posting_codes.append({"code": "TTSHGerMed", "supports_secretary_events": True})
    fake_db.catalogue = [
        {
            "keyword": "GERI Demo Row 22",
            "posting_code": "TTSHGerMed",
            "programme_code": "GERI",
            "r_year": "ALL",
            "reporting_period_id": fake_db.period_id,
            "session_type_id": fake_db.session_type_id,
            "session_type": "GERI Session [1.0h]",
            "duration_hours": 1.0,
            "is_tracked": True,
        }
    ]
    submitted_event_id = str(uuid4())
    fake_db.events = [
        fake_db._event(submitted_event_id, "TTSHGerMed", "GERI Demo Row 22", date(2025, 7, 15)),  # noqa: SLF001
    ]
    fake_db.attendance = [
        {
            "id": str(uuid4()),
            "resident_id": fake_db.resident_id,
            "teaching_event_id": submitted_event_id,
            "status": "submitted",
            "posting_code": "TTSHGerMed",
        }
    ]
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"] == []
    assert payload["reason"] == "no_eligible_scheduled_events"
