from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import admin


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
        self.adhoc_event_id = str(uuid4())
        self.admin_event_id = str(uuid4())
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
                event_id=self.adhoc_event_id,
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
                event_id=self.admin_event_id,
                posting_code="TTSHNeuro",
                teaching_name="Future PC Teaching",
                event_date=date(2026, 5, 20),
                start_time=time(14, 0),
                end_time=time(15, 0),
                session_type_id=self.other_session_type_id,
                session_type_name="Programme Teaching [1h]",
                created_by_role="admin",
            ),
        ]
        self.attendance_counts = {
            self.secretary_event_id: 2,
            self.legacy_event_id: 0,
            self.adhoc_event_id: 1,
            self.admin_event_id: 1,
        }
        self.external_attendance_counts = {
            self.secretary_event_id: 1,
            self.legacy_event_id: 0,
            self.adhoc_event_id: 0,
            self.admin_event_id: 0,
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
            "created_at": NOW,
            "updated_at": NOW,
        }

    async def execute(self, statement, params=None):  # noqa: C901
        sql = str(statement)
        self.executed_sql.append(sql)
        payload = dict(params or {})
        self._assert_read_only_guardrails(sql)

        if "/* admin_secretary_events:list */" in sql:
            rows = self._filtered_events(payload)
            total = len(rows)
            offset = int(payload.get("offset") or 0)
            limit = int(payload.get("limit") or total)
            page = rows[offset : offset + limit]
            return _FakeResult(rows=[{**row, "total": total} for row in page])

        if "/* admin_secretary_events:summary */" in sql:
            rows = self._filtered_events(payload)
            return _FakeResult(
                rows=[
                    {
                        "total_events": len(rows),
                        "with_attendance": sum(1 for row in rows if row["attendance_count"] > 0),
                        "without_attendance": sum(1 for row in rows if row["attendance_count"] == 0),
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
                    and row["created_by_role"] in {"secretary", None}
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
                "attendance_count": self.attendance_counts.get(event["id"], 0),
                "external_attendance_count": self.external_attendance_counts.get(event["id"], 0),
                "has_attendance": self.attendance_counts.get(event["id"], 0) > 0
                or self.external_attendance_counts.get(event["id"], 0) > 0,
                "recurrence_pattern": series.get("recurrence_pattern") if series else None,
                "recurrence_interval": series.get("recurrence_interval") if series else None,
                "days_of_week": series.get("days_of_week") if series else None,
                "series_end_type": series.get("end_type") if series else None,
                "series_end_date": series.get("end_date") if series else None,
                "series_end_after_count": series.get("end_after_count") if series else None,
            }
            rows.append(row)
        return rows

    def _filtered_events(self, payload: dict) -> list[dict]:
        rows = [
            row
            for row in self._projected_rows()
            if not row["is_adhoc"] and row["created_by_role"] in {"secretary", None}
        ]
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


def _client(session: FakeAdminSecretaryEventsSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def override_db():
        yield session

    app.dependency_overrides[admin.get_db_session] = override_db
    return TestClient(app)


def _headers(
    *,
    role: str = "admin",
    scope: str = "DR,GERI",
    master: bool = True,
    include_site: bool = False,
    include_actor_name: bool = False,
) -> dict[str, str]:
    headers = {
        "X-User-Role": role,
        "X-User-Id": str(uuid4()),
        "X-User-Programme": scope,
    }
    if master:
        headers["X-Admin-Level"] = "master"
    if include_site:
        site_header = "-".join(["X", "User", "Site"])
        headers[site_header] = "TTSHCardio"
    if include_actor_name:
        headers["-".join(["X", "Actor", "Name"])] = "Legacy Actor"
    return headers


def test_master_admin_can_list_secretary_events_with_counts() -> None:
    session = FakeAdminSecretaryEventsSession()
    client = _client(session)

    response = client.get("/admin/secretary-events", headers=_headers())

    assert response.status_code == 200
    payload = response.json()
    ids = {row["id"] for row in payload["items"]}
    assert session.secretary_event_id in ids
    assert session.legacy_event_id in ids
    assert session.adhoc_event_id not in ids
    assert session.admin_event_id not in ids
    first = next(row for row in payload["items"] if row["id"] == session.secretary_event_id)
    assert first["posting_display_name"] == "TTSH Cardiology"
    assert first["attendance_count"] == 2
    assert first["external_attendance_count"] == 1
    assert first["has_attendance"] is True
    assert first["session_type_name"] == "Department Teaching [1h]"
    assert payload["total"] == 2
    assert payload["summary"]["total_events"] == 2
    assert payload["summary"]["with_attendance"] == 1
    assert payload["summary"]["without_attendance"] == 1
    assert payload["summary"]["total_attendance_count"] == 2
    assert session.committed is False
    assert session.add_called is False


def test_secretary_resident_and_empty_scope_pc_cannot_access_admin_secretary_events() -> None:
    session = FakeAdminSecretaryEventsSession()
    client = _client(session)

    secretary = client.get("/admin/secretary-events", headers=_headers(role="secretary", master=False))
    resident = client.get("/admin/secretary-events", headers=_headers(role="resident", master=False))
    empty_scope_pc = client.get("/admin/secretary-events", headers=_headers(scope="", master=False))
    programme_pc = client.get("/admin/secretary-events", headers=_headers(scope="DR", master=False))

    assert secretary.status_code == 403
    assert resident.status_code == 403
    assert empty_scope_pc.status_code == 403
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


def test_admin_secretary_event_detail_is_bounded_metadata() -> None:
    session = FakeAdminSecretaryEventsSession()
    client = _client(session)

    response = client.get(
        f"/admin/secretary-events/{session.secretary_event_id}",
        headers=_headers(),
    )
    adhoc_response = client.get(
        f"/admin/secretary-events/{session.adhoc_event_id}",
        headers=_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == session.secretary_event_id
    assert payload["posting"]["code"] == "TTSHCardio"
    assert payload["recurrence"]["series_id"] == session.series_id
    assert payload["attendance_counts"]["native"] == 2
    assert payload["attendance_counts"]["external"] == 1
    assert "attendance_records" not in payload
    assert "resident_submissions" not in payload
    assert "summary" not in payload
    assert adhoc_response.status_code == 404


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
