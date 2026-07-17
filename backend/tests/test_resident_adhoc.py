from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import resident
from tests.auth_identity_test_helpers import install_stub_header_identity_middleware
from tests.resident_fakes import FakeResidentSession


ADHOC_FIXTURE_TODAY = date(2026, 5, 18)


def _fake_db() -> FakeResidentSession:
    return FakeResidentSession(today=ADHOC_FIXTURE_TODAY)


def _client(fake_db: FakeResidentSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    install_stub_header_identity_middleware(app)

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


def _configure_geri_tts_ger_med_run_club(
    fake_db: FakeResidentSession,
    *,
    catalogue_r_year: str = "ALL",
    target_r_year: str = "ALL",
    target_posting_code: str = "TTSHGerMed",
) -> None:
    fake_db.residents[0]["programme_code"] = "GERI"
    fake_db.residents[0]["r_year"] = "R3"
    fake_db.resident_postings[0]["posting_code"] = "TTSHGerMed"
    fake_db.resident_postings[0]["r_year"] = "R3"
    if not any(row["code"] == "TTSHGerMed" for row in fake_db.posting_codes):
        fake_db.posting_codes.append(
            {
                "code": "TTSHGerMed",
                "display_name": "TTSH Geriatric Medicine",
                "institution": "TTSH",
                "supports_secretary_events": True,
            }
        )
    fake_db.catalogue.append(
        fake_db._catalogue(  # noqa: SLF001
            "Run Club",
            "TTSHGerMed",
            fake_db.adhoc_session_type_id,
            Decimal("1.0"),
            programme_code="GERI",
            r_year=catalogue_r_year,
            session_type="Department/Programme Teaching [1h]",
        )
    )
    fake_db.teaching_targets.append(
        fake_db._target(  # noqa: SLF001
            target_posting_code,
            fake_db.adhoc_session_type_id,
            programme_code="GERI",
            r_year=target_r_year,
        )
    )


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
    assert payload["event"]["teaching_name"] == "Department/Programme Teaching [1h]"
    assert payload["event"]["session_type_id"] == fake_db.adhoc_session_type_id
    assert payload["event"]["is_adhoc"] is True
    assert payload["attendance"]["posting_code"] == "TTSHCardio"
    assert any(row["is_adhoc"] for row in fake_db.events)


def test_adhoc_teaching_accepts_all_r_year_catalogue_and_target_for_assigned_posting() -> None:
    fake_db = _fake_db()
    _configure_geri_tts_ger_med_run_club(fake_db)
    before_attendance = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "teaching_date": "2026-05-18",
            "start_time": "16:15",
            "attended_posting_code": "TTSHGerMed",
            "teaching_name": "Run Club",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["event"]["posting_code"] == "TTSHGerMed"
    assert payload["event"]["teaching_name"] == "Department/Programme Teaching [1h]"
    assert payload["event"]["session_type_id"] == fake_db.adhoc_session_type_id
    assert payload["attendance"]["posting_code"] == "TTSHGerMed"
    assert len(fake_db.attendance) == before_attendance + 1


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


def test_adhoc_options_include_attended_posting_options() -> None:
    fake_db = _fake_db()
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_headers(fake_db),
        params={"date": "2026-05-18"},
    )

    assert response.status_code == 200
    payload = response.json()
    posting_codes = {
        row["posting_code"] for row in payload["attended_posting_options"]
    }
    assert {"TTSHCardio", "TTSHNeuro"} <= posting_codes
    assert payload["selected_attended_posting_code"] == "TTSHCardio"


def test_adhoc_options_filter_teaching_by_selected_attended_posting() -> None:
    fake_db = _fake_db()
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_headers(fake_db),
        params={"date": "2026-05-18", "attended_posting_code": "TTSHNeuro"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["posting_code"] == "TTSHCardio"
    assert payload["selected_attended_posting_code"] == "TTSHNeuro"
    option_names = {row["teaching_name"] for row in payload["options"]}
    assert "Skills Teaching" in option_names
    assert "Journal Club" not in option_names


def test_adhoc_teaching_uses_selected_attended_posting_for_catalogue_evidence() -> None:
    fake_db = _fake_db()
    before_attendance = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "date": "2026-05-18",
            "start_time": "10:00",
            "attended_posting_code": "TTSHNeuro",
            "teaching_name": "Skills Teaching",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["event"]["posting_code"] == "TTSHCardio"
    assert payload["event"]["teaching_name"] == "Department/Programme Teaching [1h]"
    assert payload["event"]["session_type_id"] == fake_db.adhoc_session_type_id
    assert len(fake_db.attendance) == before_attendance + 1


def test_adhoc_teaching_selected_attended_posting_does_not_replace_assigned_target() -> None:
    fake_db = _fake_db()
    fake_db.teaching_targets = []
    before_events = len(fake_db.events)
    before_attendance = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "date": "2026-05-18",
            "start_time": "10:00",
            "attended_posting_code": "TTSHNeuro",
            "teaching_name": "Skills Teaching",
        },
    )

    assert response.status_code == 422
    assert "department/programme teaching [1h]" in response.json()["detail"].lower()
    assert len(fake_db.events) == before_events
    assert len(fake_db.attendance) == before_attendance


def test_adhoc_teaching_rejects_unknown_attended_posting_code() -> None:
    fake_db = _fake_db()
    before_events = len(fake_db.events)
    before_attendance = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "date": "2026-05-18",
            "start_time": "10:00",
            "attended_posting_code": "TTSHMissing",
            "teaching_name": "Skills Teaching",
        },
    )

    assert response.status_code == 422
    assert "attended" in response.json()["detail"].lower()
    assert len(fake_db.events) == before_events
    assert len(fake_db.attendance) == before_attendance


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
    assert payload["reason"] == "active_reporting_period_unavailable"
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
    assert payload["event"]["teaching_name"] == "Department/Programme Teaching [1h]"
    assert payload["event"]["details_of_session"] == "Ward case discussion"
    assert "created_by_role" not in payload["event"]
    assert "created_for_programme_code" not in payload["event"]
    created_event = next(row for row in fake_db.events if row["id"] == payload["event"]["id"])
    assert created_event["details_of_session"] == "Ward case discussion"


def test_adhoc_teaching_rejects_uncatalogued_teaching_name() -> None:
    fake_db = _fake_db()
    before_events = len(fake_db.events)
    before_attendance = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "teaching_date": "2026-05-18",
            "start_time": "10:00",
            "teaching_name": "Completely New Topic",
        },
    )

    assert response.status_code == 422
    assert "catalogue-backed" in response.json()["detail"].lower()
    assert len(fake_db.events) == before_events
    assert len(fake_db.attendance) == before_attendance


def test_adhoc_teaching_rejects_untracked_catalogue_teaching_name() -> None:
    fake_db = _fake_db()
    fake_db.catalogue[0]["is_tracked"] = False
    before_events = len(fake_db.events)
    before_attendance = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "teaching_date": "2026-05-18",
            "start_time": "10:00",
            "teaching_name": "Journal Club",
        },
    )

    assert response.status_code == 422
    assert "tracked" in response.json()["detail"].lower()
    assert len(fake_db.events) == before_events
    assert len(fake_db.attendance) == before_attendance


def test_adhoc_teaching_rejects_when_fixed_department_programme_target_unavailable() -> None:
    fake_db = _fake_db()
    fake_db.teaching_targets = []
    before_events = len(fake_db.events)
    before_attendance = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "teaching_date": "2026-05-18",
            "start_time": "10:00",
            "teaching_name": "Journal Club",
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"].lower()
    assert "department/programme teaching [1h]" in detail
    assert "unavailable" in detail
    assert len(fake_db.events) == before_events
    assert len(fake_db.attendance) == before_attendance


def test_adhoc_teaching_rejects_when_department_programme_target_is_for_wrong_posting() -> None:
    fake_db = _fake_db()
    _configure_geri_tts_ger_med_run_club(fake_db, target_posting_code="KTPHGerMed")
    before_events = len(fake_db.events)
    before_attendance = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "teaching_date": "2026-05-18",
            "start_time": "16:15",
            "attended_posting_code": "TTSHGerMed",
            "teaching_name": "Run Club",
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"].lower()
    assert "department/programme teaching [1h]" in detail
    assert "unavailable" in detail
    assert len(fake_db.events) == before_events
    assert len(fake_db.attendance) == before_attendance


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
    assert response.json()["detail"] == "No active reporting period is available"


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


def test_adhoc_options_resolve_reopened_historical_period_and_selected_date_posting() -> None:
    fake_db = _fake_db()
    fake_db.reporting_periods[0].update(
        {
            "label": "2025/26 reopened",
            "start_date": date(2025, 7, 1),
            "end_date": date(2025, 12, 31),
            "status": "active",
            "activate_on": None,
            "deactivate_on": date(2099, 1, 1),
        }
    )
    fake_db.resident_postings[0].update(
        {
            "start_date": date(2025, 7, 1),
            "end_date": date(2025, 7, 31),
        }
    )
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_headers(fake_db),
        params={"date": "2025-07-15", "attended_posting_code": "TTSHCardio"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["reporting_period_id"] == fake_db.period_id
    assert payload["posting_code"] == "TTSHCardio"
    assert any(row["teaching_name"] == "Journal Club" for row in payload["options"])
    assert not any(
        row["start_date"] <= date.today() <= row["end_date"]
        for row in fake_db.resident_postings
    )


def test_adhoc_options_fail_closed_for_overlapping_effectively_active_periods() -> None:
    fake_db = _fake_db()
    fake_db.reporting_periods.append(
        {
            "id": "00000000-0000-0000-0000-000000000099",
            "label": "Ambiguous overlap",
            "start_date": fake_db.reporting_periods[0]["start_date"],
            "end_date": fake_db.reporting_periods[0]["end_date"],
            "status": "active",
            "activate_on": None,
            "deactivate_on": None,
        }
    )
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_headers(fake_db),
        params={"date": "2026-05-18"},
    )

    assert response.status_code == 409
    assert "ambiguous" in response.json()["detail"].lower()
