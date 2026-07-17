from __future__ import annotations

from datetime import date, timedelta
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
        "X-User-Role": "external_resident",
        "X-User-Id": fake_db.external_resident_id,
    }


def test_external_scheduled_events_use_the_current_period_not_a_future_period() -> None:
    fake_db = FakeResidentSession()
    future_event_id = str(uuid4())
    fake_db.reporting_periods.append(
        {
            "id": str(uuid4()),
            "label": "Future Test Period",
            "start_date": date(2099, 1, 1),
            "end_date": date(2099, 6, 30),
            "status": "active",
            "activate_on": None,
            "deactivate_on": None,
        }
    )
    fake_db.events.append(
        fake_db._event(  # noqa: SLF001
            future_event_id,
            "TTSHCardio",
            "Future Test Teaching",
            date(2099, 2, 1),
        )
    )
    client = _client(fake_db)

    response = client.get("/resident/events", headers=_headers(fake_db))

    assert response.status_code == 200
    event_ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.event_id in event_ids
    assert future_event_id not in event_ids


def test_external_scheduled_attendance_supports_reopened_history_and_stays_external() -> None:
    fake_db = FakeResidentSession()
    historic_period_id = str(uuid4())
    historic_date = date(2025, 6, 15)
    fake_db.reporting_periods.append(
        {
            "id": historic_period_id,
            "label": "Reopened historical period",
            "start_date": date(2025, 1, 1),
            "end_date": date(2025, 12, 31),
            "status": "active",
            "activate_on": None,
            "deactivate_on": fake_db.today + timedelta(days=30),
        }
    )
    fake_db.external_resident_postings.append(
        {
            "id": str(uuid4()),
            "external_resident_id": fake_db.external_resident_id,
            "posting_code": "TTSHCardio",
            "start_date": historic_date,
            "end_date": historic_date,
            "is_current": False,
        }
    )
    historic_event = fake_db._event(  # noqa: SLF001
        str(uuid4()),
        "TTSHCardio",
        "Journal Club",
        historic_date,
    )
    fake_db.events.append(historic_event)
    before_native = len(fake_db.attendance)
    before_external = len(fake_db.external_attendance)
    client = _client(fake_db)

    historical_events = client.get(
        "/resident/events",
        headers=_headers(fake_db),
        params={"date_from": historic_date.isoformat(), "date_to": historic_date.isoformat()},
    )
    crossing_events = client.get(
        "/resident/events",
        headers=_headers(fake_db),
        params={"date_from": historic_date.isoformat(), "date_to": fake_db.today.isoformat()},
    )

    response = client.post(
        "/resident/attendance",
        headers=_headers(fake_db),
        json={"event_ids": [historic_event["id"]]},
    )

    assert historical_events.status_code == 200
    assert historic_event["id"] in {row["id"] for row in historical_events.json()["events"]}
    assert crossing_events.status_code == 200
    assert historic_event["id"] in {row["id"] for row in crossing_events.json()["events"]}
    assert response.status_code == 200
    assert len(fake_db.external_attendance) == before_external + 1
    assert len(fake_db.attendance) == before_native


def test_external_scheduled_flows_return_unavailable_or_conflict_without_a_unique_period() -> None:
    unavailable = FakeResidentSession()
    unavailable.reporting_periods[0]["status"] = "inactive"
    unavailable_client = _client(unavailable)

    unavailable_events = unavailable_client.get("/resident/events", headers=_headers(unavailable))
    unavailable_submit = unavailable_client.post(
        "/resident/attendance",
        headers=_headers(unavailable),
        json={"event_ids": [unavailable.event_id]},
    )

    assert unavailable_events.status_code == 200
    assert unavailable_events.json()["reason"] == "active_reporting_period_unavailable"
    assert unavailable_submit.status_code == 422

    overlapping = FakeResidentSession()
    overlapping.reporting_periods.append(
        {
            "id": str(uuid4()),
            "label": "Overlapping current period",
            "start_date": overlapping.today - timedelta(days=1),
            "end_date": overlapping.today + timedelta(days=1),
            "status": "active",
            "activate_on": None,
            "deactivate_on": None,
        }
    )
    overlapping_client = _client(overlapping)
    overlap_events = overlapping_client.get("/resident/events", headers=_headers(overlapping))
    overlap_submit = overlapping_client.post(
        "/resident/attendance",
        headers=_headers(overlapping),
        json={"event_ids": [overlapping.event_id]},
    )

    assert overlap_events.status_code == 409
    assert overlap_submit.status_code == 409
