from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.middleware.errors import install_error_handlers
from app.routers import resident
from app.services import resident_submission
from tests.auth_identity_test_helpers import install_stub_header_identity_middleware
from tests.resident_fakes import FakeResidentSession


ADHOC_FIXTURE_TODAY = date(2026, 5, 18)


def _fake_db() -> FakeResidentSession:
    return FakeResidentSession(today=ADHOC_FIXTURE_TODAY)


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


def _headers(fake_db: FakeResidentSession) -> dict[str, str]:
    return {
        "X-User-Role": "resident",
        "X-User-Id": fake_db.resident_id,
        "X-User-Programme": "GRM",
    }


def _configure_geri_tts_ger_med(fake_db: FakeResidentSession) -> None:
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


def test_adhoc_teaching_derives_posting_from_submitted_date() -> None:
    fake_db = _fake_db()
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "date": "2026-05-18",
            "start_time": "10:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["event"]["posting_code"] == "TTSHCardio"
    assert payload["event"]["teaching_name"] == "Department/Programme Teaching [1h]"
    assert payload["event"]["session_type_id"] is None
    assert payload["event"]["is_adhoc"] is True
    assert payload["attendance"]["posting_code"] == "TTSHCardio"
    assert any(row["is_adhoc"] for row in fake_db.events)
    assert len(fake_db.native_attendance_lock_calls) == 1
    assert len(fake_db.adhoc_helper_calls) == 1
    assert fake_db.adhoc_helper_calls[0]["attended_teaching_name"] == (
        "Department/Programme Teaching [1h]"
    )
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


def test_adhoc_teaching_accepts_canonical_teaching_date() -> None:
    fake_db = _fake_db()
    response = _client(fake_db).post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={"teaching_date": "2026-05-18", "start_time": "12:00"},
    )

    assert response.status_code == 200


def test_adhoc_teaching_accepts_equal_date_aliases() -> None:
    fake_db = _fake_db()
    response = _client(fake_db).post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "teaching_date": "2026-05-18",
            "date": "2026-05-18",
            "start_time": "12:00",
        },
    )

    assert response.status_code == 200


def test_adhoc_teaching_rejects_mismatched_date_aliases() -> None:
    fake_db = _fake_db()
    response = _client(fake_db).post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "teaching_date": "2026-05-18",
            "date": "2026-05-19",
            "start_time": "12:00",
        },
    )

    assert response.status_code == 422
    assert not fake_db.adhoc_helper_calls


def test_adhoc_teaching_rejects_missing_date_aliases() -> None:
    fake_db = _fake_db()
    response = _client(fake_db).post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={"start_time": "12:00"},
    )

    assert response.status_code == 422
    assert not fake_db.adhoc_helper_calls


def test_native_adhoc_commit_failure_rolls_back_event_and_attendance_and_returns_no_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _fake_db()
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
        headers=_headers(fake_db),
        json={
            "date": ADHOC_FIXTURE_TODAY.isoformat(),
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


def test_adhoc_teaching_uses_fixed_contract_without_catalogue_or_target() -> None:
    fake_db = _fake_db()
    _configure_geri_tts_ger_med(fake_db)
    fake_db.catalogue = []
    fake_db.teaching_targets = []
    before_attendance = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "teaching_date": "2026-05-18",
            "start_time": "16:15",
            "attended_posting_code": "TTSHGerMed",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["event"]["posting_code"] == "TTSHGerMed"
    assert payload["event"]["teaching_name"] == "Department/Programme Teaching [1h]"
    assert payload["event"]["session_type_id"] is None
    assert payload["attendance"]["posting_code"] == "TTSHGerMed"
    assert len(fake_db.attendance) == before_attendance + 1


def test_adhoc_options_are_date_first_and_use_one_fixed_option() -> None:
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
    assert len(payload["options"]) == 1
    assert payload["options"][0]["teaching_name"] == "Department/Programme Teaching [1h]"
    assert payload["options"][0]["session_type_id"] is None
    assert str(payload["options"][0]["duration_hours"]) == "1.00"
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
    assert posting_codes == {"TTSHCardio"}
    assert payload["selected_attended_posting_code"] == "TTSHCardio"


def test_adhoc_options_reject_client_selected_non_assigned_posting() -> None:
    fake_db = _fake_db()
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_headers(fake_db),
        params={"date": "2026-05-18", "attended_posting_code": "TTSHNeuro"},
    )

    assert response.status_code == 422
    assert "attended_posting_code" in response.json()["detail"]


def test_adhoc_teaching_rejects_client_selected_non_assigned_posting() -> None:
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
        },
    )

    assert response.status_code == 422
    assert len(fake_db.attendance) == before_attendance


def test_adhoc_teaching_rejects_client_selected_posting_even_without_legacy_target() -> None:
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
        },
    )

    assert response.status_code == 422
    assert "attended_posting_code" in response.json()["detail"]
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
        },
    )

    assert response.status_code == 422
    assert "attended" in response.json()["detail"].lower()
    assert len(fake_db.events) == before_events
    assert len(fake_db.attendance) == before_attendance


def test_adhoc_options_use_resident_posting_r_year_not_resident_r_year() -> None:
    fake_db = _fake_db()
    fake_db.residents[0]["r_year"] = "R3"
    fake_db.catalogue = []
    client = _client(fake_db)

    response = client.get(
        "/resident/adhoc-teaching-options",
        headers=_headers(fake_db),
        params={"date": "2026-05-18"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["r_year"] == "R2"
    assert payload["options"][0]["teaching_name"] == "Department/Programme Teaching [1h]"


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


def test_adhoc_teaching_rejects_client_supplied_teaching_name() -> None:
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
            "teaching_name": "Anything else",
        },
    )

    assert response.status_code == 422
    assert len(fake_db.events) == before_events
    assert len(fake_db.attendance) == before_attendance


def test_adhoc_teaching_ignores_catalogue_and_target_tracking_state() -> None:
    fake_db = _fake_db()
    fake_db.catalogue[0]["is_tracked"] = False
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
        },
    )

    assert response.status_code == 200
    assert len(fake_db.events) == before_events + 1
    assert len(fake_db.attendance) == before_attendance + 1


def test_adhoc_teaching_works_when_fixed_department_programme_target_is_unavailable() -> None:
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
        },
    )

    assert response.status_code == 200
    assert len(fake_db.events) == before_events + 1
    assert len(fake_db.attendance) == before_attendance + 1


def test_adhoc_teaching_ignores_legacy_target_posting_configuration() -> None:
    fake_db = _fake_db()
    _configure_geri_tts_ger_med(fake_db)
    fake_db.catalogue = []
    fake_db.teaching_targets = []
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
        },
    )

    assert response.status_code == 200
    assert len(fake_db.events) == before_events + 1
    assert len(fake_db.attendance) == before_attendance + 1


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
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "No active reporting period is available"


def test_native_adhoc_teaching_rejects_overlap_before_writing_event_or_attendance() -> None:
    fake_db = _fake_db()
    existing_event = next(
        row for row in fake_db.events if row["id"] == fake_db.second_event_id
    )
    events_before = [dict(row) for row in fake_db.events]
    attendance_before = [dict(row) for row in fake_db.attendance]
    earlier_attendance_before = dict(fake_db.attendance[0])
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "date": existing_event["event_date"].isoformat(),
            "start_time": existing_event["start_time"].isoformat(),
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Attendance overlaps an earlier accepted event"
    assert fake_db.events == events_before
    assert fake_db.attendance == attendance_before
    assert fake_db.attendance[0] == earlier_attendance_before
    assert len(fake_db.native_attendance_lock_calls) == 1
    assert fake_db.adhoc_helper_calls == []


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
            "start_time": "12:00",
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
    assert payload["options"][0]["teaching_name"] == "Department/Programme Teaching [1h]"
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


@pytest.mark.parametrize(
    (
        "sqlstate",
        "expected_status",
        "expected_detail",
        "expected_error_code",
        "expected_rollbacks",
    ),
    [
        (
            "22023",
            422,
            "Invalid ad-hoc teaching event",
            "VALIDATION_FAILED",
            1,
        ),
        (
            "28000",
            401,
            "Unauthorized",
            "UNAUTHORIZED",
            1,
        ),
        (
            "23P01",
            409,
            "Attendance overlaps an earlier accepted event",
            "CONFLICT",
            1,
        ),
        (
            "42501",
            500,
            "Internal server error",
            "INTERNAL_ERROR",
            0,
        ),
    ],
)
def test_adhoc_helper_sqlstates_use_expected_api_contract(
    monkeypatch,
    sqlstate: str,
    expected_status: int,
    expected_detail: str,
    expected_error_code: str,
    expected_rollbacks: int,
) -> None:
    class _HelperRejection(Exception):
        def __init__(self) -> None:
            super().__init__("database helper rejection")
            self.sqlstate = sqlstate

    fake_db = _fake_db()
    events_before = len(fake_db.events)
    attendance_before = len(fake_db.attendance)
    rollback_count = 0

    async def _rollback() -> None:
        nonlocal rollback_count
        rollback_count += 1

    async def _reject_helper(*_args, **_kwargs) -> None:
        raise DBAPIError(
            "SELECT mata_rls.create_adhoc_attendance(...)",
            {},
            _HelperRejection(),
            False,
        )

    monkeypatch.setattr(fake_db, "rollback", _rollback)
    monkeypatch.setattr(
        resident_submission,
        "_create_adhoc_attendance",
        _reject_helper,
    )
    client = _client(fake_db)

    response = client.post(
        "/resident/adhoc-teaching",
        headers=_headers(fake_db),
        json={
            "date": "2026-05-18",
            "start_time": "10:00",
        },
    )

    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail
    assert response.json()["error_code"] == expected_error_code
    assert rollback_count == expected_rollbacks
    assert fake_db.commits == 0
    assert len(fake_db.events) == events_before
    assert len(fake_db.attendance) == attendance_before
