from __future__ import annotations

from datetime import date, time, timedelta
from uuid import uuid4

import pytest
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


def _headers(fake_db: FakeResidentSession) -> dict[str, str]:
    return {
        "X-User-Role": "resident",
        "X-User-Id": fake_db.resident_id,
        "X-User-Programme": "GRM",
    }


def _add_scheduled_event(
    fake_db: FakeResidentSession,
    *,
    event_date: date,
    start_time: time,
    end_time: time,
) -> dict:
    event = fake_db._event(  # noqa: SLF001
        str(uuid4()),
        "TTSHCardio",
        "Journal Club",
        event_date,
        start_time=start_time,
    )
    event["end_time"] = end_time
    fake_db.events.append(event)
    return event


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


def test_attendance_rejects_explicit_pool_event_from_another_programme() -> None:
    fake_db = FakeResidentSession()
    event = fake_db._event(  # noqa: SLF001
        str(uuid4()),
        "TTSHCardio",
        "Shared Pool Display",
        fake_db.today - timedelta(days=5),
        teaching_name_id=str(uuid4()),
        source_reporting_period_id=fake_db.period_id,
        source_programme_code="REHAB",
    )
    fake_db.events.append(event)
    before_attendance = list(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [event["id"]]},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Teaching event is not visible for this resident"
    assert fake_db.attendance == before_attendance


def test_attendance_accepts_explicit_global_event_without_teaching_target() -> None:
    fake_db = FakeResidentSession()
    fake_db.teaching_targets = []
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.global_event_id]},
    )

    assert response.status_code == 200
    assert response.json()["submitted"] == 1
    assert any(
        row["resident_id"] == fake_db.resident_id
        and row["teaching_event_id"] == fake_db.global_event_id
        for row in fake_db.attendance
    )


def test_scheduled_attendance_commit_failure_rolls_back_full_batch_and_returns_no_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = FakeResidentSession()
    first = _add_scheduled_event(
        fake_db,
        event_date=fake_db.today - timedelta(days=3),
        start_time=time(8, 0),
        end_time=time(9, 0),
    )
    second = _add_scheduled_event(
        fake_db,
        event_date=fake_db.today - timedelta(days=4),
        start_time=time(14, 0),
        end_time=time(15, 0),
    )
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
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [first["id"], second["id"]]},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"
    assert "submitted" not in response.json()
    assert fake_db.commits == 1
    assert fake_db.rollbacks == 1
    assert fake_db.transaction_state() == initial
    assert cache_calls == []


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


def test_attendance_cache_failure_after_commit_is_best_effort(
    monkeypatch,
    caplog,
) -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    def _fail_cache_invalidation(*_args, **_kwargs) -> None:
        raise RuntimeError("cache backend unavailable")

    monkeypatch.setattr(
        "app.services.cache_invalidation.invalidate_cache",
        _fail_cache_invalidation,
    )

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.event_id]},
    )

    assert response.status_code == 200
    assert response.json()["submitted"] == 1
    assert fake_db.commits == 1
    assert "resident_attendance_cache_invalidation_failed" in caplog.text
    assert "cache backend unavailable" not in caplog.text


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


def test_audit_reproduction_rejects_distinct_event_with_exact_same_interval() -> None:
    fake_db = FakeResidentSession()
    existing_event = next(
        row for row in fake_db.events if row["id"] == fake_db.second_event_id
    )
    later_event = _add_scheduled_event(
        fake_db,
        event_date=existing_event["event_date"],
        start_time=existing_event["start_time"],
        end_time=existing_event["end_time"],
    )
    attendance_before = [dict(row) for row in fake_db.attendance]
    earlier_attendance_before = dict(fake_db.attendance[0])
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [later_event["id"]]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Attendance overlaps an earlier accepted event"
    assert fake_db.attendance == attendance_before
    assert fake_db.attendance[0] == earlier_attendance_before
    assert not any(
        row["teaching_event_id"] == later_event["id"] for row in fake_db.attendance
    )


@pytest.mark.parametrize(
    ("new_start", "new_end"),
    [
        (time(10, 30), time(11, 30)),
        (time(9, 30), time(10, 30)),
        (time(10, 15), time(10, 45)),
        (time(9, 30), time(11, 30)),
    ],
    ids=["starts-during", "ends-during", "contained", "contains-existing"],
)
def test_distinct_event_overlap_shapes_are_rejected(
    new_start: time,
    new_end: time,
) -> None:
    fake_db = FakeResidentSession()
    existing_event = next(
        row for row in fake_db.events if row["id"] == fake_db.second_event_id
    )
    later_event = _add_scheduled_event(
        fake_db,
        event_date=existing_event["event_date"],
        start_time=new_start,
        end_time=new_end,
    )
    attendance_before = [dict(row) for row in fake_db.attendance]
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [later_event["id"]]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Attendance overlaps an earlier accepted event"
    assert fake_db.attendance == attendance_before


@pytest.mark.parametrize(
    ("new_start", "new_end"),
    [
        (time(11, 0), time(12, 0)),
        (time(9, 0), time(10, 0)),
    ],
    ids=["starts-at-existing-end", "ends-at-existing-start"],
)
def test_adjacent_distinct_events_are_allowed(
    new_start: time,
    new_end: time,
) -> None:
    fake_db = FakeResidentSession()
    existing_event = next(
        row for row in fake_db.events if row["id"] == fake_db.second_event_id
    )
    adjacent_event = _add_scheduled_event(
        fake_db,
        event_date=existing_event["event_date"],
        start_time=new_start,
        end_time=new_end,
    )
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [adjacent_event["id"]]},
    )

    assert response.status_code == 200
    assert response.json()["submitted"] == 1
    assert any(
        row["resident_id"] == fake_db.resident_id
        and row["teaching_event_id"] == adjacent_event["id"]
        for row in fake_db.attendance
    )


def test_same_interval_on_different_date_is_allowed() -> None:
    fake_db = FakeResidentSession()
    existing_event = next(
        row for row in fake_db.events if row["id"] == fake_db.second_event_id
    )
    other_date_event = _add_scheduled_event(
        fake_db,
        event_date=existing_event["event_date"] + timedelta(days=1),
        start_time=existing_event["start_time"],
        end_time=existing_event["end_time"],
    )
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [other_date_event["id"]]},
    )

    assert response.status_code == 200
    assert any(
        row["resident_id"] == fake_db.resident_id
        and row["teaching_event_id"] == other_date_event["id"]
        for row in fake_db.attendance
    )


def test_same_interval_for_different_resident_is_allowed() -> None:
    fake_db = FakeResidentSession()
    other_posting = next(
        row
        for row in fake_db.resident_postings
        if row["resident_id"] == fake_db.other_resident_id
    )
    other_posting["posting_code"] = "TTSHCardio"
    existing_event = next(
        row for row in fake_db.events if row["id"] == fake_db.second_event_id
    )
    other_resident_event = _add_scheduled_event(
        fake_db,
        event_date=existing_event["event_date"],
        start_time=existing_event["start_time"],
        end_time=existing_event["end_time"],
    )
    headers = {
        **_headers(fake_db),
        "X-User-Id": fake_db.other_resident_id,
    }
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=headers,
        json={"event_ids": [other_resident_event["id"]]},
    )

    assert response.status_code == 200
    assert any(
        row["resident_id"] == fake_db.other_resident_id
        and row["teaching_event_id"] == other_resident_event["id"]
        for row in fake_db.attendance
    )


@pytest.mark.parametrize("prior_status", ["removed", "flagged"])
def test_non_active_distinct_prior_attendance_does_not_block_submission(
    prior_status: str,
) -> None:
    fake_db = FakeResidentSession()
    fake_db.attendance[0]["status"] = prior_status
    existing_event = next(
        row for row in fake_db.events if row["id"] == fake_db.second_event_id
    )
    later_event = _add_scheduled_event(
        fake_db,
        event_date=existing_event["event_date"],
        start_time=existing_event["start_time"],
        end_time=existing_event["end_time"],
    )
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [later_event["id"]]},
    )

    assert response.status_code == 200
    assert fake_db.attendance[0]["status"] == prior_status
    assert any(
        row["resident_id"] == fake_db.resident_id
        and row["teaching_event_id"] == later_event["id"]
        for row in fake_db.attendance
    )


def test_same_event_repeated_within_batch_is_rejected_atomically() -> None:
    fake_db = FakeResidentSession()
    attendance_before = [dict(row) for row in fake_db.attendance]
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.event_id, fake_db.event_id]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Attendance already submitted for this teaching event"
    assert fake_db.attendance == attendance_before


def test_overlapping_events_within_batch_are_rejected_atomically_in_request_order() -> None:
    fake_db = FakeResidentSession()
    event_date = fake_db.today - timedelta(days=1)
    earlier_request_event = _add_scheduled_event(
        fake_db,
        event_date=event_date,
        start_time=time(8, 0),
        end_time=time(10, 0),
    )
    later_request_event = _add_scheduled_event(
        fake_db,
        event_date=event_date,
        start_time=time(9, 0),
        end_time=time(11, 0),
    )
    attendance_before = [dict(row) for row in fake_db.attendance]
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [earlier_request_event["id"], later_request_event["id"]]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Attendance overlaps an earlier accepted event"
    assert fake_db.attendance == attendance_before
    assert not any(
        row["teaching_event_id"]
        in {earlier_request_event["id"], later_request_event["id"]}
        for row in fake_db.attendance
    )


def test_earlier_overlap_conflict_precedes_later_eligibility_error() -> None:
    fake_db = FakeResidentSession()
    existing_event = next(
        row for row in fake_db.events if row["id"] == fake_db.second_event_id
    )
    overlapping_event = _add_scheduled_event(
        fake_db,
        event_date=existing_event["event_date"],
        start_time=existing_event["start_time"],
        end_time=existing_event["end_time"],
    )
    attendance_before = [dict(row) for row in fake_db.attendance]
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [overlapping_event["id"], fake_db.future_event_id]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Attendance overlaps an earlier accepted event"
    assert fake_db.attendance == attendance_before


def test_non_overlapping_batch_preserves_request_order() -> None:
    fake_db = FakeResidentSession()
    event_date = fake_db.today - timedelta(days=1)
    later_event = _add_scheduled_event(
        fake_db,
        event_date=event_date,
        start_time=time(12, 0),
        end_time=time(13, 0),
    )
    earlier_event = _add_scheduled_event(
        fake_db,
        event_date=event_date,
        start_time=time(8, 0),
        end_time=time(9, 0),
    )
    requested_ids = [later_event["id"], earlier_event["id"]]
    attendance_count_before = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": requested_ids},
    )

    assert response.status_code == 200
    assert response.json()["submitted"] == 2
    assert [row["id"] for row in response.json()["submitted_events"]] == requested_ids
    assert [
        row["teaching_event_id"] for row in fake_db.attendance[attendance_count_before:]
    ] == requested_ids
    assert fake_db.teaching_event_lock_calls == sorted(requested_ids)
    assert len(fake_db.native_attendance_lock_calls) == 1


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
    event = next(
        row for row in fake_db.events if row["id"] == fake_db.other_posting_event_id
    )
    event.update(
        {
            "teaching_name_id": str(uuid4()),
            "source_reporting_period_id": fake_db.period_id,
            "source_programme_code": "REHAB",
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
    ktph_event = fake_db._event(  # noqa: SLF001
        str(uuid4()),
        "KTPHGerMed",
        "KTPH Teaching",
        fake_db.today - timedelta(days=1),
        teaching_name_id=str(uuid4()),
        source_reporting_period_id=fake_db.period_id,
        source_programme_code="GRM",
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
    # Keep the derived Saturday distinct from the pre-existing ``today - 2`` event.
    fake_db = FakeResidentSession(today=date(2026, 7, 29))
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


def test_legacy_weekend_exception_uses_persisted_session_type() -> None:
    fake_db = FakeResidentSession(today=date(2026, 7, 29))
    legacy_event = next(
        event for event in fake_db.events if event["id"] == fake_db.weekend_event_id
    )
    assert legacy_event["teaching_name_id"] is None
    assert legacy_event["global_session_type_id"] is None
    fake_db.weekend_exceptions.append(
        {
            "programme_code": "GRM",
            "posting_code": "TTSHCardio",
            "day_type": "sat",
            "start_time_min": None,
            "end_time_max": None,
            "session_type_id": fake_db.session_type_id,
            "session_name_pattern": None,
            "mutates_to_session_type_id": None,
            "adjusted_duration_hours": None,
        }
    )
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.weekend_event_id]},
    )

    assert response.status_code == 200
    assert response.json()["submitted"] == 1
    assert response.json()["compliance_warning"] is None


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


def test_native_attendance_removal_commit_failure_rolls_back_and_returns_no_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = FakeResidentSession()
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

    response = client.delete(
        f"/resident/attendance/{fake_db.existing_attendance_id}",
        headers=_headers(fake_db),
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"
    assert "removed_count" not in response.json()
    assert fake_db.commits == 1
    assert fake_db.rollbacks == 1
    assert fake_db.transaction_state() == initial
    assert cache_calls == []


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


def test_removed_scheduled_attendance_resubmission_creates_new_history_row() -> None:
    fake_db = FakeResidentSession()
    fake_db.attendance[0]["status"] = "removed"
    removed_id = fake_db.attendance[0]["id"]
    before_count = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.second_event_id]},
    )

    assert response.status_code == 200
    assert response.json()["submitted"] == 1
    assert len(fake_db.attendance) == before_count + 1
    removed = next(row for row in fake_db.attendance if row["id"] == removed_id)
    submitted = [
        row
        for row in fake_db.attendance
        if row["resident_id"] == fake_db.resident_id
        and row["teaching_event_id"] == fake_db.second_event_id
        and row["status"] == "submitted"
    ]
    assert removed["status"] == "removed"
    assert len(submitted) == 1
    assert submitted[0]["id"] != removed_id


def test_stale_removed_attendance_id_cannot_remove_new_resubmission() -> None:
    fake_db = FakeResidentSession()
    fake_db.attendance[0]["status"] = "removed"
    removed_id = fake_db.attendance[0]["id"]
    client = _client(fake_db)

    submitted_response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [fake_db.second_event_id]},
    )
    active = next(
        row
        for row in fake_db.attendance
        if row["resident_id"] == fake_db.resident_id
        and row["teaching_event_id"] == fake_db.second_event_id
        and row["status"] == "submitted"
    )
    removal_response = client.delete(
        f"/resident/attendance/{removed_id}",
        headers=_headers(fake_db),
    )

    assert submitted_response.status_code == 200
    assert active["id"] != removed_id
    assert removal_response.status_code == 200
    assert removal_response.json()["removed_count"] == 0
    assert active["status"] == "submitted"
    assert fake_db.native_attendance_removal_lock_calls == [removed_id]


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
    assert response.json()["detail"] == "No active reporting period is available for the teaching event date"
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
