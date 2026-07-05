from __future__ import annotations

from datetime import timedelta
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
    inserted = next(
        row
        for row in fake_db.attendance
        if row["resident_id"] == fake_db.resident_id and row["teaching_event_id"] == fake_db.event_id
    )
    assert "session_type_id" not in inserted


def test_attendance_submission_invalidates_resident_and_report_caches(monkeypatch) -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)
    calls: list[tuple[set[str], dict]] = []

    def _spy(domains, **scope):  # noqa: ANN001
        calls.append((set(domains), scope))
        return []

    monkeypatch.setattr("app.services.cache_invalidation.invalidate_cache", _spy)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.event_id]},
    )

    assert response.status_code == 200
    assert calls
    domains, scope = calls[-1]
    assert {"resident_events", "resident_attendance", "resident_dashboard", "admin_reports"} <= domains
    assert str(scope["resident_id"]) == fake_db.resident_id
    assert "TTSHCardio" in scope["posting_code"]


def test_submitted_event_no_longer_appears_in_available_events() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    submit_response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.event_id]},
    )
    events_response = client.get("/resident/events", headers=_headers(fake_db))

    assert submit_response.status_code == 200
    assert events_response.status_code == 200
    event_ids = {row["id"] for row in events_response.json()["events"]}
    assert fake_db.event_id not in event_ids


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


def test_attendance_accepts_visible_native_department_event_when_posted_elsewhere() -> None:
    fake_db = FakeResidentSession()
    fake_db.programmes[0]["native_teaching_posting_code"] = "TTSHCardio"
    fake_db.resident_postings[0]["posting_code"] = "TTSHNeuro"
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


def test_attendance_accepts_visible_native_pc_event_when_posted_elsewhere() -> None:
    fake_db = FakeResidentSession()
    fake_db.programmes[0]["native_teaching_posting_code"] = "TTSHCardio"
    fake_db.resident_postings[0]["posting_code"] = "TTSHNeuro"
    pc_event = fake_db._event(  # noqa: SLF001
        str(uuid4()),
        "TTSHCardio",
        "Journal Club",
        fake_db.today - timedelta(days=1),
    )
    pc_event["created_by_role"] = "programme_pc"
    pc_event["created_for_programme_code"] = "GRM"
    fake_db.events.append(pc_event)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [pc_event["id"]]},
    )

    assert response.status_code == 200
    assert response.json()["submitted"] == 1
    assert any(
        row["resident_id"] == fake_db.resident_id
        and row["teaching_event_id"] == pc_event["id"]
        for row in fake_db.attendance
    )


def test_attendance_accepts_rehab_native_department_event_when_posted_to_grm() -> None:
    fake_db = FakeResidentSession()
    fake_db.residents[0]["programme_code"] = "REHAB"
    fake_db.programmes.append(
        {
            "code": "REHAB",
            "name": "Rehabilitation Medicine",
            "native_teaching_posting_code": "TTSHNeuro",
        }
    )
    fake_db.catalogue.append(
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
        }
    )
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.other_posting_event_id]},
    )

    assert response.status_code == 200
    assert response.json()["submitted"] == 1
    assert any(
        row["resident_id"] == fake_db.resident_id
        and row["teaching_event_id"] == fake_db.other_posting_event_id
        and row["posting_code"] == "TTSHNeuro"
        for row in fake_db.attendance
    )


def test_attendance_rejects_unrelated_pc_event_even_when_posting_is_native() -> None:
    fake_db = FakeResidentSession()
    fake_db.programmes[0]["native_teaching_posting_code"] = "TTSHCardio"
    fake_db.resident_postings[0]["posting_code"] = "TTSHNeuro"
    pc_event = fake_db._event(  # noqa: SLF001
        str(uuid4()),
        "TTSHCardio",
        "Journal Club",
        fake_db.today - timedelta(days=1),
    )
    pc_event["created_by_role"] = "programme_pc"
    pc_event["created_for_programme_code"] = "REHAB"
    fake_db.events.append(pc_event)
    before_count = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [pc_event["id"]]},
    )

    assert response.status_code == 422
    assert "programme scope" in response.json()["detail"].lower()
    assert len(fake_db.attendance) == before_count


def test_attendance_rejects_arbitrary_ttsh_secretary_event() -> None:
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
    arbitrary_event = fake_db._event(  # noqa: SLF001
        str(uuid4()),
        "TTSHOrtho",
        "Ortho Teaching",
        fake_db.today - timedelta(days=1),
    )
    fake_db.events.append(arbitrary_event)
    before_count = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [arbitrary_event["id"]]},
    )

    assert response.status_code == 422
    assert "posting" in response.json()["detail"].lower()
    assert len(fake_db.attendance) == before_count


def test_attendance_duplicate_native_event_remains_blocked() -> None:
    fake_db = FakeResidentSession()
    fake_db.programmes[0]["native_teaching_posting_code"] = "TTSHCardio"
    fake_db.resident_postings[0]["posting_code"] = "TTSHNeuro"
    fake_db.attendance.append(
        {
            "id": str(uuid4()),
            "resident_id": fake_db.resident_id,
            "teaching_event_id": fake_db.event_id,
            "status": "submitted",
            "posting_code": "TTSHCardio",
        }
    )
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.event_id]},
    )

    assert response.status_code == 409


def test_attendance_accepts_valid_secretary_event_even_when_supports_flag_is_false() -> None:
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
    ktph_event = fake_db._event(  # noqa: SLF001
        str(uuid4()),
        "KTPHGerMed",
        "KTPH Teaching",
        fake_db.today - timedelta(days=1),
    )
    fake_db.events.append(ktph_event)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [ktph_event["id"]]},
    )

    assert response.status_code == 200
    assert response.json()["submitted"] == 1
    assert any(
        row["resident_id"] == fake_db.resident_id and row["teaching_event_id"] == ktph_event["id"]
        for row in fake_db.attendance
    )


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


def test_delete_attendance_is_idempotent_for_already_removed_row() -> None:
    fake_db = FakeResidentSession()
    fake_db.attendance[0]["status"] = "removed"
    client = _client(fake_db)

    response = client.delete(
        f"/resident/attendance/{fake_db.existing_attendance_id}",
        headers=_headers(fake_db),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "removed"
    assert len(fake_db.attendance) == 2


def test_removed_scheduled_attendance_can_be_resubmitted_without_duplicate_row() -> None:
    fake_db = FakeResidentSession()
    fake_db.attendance[0]["status"] = "removed"
    before_count = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.second_event_id]},
    )

    assert response.status_code == 200
    assert response.json()["submitted"] == 1
    assert len(fake_db.attendance) == before_count
    row = next(row for row in fake_db.attendance if row["id"] == fake_db.existing_attendance_id)
    assert row["status"] == "submitted"


def test_adhoc_delete_leaves_teaching_event_row_intact() -> None:
    fake_db = FakeResidentSession()
    adhoc_event = fake_db._event(  # noqa: SLF001
        str(uuid4()),
        "TTSHCardio",
        "Journal Club",
        fake_db.today - timedelta(days=1),
    )
    adhoc_event["is_adhoc"] = True
    fake_db.events.append(adhoc_event)
    attendance_id = str(uuid4())
    fake_db.attendance.append(
        {
            "id": attendance_id,
            "resident_id": fake_db.resident_id,
            "teaching_event_id": adhoc_event["id"],
            "status": "submitted",
            "posting_code": "TTSHCardio",
        }
    )
    client = _client(fake_db)

    response = client.delete(
        f"/resident/attendance/{attendance_id}",
        headers=_headers(fake_db),
    )

    assert response.status_code == 200
    assert any(row["id"] == adhoc_event["id"] for row in fake_db.events)
    assert next(row for row in fake_db.attendance if row["id"] == attendance_id)["status"] == "removed"


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
    fake_db.events[0]["event_date"] = fake_db.today - timedelta(days=1)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.event_id]},
    )

    assert response.status_code == 422


def test_attendance_is_blocked_when_reporting_period_is_inactive() -> None:
    fake_db = FakeResidentSession()
    fake_db.reporting_periods[0]["status"] = "inactive"
    before_count = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.event_id]},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "No active reporting period is available"
    assert len(fake_db.attendance) == before_count


def test_attendance_uses_effectively_active_scheduled_reporting_period() -> None:
    fake_db = FakeResidentSession()
    fake_db.reporting_periods[0]["status"] = "inactive"
    fake_db.reporting_periods[0]["activate_on"] = fake_db.today - timedelta(days=1)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.event_id]},
    )

    assert response.status_code == 200
    assert any(row["teaching_event_id"] == fake_db.event_id for row in fake_db.attendance)
