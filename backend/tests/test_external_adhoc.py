from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import resident
from tests.auth_identity_test_helpers import install_stub_header_identity_middleware
from tests.resident_fakes import FakeResidentSession


def _client(fake_db: FakeResidentSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    install_stub_header_identity_middleware(app)

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


def test_external_adhoc_options_use_date_matched_posting_schedule() -> None:
    fake_db = FakeResidentSession()
    fake_db.catalogue.append(
        fake_db._catalogue(  # noqa: SLF001
            "KTPH Case Teaching",
            "KTPHGerMed",
            fake_db.session_type_id,
            Decimal("1.0"),
        )
    )
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
    assert payload["r_year"] is None
    option_names = {row["teaching_name"] for row in payload["options"]}
    assert "KTPH Case Teaching" in option_names


def test_external_adhoc_options_filter_by_selected_attended_posting() -> None:
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

    assert response.status_code == 200
    payload = response.json()
    assert payload["posting_code"] == "KTPHGerMed"
    assert payload["selected_attended_posting_code"] == "TTSHCardio"
    option_names = {row["teaching_name"] for row in payload["options"]}
    assert "Journal Club" in option_names


def test_external_adhoc_options_do_not_leak_future_uat_catalogue() -> None:
    fake_db = FakeResidentSession()
    uat_period_id = str(uuid4())
    fake_db.reporting_periods.append(
        {
            "id": uat_period_id,
            "label": "UAT semantic test 2099",
            "start_date": date(2099, 1, 1),
            "end_date": date(2099, 6, 30),
            "status": "active",
            "activate_on": None,
            "deactivate_on": None,
        }
    )
    uat_row = fake_db._catalogue(  # noqa: SLF001
        "UAT-only teaching",
        "TTSHCardio",
        fake_db.session_type_id,
        Decimal("1.0"),
    )
    uat_row["reporting_period_id"] = uat_period_id
    fake_db.catalogue.append(uat_row)
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_external_headers(fake_db),
        params={"date": "2026-05-18"},
    )

    assert response.status_code == 200
    assert "UAT-only teaching" not in {row["teaching_name"] for row in response.json()["options"]}


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
            "teaching_name": "Journal Club",
        },
    )

    assert response.status_code == 422
    assert "Non-NHG Resident posting" in response.json()["detail"]
    assert len(fake_db.events) == before_events
    assert len(fake_db.external_attendance) == before_external_attendance


def test_external_adhoc_uses_date_matched_posting_schedule() -> None:
    fake_db = FakeResidentSession()
    fake_db.catalogue.append(
        fake_db._catalogue(  # noqa: SLF001
            "Journal Club",
            "KTPHGerMed",
            fake_db.session_type_id,
            Decimal("1.0"),
        )
    )
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
            "teaching_name": "Journal Club",
        },
    )

    assert response.status_code == 200
    assert response.json()["event"]["posting_code"] == "KTPHGerMed"


def test_external_adhoc_uses_attended_posting_options_but_writes_external_only() -> None:
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
            "teaching_name": "Journal Club",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["event"]["posting_code"] == "KTPHGerMed"
    assert payload["event"]["teaching_name"] == "Journal Club"
    assert len(fake_db.external_attendance) == before_external_attendance + 1
    assert len(fake_db.attendance) == before_native_attendance


def test_external_adhoc_requires_teaching_name_catalogue() -> None:
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

    assert response.status_code == 422
    assert "catalogue-backed" in response.json()["detail"].lower()
    assert len(fake_db.events) == before_events
    assert len(fake_db.external_attendance) == before_attendance


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
