from __future__ import annotations

from datetime import date, timedelta
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
    fake_db.catalogue.extend(
        [
            {
                "keyword": "Journal Club",
                "posting_code": "TTSHCardio",
                "programme_code": "REHAB",
                "r_year": "R2",
                "reporting_period_id": fake_db.period_id,
                "session_type_id": fake_db.session_type_id,
                "session_type": "Journal Club [1.0h]",
                "duration_hours": 1.0,
                "is_tracked": True,
            },
            {
                "keyword": "Skills Teaching",
                "posting_code": "TTSHNeuro",
                "programme_code": "REHAB",
                "r_year": "R2",
                "reporting_period_id": fake_db.period_id,
                "session_type_id": fake_db.second_session_type_id,
                "session_type": "Skills Teaching [2.0h]",
                "duration_hours": 2.0,
                "is_tracked": True,
            },
        ]
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
    fake_db.catalogue.append(
        {
            "keyword": "Ortho Teaching",
            "posting_code": "TTSHOrtho",
            "programme_code": "GRM",
            "r_year": "R2",
            "reporting_period_id": fake_db.period_id,
            "session_type_id": fake_db.session_type_id,
            "session_type": "Ortho Teaching [1.0h]",
            "duration_hours": 1.0,
            "is_tracked": True,
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
