from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import resident_submission
from app.errors import ApiError
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


def test_unfiltered_events_reuse_the_visible_rows_for_filter_options() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    payload = response.json()
    assert sum(
        "/* resident_available_events_for_postings */" in sql
        for sql in fake_db.executed_sql
    ) == 1
    assert {
        option["teaching_name"]
        for option in payload["filter_options"]["teaching_name_options"]
    } == {event["teaching_name"] for event in payload["events"]}


def test_native_event_timing_uses_residents_event_date_r_year() -> None:
    fake_db = FakeResidentSession()
    event = next(row for row in fake_db.events if row["id"] == fake_db.event_id)
    teaching_name_id = str(uuid4())
    event.update(
        {
            "teaching_name_id": teaching_name_id,
            "source_reporting_period_id": fake_db.period_id,
            "source_programme_code": "GRM",
            "duration_hours": Decimal("2.0"),
            "end_time": time(12, 0),
        }
    )
    fake_db.pool_event_r_year_timings[
        (
            teaching_name_id,
            fake_db.period_id,
            "GRM",
            "TTSHCardio",
            "R2",
        )
    ] = {
        "r_year": "R2",
        "teaching_target_id": fake_db.session_type_id,
        "session_type_id": fake_db.session_type_id,
        "session_type_name": "R2 teaching [1h]",
        "duration_hours": Decimal("1.0"),
    }
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    listed = next(row for row in response.json()["events"] if row["id"] == event["id"])
    assert listed["resident_r_year"] == "R2"
    assert listed["duration_hours"] == "1.0"
    assert listed["end_time"] == "11:00:00"
    assert listed["duration_is_mapped"] is True


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


def test_events_include_native_department_and_native_pc_events_when_posted_elsewhere() -> None:
    fake_db = FakeResidentSession()
    fake_db.programmes[0]["native_teaching_posting_code"] = "TTSHCardio"
    fake_db.resident_postings[0]["posting_code"] = "TTSHNeuro"
    grm_pc_event_id = str(uuid4())
    pc_event = fake_db._event(  # noqa: SLF001
        grm_pc_event_id,
        "TTSHCardio",
        "Journal Club",
        fake_db.today - timedelta(days=1),
    )
    pc_event["created_by_role"] = "programme_pc"
    pc_event["created_for_programme_code"] = "GRM"
    fake_db.events.append(pc_event)
    unrelated_pc_event_id = str(uuid4())
    unrelated_pc_event = fake_db._event(  # noqa: SLF001
        unrelated_pc_event_id,
        "TTSHCardio",
        "Journal Club",
        fake_db.today - timedelta(days=1),
    )
    unrelated_pc_event["created_by_role"] = "programme_pc"
    unrelated_pc_event["created_for_programme_code"] = "REHAB"
    fake_db.events.append(unrelated_pc_event)
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.other_posting_event_id in ids
    assert fake_db.event_id in ids
    assert grm_pc_event_id in ids
    assert unrelated_pc_event_id not in ids


def test_events_deduplicate_when_assigned_posting_is_native_department() -> None:
    fake_db = FakeResidentSession()
    fake_db.programmes[0]["native_teaching_posting_code"] = "TTSHCardio"
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    ids = [row["id"] for row in response.json()["events"]]
    assert ids.count(fake_db.event_id) == 1


def test_events_include_rehab_native_department_when_rehab_resident_posted_to_grm() -> None:
    fake_db = FakeResidentSession()
    fake_db.residents[0]["programme_code"] = "REHAB"
    fake_db.programmes.append(
        {
            "code": "REHAB",
            "name": "Rehabilitation Medicine",
            "native_teaching_posting_code": "TTSHNeuro",
        }
    )
    other_posting_event = next(
        row for row in fake_db.events if row["id"] == fake_db.other_posting_event_id
    )
    other_posting_event.update(
        {
            "teaching_name_id": str(uuid4()),
            "source_reporting_period_id": fake_db.period_id,
            "source_programme_code": "REHAB",
        }
    )
    rehab_pc_event_id = str(uuid4())
    rehab_pc_event = fake_db._event(  # noqa: SLF001
        rehab_pc_event_id,
        "TTSHNeuro",
        "Skills Teaching",
        fake_db.today - timedelta(days=1),
    )
    rehab_pc_event["created_by_role"] = "programme_pc"
    rehab_pc_event["created_for_programme_code"] = "REHAB"
    rehab_pc_event["teaching_name_id"] = str(uuid4())
    rehab_pc_event["source_reporting_period_id"] = fake_db.period_id
    rehab_pc_event["source_programme_code"] = "REHAB"
    fake_db.events.append(rehab_pc_event)
    grm_pc_event_id = str(uuid4())
    grm_pc_event = fake_db._event(  # noqa: SLF001
        grm_pc_event_id,
        "TTSHNeuro",
        "Skills Teaching",
        fake_db.today - timedelta(days=1),
    )
    grm_pc_event["created_by_role"] = "programme_pc"
    grm_pc_event["created_for_programme_code"] = "GRM"
    grm_pc_event["teaching_name_id"] = str(uuid4())
    grm_pc_event["source_reporting_period_id"] = fake_db.period_id
    grm_pc_event["source_programme_code"] = "GRM"
    fake_db.events.append(grm_pc_event)
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.event_id in ids
    assert fake_db.other_posting_event_id in ids
    assert rehab_pc_event_id in ids
    assert grm_pc_event_id not in ids


def test_events_do_not_show_arbitrary_ttsh_secretary_events() -> None:
    fake_db = FakeResidentSession()
    fake_db.programmes[0]["native_teaching_posting_code"] = "TTSHCardio"
    fake_db.posting_codes.append(
        {
            "code": "TTSHOrtho",
            "display_name": "TTSH Orthopaedic Surgery",
            "institution": "TTSH",
            "supports_secretary_events": True,
        }
    )
    arbitrary_event_id = str(uuid4())
    fake_db.events.append(
        fake_db._event(  # noqa: SLF001
            arbitrary_event_id,
            "TTSHOrtho",
            "Ortho Teaching",
            fake_db.today - timedelta(days=1),
        )
    )
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert arbitrary_event_id not in ids


def test_events_exclude_future_and_already_submitted_but_include_legacy_events() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.future_event_id not in ids
    assert fake_db.second_event_id not in ids
    assert fake_db.invisible_event_id in ids


def test_events_include_global_session_types_through_normal_posting_rules() -> None:
    fake_db = FakeResidentSession()
    fake_db.teaching_targets = []
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    payload = response.json()
    ids = {row["id"] for row in payload["events"]}
    assert fake_db.global_event_id in ids
    global_event = next(row for row in payload["events"] if row["id"] == fake_db.global_event_id)
    assert global_event["is_global"] is True


def test_explicit_pool_events_allow_admitted_host_source_but_require_exact_period() -> None:
    fake_db = FakeResidentSession()
    fake_db.teaching_targets = []
    matching_event_id = str(uuid4())
    host_programme_event_id = str(uuid4())
    wrong_period_event_id = str(uuid4())
    event_date = fake_db.today - timedelta(days=5)
    fake_db.events.extend(
        [
            fake_db._event(  # noqa: SLF001
                matching_event_id,
                "TTSHCardio",
                "Shared Pool Display",
                event_date,
                teaching_name_id=str(uuid4()),
                source_reporting_period_id=fake_db.period_id,
                source_programme_code="GRM",
            ),
            fake_db._event(  # noqa: SLF001
                host_programme_event_id,
                "TTSHCardio",
                "Shared Pool Display",
                event_date,
                teaching_name_id=str(uuid4()),
                source_reporting_period_id=fake_db.period_id,
                source_programme_code="REHAB",
            ),
            fake_db._event(  # noqa: SLF001
                wrong_period_event_id,
                "TTSHCardio",
                "Shared Pool Display",
                event_date,
                teaching_name_id=str(uuid4()),
                source_reporting_period_id=str(uuid4()),
                source_programme_code="GRM",
            ),
        ]
    )
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    event_ids = {row["id"] for row in response.json()["events"]}
    assert matching_event_id in event_ids
    assert host_programme_event_id in event_ids
    assert wrong_period_event_id not in event_ids


def test_events_hide_rows_with_both_persisted_source_id_families() -> None:
    fake_db = FakeResidentSession()
    ambiguous_event_id = str(uuid4())
    fake_db.events.append(
        fake_db._event(  # noqa: SLF001
            ambiguous_event_id,
            "TTSHCardio",
            "Ambiguous Source Evidence",
            fake_db.today - timedelta(days=5),
            teaching_name_id=str(uuid4()),
            global_session_type_id=fake_db.global_session_type_id,
            source_reporting_period_id=fake_db.period_id,
            source_programme_code="GRM",
        )
    )
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    assert ambiguous_event_id not in {
        row["id"] for row in response.json()["events"]
    }


def test_events_return_empty_reason_when_no_active_reporting_period_exists() -> None:
    fake_db = FakeResidentSession()
    fake_db.reporting_periods = []
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"] == []
    assert payload["reason"] == "active_reporting_period_unavailable"
    assert payload["ad_hoc_allowed"] is False


def test_events_hide_unsubmitted_events_when_reporting_period_is_inactive() -> None:
    fake_db = FakeResidentSession()
    fake_db.reporting_periods[0]["status"] = "inactive"
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"] == []
    assert payload["reason"] == "active_reporting_period_unavailable"
    assert payload["ad_hoc_allowed"] is False


def test_events_use_effectively_active_scheduled_reporting_period() -> None:
    fake_db = FakeResidentSession()
    fake_db.reporting_periods[0]["status"] = "inactive"
    fake_db.reporting_periods[0]["activate_on"] = fake_db.today - timedelta(days=1)
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.event_id in ids


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
    fake_db.events.append(
        fake_db._event(  # noqa: SLF001
            str(uuid4()),
            "KTPHGerMed",
            "KTPH Teaching",
            fake_db.today - timedelta(days=1),
            teaching_name_id=str(uuid4()),
            source_reporting_period_id=fake_db.period_id,
            source_programme_code="GRM",
        )
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


def test_events_accept_verified_resident_identity_without_raw_headers() -> None:
    fake_db = FakeResidentSession()
    client = _client(
        fake_db,
        identity=AuthIdentity(
            role="resident",
            subject_id=fake_db.resident_id,
            programme_code="GRM",
        ),
    )

    response = client.get("/resident/events")

    assert response.status_code == 200
    assert fake_db.event_id in {row["id"] for row in response.json()["events"]}


def test_events_reject_verified_staff_identity() -> None:
    fake_db = FakeResidentSession()
    client = _client(
        fake_db,
        identity=AuthIdentity(
            role="secretary",
            subject_id=str(uuid4()),
            posting_code="TTSHCardio",
        ),
    )

    response = client.get("/resident/events")

    assert response.status_code == 403


def test_events_use_active_period_event_window_not_today_posting_only() -> None:
    fake_db = FakeResidentSession()
    period_start = fake_db.today - timedelta(days=14)
    period_end = fake_db.today + timedelta(days=14)
    fake_db.reporting_periods = [
        {
            "id": fake_db.period_id,
            "label": "Current operational period",
            "start_date": period_start,
            "end_date": period_end,
            "status": "active",
        }
    ]
    fake_db.resident_postings = [
        {
            "resident_id": fake_db.resident_id,
            "reporting_period_id": fake_db.period_id,
            "posting_code": "TTSHGerMed",
            "r_year": "ALL",
            "start_date": fake_db.today - timedelta(days=7),
            "end_date": fake_db.today + timedelta(days=7),
            "status": "active",
        }
    ]
    fake_db.residents[0]["programme_code"] = "GERI"
    fake_db.posting_codes.append({"code": "TTSHGerMed", "supports_secretary_events": False})
    fake_db.attendance = []
    valid_event_id = str(uuid4())
    outside_window_id = str(uuid4())
    fake_db.events = [
        fake_db._event(valid_event_id, "TTSHGerMed", "GERI Demo Row 22", fake_db.today),  # noqa: SLF001
        fake_db._event(outside_window_id, "TTSHGerMed", "GERI Demo Row 22", period_start - timedelta(days=1)),  # noqa: SLF001
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


def test_events_exclude_submitted_event_in_active_period_window() -> None:
    fake_db = FakeResidentSession()
    period_start = fake_db.today - timedelta(days=14)
    period_end = fake_db.today + timedelta(days=14)
    fake_db.reporting_periods = [
        {
            "id": fake_db.period_id,
            "label": "Current operational period",
            "start_date": period_start,
            "end_date": period_end,
            "status": "active",
        }
    ]
    fake_db.resident_postings = [
        {
            "resident_id": fake_db.resident_id,
            "reporting_period_id": fake_db.period_id,
            "posting_code": "TTSHGerMed",
            "r_year": "ALL",
            "start_date": fake_db.today - timedelta(days=7),
            "end_date": fake_db.today + timedelta(days=7),
            "status": "active",
        }
    ]
    fake_db.residents[0]["programme_code"] = "GERI"
    fake_db.posting_codes.append({"code": "TTSHGerMed", "supports_secretary_events": True})
    submitted_event_id = str(uuid4())
    fake_db.events = [
        fake_db._event(submitted_event_id, "TTSHGerMed", "GERI Demo Row 22", fake_db.today),  # noqa: SLF001
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


@pytest.mark.asyncio
async def test_overlapping_events_reappear_after_attendance_is_removed() -> None:
    fake_db = FakeResidentSession()
    event_date = fake_db.today - timedelta(days=1)
    first_event_id = str(uuid4())
    second_event_id = str(uuid4())
    first = fake_db._event(  # noqa: SLF001
        first_event_id,
        "TTSHCardio",
        "Parallel Teaching A",
        event_date,
        start_time=time(10, 0),
        teaching_name_id=str(uuid4()),
        source_reporting_period_id=fake_db.period_id,
        source_programme_code="GRM",
    )
    second = fake_db._event(  # noqa: SLF001
        second_event_id,
        "TTSHCardio",
        "Parallel Teaching B",
        event_date,
        start_time=time(11, 30),
    )
    second["end_time"] = time(12, 30)
    fake_db.events = [first, second]
    fake_db.attendance = []
    r1_session_type_id = str(uuid4())
    fake_db.pool_event_r_year_timings[
        (
            first["teaching_name_id"],
            fake_db.period_id,
            "GRM",
            "TTSHCardio",
            "R2",
        )
    ] = {
        "r_year": "R2",
        "teaching_target_id": fake_db.session_type_id,
        "session_type_id": fake_db.session_type_id,
        "session_type_name": "Parallel Teaching A [2h]",
        "duration_hours": Decimal("2.0"),
    }
    fake_db.pool_event_r_year_timings[
        (
            first["teaching_name_id"],
            fake_db.period_id,
            "GRM",
            "TTSHCardio",
            "R1",
        )
    ] = {
        "r_year": "R1",
        "teaching_target_id": r1_session_type_id,
        "session_type_id": r1_session_type_id,
        "session_type_name": "Parallel Teaching A [1h]",
        "duration_hours": Decimal("1.0"),
    }

    initially_available = await resident_submission.list_available_events(
        fake_db,
        resident_id=fake_db.residents[0]["id"],
        today=fake_db.today,
    )
    assert {row["id"] for row in initially_available["events"]} == {
        first_event_id,
        second_event_id,
    }
    first_available = next(
        row for row in initially_available["events"] if row["id"] == first_event_id
    )
    assert first_available["duration_hours"] == Decimal("2.0")
    assert first_available["end_time"] == time(12, 0)

    attendance_id = str(uuid4())
    fake_db.attendance.append(
        {
            "id": attendance_id,
            "resident_id": fake_db.resident_id,
            "teaching_event_id": first_event_id,
            "status": "submitted",
            "posting_code": "TTSHCardio",
        }
    )
    after_submission = await resident_submission.list_available_events(
        fake_db,
        resident_id=fake_db.residents[0]["id"],
        today=fake_db.today,
    )
    assert after_submission["events"] == []
    assert after_submission["filter_options"]["teaching_name_options"] == []

    fake_db.resident_postings[1].update(
        {
            "posting_code": "TTSHCardio",
            "r_year": "R1",
        }
    )
    other_r_year_view = await resident_submission.list_available_events(
        fake_db,
        resident_id=fake_db.residents[1]["id"],
        today=fake_db.today,
    )
    assert {row["id"] for row in other_r_year_view["events"]} == {
        first_event_id,
        second_event_id,
    }
    assert next(
        row for row in other_r_year_view["events"] if row["id"] == first_event_id
    )["end_time"] == time(11, 0)

    fake_db.attendance[0]["status"] = "removed"
    after_removal = await resident_submission.list_available_events(
        fake_db,
        resident_id=fake_db.residents[0]["id"],
        today=fake_db.today,
    )
    assert {row["id"] for row in after_removal["events"]} == {
        first_event_id,
        second_event_id,
    }


def test_events_support_scheduled_filters_without_widening_visibility() -> None:
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

    response = client.get(
        "/resident/events",
        headers=_headers(fake_db),
        params={
            "date_from": (fake_db.today - timedelta(days=3)).isoformat(),
            "date_to": (fake_db.today + timedelta(days=20)).isoformat(),
            "teaching_name": "Skills Teaching",
            "posting_code": "TTSHNeuro",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    ids = {row["id"] for row in payload["events"]}
    assert fake_db.other_posting_event_id in ids
    assert fake_db.event_id not in ids
    assert fake_db.future_event_id not in ids
    posting_options = {row["posting_code"] for row in payload["filter_options"]["posting_options"]}
    assert posting_options == {"TTSHCardio", "TTSHNeuro"}
    teaching_options = [row["teaching_name"] for row in payload["filter_options"]["teaching_name_options"]]
    assert teaching_options == sorted(teaching_options)


def test_events_posting_filter_cannot_widen_beyond_resident_postings() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get(
        "/resident/events",
        headers=_headers(fake_db),
        params={"posting_code": "TTSHNeuro"},
    )

    assert response.status_code == 200
    assert response.json()["events"] == []


def _configure_historical_geri_case(fake_db: FakeResidentSession) -> str:
    historical_event_id = str(uuid4())
    historical_period_id = str(uuid4())
    fake_db.residents[0].update(
        {
            "name": "Historical GERI Resident",
            "mcr": "M64471D",
            "programme_code": "GERI",
        }
    )
    fake_db.reporting_periods = [
        {
            "id": historical_period_id,
            "label": "2025/26 reopened",
            "start_date": date(2025, 7, 1),
            "end_date": date(2025, 12, 31),
            "status": "active",
            "activate_on": None,
            "deactivate_on": date(2099, 1, 1),
        }
    ]
    fake_db.resident_postings = [
        {
            "resident_id": fake_db.resident_id,
            "reporting_period_id": historical_period_id,
            "posting_code": "TTSHGerMed",
            "r_year": "ALL",
            "start_date": date(2025, 7, 1),
            "end_date": date(2025, 7, 31),
            "status": "active",
        }
    ]
    fake_db.posting_codes.append(
        {
            "code": "TTSHGerMed",
            "display_name": "TTSH Geriatric Medicine",
            "institution": "TTSH",
            "supports_secretary_events": True,
        }
    )
    fake_db.attendance = []
    fake_db.events = [
        fake_db._event(  # noqa: SLF001
            historical_event_id,
            "TTSHGerMed",
            "GERI Historical Teaching",
            date(2025, 7, 15),
        )
    ]
    return historical_event_id


@pytest.mark.asyncio
async def test_events_return_reopened_july_2025_geri_event_without_a_current_posting() -> None:
    fake_db = FakeResidentSession(today=date(2026, 7, 17))
    historical_event_id = _configure_historical_geri_case(fake_db)

    payload = await resident_submission.list_available_events(
        fake_db,
        resident_id=fake_db.residents[0]["id"],
        today=date(2026, 7, 17),
    )

    assert [row["id"] for row in payload["events"]] == [historical_event_id]
    assert payload["events"][0]["reporting_period_id"] == fake_db.reporting_periods[0]["id"]
    assert payload["active_reporting_periods"][0]["label"] == "2025/26 reopened"
    assert all(
        not (row["start_date"] <= date(2026, 7, 17) <= row["end_date"])
        for row in fake_db.resident_postings
    )


def test_submission_periods_returns_all_effectively_active_periods_without_a_selector() -> None:
    fake_db = FakeResidentSession(today=date.today())
    _configure_historical_geri_case(fake_db)
    second_period_id = str(uuid4())
    fake_db.reporting_periods.append(
        {
            "id": second_period_id,
            "label": "Another reopened period",
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 6, 30),
            "status": "inactive",
            "activate_on": date(2026, 7, 1),
            "deactivate_on": date(2099, 1, 1),
        }
    )
    client = _client(fake_db)

    response = client.get("/resident/submission-periods", headers=_headers(fake_db))

    assert response.status_code == 200
    assert [row["id"] for row in response.json()["periods"]] == [
        fake_db.reporting_periods[0]["id"],
        second_period_id,
    ]


@pytest.mark.asyncio
async def test_events_query_multiple_effectively_active_periods() -> None:
    fake_db = FakeResidentSession(today=date(2026, 7, 17))
    first_event_id = _configure_historical_geri_case(fake_db)
    second_period_id = str(uuid4())
    second_event_id = str(uuid4())
    fake_db.reporting_periods.append(
        {
            "id": second_period_id,
            "label": "First half 2026 reopened",
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 6, 30),
            "status": "inactive",
            "activate_on": date(2026, 7, 1),
            "deactivate_on": date(2099, 1, 1),
        }
    )
    fake_db.resident_postings.append(
        {
            "resident_id": fake_db.resident_id,
            "reporting_period_id": second_period_id,
            "posting_code": "TTSHGerMed",
            "r_year": "ALL",
            "start_date": date(2026, 6, 1),
            "end_date": date(2026, 6, 30),
            "status": "loa_working",
        }
    )
    fake_db.events.append(
        fake_db._event(  # noqa: SLF001
            second_event_id,
            "TTSHGerMed",
            "Second Period Teaching",
            date(2026, 6, 30),
        )
    )

    payload = await resident_submission.list_available_events(
        fake_db,
        resident_id=fake_db.residents[0]["id"],
        today=date(2026, 7, 17),
    )

    assert [row["id"] for row in payload["events"]] == [first_event_id, second_event_id]
    assert {row["reporting_period_id"] for row in payload["events"]} == {
        fake_db.reporting_periods[0]["id"],
        second_period_id,
    }
    assert len(payload["active_reporting_periods"]) == 2

    isolated = await resident_submission.list_available_events(
        fake_db,
        resident_id=fake_db.residents[0]["id"],
        today=date(2026, 7, 17),
    )
    assert [row["id"] for row in isolated["events"]] == [first_event_id, second_event_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["active", "loa_working"])
async def test_events_use_inclusive_event_date_posting_boundaries(status: str) -> None:
    fake_db = FakeResidentSession(today=date(2026, 7, 17))
    historical_event_id = _configure_historical_geri_case(fake_db)
    fake_db.resident_postings[0].update(
        {
            "start_date": date(2025, 7, 15),
            "end_date": date(2025, 7, 15),
            "status": status,
        }
    )

    payload = await resident_submission.list_available_events(
        fake_db,
        resident_id=fake_db.residents[0]["id"],
        today=date(2026, 7, 17),
    )

    assert [row["id"] for row in payload["events"]] == [historical_event_id]


@pytest.mark.asyncio
async def test_events_exclude_historical_period_after_effective_deactivation() -> None:
    fake_db = FakeResidentSession(today=date(2026, 7, 17))
    _configure_historical_geri_case(fake_db)
    fake_db.reporting_periods[0]["deactivate_on"] = date(2026, 7, 16)

    payload = await resident_submission.list_available_events(
        fake_db,
        resident_id=fake_db.residents[0]["id"],
        today=date(2026, 7, 17),
    )

    assert payload["events"] == []
    assert payload["reason"] == "active_reporting_period_unavailable"
    assert payload["active_reporting_periods"] == []


@pytest.mark.asyncio
async def test_events_fail_closed_when_active_periods_overlap_an_event_date() -> None:
    fake_db = FakeResidentSession(today=date(2026, 7, 17))
    _configure_historical_geri_case(fake_db)
    fake_db.reporting_periods.append(
        {
            **fake_db.reporting_periods[0],
            "id": str(uuid4()),
            "label": "Ambiguous historical overlap",
        }
    )

    with pytest.raises(ApiError) as raised:
        await resident_submission.list_available_events(
            fake_db,
            resident_id=fake_db.residents[0]["id"],
            today=date(2026, 7, 17),
        )

    assert raised.value.status_code == 409
