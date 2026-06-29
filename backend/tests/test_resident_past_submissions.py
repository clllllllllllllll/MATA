from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import resident
from tests.resident_fakes import FakeResidentSession


def _client(fake_db: FakeResidentSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

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


def test_past_submissions_route_returns_submitted_and_removed_own_rows() -> None:
    fake_db = FakeResidentSession()
    fake_db.attendance[0]["status"] = "removed"
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

    response = client.get("/resident/attendance", headers=_headers(fake_db))

    assert response.status_code == 200
    rows = response.json()["attendance"]
    statuses = {row["status"] for row in rows}
    assert {"submitted", "removed"} <= statuses
    assert all(row["attendance_id"] != fake_db.other_attendance_id for row in rows)
    assert all("created_by_role" not in row for row in rows)


def test_past_submissions_filters_source_status_date_posting_and_teaching_name() -> None:
    fake_db = FakeResidentSession()
    adhoc_event = fake_db._event(  # noqa: SLF001
        str(uuid4()),
        "TTSHCardio",
        "Journal Club",
        fake_db.today - timedelta(days=1),
    )
    adhoc_event["is_adhoc"] = True
    fake_db.events.append(adhoc_event)
    fake_db.attendance.append(
        {
            "id": str(uuid4()),
            "resident_id": fake_db.resident_id,
            "teaching_event_id": adhoc_event["id"],
            "status": "removed",
            "posting_code": "TTSHCardio",
        }
    )
    client = _client(fake_db)

    response = client.get(
        "/resident/attendance",
        headers=_headers(fake_db),
        params={
            "date_from": (fake_db.today - timedelta(days=2)).isoformat(),
            "date_to": fake_db.today.isoformat(),
            "posting_code": "TTSHCardio",
            "teaching_name": "Journal Club",
            "source": "adhoc",
            "status": "removed",
            "limit": 5,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    rows = response.json()["attendance"]
    assert len(rows) == 1
    assert rows[0]["source"] == "adhoc"
    assert rows[0]["status"] == "removed"
    assert rows[0]["teaching_name"] == "Journal Club"


def test_legacy_attendance_history_remains_compatibility_route() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.get("/resident/attendance-history", headers=_headers(fake_db))

    assert response.status_code == 200
    assert "attendance" in response.json()


def test_past_submissions_order_has_unique_tie_breaker() -> None:
    service_source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "resident_submission.py"
    ).read_text()

    assert (
        "ORDER BY events.event_date DESC, events.start_time DESC, "
        "attendance.submitted_at DESC, attendance.id DESC"
    ) in service_source
