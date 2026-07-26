from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
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


def _external_headers(fake_db: FakeResidentSession) -> dict[str, str]:
    return {
        "X-User-Role": "external_resident",
        "X-User-Id": fake_db.external_resident_id,
    }


def _external_schedule_row(
    fake_db: FakeResidentSession,
    *,
    programme_code: str | None,
    posting_code: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    return {
        "id": str(uuid4()),
        "external_resident_id": fake_db.external_resident_id,
        "programme_code": programme_code,
        "posting_code": posting_code,
        "start_date": start_date or fake_db.today - timedelta(days=30),
        "end_date": end_date,
        "is_current": end_date is None or fake_db.today <= end_date,
    }


def _programme_event(
    fake_db: FakeResidentSession,
    *,
    programme_code: str,
    posting_code: str,
    teaching_name: str,
    event_date: date | None = None,
) -> dict:
    event = fake_db._event(  # noqa: SLF001
        str(uuid4()),
        posting_code,
        teaching_name,
        event_date or fake_db.today - date.resolution,
    )
    event["created_by_role"] = "programme_pc"
    event["created_for_programme_code"] = programme_code
    fake_db.events.append(event)
    return event


def _set_secretary_support(
    fake_db: FakeResidentSession,
    posting_code: str,
    *,
    enabled: bool,
) -> None:
    posting = next(row for row in fake_db.posting_codes if row["code"] == posting_code)
    posting["supports_secretary_events"] = enabled


def test_external_events_visible_when_supports_secretary_events_true() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_external_headers(fake_db))

    assert response.status_code == 200
    events = response.json()["events"]
    ids = {row["id"] for row in events}
    assert fake_db.event_id in ids
    assert all("created_by_role" not in row for row in events)


def test_external_events_use_date_matched_posting_schedule() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_residents[0]["current_nhg_posting_code"] = "TTSHCardio"
    fake_db.external_resident_postings = [
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "programme_code": "GERI",
            "posting_code": "TTSHNeuro",
            "start_date": fake_db.today - date.resolution,
            "end_date": fake_db.today + date.resolution,
            "is_current": True,
        }
    ]
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_external_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.other_posting_event_id in ids
    assert fake_db.event_id not in ids


def test_external_events_accept_verified_external_identity_without_raw_headers() -> None:
    fake_db = FakeResidentSession()
    client = _client(
        fake_db,
        identity=AuthIdentity(
            role="external_resident",
            subject_id=fake_db.external_resident_id,
            home_cluster="NUH",
        ),
    )

    response = client.get("/resident/events")

    assert response.status_code == 200
    assert fake_db.event_id in {row["id"] for row in response.json()["events"]}


def test_external_events_hidden_when_supports_secretary_events_false() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_residents[0]["current_nhg_posting_code"] = "KTPHGerMed"
    fake_db.external_resident_postings = [
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "programme_code": "GERI",
            "posting_code": "KTPHGerMed",
            "start_date": date(2026, 5, 1),
            "end_date": None,
            "is_current": True,
        }
    ]
    fake_db.events.append(
        fake_db._event(  # noqa: SLF001
            str(uuid4()),
            "KTPHGerMed",
            "Secretary Teaching",
            date(2026, 5, 18),
            duration_hours=Decimal("1.0"),
        )
    )
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_external_headers(fake_db))

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"] == []
    assert payload["reason"] == "secretary_events_not_supported"
    assert len(payload["active_reporting_periods"]) == 1


def test_external_events_exclude_already_submitted_records() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_external_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.second_event_id not in ids


def test_external_event_visibility_does_not_require_teaching_name_catalogue() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_residents[0]["current_nhg_posting_code"] = "KTPHGerMed"
    fake_db.external_resident_postings = [
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "programme_code": "GERI",
            "posting_code": "KTPHGerMed",
            "start_date": date(2026, 5, 1),
            "end_date": None,
            "is_current": True,
        }
    ]
    for row in fake_db.posting_codes:
        if row["code"] == "KTPHGerMed":
            row["supports_secretary_events"] = True
    event_id = str(uuid4())
    event = fake_db._event(event_id, "KTPHGerMed", "Unmapped External Event", date(2026, 5, 18))  # noqa: SLF001
    event["created_by_role"] = "secretary"
    fake_db.events.append(event)
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_external_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert event_id in ids


def test_external_attendance_creates_external_record_only() -> None:
    fake_db = FakeResidentSession()
    before_external = len(fake_db.external_attendance)
    before_native = len(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [fake_db.event_id]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["submitted"] == 1
    assert all("created_by_role" not in row for row in payload["submitted_events"])
    assert len(fake_db.external_attendance) == before_external + 1
    assert len(fake_db.attendance) == before_native


def test_external_legacy_null_role_secretary_event_is_visible_and_submittable() -> None:
    fake_db = FakeResidentSession()
    event_id = str(uuid4())
    event = fake_db._event(  # noqa: SLF001
        event_id,
        "TTSHCardio",
        "Legacy Teaching",
        fake_db.today - date.resolution,
    )
    event["created_by_role"] = None
    fake_db.events.append(event)
    client = _client(fake_db)

    list_response = client.get("/resident/events", headers=_external_headers(fake_db))
    submit_response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [event_id]},
    )

    assert list_response.status_code == 200
    assert event_id in {row["id"] for row in list_response.json()["events"]}
    assert submit_response.status_code == 200
    assert any(row["teaching_event_id"] == event_id for row in fake_db.external_attendance)


def test_external_geri_schedule_lists_secretary_and_exact_programme_events() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings = [
        _external_schedule_row(
            fake_db,
            programme_code="GERI",
            posting_code="TTSHGerMed",
        )
    ]
    _set_secretary_support(fake_db, "TTSHGerMed", enabled=True)
    secretary_event = fake_db._event(  # noqa: SLF001
        str(uuid4()),
        "TTSHGerMed",
        "Secretary GERI Teaching",
        fake_db.today - date.resolution,
    )
    fake_db.events.append(secretary_event)
    programme_event = _programme_event(
        fake_db,
        programme_code="GERI",
        posting_code="TTSHGerMed",
        teaching_name="GERI PC Teaching",
    )
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_external_headers(fake_db))

    assert response.status_code == 200
    event_ids = {row["id"] for row in response.json()["events"]}
    assert secretary_event["id"] in event_ids
    assert programme_event["id"] in event_ids


def test_external_can_submit_exact_programme_event_to_external_attendance_only() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings = [
        _external_schedule_row(
            fake_db,
            programme_code="GERI",
            posting_code="TTSHGerMed",
        )
    ]
    programme_event = _programme_event(
        fake_db,
        programme_code="GERI",
        posting_code="TTSHGerMed",
        teaching_name="GERI PC Teaching",
    )
    before_external = len(fake_db.external_attendance)
    before_native = list(fake_db.attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [programme_event["id"]]},
    )

    assert response.status_code == 200
    assert response.json()["submitted"] == 1
    assert len(fake_db.external_attendance) == before_external + 1
    assert fake_db.external_attendance[-1]["teaching_event_id"] == programme_event["id"]
    assert fake_db.external_attendance[-1]["posting_code"] == "TTSHGerMed"
    assert fake_db.attendance == before_native


def test_external_programme_event_does_not_depend_on_secretary_capability() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings = [
        _external_schedule_row(
            fake_db,
            programme_code="GERI",
            posting_code="TTSHGerMed",
        )
    ]
    _set_secretary_support(fake_db, "TTSHGerMed", enabled=False)
    programme_event = _programme_event(
        fake_db,
        programme_code="GERI",
        posting_code="TTSHGerMed",
        teaching_name="GERI PC Teaching Without Secretary Support",
    )
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_external_headers(fake_db))

    assert response.status_code == 200
    assert programme_event["id"] in {row["id"] for row in response.json()["events"]}


def test_external_null_role_programme_event_uses_exact_owner_scope() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings = [
        _external_schedule_row(
            fake_db,
            programme_code="GERI",
            posting_code="TTSHGerMed",
        )
    ]
    _set_secretary_support(fake_db, "TTSHGerMed", enabled=False)
    programme_event = _programme_event(
        fake_db,
        programme_code="GERI",
        posting_code="TTSHGerMed",
        teaching_name="Legacy GERI PC Teaching",
    )
    programme_event["created_by_role"] = None
    client = _client(fake_db)

    listed = client.get("/resident/events", headers=_external_headers(fake_db))
    submitted = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [programme_event["id"]]},
    )

    assert listed.status_code == 200
    assert programme_event["id"] in {row["id"] for row in listed.json()["events"]}
    assert submitted.status_code == 200


def test_external_rejects_other_programme_and_other_posting_pc_events() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings = [
        _external_schedule_row(
            fake_db,
            programme_code="GERI",
            posting_code="TTSHGerMed",
        )
    ]
    other_programme_event = _programme_event(
        fake_db,
        programme_code="IM",
        posting_code="TTSHGerMed",
        teaching_name="IM PC Teaching",
    )
    other_posting_event = _programme_event(
        fake_db,
        programme_code="GERI",
        posting_code="TTSHCardio",
        teaching_name="GERI PC Teaching Elsewhere",
    )
    before_external = list(fake_db.external_attendance)
    client = _client(fake_db)

    listed = client.get("/resident/events", headers=_external_headers(fake_db))
    other_programme_submit = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [other_programme_event["id"]]},
    )
    other_posting_submit = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [other_posting_event["id"]]},
    )

    assert listed.status_code == 200
    listed_ids = {row["id"] for row in listed.json()["events"]}
    assert other_programme_event["id"] not in listed_ids
    assert other_posting_event["id"] not in listed_ids
    assert other_programme_submit.status_code == 422
    assert other_posting_submit.status_code == 422
    assert fake_db.external_attendance == before_external


def test_external_programme_event_outside_schedule_dates_is_unavailable() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings = [
        _external_schedule_row(
            fake_db,
            programme_code="GERI",
            posting_code="TTSHGerMed",
            start_date=fake_db.today - timedelta(days=20),
            end_date=fake_db.today - timedelta(days=10),
        )
    ]
    programme_event = _programme_event(
        fake_db,
        programme_code="GERI",
        posting_code="TTSHGerMed",
        teaching_name="Outside Schedule PC Teaching",
    )
    client = _client(fake_db)

    listed = client.get("/resident/events", headers=_external_headers(fake_db))
    submitted = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [programme_event["id"]]},
    )

    assert listed.status_code == 200
    assert programme_event["id"] not in {row["id"] for row in listed.json()["events"]}
    assert submitted.status_code == 422


def test_external_programme_event_in_schedule_gap_is_unavailable() -> None:
    fake_db = FakeResidentSession()
    event_date = fake_db.today - timedelta(days=5)
    fake_db.external_resident_postings = [
        _external_schedule_row(
            fake_db,
            programme_code="GERI",
            posting_code="TTSHGerMed",
            start_date=fake_db.today - timedelta(days=20),
            end_date=fake_db.today - timedelta(days=6),
        ),
        _external_schedule_row(
            fake_db,
            programme_code="GERI",
            posting_code="TTSHGerMed",
            start_date=fake_db.today - timedelta(days=4),
            end_date=None,
        ),
    ]
    programme_event = _programme_event(
        fake_db,
        programme_code="GERI",
        posting_code="TTSHGerMed",
        teaching_name="Gap PC Teaching",
        event_date=event_date,
    )
    client = _client(fake_db)

    listed = client.get("/resident/events", headers=_external_headers(fake_db))
    submitted = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [programme_event["id"]]},
    )

    assert listed.status_code == 200
    assert programme_event["id"] not in {row["id"] for row in listed.json()["events"]}
    assert submitted.status_code == 422


def test_external_scheduled_flow_rejects_another_residents_adhoc_event() -> None:
    fake_db = FakeResidentSession()
    adhoc_event = fake_db._event(  # noqa: SLF001
        str(uuid4()),
        "TTSHCardio",
        "Another Resident Ad-hoc Teaching",
        fake_db.today - date.resolution,
    )
    adhoc_event["is_adhoc"] = True
    adhoc_event["created_by_role"] = "external_resident"
    fake_db.events.append(adhoc_event)
    before_external = list(fake_db.external_attendance)
    client = _client(fake_db)

    listed = client.get("/resident/events", headers=_external_headers(fake_db))
    submitted = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [adhoc_event["id"]]},
    )

    assert listed.status_code == 200
    assert adhoc_event["id"] not in {row["id"] for row in listed.json()["events"]}
    assert submitted.status_code == 422
    assert fake_db.external_attendance == before_external


def test_external_already_submitted_programme_event_is_hidden_and_rejected() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings = [
        _external_schedule_row(
            fake_db,
            programme_code="GERI",
            posting_code="TTSHGerMed",
        )
    ]
    programme_event = _programme_event(
        fake_db,
        programme_code="GERI",
        posting_code="TTSHGerMed",
        teaching_name="Submitted GERI PC Teaching",
    )
    fake_db.external_attendance.append(
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "teaching_event_id": programme_event["id"],
            "status": "submitted",
            "posting_code": "TTSHGerMed",
            "submitted_at": fake_db.now,
        }
    )
    client = _client(fake_db)

    listed = client.get("/resident/events", headers=_external_headers(fake_db))
    submitted = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [programme_event["id"]]},
    )

    assert listed.status_code == 200
    assert programme_event["id"] not in {row["id"] for row in listed.json()["events"]}
    assert submitted.status_code == 409


def test_external_rejects_later_distinct_event_that_overlaps_accepted_event() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings = [
        _external_schedule_row(
            fake_db,
            programme_code="GERI",
            posting_code="TTSHGerMed",
        )
    ]
    accepted_event = _programme_event(
        fake_db,
        programme_code="GERI",
        posting_code="TTSHGerMed",
        teaching_name="Accepted GERI Teaching",
    )
    later_event = _programme_event(
        fake_db,
        programme_code="GERI",
        posting_code="TTSHGerMed",
        teaching_name="Overlapping GERI Teaching",
    )
    fake_db.external_attendance.append(
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "teaching_event_id": accepted_event["id"],
            "status": "submitted",
            "posting_code": "TTSHGerMed",
            "submitted_at": fake_db.now,
        }
    )
    before_external = list(fake_db.external_attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [later_event["id"]]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Attendance overlaps an earlier accepted event"
    assert fake_db.external_attendance == before_external


def _assert_shared_posting_programme_isolation(
    *,
    resident_programme: str,
    other_programme: str,
    posting_code: str,
) -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings = [
        _external_schedule_row(
            fake_db,
            programme_code=resident_programme,
            posting_code=posting_code,
        )
    ]
    own_event = _programme_event(
        fake_db,
        programme_code=resident_programme,
        posting_code=posting_code,
        teaching_name=f"{resident_programme} Shared Posting Teaching",
    )
    other_event = _programme_event(
        fake_db,
        programme_code=other_programme,
        posting_code=posting_code,
        teaching_name=f"{other_programme} Shared Posting Teaching",
    )
    client = _client(fake_db)

    listed = client.get("/resident/events", headers=_external_headers(fake_db))
    rejected = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [other_event["id"]]},
    )

    assert listed.status_code == 200
    listed_ids = {row["id"] for row in listed.json()["events"]}
    assert own_event["id"] in listed_ids
    assert other_event["id"] not in listed_ids
    assert rejected.status_code == 422


def test_aim_does_not_see_im_events_at_shared_ttsh_general_medicine_posting() -> None:
    _assert_shared_posting_programme_isolation(
        resident_programme="AIM",
        other_programme="IM",
        posting_code="TTSHGenMed",
    )


def test_gs_does_not_see_sig_events_at_shared_ttsh_general_surgery_posting() -> None:
    _assert_shared_posting_programme_isolation(
        resident_programme="GS",
        other_programme="SIG",
        posting_code="TTSHGenSrg",
    )


def test_unresolved_legacy_programme_keeps_secretary_visibility_but_denies_pc_event() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings = [
        _external_schedule_row(
            fake_db,
            programme_code=None,
            posting_code="TTSHCardio",
        )
    ]
    secretary_event = fake_db._event(  # noqa: SLF001
        str(uuid4()),
        "TTSHCardio",
        "Secretary Teaching For Legacy Schedule",
        fake_db.today - date.resolution,
    )
    fake_db.events.append(secretary_event)
    programme_event = _programme_event(
        fake_db,
        programme_code="CARDIO",
        posting_code="TTSHCardio",
        teaching_name="CARDIO PC Teaching For Legacy Schedule",
    )
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_external_headers(fake_db))

    assert response.status_code == 200
    listed_ids = {row["id"] for row in response.json()["events"]}
    assert secretary_event["id"] in listed_ids
    assert programme_event["id"] not in listed_ids


def test_overlapping_legacy_schedule_contexts_fail_closed() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings = [
        _external_schedule_row(
            fake_db,
            programme_code="GERI",
            posting_code="TTSHGenMed",
        ),
        _external_schedule_row(
            fake_db,
            programme_code="IM",
            posting_code="TTSHGenMed",
        ),
    ]
    programme_event = _programme_event(
        fake_db,
        programme_code="GERI",
        posting_code="TTSHGenMed",
        teaching_name="Ambiguous Legacy Schedule Teaching",
    )
    before_external = list(fake_db.external_attendance)
    client = _client(fake_db)

    listed = client.get("/resident/events", headers=_external_headers(fake_db))
    submitted = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [programme_event["id"]]},
    )

    assert listed.status_code == 200
    assert programme_event["id"] not in {row["id"] for row in listed.json()["events"]}
    assert submitted.status_code == 422
    assert fake_db.external_attendance == before_external


def test_overlapping_legacy_contexts_at_different_postings_fail_closed() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_resident_postings = [
        _external_schedule_row(
            fake_db,
            programme_code="GERI",
            posting_code="TTSHGerMed",
        ),
        _external_schedule_row(
            fake_db,
            programme_code="CARDIO",
            posting_code="TTSHCardio",
        ),
    ]
    programme_event = _programme_event(
        fake_db,
        programme_code="GERI",
        posting_code="TTSHGerMed",
        teaching_name="Cross-posting Ambiguous Legacy Teaching",
    )
    before_external = list(fake_db.external_attendance)
    client = _client(fake_db)

    listed = client.get("/resident/events", headers=_external_headers(fake_db))
    submitted = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [programme_event["id"]]},
    )

    assert listed.status_code == 200
    assert programme_event["id"] not in {row["id"] for row in listed.json()["events"]}
    assert submitted.status_code == 422
    assert fake_db.external_attendance == before_external


def test_external_attendance_uses_event_date_matched_posting_schedule() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_residents[0]["current_nhg_posting_code"] = "TTSHCardio"
    event = next(row for row in fake_db.events if row["id"] == fake_db.other_posting_event_id)
    fake_db.external_resident_postings = [
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "programme_code": "GERI",
            "posting_code": "TTSHNeuro",
            "start_date": event["event_date"],
            "end_date": event["event_date"],
            "is_current": True,
        }
    ]
    before_external = len(fake_db.external_attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [fake_db.other_posting_event_id]},
    )

    assert response.status_code == 200
    assert len(fake_db.external_attendance) == before_external + 1
    assert fake_db.external_attendance[-1]["posting_code"] == "TTSHNeuro"


def test_external_duplicate_attendance_is_rejected() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [fake_db.second_event_id]},
    )

    assert response.status_code == 409


def test_external_cannot_submit_attendance_for_event_outside_current_posting() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [fake_db.other_posting_event_id]},
    )

    assert response.status_code == 422


def test_external_cannot_submit_secretary_event_when_support_disabled() -> None:
    fake_db = FakeResidentSession()
    fake_db.external_residents[0]["current_nhg_posting_code"] = "KTPHGerMed"
    fake_db.external_resident_postings = [
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "programme_code": "GERI",
            "posting_code": "KTPHGerMed",
            "start_date": date(2026, 5, 1),
            "end_date": None,
            "is_current": True,
        }
    ]
    event_id = str(uuid4())
    event = fake_db._event(event_id, "KTPHGerMed", "Secretary Teaching", date(2026, 5, 18))  # noqa: SLF001
    event["created_by_role"] = "secretary"
    fake_db.events.append(event)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [event_id]},
    )

    assert response.status_code == 422


def test_external_weekend_non_exception_stores_and_returns_warning() -> None:
    # Keep the derived Saturday distinct from the pre-existing ``today - 2`` event.
    fake_db = FakeResidentSession(today=date(2026, 7, 29))
    before = len(fake_db.external_attendance)
    client = _client(fake_db)

    response = client.post(
        "/resident/attendance",
        headers=_external_headers(fake_db),
        json={"event_ids": [fake_db.weekend_event_id]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["submitted"] == 1
    assert payload["compliance_warning"].startswith("1 session(s) submitted on a weekend")
    assert len(fake_db.external_attendance) == before + 1


def test_external_resident_can_remove_own_external_attendance() -> None:
    fake_db = FakeResidentSession()
    before_native = list(fake_db.attendance)
    client = _client(fake_db)

    response = client.delete(
        f"/resident/attendance/{fake_db.external_existing_attendance_id}",
        headers=_external_headers(fake_db),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "removed"
    assert response.json()["removed_count"] == 1
    assert next(
        row
        for row in fake_db.external_attendance
        if row["id"] == fake_db.external_existing_attendance_id
    )["status"] == "removed"
    assert fake_db.attendance == before_native


def test_external_resident_cannot_remove_another_external_residents_attendance() -> None:
    fake_db = FakeResidentSession()
    other_attendance_id = str(uuid4())
    fake_db.external_attendance.append(
        {
            "id": other_attendance_id,
            "external_resident_id": fake_db.other_external_resident_id,
            "teaching_event_id": fake_db.second_event_id,
            "status": "submitted",
            "posting_code": "TTSHCardio",
            "submitted_at": fake_db.now,
        }
    )
    client = _client(fake_db)

    response = client.delete(
        f"/resident/attendance/{other_attendance_id}",
        headers=_external_headers(fake_db),
    )

    assert response.status_code == 404
    assert next(row for row in fake_db.external_attendance if row["id"] == other_attendance_id)[
        "status"
    ] == "submitted"
