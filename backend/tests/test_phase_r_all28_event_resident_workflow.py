"""Focused in-memory Phase R event, resident, and resolver workflow coverage.

The test exercises the existing router/service paths with the established test
sessions.  It deliberately does not claim PostgreSQL policy or RLS evidence;
that remains covered by the restricted Phase R/PostgreSQL suite.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID, uuid5

import pytest

from app.services.teaching_target_resolution import (
    MappedTargetResolution,
    PendingMappingResolution,
    resolve_native_teaching_target,
)
from tests.phase_r_readiness_fixtures import synthetic_posting_code
from tests.phase_r_readiness_manifest import (
    PROGRAMME_READINESS_EXPECTATIONS,
    ProgrammeReadinessExpectation,
)
from tests.resident_fakes import FakeResidentSession
from tests.test_programme_teaching_events import (
    FakeProgrammeTeachingEventsSession,
    _client as programme_pc_client,
    _headers as programme_pc_headers,
)
from tests.test_resident_attendance import _client as resident_client
from tests.test_secretary_events import (
    FakeSecretarySession,
    _client as secretary_client,
    _headers as secretary_headers,
)
from tests.test_teaching_target_resolution import _ReadOnlyDb


_WORKFLOW_NAMESPACE = UUID("7d92d0af-9b1d-46c8-9e5b-4e5dc6c3779f")
_EVENT_DATE = date(2026, 5, 18)


def _other_programme(
    expectation: ProgrammeReadinessExpectation,
) -> ProgrammeReadinessExpectation:
    return next(
        candidate
        for candidate in PROGRAMME_READINESS_EXPECTATIONS
        if candidate.code != expectation.code
    )


def _pool_name(expectation: ProgrammeReadinessExpectation, state: str) -> str:
    return f"Phase R {expectation.code} {state} pool teaching"


def _secretary_session(
    expectation: ProgrammeReadinessExpectation,
    *,
    capability_active: bool = True,
    include_capability: bool = True,
    capability_programme_code: str | None = None,
) -> tuple[FakeSecretarySession, str]:
    """Configure the existing Secretary fake with one synthetic pool source."""

    session = FakeSecretarySession()
    posting_code = synthetic_posting_code(expectation.code)
    teaching_name_id = str(uuid5(_WORKFLOW_NAMESPACE, f"secretary/{expectation.code}"))
    session.teaching_names = [
        {
            "id": teaching_name_id,
            "display_name": _pool_name(expectation, "secretary"),
            "programme_code": expectation.code,
            "reporting_period_id": session.reporting_period_id,
            "is_active": True,
        }
    ]
    session.secretary_programme_pools = (
        [
            {
                "posting_code": posting_code,
                "programme_code": capability_programme_code or expectation.code,
                "is_active": capability_active,
                "can_manage_teaching_names": True,
            }
        ]
        if include_capability
        else []
    )
    return session, teaching_name_id


def _secretary_event_request(teaching_name_id: str, *, start_time: str) -> dict[str, object]:
    return {
        "teaching_name_id": teaching_name_id,
        "event_date": _EVENT_DATE.isoformat(),
        "start_time": start_time,
        "cme_points_awarded": False,
        "smc_event_code": None,
    }


def _programme_pc_session(
    expectation: ProgrammeReadinessExpectation,
) -> tuple[FakeProgrammeTeachingEventsSession, str, str, str]:
    """Configure pending/mapped sources in the existing PC event fake."""

    session = FakeProgrammeTeachingEventsSession()
    other = _other_programme(expectation)
    posting_code = synthetic_posting_code(expectation.code)
    other_posting_code = synthetic_posting_code(other.code)
    pending_name = session._teaching_name(_pool_name(expectation, "pending"), expectation.code)  # noqa: SLF001
    mapped_name = session._teaching_name(_pool_name(expectation, "mapped"), expectation.code)  # noqa: SLF001
    other_name = session._teaching_name(_pool_name(other, "cross"), other.code)  # noqa: SLF001
    session.teaching_names = [pending_name, mapped_name, other_name]
    session.teaching_name_mappings = [
        session._mapping_scope(  # noqa: SLF001
            teaching_name_id=pending_name["id"],
            posting_code=posting_code,
        ),
        session._mapping_scope(  # noqa: SLF001
            teaching_name_id=mapped_name["id"],
            posting_code=posting_code,
            teaching_target_id=str(uuid5(_WORKFLOW_NAMESPACE, f"target/{expectation.code}")),
        ),
        session._mapping_scope(  # noqa: SLF001
            teaching_name_id=other_name["id"],
            posting_code=other_posting_code,
        ),
    ]
    for mapping in session.teaching_name_mappings:
        mapping["r_year"] = expectation.expected_fixture_r_years[0]
    session.secretary_programme_pools = [
        {"posting_code": posting_code, "programme_code": expectation.code, "is_active": True},
        {"posting_code": other_posting_code, "programme_code": other.code, "is_active": True},
    ]
    session.events = []
    session.attendance_event_ids = set()
    session.external_attendance_event_ids = set()
    session.attendance_statuses = {}
    session.external_attendance_statuses = {}
    return session, pending_name["id"], mapped_name["id"], other_name["id"]


def _programme_pc_event_request(
    expectation: ProgrammeReadinessExpectation,
    *,
    teaching_name_id: str,
    start_time: str,
) -> dict[str, object]:
    return {
        "programme_code": expectation.code,
        "posting_code": synthetic_posting_code(expectation.code),
        "teaching_name_id": teaching_name_id,
        "event_date": _EVENT_DATE.isoformat(),
        "start_time": start_time,
        "cme_points_awarded": False,
        "smc_event_code": None,
    }


def _prior_weekday(today: date) -> date:
    candidate = today - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _resident_session(
    expectation: ProgrammeReadinessExpectation,
) -> tuple[FakeResidentSession, dict[str, object], dict[str, object], dict[str, object]]:
    """Adapt the established native Resident fake to one canonical programme."""

    session = FakeResidentSession()
    other = _other_programme(expectation)
    posting_code = synthetic_posting_code(expectation.code)
    r_year = expectation.expected_fixture_r_years[0]
    event_date = _prior_weekday(session.today)
    mapped_date = event_date - timedelta(days=1)
    resident = session.residents[0]
    resident["programme_code"] = expectation.code
    resident["r_year"] = r_year
    session.residents = [resident]
    session.programmes = [
        {
            "code": expectation.code,
            "name": expectation.name,
            "native_teaching_posting_code": None,
        }
    ]
    session.posting_codes = [
        {
            "code": posting_code,
            "display_name": posting_code,
            "institution": None,
            "supports_secretary_events": True,
        }
    ]
    session.resident_postings = [
        {
            "resident_id": session.resident_id,
            "reporting_period_id": session.period_id,
            "posting_code": posting_code,
            "r_year": r_year,
            "start_date": mapped_date - timedelta(days=7),
            "end_date": session.today + timedelta(days=7),
            "status": "active",
        }
    ]
    pending_event = session._event(  # noqa: SLF001
        str(uuid5(_WORKFLOW_NAMESPACE, f"resident/{expectation.code}/pending")),
        posting_code,
        _pool_name(expectation, "pending"),
        event_date,
        teaching_name_id=str(uuid5(_WORKFLOW_NAMESPACE, f"name/{expectation.code}/pending")),
        source_reporting_period_id=session.period_id,
        source_programme_code=expectation.code,
    )
    mapped_event = session._event(  # noqa: SLF001
        str(uuid5(_WORKFLOW_NAMESPACE, f"resident/{expectation.code}/mapped")),
        posting_code,
        _pool_name(expectation, "mapped"),
        mapped_date,
        teaching_name_id=str(uuid5(_WORKFLOW_NAMESPACE, f"name/{expectation.code}/mapped")),
        source_reporting_period_id=session.period_id,
        source_programme_code=expectation.code,
    )
    cross_programme_event = session._event(  # noqa: SLF001
        str(uuid5(_WORKFLOW_NAMESPACE, f"resident/{expectation.code}/cross")),
        posting_code,
        _pool_name(other, "cross"),
        event_date,
        teaching_name_id=str(uuid5(_WORKFLOW_NAMESPACE, f"name/{other.code}/cross")),
        source_reporting_period_id=session.period_id,
        source_programme_code=other.code,
    )
    for event in (pending_event, mapped_event):
        event["created_by_role"] = "programme_pc"
        event["created_for_programme_code"] = expectation.code
    cross_programme_event["created_by_role"] = "programme_pc"
    cross_programme_event["created_for_programme_code"] = other.code
    session.events = [pending_event, mapped_event, cross_programme_event]
    session.attendance = []
    session.external_attendance = []
    session.teaching_targets = []
    session.global_session_types = []
    return session, pending_event, mapped_event, cross_programme_event


def _resident_headers(
    session: FakeResidentSession,
    expectation: ProgrammeReadinessExpectation,
) -> dict[str, str]:
    return {
        "X-User-Role": "resident",
        "X-User-Id": session.resident_id,
        "X-User-Programme": expectation.code,
    }


@pytest.mark.parametrize(
    "expectation",
    PROGRAMME_READINESS_EXPECTATIONS,
    ids=lambda expectation: expectation.code,
)
def test_phase_r_all_28_secretary_capability_controls_pool_event_provenance_and_timing(
    expectation: ProgrammeReadinessExpectation,
) -> None:
    session, teaching_name_id = _secretary_session(expectation)
    posting_code = synthetic_posting_code(expectation.code)
    created = secretary_client(session).post(
        "/secretary/teaching-events",
        headers=secretary_headers(session, site=posting_code),
        json=_secretary_event_request(teaching_name_id, start_time="23:00"),
    )

    assert created.status_code == 200
    payload = created.json()
    assert payload["posting_code"] == posting_code
    assert payload["teaching_name_id"] == teaching_name_id
    assert payload["global_session_type_id"] is None
    assert payload["source_programme_code"] == expectation.code
    assert payload["source_reporting_period_id"] == session.reporting_period_id
    assert payload["created_for_programme_code"] is None
    assert payload["duration_hours"] == "1.00"
    assert payload["end_time"] == "00:00:00"
    assert session.audit_logs[-1]["action"] == "secretary.teaching_event.create"

    too_late = secretary_client(session).post(
        "/secretary/teaching-events",
        headers=secretary_headers(session, site=posting_code),
        json=_secretary_event_request(teaching_name_id, start_time="23:01"),
    )
    assert too_late.status_code == 422

    denied_setups = (
        {"capability_active": False},
        {"include_capability": False},
        {"capability_programme_code": _other_programme(expectation).code},
    )
    for setup in denied_setups:
        denied_session, denied_source_id = _secretary_session(expectation, **setup)
        before_event_count = len(denied_session.events)
        denied = secretary_client(denied_session).post(
            "/secretary/teaching-events",
            headers=secretary_headers(denied_session, site=posting_code),
            json=_secretary_event_request(denied_source_id, start_time="10:00"),
        )
        assert denied.status_code == 403
        assert len(denied_session.events) == before_event_count


@pytest.mark.parametrize(
    "expectation",
    PROGRAMME_READINESS_EXPECTATIONS,
    ids=lambda expectation: expectation.code,
)
def test_phase_r_all_28_pc_scope_controls_pending_and_mapped_pool_events(
    expectation: ProgrammeReadinessExpectation,
) -> None:
    session, pending_name_id, mapped_name_id, other_name_id = _programme_pc_session(expectation)
    client = programme_pc_client(session)
    other = _other_programme(expectation)
    pending = client.post(
        "/admin/programme-teaching-events",
        headers=programme_pc_headers(scope=expectation.code),
        json=_programme_pc_event_request(
            expectation,
            teaching_name_id=pending_name_id,
            start_time="23:00",
        ),
    )
    mapped = client.post(
        "/admin/programme-teaching-events",
        headers=programme_pc_headers(scope=expectation.code),
        json=_programme_pc_event_request(
            expectation,
            teaching_name_id=mapped_name_id,
            start_time="10:00",
        ),
    )

    assert pending.status_code == 200
    assert mapped.status_code == 200
    for response, source_id in ((pending, pending_name_id), (mapped, mapped_name_id)):
        payload = response.json()
        assert payload["created_for_programme_code"] == expectation.code
        assert payload["teaching_name_id"] == source_id
        assert payload["global_session_type_id"] is None
        assert payload["source_programme_code"] == expectation.code
        assert payload["source_reporting_period_id"] == session.period_id
        assert payload["duration_hours"] == "1.00"
    assert pending.json()["end_time"] == "00:00:00"

    null_scope_headers = programme_pc_headers(scope="unused")
    del null_scope_headers["X-User-Programme"]
    denied_headers = (
        null_scope_headers,
        programme_pc_headers(scope=""),
        programme_pc_headers(scope=other.code),
    )
    before_event_count = len(session.events)
    for headers in denied_headers:
        denied = client.post(
            "/admin/programme-teaching-events",
            headers=headers,
            json=_programme_pc_event_request(
                expectation,
                teaching_name_id=pending_name_id,
                start_time="10:00",
            ),
        )
        assert denied.status_code == 403
    cross_source = client.post(
        "/admin/programme-teaching-events",
        headers=programme_pc_headers(scope=f"{expectation.code},{other.code}"),
        json=_programme_pc_event_request(
            expectation,
            teaching_name_id=other_name_id,
            start_time="10:00",
        ),
    )
    assert cross_source.status_code == 422
    assert len(session.events) == before_event_count


@pytest.mark.parametrize(
    "expectation",
    PROGRAMME_READINESS_EXPECTATIONS,
    ids=lambda expectation: expectation.code,
)
def test_phase_r_all_28_native_resident_visibility_attendance_and_cross_programme_denial(
    expectation: ProgrammeReadinessExpectation,
) -> None:
    session, pending_event, mapped_event, cross_programme_event = _resident_session(expectation)
    client = resident_client(session)
    headers = _resident_headers(session, expectation)

    available = client.get("/resident/events", headers=headers)
    assert available.status_code == 200
    event_ids = {row["id"] for row in available.json()["events"]}
    assert pending_event["id"] in event_ids
    assert mapped_event["id"] in event_ids
    assert cross_programme_event["id"] not in event_ids

    submitted_pending = client.post(
        "/resident/attendance",
        headers=headers,
        json={"event_ids": [pending_event["id"]]},
    )
    duplicate_pending = client.post(
        "/resident/attendance",
        headers=headers,
        json={"event_ids": [pending_event["id"]]},
    )
    submitted_mapped = client.post(
        "/resident/attendance",
        headers=headers,
        json={"event_ids": [mapped_event["id"]]},
    )
    before_cross_programme_attempt = len(session.attendance)
    cross_programme = client.post(
        "/resident/attendance",
        headers=headers,
        json={"event_ids": [cross_programme_event["id"]]},
    )

    assert submitted_pending.status_code == 200
    assert submitted_pending.json()["submitted"] == 1
    assert duplicate_pending.status_code == 409
    assert submitted_mapped.status_code == 200
    assert submitted_mapped.json()["submitted"] == 1
    assert cross_programme.status_code == 422
    assert len(session.attendance) == before_cross_programme_attempt
    assert {
        row["teaching_event_id"]
        for row in session.attendance
        if row["resident_id"] == session.resident_id and row["status"] == "submitted"
    } == {pending_event["id"], mapped_event["id"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expectation",
    PROGRAMME_READINESS_EXPECTATIONS,
    ids=lambda expectation: expectation.code,
)
async def test_phase_r_all_28_pool_resolver_classifies_pending_and_mapped_sources(
    expectation: ProgrammeReadinessExpectation,
) -> None:
    session, pending_event, mapped_event, _ = _resident_session(expectation)
    resident_id = UUID(session.resident_id)
    r_year = expectation.expected_fixture_r_years[0]
    reporting_period_id = UUID(session.period_id)
    pending_event_id = UUID(str(pending_event["id"]))
    mapped_event_id = UUID(str(mapped_event["id"]))
    pending_name_id = UUID(str(pending_event["teaching_name_id"]))
    mapped_name_id = UUID(str(mapped_event["teaching_name_id"]))

    pending_db = _ReadOnlyDb(
        {
            "outcome": "pending_mapping",
            "unavailable_reason": None,
            "event_id": pending_event_id,
            "reporting_period_id": reporting_period_id,
            "programme_code": expectation.code,
            "posting_code": synthetic_posting_code(expectation.code),
            "r_year": r_year,
            "global_session_type_id": None,
            "teaching_name_id": pending_name_id,
            "mapping_id": uuid5(_WORKFLOW_NAMESPACE, f"mapping/{expectation.code}/pending"),
            "mapping_revision": 1,
            "teaching_target_id": None,
            "session_type_id": None,
        }
    )
    mapped_target_id = uuid5(_WORKFLOW_NAMESPACE, f"target/{expectation.code}/mapped")
    mapped_session_type_id = uuid5(_WORKFLOW_NAMESPACE, f"session/{expectation.code}")
    mapped_db = _ReadOnlyDb(
        {
            "outcome": "mapped_target",
            "unavailable_reason": None,
            "event_id": mapped_event_id,
            "reporting_period_id": reporting_period_id,
            "programme_code": expectation.code,
            "posting_code": synthetic_posting_code(expectation.code),
            "r_year": r_year,
            "global_session_type_id": None,
            "teaching_name_id": mapped_name_id,
            "mapping_id": uuid5(_WORKFLOW_NAMESPACE, f"mapping/{expectation.code}/mapped"),
            "mapping_revision": 1,
            "teaching_target_id": mapped_target_id,
            "session_type_id": mapped_session_type_id,
        }
    )

    pending = await resolve_native_teaching_target(
        pending_db,  # type: ignore[arg-type]
        resident_id=resident_id,
        event_id=pending_event_id,
    )
    mapped = await resolve_native_teaching_target(
        mapped_db,  # type: ignore[arg-type]
        resident_id=resident_id,
        event_id=mapped_event_id,
    )

    assert isinstance(pending, PendingMappingResolution)
    assert pending.programme_code == expectation.code
    assert pending.posting_code == synthetic_posting_code(expectation.code)
    assert pending.r_year == r_year
    assert pending.teaching_name_id == pending_name_id
    assert isinstance(mapped, MappedTargetResolution)
    assert mapped.programme_code == expectation.code
    assert mapped.posting_code == synthetic_posting_code(expectation.code)
    assert mapped.r_year == r_year
    assert mapped.teaching_name_id == mapped_name_id
    assert mapped.teaching_target_id == mapped_target_id
    assert mapped.session_type_id == mapped_session_type_id
    assert pending_db.calls == [
        {"resident_id": str(resident_id), "event_id": str(pending_event_id)}
    ]
    assert mapped_db.calls == [
        {"resident_id": str(resident_id), "event_id": str(mapped_event_id)}
    ]
