from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import IntegrityError

from app.dependencies.staff_actor import StaffActorContext
from app.errors import ApiError
from app.middleware.auth_stub import AuthIdentity
from app.middleware.errors import install_error_handlers
from app.routers import admin
from app.services import admin_secretary_events, cache_invalidation


NOW = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)


class _FakeResult:
    def __init__(self, rows: list[dict] | None = None, scalar: object | None = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

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


class FakeAdminSecretaryEventsSession:
    def __init__(self) -> None:
        self.session_type_id = str(uuid4())
        self.other_session_type_id = str(uuid4())
        self.series_id = str(uuid4())
        self.reporting_period_id = str(uuid4())
        self.other_reporting_period_id = str(uuid4())
        self.secretary_event_id = str(uuid4())
        self.legacy_event_id = str(uuid4())
        self.programme_pc_event_id = str(uuid4())
        self.resident_adhoc_event_id = str(uuid4())
        self.external_adhoc_event_id = str(uuid4())
        self.executed_sql: list[str] = []
        self.committed = False
        self.add_called = False
        self.periods = {
            self.reporting_period_id: {
                "id": self.reporting_period_id,
                "label": "Jan - Jun 2026",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 6, 30),
            },
            self.other_reporting_period_id: {
                "id": self.other_reporting_period_id,
                "label": "Jul - Dec 2026",
                "start_date": date(2026, 7, 1),
                "end_date": date(2026, 12, 31),
            },
        }
        self.posting_codes = {
            "TTSHCardio": {
                "code": "TTSHCardio",
                "display_name": "TTSH Cardiology",
                "institution": "TTSH",
                "department": "Cardiology",
            },
            "TTSHNeuro": {
                "code": "TTSHNeuro",
                "display_name": "TTSH Neurology",
                "institution": "TTSH",
                "department": "Neurology",
            },
        }
        self.series = {
            self.series_id: {
                "id": self.series_id,
                "posting_code": "TTSHCardio",
                "recurrence_pattern": "weekly",
                "recurrence_interval": 1,
                "days_of_week": ["wed"],
                "end_type": "by_count",
                "end_date": None,
                "end_after_count": 3,
                "created_at": NOW,
                "updated_at": NOW,
            }
        }
        self.events = [
            self._event(
                event_id=self.secretary_event_id,
                posting_code="TTSHCardio",
                teaching_name="Journal Club",
                event_date=date(2026, 5, 6),
                start_time=time(10, 0),
                end_time=time(11, 0),
                session_type_id=self.session_type_id,
                session_type_name="Department Teaching [1h]",
                series_id=self.series_id,
                cme_points_awarded=True,
                smc_event_code="SMC-CARD-1",
                created_by_role="secretary",
            ),
            self._event(
                event_id=self.legacy_event_id,
                posting_code="TTSHCardio",
                teaching_name="Legacy Grand Round",
                event_date=date(2026, 5, 13),
                start_time=time(9, 0),
                end_time=time(10, 0),
                session_type_id=self.session_type_id,
                session_type_name="Department Teaching [1h]",
                created_by_role=None,
            ),
            self._event(
                event_id=self.programme_pc_event_id,
                posting_code="TTSHNeuro",
                teaching_name="Programme PC Teaching",
                event_date=date(2026, 5, 20),
                start_time=time(14, 0),
                end_time=time(15, 0),
                session_type_id=self.other_session_type_id,
                session_type_name="Programme Teaching [1h]",
                created_by_role="secretary",
                created_for_programme_code="DR",
            ),
            self._event(
                event_id=self.resident_adhoc_event_id,
                posting_code="TTSHCardio",
                teaching_name="Resident Adhoc",
                event_date=date(2026, 5, 9),
                start_time=time(9, 0),
                end_time=time(10, 0),
                session_type_id=self.session_type_id,
                session_type_name="Department Teaching [1h]",
                is_adhoc=True,
                created_by_role="resident",
            ),
            self._event(
                event_id=self.external_adhoc_event_id,
                posting_code="TTSHNeuro",
                teaching_name="Non-NHG Resident Adhoc",
                event_date=date(2026, 5, 10),
                start_time=time(14, 0),
                end_time=time(15, 0),
                session_type_id=self.other_session_type_id,
                session_type_name="Programme Teaching [1h]",
                is_adhoc=True,
                created_by_role="external_resident",
            ),
        ]
        self.attendance_statuses = {
            self.secretary_event_id: ("submitted", "flagged"),
            self.legacy_event_id: ("flagged",),
            self.programme_pc_event_id: ("removed",),
            self.resident_adhoc_event_id: ("submitted",),
            self.external_adhoc_event_id: (),
        }
        self.external_attendance_statuses = {
            self.secretary_event_id: ("removed",),
            self.legacy_event_id: ("removed",),
            self.programme_pc_event_id: ("submitted", "flagged"),
            self.resident_adhoc_event_id: (),
            self.external_adhoc_event_id: ("submitted",),
        }
        self.attendance_counts = {
            event_id: len(statuses) for event_id, statuses in self.attendance_statuses.items()
        }
        self.external_attendance_counts = {
            event_id: len(statuses)
            for event_id, statuses in self.external_attendance_statuses.items()
        }
        self.submitted_attendance_counts = {
            event_id: statuses.count("submitted")
            for event_id, statuses in self.attendance_statuses.items()
        }
        self.submitted_external_attendance_counts = {
            event_id: statuses.count("submitted")
            for event_id, statuses in self.external_attendance_statuses.items()
        }

    def _event(
        self,
        *,
        event_id: str,
        posting_code: str,
        teaching_name: str,
        event_date: date,
        start_time: time,
        end_time: time,
        session_type_id: str,
        session_type_name: str,
        series_id: str | None = None,
        cme_points_awarded: bool = False,
        smc_event_code: str | None = None,
        is_adhoc: bool = False,
        created_by_role: str | None = "secretary",
        created_for_programme_code: str | None = None,
    ) -> dict:
        return {
            "id": event_id,
            "posting_code": posting_code,
            "teaching_name": teaching_name,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
            "duration_hours": Decimal("1.0"),
            "session_type_id": session_type_id,
            "session_type_name": session_type_name,
            "series_id": series_id,
            "cme_points_awarded": cme_points_awarded,
            "smc_event_code": smc_event_code,
            "is_adhoc": is_adhoc,
            "created_by_role": created_by_role,
            "created_for_programme_code": created_for_programme_code,
            "created_at": NOW,
            "updated_at": NOW,
        }

    async def execute(self, statement, params=None):  # noqa: C901
        sql = str(statement)
        self.executed_sql.append(sql)
        payload = dict(params or {})
        self._assert_read_only_guardrails(sql)

        if "/* admin_secretary_events:list */" in sql:
            rows = self._filtered_events(payload, sql)
            total = len(rows)
            offset = int(payload.get("offset") or 0)
            limit = int(payload.get("limit") or total)
            page = rows[offset : offset + limit]
            return _FakeResult(rows=[{**row, "total": total} for row in page])

        if "/* admin_secretary_events:summary */" in sql:
            rows = self._filtered_events(payload, sql)
            return _FakeResult(
                rows=[
                    {
                        "total_events": len(rows),
                        "with_attendance": sum(
                            1
                            for row in rows
                            if row["attendance_count"] > 0
                            or row["external_attendance_count"] > 0
                        ),
                        "without_attendance": sum(
                            1
                            for row in rows
                            if row["attendance_count"] == 0
                            and row["external_attendance_count"] == 0
                        ),
                        "total_attendance_count": sum(row["attendance_count"] for row in rows),
                        "total_external_attendance_count": sum(
                            row["external_attendance_count"] for row in rows
                        ),
                    }
                ]
            )

        if "/* admin_secretary_events:detail */" in sql:
            event = next(
                (
                    row
                    for row in self._projected_rows()
                    if row["id"] == str(payload["event_id"])
                    and not row["is_adhoc"]
                ),
                None,
            )
            return _FakeResult(rows=[event] if event else [])

        raise AssertionError(f"Unexpected SQL: {sql}")

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        return None

    def add(self, _obj) -> None:
        self.add_called = True

    def _assert_read_only_guardrails(self, sql: str) -> None:
        lowered = sql.lower()
        assert "x-user-site" not in lowered
        assert "x-actor-name" not in lowered
        assert "calculate_compliance" not in lowered
        assert "period_snapshots" not in lowered
        assert "clawback" not in lowered
        assert "hibernate_stale_surplus" not in lowered
        assert "insert into" not in lowered
        assert "update " not in lowered
        assert "delete from" not in lowered

    def _projected_rows(self) -> list[dict]:
        rows = []
        for event in self.events:
            posting = self.posting_codes.get(event["posting_code"], {})
            series = self.series.get(event["series_id"])
            row = {
                **event,
                "posting_display_name": posting.get("display_name"),
                "posting_institution": posting.get("institution"),
                "posting_department": posting.get("department"),
                "attendance_count": self.submitted_attendance_counts.get(
                    event["id"], 0
                ),
                "external_attendance_count": self.submitted_external_attendance_counts.get(
                    event["id"], 0
                ),
                "native_attendance_count": self.attendance_counts.get(event["id"], 0),
                "non_nhg_attendance_count": self.external_attendance_counts.get(
                    event["id"], 0
                ),
                "has_attendance": self.submitted_attendance_counts.get(event["id"], 0)
                > 0
                or self.submitted_external_attendance_counts.get(event["id"], 0) > 0,
                "recurrence_pattern": series.get("recurrence_pattern") if series else None,
                "recurrence_interval": series.get("recurrence_interval") if series else None,
                "days_of_week": series.get("days_of_week") if series else None,
                "series_end_type": series.get("end_type") if series else None,
                "series_end_date": series.get("end_date") if series else None,
                "series_end_after_count": series.get("end_after_count") if series else None,
            }
            rows.append(row)
        return rows

    def _filtered_events(self, payload: dict, sql: str) -> list[dict]:
        rows = [
            row
            for row in self._projected_rows()
            if not row["is_adhoc"]
        ]
        if "te.created_for_programme_code IS NOT NULL" in sql:
            rows = [row for row in rows if row["created_for_programme_code"] is not None]
        elif "te.created_for_programme_code IS NULL" in sql:
            rows = [row for row in rows if row["created_for_programme_code"] is None]
        if payload.get("reporting_period_id"):
            period = self.periods[str(payload["reporting_period_id"])]
            rows = [
                row
                for row in rows
                if period["start_date"] <= row["event_date"] <= period["end_date"]
            ]
        if payload.get("posting_code"):
            rows = [row for row in rows if row["posting_code"] == payload["posting_code"]]
        if payload.get("date_from"):
            rows = [row for row in rows if row["event_date"] >= payload["date_from"]]
        if payload.get("date_to"):
            rows = [row for row in rows if row["event_date"] <= payload["date_to"]]
        if payload.get("teaching_name_pattern"):
            needle = str(payload["teaching_name_pattern"]).replace("%", "").casefold()
            rows = [row for row in rows if needle in row["teaching_name"].casefold()]
        if payload.get("search_pattern"):
            needle = str(payload["search_pattern"]).replace("%", "").casefold()
            rows = [
                row
                for row in rows
                if needle in row["teaching_name"].casefold()
                or needle in row["posting_code"].casefold()
                or needle in (row["posting_display_name"] or "").casefold()
                or needle in (row["smc_event_code"] or "").casefold()
            ]
        if payload.get("has_attendance") is True:
            rows = [row for row in rows if row["has_attendance"]]
        if payload.get("has_attendance") is False:
            rows = [row for row in rows if not row["has_attendance"]]
        if payload.get("session_type_id"):
            rows = [row for row in rows if row["session_type_id"] == str(payload["session_type_id"])]
        if payload.get("series_id"):
            rows = [row for row in rows if row["series_id"] == str(payload["series_id"])]
        rows.sort(key=lambda row: (row["event_date"], row["start_time"], row["teaching_name"]))
        return rows


class _ForeignKeyViolation(Exception):
    sqlstate = "23503"


class FakeAdminEventForceDeleteSession:
    def __init__(
        self,
        *,
        native_statuses: tuple[str, ...] = (),
        external_statuses: tuple[str, ...] = (),
        source_type: str = "programme_pc",
        is_adhoc: bool = False,
        created_by_role: str | None = None,
        fail_at: str | None = None,
        count_mismatch: bool = False,
    ) -> None:
        self.event_id = str(uuid4())
        self.sibling_event_id = str(uuid4())
        self.unrelated_event_id = str(uuid4())
        self.series_id = str(uuid4())
        owner = "DR" if source_type == "programme_pc" else None
        self.events = {
            self.event_id: self._event(
                self.event_id,
                teaching_name="Programme PC Teaching" if owner else "Secretary Teaching",
                owner=owner,
                series_id=self.series_id,
                is_adhoc=is_adhoc,
                created_by_role=(
                    created_by_role
                    if created_by_role is not None
                    else "secretary" if owner else "programme_pc"
                ),
            ),
            self.sibling_event_id: self._event(
                self.sibling_event_id,
                teaching_name="Series sibling",
                owner=owner,
                series_id=self.series_id,
                event_date=date(2026, 5, 27),
            ),
            self.unrelated_event_id: self._event(
                self.unrelated_event_id,
                teaching_name="Unrelated teaching",
                owner=None,
                series_id=None,
                event_date=date(2026, 6, 3),
            ),
        }
        self.event_series = {self.series_id: {"id": self.series_id}}
        self.native_attendance = [
            {
                "id": str(uuid4()),
                "teaching_event_id": self.event_id,
                "status": status,
            }
            for status in native_statuses
        ]
        self.external_attendance = [
            {
                "id": str(uuid4()),
                "teaching_event_id": self.event_id,
                "status": status,
            }
            for status in external_statuses
        ]
        self.unrelated_native_attendance_id = str(uuid4())
        self.unrelated_external_attendance_id = str(uuid4())
        self.native_attendance.append(
            {
                "id": self.unrelated_native_attendance_id,
                "teaching_event_id": self.unrelated_event_id,
                "status": "submitted",
            }
        )
        self.external_attendance.append(
            {
                "id": self.unrelated_external_attendance_id,
                "teaching_event_id": self.sibling_event_id,
                "status": "submitted",
            }
        )
        self.audit_logs: list[dict] = []
        self.executed_sql: list[str] = []
        self.operations: list[str] = []
        self.committed = False
        self.rollback_count = 0
        self.fail_at = fail_at
        self.count_mismatch = count_mismatch
        self._initial = self._snapshot()

    @staticmethod
    def _event(
        event_id: str,
        *,
        teaching_name: str,
        owner: str | None,
        series_id: str | None,
        event_date: date = date(2026, 5, 20),
        is_adhoc: bool = False,
        created_by_role: str | None = "secretary",
    ) -> dict:
        return {
            "id": event_id,
            "posting_code": "TTSHCardio",
            "created_for_programme_code": owner,
            "teaching_name": teaching_name,
            "details_of_session": "Bounded operational context",
            "event_date": event_date,
            "start_time": time(10, 0),
            "end_time": time(11, 0),
            "duration_hours": Decimal("1.0"),
            "session_type_id": str(uuid4()),
            "series_id": series_id,
            "cme_points_awarded": True,
            "smc_event_code": "SMC-001",
            "is_adhoc": is_adhoc,
            "created_by_role": created_by_role,
            "created_at": NOW,
            "updated_at": NOW,
        }

    def _snapshot(self) -> dict:
        return {
            "events": deepcopy(self.events),
            "event_series": deepcopy(self.event_series),
            "native_attendance": deepcopy(self.native_attendance),
            "external_attendance": deepcopy(self.external_attendance),
            "audit_logs": deepcopy(self.audit_logs),
        }

    def _restore(self, snapshot: dict) -> None:
        self.events = deepcopy(snapshot["events"])
        self.event_series = deepcopy(snapshot["event_series"])
        self.native_attendance = deepcopy(snapshot["native_attendance"])
        self.external_attendance = deepcopy(snapshot["external_attendance"])
        self.audit_logs = deepcopy(snapshot["audit_logs"])

    def _target_native(self) -> list[dict]:
        return [
            row for row in self.native_attendance if row["teaching_event_id"] == self.event_id
        ]

    def _target_external(self) -> list[dict]:
        return [
            row
            for row in self.external_attendance
            if row["teaching_event_id"] == self.event_id
        ]

    async def execute(self, statement, params=None):  # noqa: C901
        sql = str(statement)
        payload = dict(params or {})
        self.executed_sql.append(sql)

        if "/* admin_secretary_events:force_delete_lock */" in sql:
            self.operations.append("lock_event")
            event = self.events.get(str(payload["event_id"]))
            return _FakeResult(rows=[deepcopy(event)] if event else [])

        if "/* admin_secretary_events:force_delete_counts */" in sql:
            self.operations.append("count_attendance")
            native_count = len(self._target_native())
            external_count = len(self._target_external())
            if self.count_mismatch:
                native_count += 1
            return _FakeResult(
                rows=[
                    {
                        "native_attendance_count": native_count,
                        "external_attendance_count": external_count,
                    }
                ]
            )

        if "/* admin_secretary_events:force_delete_native_attendance */" in sql:
            self.operations.append("delete_native_attendance")
            deleted = self._target_native()
            self.native_attendance = [
                row
                for row in self.native_attendance
                if row["teaching_event_id"] != self.event_id
            ]
            return _FakeResult(rows=[{"id": row["id"]} for row in deleted])

        if "/* admin_secretary_events:force_delete_external_attendance */" in sql:
            self.operations.append("delete_external_attendance")
            deleted = self._target_external()
            self.external_attendance = [
                row
                for row in self.external_attendance
                if row["teaching_event_id"] != self.event_id
            ]
            return _FakeResult(rows=[{"id": row["id"]} for row in deleted])

        if "/* admin_secretary_events:force_delete_event */" in sql:
            self.operations.append("delete_event")
            if self.fail_at == "event_delete_integrity":
                raise IntegrityError("DELETE", payload, _ForeignKeyViolation())
            event = self.events.pop(str(payload["event_id"]), None)
            return _FakeResult(rows=[{"id": event["id"]}] if event else [])

        if "INSERT INTO audit_logs" in sql:
            self.operations.append("write_audit")
            if self.fail_at == "audit":
                raise RuntimeError("forced audit failure")
            audit = {**payload, "created_at": NOW}
            self.audit_logs.append(deepcopy(audit))
            return _FakeResult(rows=[audit])

        raise AssertionError(f"Unexpected SQL: {sql}")

    async def commit(self) -> None:
        self.operations.append("commit")
        if self.fail_at == "commit":
            raise RuntimeError("forced commit failure")
        self.committed = True

    async def rollback(self) -> None:
        self.operations.append("rollback")
        self.rollback_count += 1
        self._restore(self._initial)


def _force_delete_body(
    session: FakeAdminEventForceDeleteSession,
    *,
    reason: str,
    confirmation: str = "DELETE",
    expected_native_attendance_count: int | None = None,
    expected_external_attendance_count: int | None = None,
) -> dict:
    return {
        "reason": reason,
        "confirmation": confirmation,
        "expected_native_attendance_count": (
            len(session._target_native())
            if expected_native_attendance_count is None
            else expected_native_attendance_count
        ),
        "expected_external_attendance_count": (
            len(session._target_external())
            if expected_external_attendance_count is None
            else expected_external_attendance_count
        ),
    }


def _client(
    session: FakeAdminSecretaryEventsSession | FakeAdminEventForceDeleteSession,
    *,
    identity: AuthIdentity | None = None,
) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    if identity is not None:

        @app.middleware("http")
        async def inject_verified_identity(request, call_next):  # noqa: ANN001
            request.state.identity = identity
            return await call_next(request)

    app.include_router(admin.router)

    async def override_db():
        yield session

    app.dependency_overrides[admin.get_db_session] = override_db
    return TestClient(app, raise_server_exceptions=False)


def _headers(
    *,
    role: str = "admin",
    scope: str | None = "DR,GERI",
    master: bool = True,
    user_id: str | None = None,
    include_site: bool = False,
    include_actor_name: bool = False,
) -> dict[str, str]:
    headers = {
        "X-User-Role": role,
        "X-User-Id": user_id or str(uuid4()),
    }
    if scope is not None:
        headers["X-User-Programme"] = scope
    if master:
        headers["X-Admin-Level"] = "master"
    if include_site:
        site_header = "-".join(["X", "User", "Site"])
        headers[site_header] = "TTSHCardio"
    if include_actor_name:
        headers["-".join(["X", "Actor", "Name"])] = "Legacy Actor"
    return headers


def test_master_admin_list_includes_secretary_and_programme_pc_events_with_counts() -> None:
    session = FakeAdminSecretaryEventsSession()
    client = _client(session)

    response = client.get("/admin/secretary-events", headers=_headers())

    assert response.status_code == 200
    payload = response.json()
    ids = {row["id"] for row in payload["items"]}
    assert session.secretary_event_id in ids
    assert session.legacy_event_id in ids
    assert session.programme_pc_event_id in ids
    assert session.resident_adhoc_event_id not in ids
    assert session.external_adhoc_event_id not in ids
    first = next(row for row in payload["items"] if row["id"] == session.secretary_event_id)
    legacy = next(row for row in payload["items"] if row["id"] == session.legacy_event_id)
    pc_event = next(
        row for row in payload["items"] if row["id"] == session.programme_pc_event_id
    )
    assert first["posting_display_name"] == "TTSH Cardiology"
    assert first["attendance_count"] == 1
    assert first["native_attendance_count"] == 2
    assert first["external_attendance_count"] == 0
    assert first["non_nhg_attendance_count"] == 1
    assert first["total_attendance_count"] == 3
    assert first["has_attendance"] is True
    assert first["source_type"] == "secretary"
    assert first["created_for_programme_code"] is None
    assert first["force_delete_allowed"] is True
    assert first["session_type_name"] == "Department Teaching [1h]"
    assert session.attendance_statuses[session.secretary_event_id] == (
        "submitted",
        "flagged",
    )
    assert session.external_attendance_statuses[session.secretary_event_id] == ("removed",)
    assert pc_event["source_type"] == "programme_pc"
    assert pc_event["created_for_programme_code"] == "DR"
    assert pc_event["created_by_role"] == "secretary"
    assert pc_event["total_attendance_count"] == 3
    assert pc_event["attendance_count"] == 0
    assert pc_event["external_attendance_count"] == 1
    assert pc_event["native_attendance_count"] == 1
    assert pc_event["non_nhg_attendance_count"] == 2
    assert legacy["attendance_count"] == 0
    assert legacy["external_attendance_count"] == 0
    assert legacy["native_attendance_count"] == 1
    assert legacy["non_nhg_attendance_count"] == 1
    assert legacy["total_attendance_count"] == 2
    assert legacy["has_attendance"] is False
    assert payload["total"] == 3
    assert payload["summary"]["total_events"] == 3
    assert payload["summary"]["with_attendance"] == 2
    assert payload["summary"]["without_attendance"] == 1
    assert payload["summary"]["total_attendance_count"] == 1
    assert payload["summary"]["total_external_attendance_count"] == 1
    assert session.committed is False
    assert session.add_called is False

    list_sql = next(
        sql for sql in session.executed_sql if "/* admin_secretary_events:list */" in sql
    )
    assert list_sql.count("status = 'submitted'") == 2
    assert "JOIN attendance_records" not in list_sql
    assert "JOIN external_attendance_records" not in list_sql
    assert "JOIN teaching_name_catalogue" not in list_sql
    assert len(ids) == len(payload["items"])


def test_secretary_resident_and_empty_scope_pc_cannot_access_admin_secretary_events() -> None:
    session = FakeAdminSecretaryEventsSession()
    client = _client(session)

    secretary = client.get("/admin/secretary-events", headers=_headers(role="secretary", master=False))
    resident = client.get("/admin/secretary-events", headers=_headers(role="resident", master=False))
    empty_scope_pc = client.get("/admin/secretary-events", headers=_headers(scope="", master=False))
    null_scope_pc = client.get(
        "/admin/secretary-events", headers=_headers(scope=None, master=False)
    )
    programme_pc = client.get("/admin/secretary-events", headers=_headers(scope="DR", master=False))

    assert secretary.status_code == 403
    assert resident.status_code == 403
    assert empty_scope_pc.status_code == 403
    assert null_scope_pc.status_code == 403
    assert programme_pc.status_code == 403


def test_admin_secretary_event_list_filters_are_applied() -> None:
    session = FakeAdminSecretaryEventsSession()
    client = _client(session)

    response = client.get(
        "/admin/secretary-events",
        headers=_headers(),
        params={
            "reporting_period_id": session.reporting_period_id,
            "posting_code": "TTSHCardio",
            "date_from": "2026-05-01",
            "date_to": "2026-05-10",
            "search": "journal",
            "has_attendance": "true",
            "limit": "10",
            "offset": "0",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [row["id"] for row in payload["items"]] == [session.secretary_event_id]
    assert payload["summary"]["total_events"] == 1

    without_submitted_attendance = client.get(
        "/admin/secretary-events",
        headers=_headers(),
        params={"has_attendance": "false"},
    )
    assert without_submitted_attendance.status_code == 200
    without_payload = without_submitted_attendance.json()
    assert [row["id"] for row in without_payload["items"]] == [
        session.legacy_event_id
    ]
    assert without_payload["items"][0]["total_attendance_count"] == 2


def test_admin_secretary_event_source_filter_uses_programme_owner_marker() -> None:
    session = FakeAdminSecretaryEventsSession()
    client = _client(session)

    secretary = client.get(
        "/admin/secretary-events",
        headers=_headers(),
        params={"source_type": "secretary"},
    )
    programme_pc = client.get(
        "/admin/secretary-events",
        headers=_headers(),
        params={"source_type": "programme_pc"},
    )
    invalid = client.get(
        "/admin/secretary-events",
        headers=_headers(),
        params={"source_type": "resident"},
    )

    assert secretary.status_code == 200
    assert {row["id"] for row in secretary.json()["items"]} == {
        session.secretary_event_id,
        session.legacy_event_id,
    }
    assert {row["source_type"] for row in secretary.json()["items"]} == {"secretary"}
    assert programme_pc.status_code == 200
    assert [row["id"] for row in programme_pc.json()["items"]] == [
        session.programme_pc_event_id
    ]
    assert programme_pc.json()["items"][0]["created_by_role"] == "secretary"
    assert invalid.status_code == 422


def test_admin_secretary_event_detail_is_bounded_metadata() -> None:
    session = FakeAdminSecretaryEventsSession()
    client = _client(session)

    response = client.get(
        f"/admin/secretary-events/{session.secretary_event_id}",
        headers=_headers(),
    )
    adhoc_response = client.get(
        f"/admin/secretary-events/{session.resident_adhoc_event_id}",
        headers=_headers(),
    )
    pc_response = client.get(
        f"/admin/secretary-events/{session.programme_pc_event_id}",
        headers=_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == session.secretary_event_id
    assert payload["posting"]["code"] == "TTSHCardio"
    assert payload["recurrence"]["series_id"] == session.series_id
    assert payload["attendance_counts"]["native"] == 2
    assert payload["attendance_counts"]["external"] == 1
    assert payload["attendance_counts"]["total"] == 3
    assert payload["source_type"] == "secretary"
    assert "attendance_records" not in payload
    assert "resident_submissions" not in payload
    assert "summary" not in payload
    assert adhoc_response.status_code == 404
    assert pc_response.status_code == 200
    assert pc_response.json()["source_type"] == "programme_pc"
    assert pc_response.json()["created_for_programme_code"] == "DR"


def test_admin_secretary_events_do_not_require_or_use_secretary_headers() -> None:
    session = FakeAdminSecretaryEventsSession()
    client = _client(session)
    site_header = "-".join(["X", "User", "Site"])

    response = client.get(
        "/admin/secretary-events",
        headers=_headers(include_site=True, include_actor_name=True),
    )

    assert response.status_code == 200
    assert any("/* admin_secretary_events:list */" in sql for sql in session.executed_sql)
    assert all(site_header not in sql for sql in session.executed_sql)
    assert all("-".join(["X", "Actor", "Name"]) not in sql for sql in session.executed_sql)


@pytest.mark.parametrize(
    ("native_statuses", "external_statuses"),
    [
        ((), ()),
        (("submitted",), ()),
        ((), ("removed",)),
        (("submitted", "flagged"), ("submitted", "removed")),
    ],
    ids=["no-attendance", "native", "external", "mixed-all-statuses"],
)
def test_master_admin_force_delete_removes_exact_linked_rows_and_selected_occurrence(
    monkeypatch: pytest.MonkeyPatch,
    native_statuses: tuple[str, ...],
    external_statuses: tuple[str, ...],
) -> None:
    session = FakeAdminEventForceDeleteSession(
        native_statuses=native_statuses,
        external_statuses=external_statuses,
    )
    cache_calls: list[tuple[tuple[str, ...], dict]] = []

    def cache_spy(domains, **scope):  # noqa: ANN001
        assert session.committed is True
        session.operations.append("invalidate_cache")
        cache_calls.append((tuple(domains), scope))
        return []

    monkeypatch.setattr("app.services.cache_invalidation.invalidate_cache", cache_spy)
    response = _client(session).post(
        f"/admin/secretary-events/{session.event_id}/force-delete",
        headers=_headers(),
        json=_force_delete_body(session, reason="Operational correction"),
    )

    assert response.status_code == 200
    assert response.json() == {
        "event_id": session.event_id,
        "deleted": True,
        "source_type": "programme_pc",
        "native_attendance_deleted": len(native_statuses),
        "external_attendance_deleted": len(external_statuses),
        "total_attendance_deleted": len(native_statuses) + len(external_statuses),
    }
    assert session.event_id not in session.events
    assert session.sibling_event_id in session.events
    assert session.unrelated_event_id in session.events
    assert session.series_id in session.event_series
    assert session._target_native() == []
    assert session._target_external() == []
    assert any(
        row["id"] == session.unrelated_native_attendance_id
        for row in session.native_attendance
    )
    assert any(
        row["id"] == session.unrelated_external_attendance_id
        for row in session.external_attendance
    )
    assert len(session.audit_logs) == 1
    assert session.rollback_count == 0
    assert session.operations == [
        "lock_event",
        "count_attendance",
        "delete_native_attendance",
        "delete_external_attendance",
        "delete_event",
        "write_audit",
        "commit",
        "invalidate_cache",
    ]
    assert len(cache_calls) == 1
    domains, scope = cache_calls[0]
    assert {
        "teaching_events",
        "secretary_events",
        "admin_secretary_events",
        "resident_events",
        "resident_attendance",
        "external_attendance",
        "resident_dashboard",
        "admin_reports",
    }.issubset(set(domains))
    assert str(scope["event_id"]) == session.event_id
    assert scope["posting_code"] == "TTSHCardio"
    assert scope["programme_code"] == "DR"


def test_force_delete_cache_failure_does_not_misreport_committed_deletion(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = FakeAdminEventForceDeleteSession(
        native_statuses=("submitted",),
        external_statuses=("submitted",),
    )

    def fail_cache_invalidation(**_kwargs) -> None:
        raise RuntimeError("forced cache invalidation failure")

    monkeypatch.setattr(
        cache_invalidation,
        "invalidate_after_admin_event_force_delete",
        fail_cache_invalidation,
    )
    response = _client(session).post(
        f"/admin/secretary-events/{session.event_id}/force-delete",
        headers=_headers(),
        json=_force_delete_body(session, reason="Committed cache failure exercise"),
    )

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert session.committed is True
    assert session.event_id not in session.events
    assert len(session.audit_logs) == 1
    assert "admin_teaching_event_cache_invalidation_failed" in caplog.text
    assert "exception_class=RuntimeError" in caplog.text
    assert "forced cache invalidation failure" not in caplog.text
    assert "Traceback" not in caplog.text


def test_explicit_master_with_empty_scope_can_force_delete_secretary_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeAdminEventForceDeleteSession(source_type="secretary")
    monkeypatch.setattr(
        "app.services.cache_invalidation.invalidate_cache", lambda *_args, **_kwargs: []
    )

    response = _client(session).post(
        f"/admin/secretary-events/{session.event_id}/force-delete",
        headers=_headers(scope="", master=True),
        json=_force_delete_body(session, reason="Duplicate schedule"),
    )

    assert response.status_code == 200
    assert response.json()["source_type"] == "secretary"
    audit_before = json.loads(session.audit_logs[0]["before_json"])
    assert audit_before["created_for_programme_code"] is None
    assert audit_before["created_by_role"] == "programme_pc"


def test_force_delete_audit_contains_actor_snapshot_reason_source_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeAdminEventForceDeleteSession(
        native_statuses=("submitted", "flagged"),
        external_statuses=("removed",),
    )
    actor_id = str(uuid4())
    monkeypatch.setattr(
        "app.services.cache_invalidation.invalidate_cache", lambda *_args, **_kwargs: []
    )

    response = _client(session).post(
        f"/admin/secretary-events/{session.event_id}/force-delete",
        headers=_headers(scope="", user_id=actor_id),
        json=_force_delete_body(session, reason="  Incorrect operational schedule  "),
    )

    assert response.status_code == 200
    assert len(session.audit_logs) == 1
    audit = session.audit_logs[0]
    before = json.loads(audit["before_json"])
    after = json.loads(audit["after_json"])
    metadata = json.loads(audit["metadata_json"])
    assert audit["actor_user_id"] == actor_id
    assert audit["actor_role"] == "admin"
    assert audit["actor_admin_level"] == "master"
    assert audit["actor_name"]
    assert audit["action"] == "admin.teaching_event.force_delete"
    assert audit["entity_type"] == "teaching_event"
    assert audit["entity_id"] == session.event_id
    assert before["id"] == session.event_id
    assert before["teaching_name"] == "Programme PC Teaching"
    assert before["details_of_session"] == "Bounded operational context"
    assert before["posting_code"] == "TTSHCardio"
    assert before["created_for_programme_code"] == "DR"
    assert before["series_id"] == session.series_id
    assert after["deleted"] is True
    assert after["native_attendance_deleted"] == 2
    assert after["external_attendance_deleted"] == 1
    assert after["total_attendance_deleted"] == 3
    assert after["deleted_at"]
    assert metadata["deletion_reason"] == "Incorrect operational schedule"
    assert metadata["event_source_type"] == "programme_pc"
    assert metadata["owner_programme_code"] == "DR"
    assert metadata["posting_code"] == "TTSHCardio"
    assert metadata["event_date"] == "2026-05-20"
    assert metadata["teaching_name"] == "Programme PC Teaching"
    assert metadata["series_id"] == session.series_id
    assert metadata["native_attendance_deleted"] == 2
    assert metadata["external_attendance_deleted"] == 1
    assert metadata["total_attendance_deleted"] == 3
    assert metadata["deleted_at"]
    assert metadata["attendance_identifiers_included"] is False
    serialized_audit = json.dumps(audit, default=str).casefold()
    assert "mcr" not in serialized_audit
    assert "access_token" not in serialized_audit


@pytest.mark.parametrize(
    ("role", "scope"),
    [
        ("secretary", "DR"),
        ("resident", "DR"),
        ("external_resident", "DR"),
        ("admin", "DR"),
        ("admin", ""),
        ("admin", None),
    ],
    ids=[
        "secretary",
        "resident",
        "non-nhg-resident",
        "programme-pc",
        "empty-scope-programme-pc",
        "null-scope-programme-pc",
    ],
)
def test_non_master_callers_cannot_force_delete(
    role: str,
    scope: str | None,
) -> None:
    session = FakeAdminEventForceDeleteSession()
    response = _client(session).post(
        f"/admin/secretary-events/{session.event_id}/force-delete",
        headers=_headers(role=role, scope=scope, master=False),
        json=_force_delete_body(session, reason="Should not be allowed"),
    )

    assert response.status_code == 403
    assert session.executed_sql == []
    assert session._snapshot() == session._initial


def test_verified_programme_admin_cannot_spoof_master_header() -> None:
    session = FakeAdminEventForceDeleteSession()
    identity = AuthIdentity(
        role="admin",
        subject_id=str(uuid4()),
        programme_scope=[],
        admin_level="programme",
    )
    response = _client(session, identity=identity).post(
        f"/admin/secretary-events/{session.event_id}/force-delete",
        headers=_headers(scope="", master=True),
        json=_force_delete_body(session, reason="Spoof attempt"),
    )

    assert response.status_code == 403
    assert session.executed_sql == []
    assert session._snapshot() == session._initial


def test_force_delete_service_rejects_non_master_actor_before_database_work() -> None:
    session = FakeAdminEventForceDeleteSession()
    actor = StaffActorContext(
        actor_user_id=uuid4(),
        actor_role="admin",
        actor_name="Programme PC",
        actor_admin_level="programme",
    )

    with pytest.raises(ApiError) as exc_info:
        asyncio.run(
            admin_secretary_events.force_delete_event(
                session,
                event_id=uuid4(),
                reason="Operational reason",
                expected_native_attendance_count=0,
                expected_external_attendance_count=0,
                actor=actor,
            )
        )

    assert exc_info.value.status_code == 403
    assert session.executed_sql == []
    assert session.rollback_count == 1
    assert session._snapshot() == session._initial


@pytest.mark.parametrize(
    "body",
    [
        {"reason": "", "confirmation": "DELETE"},
        {"reason": "   ", "confirmation": "DELETE"},
        {"reason": "Operational correction", "confirmation": "delete"},
        {"reason": "Operational correction", "confirmation": "DELETE "},
    ],
    ids=["empty-reason", "blank-reason", "lowercase-confirmation", "spaced-confirmation"],
)
def test_force_delete_requires_reason_and_exact_confirmation(body: dict) -> None:
    session = FakeAdminEventForceDeleteSession()
    response = _client(session).post(
        f"/admin/secretary-events/{session.event_id}/force-delete",
        headers=_headers(),
        json={
            **body,
            "expected_native_attendance_count": 0,
            "expected_external_attendance_count": 0,
        },
    )

    assert response.status_code == 422
    assert session.executed_sql == []
    assert session._snapshot() == session._initial


def test_force_delete_requires_confirmation_impact_counts() -> None:
    session = FakeAdminEventForceDeleteSession()
    response = _client(session).post(
        f"/admin/secretary-events/{session.event_id}/force-delete",
        headers=_headers(),
        json={"reason": "Missing impact", "confirmation": "DELETE"},
    )

    assert response.status_code == 422
    assert session.executed_sql == []
    assert session._snapshot() == session._initial


@pytest.mark.parametrize("created_by_role", ["resident", "external_resident"])
def test_force_delete_rejects_native_and_non_nhg_ad_hoc_events(
    created_by_role: str,
) -> None:
    session = FakeAdminEventForceDeleteSession(
        native_statuses=("submitted",),
        external_statuses=("submitted",),
        source_type="secretary",
        is_adhoc=True,
        created_by_role=created_by_role,
    )
    response = _client(session).post(
        f"/admin/secretary-events/{session.event_id}/force-delete",
        headers=_headers(),
        json=_force_delete_body(session, reason="Not eligible"),
    )

    assert response.status_code == 422
    assert "Ad-hoc" in response.json()["detail"]
    assert session.operations == ["lock_event", "rollback"]
    assert session._snapshot() == session._initial


def test_force_delete_returns_404_for_missing_event() -> None:
    session = FakeAdminEventForceDeleteSession()
    response = _client(session).post(
        f"/admin/secretary-events/{uuid4()}/force-delete",
        headers=_headers(),
        json=_force_delete_body(session, reason="Missing event"),
    )

    assert response.status_code == 404
    assert session.operations == ["lock_event", "rollback"]
    assert session._snapshot() == session._initial


def test_force_delete_commit_failure_rolls_back_event_attendance_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeAdminEventForceDeleteSession(
        native_statuses=("submitted", "flagged"),
        external_statuses=("removed",),
        fail_at="commit",
    )
    cache_calls: list[object] = []
    monkeypatch.setattr(
        "app.services.cache_invalidation.invalidate_cache",
        lambda *args, **kwargs: cache_calls.append((args, kwargs)),
    )

    response = _client(session).post(
        f"/admin/secretary-events/{session.event_id}/force-delete",
        headers=_headers(),
        json=_force_delete_body(session, reason="Rollback exercise"),
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"
    assert session.committed is False
    assert session.rollback_count == 1
    assert session._snapshot() == session._initial
    assert session.audit_logs == []
    assert cache_calls == []
    assert session.operations == [
        "lock_event",
        "count_attendance",
        "delete_native_attendance",
        "delete_external_attendance",
        "delete_event",
        "write_audit",
        "commit",
        "rollback",
    ]


def test_force_delete_count_change_returns_409_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeAdminEventForceDeleteSession(
        native_statuses=("submitted",),
        external_statuses=("submitted",),
        count_mismatch=True,
    )
    cache_calls: list[object] = []
    monkeypatch.setattr(
        "app.services.cache_invalidation.invalidate_cache",
        lambda *args, **kwargs: cache_calls.append((args, kwargs)),
    )

    response = _client(session).post(
        f"/admin/secretary-events/{session.event_id}/force-delete",
        headers=_headers(),
        json=_force_delete_body(
            session,
            reason="Concurrent edit",
            expected_native_attendance_count=len(session._target_native()) + 1,
        ),
    )

    assert response.status_code == 409
    assert "changed during deletion" in response.json()["detail"]
    assert session._snapshot() == session._initial
    assert session.audit_logs == []
    assert cache_calls == []


def test_force_delete_stale_confirmation_impact_returns_409_before_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeAdminEventForceDeleteSession(
        native_statuses=("submitted",),
        external_statuses=("submitted",),
    )
    cache_calls: list[object] = []
    monkeypatch.setattr(
        "app.services.cache_invalidation.invalidate_cache",
        lambda *args, **kwargs: cache_calls.append((args, kwargs)),
    )

    response = _client(session).post(
        f"/admin/secretary-events/{session.event_id}/force-delete",
        headers=_headers(),
        json=_force_delete_body(
            session,
            reason="Stale displayed impact",
            expected_native_attendance_count=0,
            expected_external_attendance_count=0,
        ),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Linked attendance changed since confirmation; "
        "review the updated impact and retry"
    )
    assert session.operations == ["lock_event", "count_attendance", "rollback"]
    assert session._snapshot() == session._initial
    assert session.audit_logs == []
    assert cache_calls == []


def test_force_delete_foreign_key_conflict_returns_safe_409_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeAdminEventForceDeleteSession(
        native_statuses=("submitted",),
        external_statuses=("submitted",),
        fail_at="event_delete_integrity",
    )
    cache_calls: list[object] = []
    monkeypatch.setattr(
        "app.services.cache_invalidation.invalidate_cache",
        lambda *args, **kwargs: cache_calls.append((args, kwargs)),
    )

    response = _client(session).post(
        f"/admin/secretary-events/{session.event_id}/force-delete",
        headers=_headers(),
        json=_force_delete_body(session, reason="Concurrent insert"),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Teaching event attendance changed during deletion; please retry"
    )
    assert session._snapshot() == session._initial
    assert session.audit_logs == []
    assert cache_calls == []
