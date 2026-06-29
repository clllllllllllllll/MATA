from __future__ import annotations

from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import resident
from tests.resident_fakes import FakeResidentSession


ADHOC_FIXTURE_TODAY = date(2026, 5, 18)


def _fake_db() -> FakeResidentSession:
    return FakeResidentSession(today=ADHOC_FIXTURE_TODAY)


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
    fake_db = _fake_db()
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


def test_adhoc_options_are_date_first_and_catalogue_backed() -> None:
    fake_db = _fake_db()
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_headers(fake_db),
        params={"date": "2026-05-18"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["posting_code"] == "TTSHCardio"
    assert payload["r_year"] == "R2"
    option_names = {row["teaching_name"] for row in payload["options"]}
    assert "Journal Club" in option_names
    assert "" not in option_names
    assert "created_by_role" not in payload["options"][0]


def test_adhoc_options_use_resident_posting_r_year_not_resident_r_year() -> None:
    fake_db = _fake_db()
    fake_db.residents[0]["r_year"] = "R3"
    fake_db.catalogue[0]["r_year"] = "R2"
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_headers(fake_db),
        params={"date": "2026-05-18"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["r_year"] == "R2"
    assert any(row["teaching_name"] == "Journal Club" for row in payload["options"])


def test_adhoc_options_public_holiday_is_blocked() -> None:
    fake_db = _fake_db()
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_headers(fake_db),
        params={"date": "2026-05-01"},
    )

    assert response.status_code == 422


def test_adhoc_options_no_posting_returns_unavailable_state() -> None:
    fake_db = _fake_db()
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_headers(fake_db),
        params={"date": "2030-01-15"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["reason"] == "posting_unavailable"
    assert payload["options"] == []


def test_adhoc_options_compatibility_alias_accepts_teaching_date() -> None:
    fake_db = _fake_db()
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching/options",
        headers=_headers(fake_db),
        params={"teaching_date": "2026-05-18"},
    )

    assert response.status_code == 200
    assert response.json()["posting_code"] == "TTSHCardio"


def test_adhoc_options_compatibility_alias_accepts_date() -> None:
    fake_db = _fake_db()
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching/options",
        headers=_headers(fake_db),
        params={"date": "2026-05-18"},
    )

    assert response.status_code == 200
    assert response.json()["posting_code"] == "TTSHCardio"


def test_adhoc_teaching_stores_optional_details_of_session() -> None:
    fake_db = _fake_db()
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "teaching_date": "2026-05-18",
            "start_time": "10:00",
            "teaching_name": "Journal Club",
            "details_of_session": "Ward case discussion",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["event"]["details_of_session"] == "Ward case discussion"
    assert "created_by_role" not in payload["event"]
    assert "created_for_programme_code" not in payload["event"]
    created_event = next(row for row in fake_db.events if row["id"] == payload["event"]["id"])
    assert created_event["details_of_session"] == "Ward case discussion"


def test_adhoc_teaching_rejects_frontend_posting_code_authority() -> None:
    fake_db = _fake_db()
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "teaching_date": "2026-05-18",
            "posting_code": "TTSHNeuro",
            "start_time": "10:00",
            "teaching_name": "Journal Club",
        },
    )

    assert response.status_code == 422


def test_adhoc_teaching_on_public_holiday_returns_422_and_writes_nothing() -> None:
    fake_db = _fake_db()
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
    fake_db = _fake_db()
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


def test_adhoc_teaching_rejects_when_no_posting_exists_for_date() -> None:
    fake_db = _fake_db()
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "date": "2030-01-15",
            "start_time": "10:00",
            "teaching_name": "Journal Club",
        },
    )

    assert response.status_code == 422
    assert "no active resident posting" in response.json()["detail"].lower()


def test_adhoc_weekend_non_exception_returns_warning() -> None:
    fake_db = _fake_db()
    weekend_offset = (fake_db.today.weekday() - 5) % 7
    weekend_date = fake_db.today - timedelta(days=weekend_offset)
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "date": weekend_date.isoformat(),
            "start_time": "10:00",
            "teaching_name": "Journal Club",
        },
    )

    assert response.status_code == 200
    assert response.json()["compliance_warning"].startswith(
        "1 session(s) submitted on a weekend"
    )


def test_adhoc_teaching_is_blocked_when_reporting_period_is_inactive() -> None:
    fake_db = _fake_db()
    fake_db.reporting_periods[0]["status"] = "inactive"
    before_events = len(fake_db.events)
    before_attendance = len(fake_db.attendance)
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
    assert response.json()["detail"] == "No active reporting period is available"
    assert len(fake_db.events) == before_events
    assert len(fake_db.attendance) == before_attendance


def test_adhoc_teaching_uses_effectively_active_scheduled_reporting_period() -> None:
    fake_db = _fake_db()
    fake_db.reporting_periods[0]["status"] = "inactive"
    fake_db.reporting_periods[0]["activate_on"] = fake_db.today - timedelta(days=1)
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
    assert response.json()["event"]["is_adhoc"] is True
