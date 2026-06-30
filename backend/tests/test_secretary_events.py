from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.middleware.auth_stub import AuthIdentity
from app.middleware.errors import install_error_handlers
from app.routers import secretary
from tests.auth_identity_test_helpers import install_stub_header_identity_middleware


class _FakeResult:
    def __init__(
        self,
        rows: list[dict] | None = None,
        scalar: object | None = None,
        rowcount: int = 0,
    ) -> None:
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict]:
        return list(self._rows)

    def one(self) -> dict:
        if len(self._rows) != 1:
            raise AssertionError(f"Expected exactly one row, got {len(self._rows)}")
        return self._rows[0]

    def one_or_none(self) -> dict | None:
        if len(self._rows) > 1:
            raise AssertionError(f"Expected at most one row, got {len(self._rows)}")
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._scalar


class FakeSecretarySession:
    def __init__(self) -> None:
        self.now = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
        self.secretary_id = str(uuid4())
        self.admin_id = str(uuid4())
        self.resident_id = str(uuid4())
        self.other_resident_id = str(uuid4())
        self.session_type_id = str(uuid4())
        self.other_session_type_id = str(uuid4())
        self.series_id = str(uuid4())
        self.attended_event_id = str(uuid4())
        self.other_event_id = str(uuid4())
        self.pc_event_id = str(uuid4())
        self.unrelated_pc_event_id = str(uuid4())
        self.deleted_event_ids: list[str] = []
        self.cache_mutation_count = 0
        self.audit_logs: list[dict] = []

        self.public_holidays = [
            {
                "holiday_date": date(2026, 5, 1),
                "name": "Labour Day",
            }
        ]
        self.catalogue = [
            {
                "keyword": "Journal Club",
                "posting_code": "TTSHCardio",
                "programme_code": "CARD",
                "session_type_id": self.session_type_id,
                "session_type": "Department Teaching [1h]",
                "duration_hours": Decimal("1.0"),
                "is_tracked": True,
            },
            {
                "keyword": "Wrong Site Teaching",
                "posting_code": "TTSHNeuro",
                "programme_code": "NEURO",
                "session_type_id": self.other_session_type_id,
                "session_type": "Other Teaching [1h]",
                "duration_hours": Decimal("1.0"),
                "is_tracked": True,
            },
            {
                "keyword": "GERI Demo Row 22",
                "posting_code": "TTSHGerMed",
                "programme_code": "GERI",
                "session_type_id": str(uuid4()),
                "session_type": "GERI Session [1h]",
                "duration_hours": Decimal("1.0"),
                "is_tracked": True,
            },
            {
                "keyword": "GERI Demo Row 2",
                "posting_code": "TTSHGerMed",
                "programme_code": "GERI",
                "session_type_id": str(uuid4()),
                "session_type": "GERI Session [1h]",
                "duration_hours": Decimal("1.0"),
                "is_tracked": True,
            },
            {
                "keyword": "GERI Demo Row 10",
                "posting_code": "TTSHGerMed",
                "programme_code": "GERI",
                "session_type_id": str(uuid4()),
                "session_type": "GERI Session [1h]",
                "duration_hours": Decimal("1.0"),
                "is_tracked": True,
            },
            {
                "keyword": "GERI Demo Row 11",
                "posting_code": "TTSHGerMed",
                "programme_code": "GERI",
                "session_type_id": str(uuid4()),
                "session_type": "GERI Session [1h]",
                "duration_hours": Decimal("1.0"),
                "is_tracked": True,
            },
            {
                "keyword": "GERI Shared Teaching",
                "posting_code": "TTSHGerMed",
                "programme_code": "GERI",
                "session_type_id": str(uuid4()),
                "session_type": "GERI Shared [2h]",
                "duration_hours": Decimal("2.0"),
                "is_tracked": True,
            },
            {
                "keyword": "GERI Shared Teaching",
                "posting_code": "TTSHContCC",
                "programme_code": "GERI",
                "session_type_id": str(uuid4()),
                "session_type": "GERI Shared Alt [1h]",
                "duration_hours": Decimal("1.0"),
                "is_tracked": True,
            },
        ]
        self.global_session_types = [
            {
                "id": str(uuid4()),
                "name": "Department Meeting [1h]",
                "duration_hours": Decimal("1.0"),
                "is_active": True,
            },
            {
                "id": str(uuid4()),
                "name": "Inactive Global [1h]",
                "duration_hours": Decimal("1.0"),
                "is_active": False,
            },
        ]
        self.secretary_programme_pools = [
            {
                "posting_code": "TTSHGerMed",
                "programme_code": "GERI",
                "is_active": True,
            },
            {
                "posting_code": "TTSHGerMed",
                "programme_code": "CARD",
                "is_active": False,
            },
        ]
        self.residents = [
            {
                "id": self.resident_id,
                "name": "Resident One",
                "mcr": "M12345A",
                "programme_code": "CARD",
                "r_year": "R2",
                "posting_code": "TTSHCardio",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 12, 31),
                "status": "active",
            },
            {
                "id": self.other_resident_id,
                "name": "Resident Two",
                "mcr": "M54321B",
                "programme_code": "NEURO",
                "r_year": "R1",
                "posting_code": "TTSHNeuro",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 12, 31),
                "status": "active",
            },
        ]
        self.events = [
            self._event(
                event_id=self.attended_event_id,
                posting_code="TTSHCardio",
                teaching_name="Journal Club",
                event_date=date(2026, 5, 6),
                start_time=time(10, 0),
                end_time=time(11, 0),
                series_id=self.series_id,
            ),
            self._event(
                event_id=str(uuid4()),
                posting_code="TTSHCardio",
                teaching_name="Journal Club",
                event_date=date(2026, 5, 13),
                start_time=time(10, 0),
                end_time=time(11, 0),
                series_id=self.series_id,
            ),
            self._event(
                event_id=str(uuid4()),
                posting_code="TTSHCardio",
                teaching_name="Journal Club",
                event_date=date(2026, 5, 20),
                start_time=time(10, 0),
                end_time=time(11, 0),
                series_id=self.series_id,
            ),
            self._event(
                event_id=self.other_event_id,
                posting_code="TTSHNeuro",
                teaching_name="Wrong Site Teaching",
                event_date=date(2026, 5, 7),
                start_time=time(10, 0),
                end_time=time(11, 0),
                session_type_id=self.other_session_type_id,
            ),
            {
                "id": self.pc_event_id,
                "posting_code": "TTSHCardio",
                "created_for_programme_code": "CARD",
                "teaching_name": "Journal Club",
                "event_date": date(2026, 5, 15),
                "start_time": time(10, 0),
                "end_time": time(11, 0),
                "duration_hours": Decimal("1.0"),
                "session_type_id": self.session_type_id,
                "session_type": "Department Teaching [1h]",
                "series_id": None,
                "cme_points_awarded": False,
                "smc_event_code": None,
                "is_adhoc": False,
                "created_by_role": "programme_pc",
                "created_at": self.now,
                "updated_at": self.now,
            },
            {
                "id": str(uuid4()),
                "posting_code": "TTSHCardio",
                "teaching_name": "Journal Club",
                "event_date": date(2026, 5, 9),
                "start_time": time(9, 0),
                "end_time": time(10, 0),
                "duration_hours": Decimal("1.0"),
                "session_type_id": self.session_type_id,
                "session_type": "Department Teaching [1h]",
                "series_id": None,
                "cme_points_awarded": False,
                "smc_event_code": None,
                "is_adhoc": True,
                "created_by_role": "resident",
                "created_at": self.now,
                "updated_at": self.now,
            },
        ]
        self.series = [
            {
                "id": self.series_id,
                "posting_code": "TTSHCardio",
                "recurrence_pattern": "weekly",
                "recurrence_interval": 1,
                "days_of_week": ["wed"],
                "end_type": "by_count",
                "end_date": None,
                "end_after_count": 3,
                "created_at": self.now,
                "updated_at": self.now,
            }
        ]
        self.attendance_event_ids = {self.attended_event_id}

    def _event(
        self,
        *,
        event_id: str,
        posting_code: str,
        teaching_name: str,
        event_date: date,
        start_time: time,
        end_time: time,
        series_id: str | None = None,
        session_type_id: str | None = None,
        duration_hours: Decimal = Decimal("1.0"),
    ) -> dict:
        return {
            "id": event_id,
            "posting_code": posting_code,
            "teaching_name": teaching_name,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
            "duration_hours": duration_hours,
            "session_type_id": session_type_id or self.session_type_id,
            "session_type": "Department Teaching [1h]",
            "series_id": series_id,
            "cme_points_awarded": False,
            "smc_event_code": None,
            "is_adhoc": False,
            "created_for_programme_code": None,
            "created_by_role": "secretary",
            "created_at": self.now,
            "updated_at": self.now,
        }

    def allow_cardio_card_programme_pool(self) -> None:
        self.secretary_programme_pools.append(
            {
                "posting_code": "TTSHCardio",
                "programme_code": "CARD",
                "is_active": True,
            }
        )

    def add_unrelated_pc_event_for_cardio(self) -> None:
        row = self._event(
            event_id=self.unrelated_pc_event_id,
            posting_code="TTSHCardio",
            teaching_name="Journal Club",
            event_date=date(2026, 5, 22),
            start_time=time(10, 0),
            end_time=time(11, 0),
        )
        row["created_by_role"] = "programme_pc"
        row["created_for_programme_code"] = "GERI"
        self.events.append(row)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def execute(self, statement, params=None):  # noqa: C901, PLR0912, PLR0915
        sql = str(statement)
        payload = dict(params or {})

        if "INSERT INTO audit_logs" in sql:
            row = dict(payload)
            row["created_at"] = self.now
            self.audit_logs.append(row)
            return _FakeResult(rows=[row])

        if "/* audit_snapshot:secretary_event */" in sql:
            event = next(
                (
                    row
                    for row in self.events
                    if row["id"] == str(payload["event_id"])
                    and row["posting_code"] == payload["posting_code"]
                ),
                None,
            )
            return _FakeResult(rows=[dict(event)] if event else [])

        if "/* audit_snapshot:secretary_series */" in sql:
            series = next(
                (
                    row
                    for row in self.series
                    if row["id"] == str(payload["series_id"])
                    and row["posting_code"] == payload["posting_code"]
                ),
                None,
            )
            return _FakeResult(rows=[dict(series)] if series else [])

        if "/* audit_snapshot:secretary_series_events */" in sql:
            rows = [
                dict(row)
                for row in self.events
                if row["series_id"] == str(payload["series_id"])
                and row["posting_code"] == payload["posting_code"]
            ]
            rows.sort(key=lambda row: (row["event_date"], row["start_time"]))
            return _FakeResult(rows=rows)

        if "FROM public_holidays" in sql:
            holiday_date = payload["event_date"]
            holiday = next(
                (row for row in self.public_holidays if row["holiday_date"] == holiday_date),
                None,
            )
            return _FakeResult(rows=[holiday] if holiday else [], scalar=1 if holiday else None)

        if "FROM teaching_name_catalogue" in sql and "JOIN session_types" in sql:
            programme_codes = payload.get("programme_codes") or []
            use_programme_pool = bool(programme_codes)
            rows = [
                {
                    "keyword": row["keyword"],
                    "session_type_id": row["session_type_id"],
                    "session_type": row["session_type"],
                    "duration_hours": row["duration_hours"],
                    "is_tracked": row["is_tracked"],
                    "is_global": False,
                    "posting_code": row["posting_code"],
                }
                for row in self.catalogue
                if (
                    row["programme_code"] in set(programme_codes)
                    if use_programme_pool
                    else row["posting_code"] == payload["posting_code"]
                )
                and (
                    payload.get("teaching_name") in {None, ""}
                    or row["keyword"] == payload.get("teaching_name")
                )
            ]
            return _FakeResult(rows=rows)

        if "FROM secretary_programme_pools" in sql and "FROM teaching_events" not in sql:
            rows = [
                row
                for row in self.secretary_programme_pools
                if row["posting_code"] == payload["posting_code"] and row["is_active"]
                and (
                    "programme_code" not in payload
                    or row["programme_code"] == payload["programme_code"]
                )
            ]
            return _FakeResult(rows=rows)

        if "FROM global_session_types" in sql:
            rows = [
                {
                    "keyword": row["name"],
                    "session_type_id": None,
                    "session_type": row["name"],
                    "duration_hours": row["duration_hours"],
                    "is_tracked": False,
                    "is_global": True,
                }
                for row in self.global_session_types
                if row["is_active"]
                and (
                    "teaching_name" not in payload
                    or row["name"] == payload["teaching_name"]
                )
            ]
            return _FakeResult(rows=rows)

        if "DELETE FROM teaching_events" in sql:
            ids = {str(value) for value in payload.get("event_ids", [])}
            if not ids and "event_id" in payload:
                ids = {str(payload["event_id"])}
            self.deleted_event_ids.extend(sorted(ids))
            self.events = [row for row in self.events if row["id"] not in ids]
            return _FakeResult(rowcount=len(ids))

        if "DELETE FROM event_series" in sql:
            self.series = [row for row in self.series if row["id"] != str(payload["series_id"])]
            return _FakeResult(rowcount=1)

        if "FROM teaching_events" in sql and "COUNT(*)" in sql and "GROUP BY" in sql:
            scoped_rows = [row for row in self.events if row["posting_code"] == payload["posting_code"]]
            if "created_by_role = 'secretary'" in sql:
                scoped_rows = [row for row in scoped_rows if row["created_by_role"] == "secretary"]
            if "is_adhoc = false" in sql:
                scoped_rows = [row for row in scoped_rows if not row["is_adhoc"]]
            rows = [
                {
                    "total_events": len(scoped_rows),
                    "cme_events": len(
                        [
                            row
                            for row in scoped_rows
                            if row["cme_points_awarded"]
                        ]
                    ),
                    "with_smc_code": len(
                        [
                            row
                            for row in scoped_rows
                            if row["smc_event_code"]
                        ]
                    ),
                }
            ]
            return _FakeResult(rows=rows)

        if "FROM teaching_events" in sql and "WHERE id = :source_event_id" in sql:
            event = next(
                (
                    row
                    for row in self.events
                    if row["id"] == str(payload["source_event_id"])
                    and row["posting_code"] == payload["posting_code"]
                ),
                None,
            )
            return _FakeResult(rows=[event] if event else [])

        if "FROM teaching_events" in sql and "WHERE id = :event_id" in sql:
            event = next(
                (
                    row
                    for row in self.events
                    if row["id"] == str(payload["event_id"])
                    and row["posting_code"] == payload["posting_code"]
                ),
                None,
            )
            return _FakeResult(rows=[event] if event else [])

        if "FROM teaching_events" in sql and "WHERE series_id = :series_id" in sql:
            rows = [
                row
                for row in self.events
                if row["series_id"] == str(payload["series_id"])
                and row["posting_code"] == payload["posting_code"]
            ]
            if payload.get("scope") == "single":
                rows = [row for row in rows if row["id"] == str(payload["event_id"])]
            if payload.get("scope") == "following":
                anchor = next(
                    (row for row in rows if row["id"] == str(payload["event_id"])),
                    None,
                )
                if anchor is None:
                    rows = []
                else:
                    rows = [row for row in rows if row["event_date"] >= anchor["event_date"]]
            return _FakeResult(rows=rows)

        if "FROM teaching_events" in sql:
            rows = [row for row in self.events if row["posting_code"] == payload["posting_code"]]
            if "created_by_role = 'secretary'" in sql:
                rows = [row for row in rows if row["created_by_role"] == "secretary"]
            if "created_by_role IN ('secretary', 'programme_pc')" in sql:
                rows = [
                    row
                    for row in rows
                    if row["created_by_role"] in {"secretary", "programme_pc"}
                ]
            if "created_for_programme_code IS NULL" in sql and "secretary_programme_pools" in sql:
                active_programmes = {
                    row["programme_code"]
                    for row in self.secretary_programme_pools
                    if row["posting_code"] == payload["posting_code"] and row["is_active"]
                }
                rows = [
                    row
                    for row in rows
                    if row.get("created_for_programme_code") is None
                    or row.get("created_for_programme_code") in active_programmes
                ]
            if "is_adhoc = false" in sql:
                rows = [row for row in rows if not row["is_adhoc"]]
            if "date_from" in payload:
                rows = [row for row in rows if row["event_date"] >= payload["date_from"]]
            if "date_to" in payload:
                rows = [row for row in rows if row["event_date"] <= payload["date_to"]]
            if "session_type_id" in payload:
                rows = [row for row in rows if row["session_type_id"] == str(payload["session_type_id"])]
            rows.sort(key=lambda row: (row["event_date"], row["start_time"]))
            return _FakeResult(rows=rows)

        if "FROM resident_postings" in sql:
            today = payload["today"]
            rows = [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "mcr": row["mcr"],
                    "programme_code": row["programme_code"],
                    "r_year": row["r_year"],
                    "posting_code": row["posting_code"],
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "status": row["status"],
                }
                for row in self.residents
                if row["posting_code"] == payload["posting_code"]
                and row["start_date"] <= today <= row["end_date"]
            ]
            return _FakeResult(rows=rows)

        if "SELECT 1" in sql and "FROM attendance_records" in sql:
            ids = set(payload.get("event_ids", []))
            if not ids and "event_id" in payload:
                ids = {str(payload["event_id"])}
            has_attendance = bool(ids & self.attendance_event_ids)
            return _FakeResult(scalar=1 if has_attendance else None)

        if "INSERT INTO event_series" in sql:
            row = {
                "id": str(uuid4()),
                "posting_code": payload["posting_code"],
                "recurrence_pattern": payload["recurrence_pattern"],
                "recurrence_interval": payload["recurrence_interval"],
                "days_of_week": payload.get("days_of_week"),
                "end_type": payload["end_type"],
                "end_date": payload.get("end_date"),
                "end_after_count": payload.get("end_after_count"),
                "created_at": self.now,
                "updated_at": self.now,
            }
            self.series.append(row)
            return _FakeResult(rows=[row])

        if "INSERT INTO teaching_events" in sql:
            row = self._event(
                event_id=str(uuid4()),
                posting_code=payload["posting_code"],
                teaching_name=payload["teaching_name"],
                event_date=payload["event_date"],
                start_time=payload["start_time"],
                end_time=payload["end_time"],
                duration_hours=payload["duration_hours"],
                session_type_id=str(payload["session_type_id"])
                if payload.get("session_type_id")
                else None,
                series_id=str(payload["series_id"]) if payload.get("series_id") else None,
            )
            row["cme_points_awarded"] = payload["cme_points_awarded"]
            row["smc_event_code"] = payload.get("smc_event_code")
            self.events.append(row)
            return _FakeResult(rows=[row])

        if "UPDATE teaching_events" in sql:
            row = next(
                (
                    event
                    for event in self.events
                    if event["id"] == str(payload["event_id"])
                    and event["posting_code"] == payload["posting_code"]
                    and event["created_by_role"] == "secretary"
                    and not event["is_adhoc"]
                ),
                None,
            )
            if row is None:
                return _FakeResult(rows=[])
            row.update(
                {
                    "teaching_name": payload["teaching_name"],
                    "event_date": payload["event_date"],
                    "start_time": payload["start_time"],
                    "end_time": payload["end_time"],
                    "duration_hours": payload["duration_hours"],
                    "session_type_id": str(payload["session_type_id"])
                    if payload.get("session_type_id")
                    else None,
                    "cme_points_awarded": payload["cme_points_awarded"],
                    "smc_event_code": payload.get("smc_event_code"),
                    "updated_at": self.now,
                }
            )
            return _FakeResult(rows=[row])

        raise AssertionError(f"Unhandled SQL: {sql}\nparams={payload}")


def _client(
    fake_db: FakeSecretarySession,
    *,
    identity: AuthIdentity | None = None,
) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    install_stub_header_identity_middleware(app, default_identity=identity)

    async def _db_override():
        yield fake_db

    app.dependency_overrides[secretary.get_db_session] = _db_override
    app.include_router(secretary.router)
    return TestClient(app)


def _headers(fake_db: FakeSecretarySession, *, role: str = "secretary", site: str = "TTSHCardio"):
    return {
        "X-User-Role": role,
        "X-User-Id": fake_db.secretary_id if role == "secretary" else fake_db.admin_id,
        "X-User-Site": site,
    }


def _audit_json(row: dict, field: str) -> dict | None:
    value = row[field]
    if value is None:
        return None
    return json.loads(value)


def test_non_secretary_access_rejected() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.get("/secretary/teaching-events", headers=_headers(fake_db, role="admin"))

    assert response.status_code == 403


def test_secretary_context_uses_verified_identity_posting_without_raw_headers() -> None:
    fake_db = FakeSecretarySession()
    client = _client(
        fake_db,
        identity=AuthIdentity(
            role="secretary",
            subject_id=fake_db.secretary_id,
            posting_code="TTSHGerMed",
        ),
    )

    response = client.get("/secretary/teaching-name-options")

    assert response.status_code == 200
    keywords = [row["keyword"] for row in response.json()["options"]]
    assert "GERI Demo Row 22" in keywords
    assert "Journal Club" not in keywords


def test_secretary_mutation_endpoint_allows_missing_actor_name_and_writes_audit() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    headers = _headers(fake_db)

    response = client.post(
        "/secretary/teaching-events",
        headers=headers,
        json={"teaching_name": "Journal Club", "event_date": "2026-05-18", "start_time": "10:00"},
    )

    assert response.status_code == 200
    assert fake_db.audit_logs[-1]["actor_name"] == "Unknown actor"
    assert fake_db.audit_logs[-1]["action"] == "secretary.teaching_event.create"


def test_secretary_mutation_endpoint_allows_blank_actor_name() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    headers = _headers(fake_db)
    headers["-".join(["X", "Actor", "Name"])] = "   "

    response = client.post(
        "/secretary/teaching-events",
        headers=headers,
        json={"teaching_name": "Journal Club", "event_date": "2026-05-18", "start_time": "10:00"},
    )

    assert response.status_code == 200
    assert fake_db.audit_logs[-1]["actor_name"] == "Unknown actor"


def test_secretary_read_endpoints_do_not_require_actor_name() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    headers = _headers(fake_db)
    paths = [
        "/secretary/teaching-events",
        "/secretary/cme-dashboard",
        "/secretary/residents",
        "/secretary/teaching-name-options",
    ]

    for path in paths:
        response = client.get(path, headers=headers)
        assert response.status_code == 200, path


def test_secretary_teaching_event_mutations_write_audit_logs() -> None:
    fake_db = FakeSecretarySession()
    fake_db.attendance_event_ids = set()
    client = _client(fake_db)
    headers = _headers(fake_db)
    source_event_id = fake_db.events[0]["id"]

    created = client.post(
        "/secretary/teaching-events",
        headers=headers,
        json={
            "teaching_name": "Journal Club",
            "event_date": "2026-05-18",
            "start_time": "10:00",
            "cme_points_awarded": True,
            "smc_event_code": "SMC-1",
        },
    )
    assert created.status_code == 200

    duplicated = client.post(
        "/secretary/teaching-events/duplicate",
        headers=headers,
        json={
            "source_event_id": source_event_id,
            "event_date": "2026-05-25",
            "start_time": "10:00",
        },
    )
    assert duplicated.status_code == 200
    duplicated_id = duplicated.json()["id"]

    updated = client.put(
        f"/secretary/teaching-events/{duplicated_id}",
        headers=headers,
        json={
            "teaching_name": "Journal Club",
            "event_date": "2026-05-26",
            "start_time": "11:00",
            "cme_points_awarded": False,
            "smc_event_code": "SMC-2",
        },
    )
    assert updated.status_code == 200

    deleted = client.delete(
        f"/secretary/teaching-events/{duplicated_id}",
        headers=headers,
    )
    assert deleted.status_code == 200

    series_created = client.post(
        "/secretary/teaching-events/series",
        headers=headers,
        json={
            "teaching_name": "Journal Club",
            "start_date": "2026-04-24",
            "start_time": "10:00",
            "recurrence_pattern": "weekly",
            "recurrence_interval": 1,
            "days_of_week": ["fri"],
            "end_type": "by_count",
            "end_after_count": 2,
        },
    )
    assert series_created.status_code == 200

    series_payload = series_created.json()
    series_id = series_payload["series"]["id"]
    series_event_id = series_payload["events"][0]["id"]
    series_deleted = client.delete(
        f"/secretary/teaching-events/series/{series_id}",
        headers=headers,
        params={"scope": "single", "event_id": series_event_id},
    )
    assert series_deleted.status_code == 200

    assert [row["action"] for row in fake_db.audit_logs] == [
        "secretary.teaching_event.create",
        "secretary.teaching_event.duplicate",
        "secretary.teaching_event.update",
        "secretary.teaching_event.delete",
        "secretary.teaching_event_series.create",
        "secretary.teaching_event_series.delete_single",
    ]
    assert {row["actor_name"] for row in fake_db.audit_logs} == {"Unknown actor"}
    assert fake_db.audit_logs[0]["entity_type"] == "teaching_event"
    assert _audit_json(fake_db.audit_logs[0], "before_json") is None
    assert _audit_json(fake_db.audit_logs[0], "after_json")["teaching_name"] == "Journal Club"
    assert _audit_json(fake_db.audit_logs[1], "before_json")["id"] == source_event_id
    assert _audit_json(fake_db.audit_logs[1], "after_json")["id"] == duplicated_id
    assert _audit_json(fake_db.audit_logs[2], "before_json")["event_date"] == "2026-05-25"
    assert _audit_json(fake_db.audit_logs[2], "after_json")["event_date"] == "2026-05-26"
    assert _audit_json(fake_db.audit_logs[3], "before_json")["id"] == duplicated_id
    assert _audit_json(fake_db.audit_logs[3], "after_json") is None
    series_after = _audit_json(fake_db.audit_logs[4], "after_json")
    series_metadata = _audit_json(fake_db.audit_logs[4], "metadata_json")
    assert fake_db.audit_logs[4]["entity_type"] == "teaching_event_series"
    assert series_after["created_count"] == 1
    assert series_metadata["created_event_ids"] == [series_event_id]
    delete_before = _audit_json(fake_db.audit_logs[5], "before_json")
    delete_metadata = _audit_json(fake_db.audit_logs[5], "metadata_json")
    assert delete_before["scope"] == "single"
    assert delete_metadata["deleted_event_ids"] == [series_event_id]
    assert delete_metadata["deleted_count"] == 1
    assert delete_metadata["posting_code"] == "TTSHCardio"


@pytest.mark.parametrize(
    ("scope", "expected_action"),
    [
        ("single", "secretary.teaching_event_series.delete_single"),
        ("following", "secretary.teaching_event_series.delete_following"),
        ("all", "secretary.teaching_event_series.delete_all"),
    ],
)
def test_secretary_series_delete_audit_action_matches_scope(
    scope: str,
    expected_action: str,
) -> None:
    fake_db = FakeSecretarySession()
    fake_db.attendance_event_ids = set()
    client = _client(fake_db)
    params = {"scope": scope}
    if scope in {"single", "following"}:
        params["event_id"] = fake_db.events[1]["id"]

    response = client.delete(
        f"/secretary/teaching-events/series/{fake_db.series_id}",
        headers=_headers(fake_db),
        params=params,
    )

    assert response.status_code == 200
    assert fake_db.audit_logs[-1]["action"] == expected_action


def test_create_event_derives_posting_scope_and_computes_end_time() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.post(
        "/secretary/teaching-events",
        headers=_headers(fake_db),
        json={
            "teaching_name": "Journal Club",
            "event_date": "2026-05-18",
            "start_time": "10:00",
            "cme_points_awarded": True,
            "smc_event_code": "SMC-1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["posting_code"] == "TTSHCardio"
    assert payload["end_time"] == "11:00:00"
    assert payload["session_type_id"] == fake_db.session_type_id
    assert fake_db.events[-1]["posting_code"] == "TTSHCardio"


def test_create_event_rejects_client_posting_code_and_end_time() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    base_payload = {
        "teaching_name": "Journal Club",
        "event_date": "2026-05-18",
        "start_time": "10:00",
    }

    posting_response = client.post(
        "/secretary/teaching-events",
        headers=_headers(fake_db),
        json={**base_payload, "posting_code": "TTSHNeuro"},
    )
    end_time_response = client.post(
        "/secretary/teaching-events",
        headers=_headers(fake_db),
        json={**base_payload, "end_time": "12:00"},
    )

    assert posting_response.status_code == 422
    assert end_time_response.status_code == 422


def test_create_event_on_public_holiday_returns_422() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.post(
        "/secretary/teaching-events",
        headers=_headers(fake_db),
        json={
            "teaching_name": "Journal Club",
            "event_date": "2026-05-01",
            "start_time": "10:00",
        },
    )

    assert response.status_code == 422


def test_list_endpoint_only_returns_secretary_posting_events() -> None:
    fake_db = FakeSecretarySession()
    fake_db.allow_cardio_card_programme_pool()
    client = _client(fake_db)

    response = client.get("/secretary/teaching-events", headers=_headers(fake_db))

    assert response.status_code == 200
    payload = response.json()
    assert {row["posting_code"] for row in payload["events"]} == {"TTSHCardio"}
    assert fake_db.other_event_id not in {row["id"] for row in payload["events"]}
    assert {row["created_by_role"] for row in payload["events"]} == {
        "secretary",
        "programme_pc",
    }
    assert all(not row["is_adhoc"] for row in payload["events"])
    assert payload["events"][0]["session_type"] == "Department Teaching [1h]"


def test_secretary_schedule_includes_programme_pc_events_for_same_posting() -> None:
    fake_db = FakeSecretarySession()
    fake_db.allow_cardio_card_programme_pool()
    client = _client(fake_db)

    response = client.get("/secretary/teaching-events", headers=_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.pc_event_id in ids
    pc_event = next(row for row in response.json()["events"] if row["id"] == fake_db.pc_event_id)
    assert pc_event["created_by_role"] == "programme_pc"


def test_secretary_schedule_excludes_pc_events_outside_active_programme_pool() -> None:
    fake_db = FakeSecretarySession()
    fake_db.allow_cardio_card_programme_pool()
    fake_db.add_unrelated_pc_event_for_cardio()
    client = _client(fake_db)

    response = client.get("/secretary/teaching-events", headers=_headers(fake_db))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["events"]}
    assert fake_db.pc_event_id in ids
    assert fake_db.unrelated_pc_event_id not in ids


def test_secretary_cannot_mutate_pc_event_outside_active_programme_pool() -> None:
    fake_db = FakeSecretarySession()
    fake_db.allow_cardio_card_programme_pool()
    fake_db.add_unrelated_pc_event_for_cardio()
    client = _client(fake_db)

    update_response = client.put(
        f"/secretary/teaching-events/{fake_db.unrelated_pc_event_id}",
        headers=_headers(fake_db),
        json={
            "teaching_name": "Journal Club",
            "event_date": "2026-05-26",
            "start_time": "10:00",
        },
    )
    delete_response = client.delete(
        f"/secretary/teaching-events/{fake_db.unrelated_pc_event_id}",
        headers=_headers(fake_db),
    )

    assert update_response.status_code == 404
    assert delete_response.status_code == 404


def test_secretary_cannot_access_another_posting_event() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.delete(
        f"/secretary/teaching-events/{fake_db.other_event_id}",
        headers=_headers(fake_db),
    )

    assert response.status_code == 404


def test_teaching_name_options_use_programme_pool_and_include_active_globals() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.get(
        "/secretary/teaching-name-options",
        headers=_headers(fake_db, site="TTSHGerMed"),
    )

    assert response.status_code == 200
    options = response.json()["options"]
    keywords = [row["keyword"] for row in options]

    assert "GERI Demo Row 22" in keywords
    assert keywords.count("GERI Shared Teaching") == 1
    assert "Department Meeting [1h]" in keywords
    assert "Wrong Site Teaching" not in keywords
    assert "Journal Club" not in keywords
    assert "Inactive Global [1h]" not in keywords

    shared = next(row for row in options if row["keyword"] == "GERI Shared Teaching")
    assert shared["posting_codes"] == ["TTSHContCC", "TTSHGerMed"]
    assert shared["session_type_id"] is None
    assert shared["session_type"] is None

    row2_index = keywords.index("GERI Demo Row 2")
    row10_index = keywords.index("GERI Demo Row 10")
    row11_index = keywords.index("GERI Demo Row 11")
    assert row2_index < row10_index < row11_index


def test_create_event_accepts_keyword_from_mapped_programme_pool() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.post(
        "/secretary/teaching-events",
        headers=_headers(fake_db, site="TTSHGerMed"),
        json={
            "teaching_name": "GERI Demo Row 22",
            "event_date": "2026-05-18",
            "start_time": "10:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["posting_code"] == "TTSHGerMed"
    assert payload["teaching_name"] == "GERI Demo Row 22"


def test_teaching_name_options_fall_back_to_exact_posting_when_unmapped() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.get(
        "/secretary/teaching-name-options",
        headers=_headers(fake_db, site="TTSHCardio"),
    )

    assert response.status_code == 200
    keywords = [row["keyword"] for row in response.json()["options"]]
    assert "Journal Club" in keywords
    assert "GERI Demo Row 22" not in keywords


def test_teaching_name_options_ignore_inactive_programme_pool_mapping() -> None:
    fake_db = FakeSecretarySession()
    fake_db.secretary_programme_pools.append(
        {
            "posting_code": "TTSHCardio",
            "programme_code": "GERI",
            "is_active": False,
        }
    )
    client = _client(fake_db)

    response = client.get(
        "/secretary/teaching-name-options",
        headers=_headers(fake_db, site="TTSHCardio"),
    )

    assert response.status_code == 200
    keywords = [row["keyword"] for row in response.json()["options"]]
    assert "Journal Club" in keywords
    assert "GERI Demo Row 22" not in keywords


def test_residents_endpoint_lists_only_current_own_posting_residents() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.get("/secretary/residents", headers=_headers(fake_db))

    assert response.status_code == 200
    residents = response.json()["residents"]
    assert [row["mcr"] for row in residents] == ["M12345A"]


def test_duplicate_event_respects_scope_and_rejects_client_posting_code() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.post(
        "/secretary/teaching-events/duplicate",
        headers=_headers(fake_db),
        json={
            "source_event_id": fake_db.attended_event_id,
            "event_date": "2026-05-25",
            "start_time": "10:00",
            "teaching_name": "Journal Club",
        },
    )
    forbidden_body = client.post(
        "/secretary/teaching-events/duplicate",
        headers=_headers(fake_db),
        json={
            "source_event_id": fake_db.attended_event_id,
            "event_date": "2026-05-25",
            "start_time": "10:00",
            "posting_code": "TTSHNeuro",
        },
    )
    wrong_scope = client.post(
        "/secretary/teaching-events/duplicate",
        headers=_headers(fake_db),
        json={
            "source_event_id": fake_db.other_event_id,
            "event_date": "2026-05-25",
            "start_time": "10:00",
        },
    )

    assert response.status_code == 200
    assert response.json()["posting_code"] == "TTSHCardio"
    assert forbidden_body.status_code == 422
    assert wrong_scope.status_code == 404


def test_delete_event_without_attendance_succeeds_and_with_attendance_conflicts() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    deleteable_id = fake_db.events[1]["id"]

    ok_response = client.delete(
        f"/secretary/teaching-events/{deleteable_id}",
        headers=_headers(fake_db),
    )
    conflict_response = client.delete(
        f"/secretary/teaching-events/{fake_db.attended_event_id}",
        headers=_headers(fake_db),
    )

    assert ok_response.status_code == 200
    assert ok_response.json()["deleted_count"] == 1
    assert conflict_response.status_code == 409


def test_recurring_series_create_scopes_events_and_skips_public_holidays() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.post(
        "/secretary/teaching-events/series",
        headers=_headers(fake_db),
        json={
            "teaching_name": "Journal Club",
            "start_date": "2026-04-24",
            "start_time": "10:00",
            "recurrence_pattern": "weekly",
            "recurrence_interval": 1,
            "days_of_week": ["fri"],
            "end_type": "by_count",
            "end_after_count": 3,
        },
    )
    forbidden_body = client.post(
        "/secretary/teaching-events/series",
        headers=_headers(fake_db),
        json={
            "teaching_name": "Journal Club",
            "posting_code": "TTSHNeuro",
            "start_date": "2026-04-24",
            "start_time": "10:00",
            "recurrence_pattern": "weekly",
            "recurrence_interval": 1,
            "days_of_week": ["fri"],
            "end_type": "by_count",
            "end_after_count": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["created_count"] == 2
    assert payload["warnings"] == [
        "Skipped public holiday occurrence on 2026-05-01 (Labour Day)"
    ]
    assert {row["posting_code"] for row in payload["events"]} == {"TTSHCardio"}
    assert forbidden_body.status_code == 422


def test_series_deletion_scopes_single_following_all_and_blocks_attendance() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    second_event_id = fake_db.events[1]["id"]
    third_event_id = fake_db.events[2]["id"]

    single = client.delete(
        f"/secretary/teaching-events/series/{fake_db.series_id}",
        headers=_headers(fake_db),
        params={"scope": "single", "event_id": third_event_id},
    )
    following = client.delete(
        f"/secretary/teaching-events/series/{fake_db.series_id}",
        headers=_headers(fake_db),
        params={"scope": "following", "event_id": second_event_id},
    )
    blocked = client.delete(
        f"/secretary/teaching-events/series/{fake_db.series_id}",
        headers=_headers(fake_db),
        params={"scope": "all"},
    )

    assert single.status_code == 200
    assert single.json()["deleted_count"] == 1
    assert following.status_code == 200
    assert following.json()["deleted_count"] == 1
    assert blocked.status_code == 409


def test_cme_dashboard_is_scoped_to_secretary_posting() -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)

    response = client.get("/secretary/cme-dashboard", headers=_headers(fake_db))

    assert response.status_code == 200
    payload = response.json()
    assert payload["posting_code"] == "TTSHCardio"
    assert payload["total_events"] == 3


def test_cache_invalidation_called_after_event_mutations(monkeypatch) -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    calls: list[tuple[set[str], dict]] = []
    deleteable_event_id = fake_db.events[1]["id"]
    series_delete_event_id = fake_db.events[2]["id"]

    def _spy(domains, **scope):  # noqa: ANN001
        calls.append((set(domains), scope))
        return []

    monkeypatch.setattr("app.services.cache_invalidation.invalidate_cache", _spy)

    client.post(
        "/secretary/teaching-events",
        headers=_headers(fake_db),
        json={
            "teaching_name": "Journal Club",
            "event_date": "2026-05-18",
            "start_time": "10:00",
        },
    )
    client.post(
        "/secretary/teaching-events/duplicate",
        headers=_headers(fake_db),
        json={
            "source_event_id": fake_db.events[0]["id"],
            "event_date": "2026-05-25",
            "start_time": "10:00",
        },
    )
    client.delete(
        f"/secretary/teaching-events/{deleteable_event_id}",
        headers=_headers(fake_db),
    )
    client.post(
        "/secretary/teaching-events/series",
        headers=_headers(fake_db),
        json={
            "teaching_name": "Journal Club",
            "start_date": "2026-04-24",
            "start_time": "10:00",
            "recurrence_pattern": "weekly",
            "recurrence_interval": 1,
            "days_of_week": ["fri"],
            "end_type": "by_count",
            "end_after_count": 2,
        },
    )
    client.delete(
        f"/secretary/teaching-events/series/{fake_db.series_id}",
        headers=_headers(fake_db),
        params={"scope": "single", "event_id": series_delete_event_id},
    )

    assert len(calls) >= 5
    assert all({"secretary_events", "resident_events"} <= domains for domains, _scope in calls)
    assert all(scope["posting_code"] == "TTSHCardio" for _domains, scope in calls)


def test_secretary_event_mutation_invalidates_scoped_event_domains(monkeypatch) -> None:
    fake_db = FakeSecretarySession()
    client = _client(fake_db)
    calls: list[tuple[set[str], dict]] = []

    def _spy(domains, **scope):  # noqa: ANN001
        calls.append((set(domains), scope))
        return []

    monkeypatch.setattr("app.services.cache_invalidation.invalidate_cache", _spy)

    response = client.post(
        "/secretary/teaching-events",
        headers=_headers(fake_db),
        json={
            "teaching_name": "Journal Club",
            "event_date": "2026-05-18",
            "start_time": "10:00",
        },
    )

    assert response.status_code == 200
    assert calls
    domains, scope = calls[-1]
    assert {"secretary_events", "resident_events", "admin_reports", "resident_dashboard"} <= domains
    assert scope["posting_code"] == "TTSHCardio"
