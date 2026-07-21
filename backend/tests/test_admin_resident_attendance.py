from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import admin
from app.services.current_posting import NATIVE_CURRENT_POSTING_JOIN_SQL


TODAY = date.today()
NOW = datetime.combine(TODAY, time(12, 0), tzinfo=timezone.utc)


def _uuid(value: int) -> str:
    return str(UUID(int=value))


class _FakeResult:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or []

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict]:
        return list(self._rows)

    def one_or_none(self) -> dict | None:
        if len(self._rows) > 1:
            raise AssertionError(f"Expected at most one row, got {len(self._rows)}")
        return self._rows[0] if self._rows else None


class FakeAdminResidentAttendanceSession:
    def __init__(self) -> None:
        self.current_period_id = _uuid(10)
        self.historical_period_id = _uuid(11)
        self.dr_resident_id = _uuid(1)
        self.dr_no_posting_id = _uuid(2)
        self.geri_resident_id = _uuid(3)
        self.executed_sql: list[str] = []
        self.committed = False
        self.add_called = False

        self.reporting_periods = [
            {
                "id": self.historical_period_id,
                "label": "Historical",
                "start_date": TODAY - timedelta(days=270),
                "end_date": TODAY - timedelta(days=91),
                "status": "active",
                "activate_on": None,
                "deactivate_on": None,
            },
            {
                "id": self.current_period_id,
                "label": "Current",
                "start_date": TODAY - timedelta(days=90),
                "end_date": TODAY + timedelta(days=90),
                "status": "active",
                "activate_on": None,
                "deactivate_on": None,
            },
        ]
        self.posting_codes = {
            "TTSHCardio": "TTSH Cardiology",
            "TTSHNeuro": "TTSH Neurology",
            "TTSHGeneral": "TTSH General Medicine",
            "TTSHGerMed": "TTSH Geriatric Medicine",
            "TTSHDR": "TTSH Diagnostic Radiology",
        }
        self.residents = {
            self.dr_resident_id: {
                "id": self.dr_resident_id,
                "name": "Alpha Resident",
                "mcr": "M10000A",
                "programme_code": "DR",
                "r_year": "R3",
            },
            self.dr_no_posting_id: {
                "id": self.dr_no_posting_id,
                "name": "Beta Resident",
                "mcr": "M20000B",
                "programme_code": "DR",
                "r_year": "R2",
            },
            self.geri_resident_id: {
                "id": self.geri_resident_id,
                "name": "Gamma Resident",
                "mcr": "M30000C",
                "programme_code": "GERI",
                "r_year": "ALL",
            },
        }
        self.external_residents = {
            _uuid(800): {
                "id": _uuid(800),
                "name": "Non-NHG Resident",
                "mcr": "E80000Z",
            }
        }
        self.resident_postings = [
            {
                "resident_id": self.dr_resident_id,
                "reporting_period_id": self.current_period_id,
                "posting_code": "TTSHGeneral",
                "start_date": TODAY - timedelta(days=60),
                "end_date": TODAY - timedelta(days=31),
                "status": "active",
            },
            {
                "resident_id": self.dr_resident_id,
                "reporting_period_id": self.current_period_id,
                "posting_code": "TTSHCardio",
                "start_date": TODAY - timedelta(days=30),
                "end_date": TODAY + timedelta(days=30),
                "status": "loa_working",
            },
            {
                "resident_id": self.dr_resident_id,
                "reporting_period_id": self.current_period_id,
                "posting_code": "TTSHNeuro",
                "start_date": TODAY + timedelta(days=31),
                "end_date": TODAY + timedelta(days=60),
                "status": "active",
            },
            {
                "resident_id": self.geri_resident_id,
                "reporting_period_id": self.current_period_id,
                "posting_code": "TTSHGerMed",
                "start_date": TODAY - timedelta(days=30),
                "end_date": TODAY + timedelta(days=30),
                "status": "active",
            },
        ]

        self.secretary_event_id = _uuid(201)
        self.pc_event_id = _uuid(202)
        self.adhoc_event_id = _uuid(203)
        self.tie_event_a_id = _uuid(204)
        self.tie_event_b_id = _uuid(205)
        self.historical_event_id = _uuid(206)
        self.geri_event_id = _uuid(207)
        self.external_only_event_id = _uuid(208)
        self.events = {
            self.secretary_event_id: self._event(
                self.secretary_event_id,
                teaching_name="Secretary Teaching",
                event_date=TODAY - timedelta(days=1),
                start_time=time(9, 0),
                posting_code="TTSHCardio",
                is_adhoc=False,
                created_for_programme_code=None,
                created_by_role="programme_pc",
            ),
            self.pc_event_id: self._event(
                self.pc_event_id,
                teaching_name="Programme Teaching",
                event_date=TODAY - timedelta(days=2),
                start_time=time(10, 0),
                posting_code="TTSHDR",
                is_adhoc=False,
                created_for_programme_code="DR",
                created_by_role="secretary",
            ),
            self.adhoc_event_id: self._event(
                self.adhoc_event_id,
                teaching_name="Ad-hoc Case Review",
                event_date=TODAY - timedelta(days=3),
                start_time=time(11, 0),
                posting_code="TTSHCardio",
                is_adhoc=True,
                created_for_programme_code=None,
                created_by_role="resident",
                details="Resident-submitted details",
            ),
            self.tie_event_a_id: self._event(
                self.tie_event_a_id,
                teaching_name="Tie A",
                event_date=TODAY - timedelta(days=4),
                start_time=time(8, 0),
                posting_code="TTSHCardio",
                is_adhoc=False,
                created_for_programme_code=None,
                created_by_role="secretary",
            ),
            self.tie_event_b_id: self._event(
                self.tie_event_b_id,
                teaching_name="Tie B",
                event_date=TODAY - timedelta(days=4),
                start_time=time(8, 0),
                posting_code="TTSHCardio",
                is_adhoc=False,
                created_for_programme_code=None,
                created_by_role="secretary",
            ),
            self.historical_event_id: self._event(
                self.historical_event_id,
                teaching_name="Historical Teaching",
                event_date=TODAY - timedelta(days=120),
                start_time=time(8, 30),
                posting_code="TTSHCardio",
                is_adhoc=False,
                created_for_programme_code=None,
                created_by_role="secretary",
            ),
            self.geri_event_id: self._event(
                self.geri_event_id,
                teaching_name="Geri Teaching",
                event_date=TODAY - timedelta(days=1),
                start_time=time(8, 30),
                posting_code="TTSHGerMed",
                is_adhoc=False,
                created_for_programme_code="GERI",
                created_by_role="programme_pc",
            ),
            self.external_only_event_id: self._event(
                self.external_only_event_id,
                teaching_name="External Only",
                event_date=TODAY,
                start_time=time(12, 0),
                posting_code="TTSHCardio",
                is_adhoc=True,
                created_for_programme_code=None,
                created_by_role="external_resident",
            ),
        }

        self.secretary_attendance_id = _uuid(301)
        self.pc_attendance_id = _uuid(302)
        self.adhoc_attendance_id = _uuid(303)
        self.tie_attendance_a_id = _uuid(304)
        self.tie_attendance_b_id = _uuid(305)
        self.historical_attendance_id = _uuid(306)
        self.geri_attendance_id = _uuid(307)
        self.attendance = [
            self._attendance(
                self.secretary_attendance_id,
                self.dr_resident_id,
                self.secretary_event_id,
                "submitted",
            ),
            self._attendance(
                self.pc_attendance_id,
                self.dr_resident_id,
                self.pc_event_id,
                "flagged",
            ),
            self._attendance(
                self.adhoc_attendance_id,
                self.dr_resident_id,
                self.adhoc_event_id,
                "removed",
            ),
            self._attendance(
                self.tie_attendance_a_id,
                self.dr_resident_id,
                self.tie_event_a_id,
                "submitted",
            ),
            self._attendance(
                self.tie_attendance_b_id,
                self.dr_resident_id,
                self.tie_event_b_id,
                "submitted",
            ),
            self._attendance(
                self.historical_attendance_id,
                self.dr_resident_id,
                self.historical_event_id,
                "submitted",
            ),
            self._attendance(
                self.geri_attendance_id,
                self.geri_resident_id,
                self.geri_event_id,
                "submitted",
            ),
        ]
        self.external_attendance = [
            {
                "id": _uuid(900),
                "external_resident_id": _uuid(800),
                "teaching_event_id": self.external_only_event_id,
                "status": "submitted",
            },
            {
                "id": _uuid(901),
                "external_resident_id": _uuid(800),
                "teaching_event_id": self.secretary_event_id,
                "status": "submitted",
            },
        ]

    @staticmethod
    def _event(
        event_id: str,
        *,
        teaching_name: str,
        event_date: date,
        start_time: time,
        posting_code: str,
        is_adhoc: bool,
        created_for_programme_code: str | None,
        created_by_role: str,
        details: str | None = None,
    ) -> dict:
        return {
            "id": event_id,
            "teaching_name": teaching_name,
            "details_of_session": details,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": time(start_time.hour + 1, start_time.minute),
            "posting_code": posting_code,
            "is_adhoc": is_adhoc,
            "created_for_programme_code": created_for_programme_code,
            "created_by_role": created_by_role,
        }

    @staticmethod
    def _attendance(
        attendance_id: str,
        resident_id: str,
        event_id: str,
        status: str,
    ) -> dict:
        return {
            "id": attendance_id,
            "resident_id": resident_id,
            "teaching_event_id": event_id,
            "status": status,
            "submitted_at": NOW,
        }

    def _current_posting(self, resident_id: str, reporting_period_id: str | None) -> dict | None:
        eligible = [
            row
            for row in self.resident_postings
            if row["resident_id"] == resident_id
            and row["reporting_period_id"] == reporting_period_id
            and row["status"] in {"active", "loa_working"}
        ]

        def rank(row: dict) -> tuple[int, int, int, str]:
            if row["start_date"] <= TODAY <= row["end_date"]:
                bucket = 0
                distance = 0
            elif row["start_date"] > TODAY:
                bucket = 1
                distance = (row["start_date"] - TODAY).days
            else:
                bucket = 2
                distance = (TODAY - row["end_date"]).days
            return bucket, distance, -row["start_date"].toordinal(), row["posting_code"]

        return min(eligible, key=rank) if eligible else None

    def _resident_row(self, resident: dict, reporting_period_id: str | None) -> dict:
        posting = self._current_posting(resident["id"], reporting_period_id)
        posting_code = posting["posting_code"] if posting else None
        return {
            "resident_id": resident["id"],
            "name": resident["name"],
            "mcr": resident["mcr"],
            "programme_code": resident["programme_code"],
            "r_year": resident["r_year"],
            "current_posting_code": posting_code,
            "current_posting_label": self.posting_codes.get(posting_code),
            "attendance_count": sum(
                1 for row in self.attendance if row["resident_id"] == resident["id"]
            ),
        }

    def _overview_rows(self, payload: dict) -> list[dict]:
        rows = [
            self._resident_row(resident, payload.get("reporting_period_id"))
            for resident in self.residents.values()
        ]
        if payload.get("programme_scope"):
            rows = [
                row
                for row in rows
                if row["programme_code"] in set(payload["programme_scope"])
            ]
        if payload.get("programme_code"):
            rows = [
                row for row in rows if row["programme_code"] == payload["programme_code"]
            ]
        if payload.get("search_pattern"):
            needle = str(payload["search_pattern"]).replace("%", "").casefold()
            rows = [
                row
                for row in rows
                if needle in row["name"].casefold() or needle in row["mcr"].casefold()
            ]
        if payload.get("posting_code"):
            rows = [
                row
                for row in rows
                if row["current_posting_code"] == payload["posting_code"]
            ]
        return sorted(
            rows,
            key=lambda row: (row["name"].casefold(), row["mcr"], row["resident_id"]),
        )

    @staticmethod
    def _source(event: dict) -> str:
        if event["is_adhoc"]:
            return "Ad-hoc"
        if event["created_for_programme_code"] is not None:
            return "Programme PC"
        return "Department Secretary"

    def _history_rows(self, payload: dict) -> list[dict]:
        resident = self.residents.get(str(payload["resident_id"]))
        if resident is None:
            return []
        if payload.get("programme_scope") and resident["programme_code"] not in set(
            payload["programme_scope"]
        ):
            return []
        rows: list[dict] = []
        for attendance in self.attendance:
            if attendance["resident_id"] != resident["id"]:
                continue
            event = self.events[attendance["teaching_event_id"]]
            source = self._source(event)
            if payload.get("reporting_period_id"):
                period = next(
                    row
                    for row in self.reporting_periods
                    if row["id"] == str(payload["reporting_period_id"])
                )
                if not period["start_date"] <= event["event_date"] <= period["end_date"]:
                    continue
            if payload.get("posting_code") and event["posting_code"] != payload["posting_code"]:
                continue
            if payload.get("date_from") and event["event_date"] < payload["date_from"]:
                continue
            if payload.get("date_to") and event["event_date"] > payload["date_to"]:
                continue
            if payload.get("source_label") and source != payload["source_label"]:
                continue
            if payload.get("status") and attendance["status"] != payload["status"]:
                continue
            rows.append(
                {
                    "attendance_id": attendance["id"],
                    "teaching_event_id": event["id"],
                    "teaching_name": event["teaching_name"],
                    "details_of_session": event["details_of_session"],
                    "event_date": event["event_date"],
                    "start_time": event["start_time"],
                    "end_time": event["end_time"],
                    "posting_code": event["posting_code"],
                    "posting_label": self.posting_codes[event["posting_code"]],
                    "source": source,
                    "status": attendance["status"],
                    "submitted_at": attendance["submitted_at"],
                }
            )
        return sorted(
            rows,
            key=lambda row: (row["event_date"], row["start_time"], row["attendance_id"]),
            reverse=True,
        )

    def _scoped_resident(self, payload: dict) -> dict | None:
        resident = self.residents.get(str(payload["resident_id"]))
        if resident is None:
            return None
        if payload.get("programme_scope") and resident["programme_code"] not in set(
            payload["programme_scope"]
        ):
            return None
        return self._resident_row(resident, payload.get("reporting_period_id"))

    async def execute(self, statement, params=None):  # noqa: C901
        sql = str(statement)
        payload = dict(params or {})
        self.executed_sql.append(sql)
        self._assert_read_only_native_sql(sql)

        if "/* reporting_period_resolution:list */" in sql:
            return _FakeResult(self.reporting_periods)
        if "/* admin_resident_attendance:overview_count */" in sql:
            return _FakeResult([{"total": len(self._overview_rows(payload))}])
        if "/* admin_resident_attendance:overview */" in sql:
            rows = self._overview_rows(payload)
            offset = int(payload["offset"])
            limit = int(payload["limit"])
            return _FakeResult(rows[offset : offset + limit])
        if "/* admin_resident_attendance:resident */" in sql:
            row = self._scoped_resident(payload)
            return _FakeResult([row] if row else [])
        if "/* admin_resident_attendance:history_count */" in sql:
            return _FakeResult([{"total": len(self._history_rows(payload))}])
        if "/* admin_resident_attendance:history */" in sql:
            rows = self._history_rows(payload)
            offset = int(payload["offset"])
            limit = int(payload["limit"])
            return _FakeResult(rows[offset : offset + limit])
        raise AssertionError(f"Unexpected SQL: {sql}\nparams={payload}")

    @staticmethod
    def _assert_read_only_native_sql(sql: str) -> None:
        lowered = sql.lower()
        assert "external_residents" not in lowered
        assert "external_resident_postings" not in lowered
        assert "external_attendance_records" not in lowered
        assert "session_types" not in lowered
        assert "teaching_name_catalogue" not in lowered
        assert "compliance" not in lowered
        assert "surplus" not in lowered
        assert "clawback" not in lowered
        assert "insert into" not in lowered
        assert "update " not in lowered
        assert "delete from" not in lowered

    async def commit(self) -> None:
        self.committed = True

    def add(self, _value) -> None:
        self.add_called = True


def _client(session: FakeAdminResidentAttendanceSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def override_db():
        yield session

    app.dependency_overrides[admin.get_db_session] = override_db
    return TestClient(app)


def _headers(*, scope: str | None = "DR", master: bool = False) -> dict[str, str]:
    headers = {
        "X-User-Role": "admin",
        "X-User-Id": str(uuid4()),
    }
    if scope is not None:
        headers["X-User-Programme"] = scope
    if master:
        headers["X-Admin-Level"] = "master"
    return headers


def test_pc_overview_is_scoped_native_and_uses_shared_current_posting() -> None:
    session = FakeAdminResidentAttendanceSession()
    response = _client(session).get("/admin/resident-attendance", headers=_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert {row["resident_id"] for row in payload["items"]} == {
        session.dr_resident_id,
        session.dr_no_posting_id,
    }
    alpha = next(row for row in payload["items"] if row["resident_id"] == session.dr_resident_id)
    beta = next(
        row for row in payload["items"] if row["resident_id"] == session.dr_no_posting_id
    )
    assert alpha["attendance_count"] == 6
    assert alpha["current_posting_code"] == "TTSHCardio"
    assert alpha["current_posting_label"] == "TTSH Cardiology"
    assert beta["attendance_count"] == 0
    assert beta["current_posting_code"] is None
    assert beta["current_posting_label"] is None
    assert all(row["mcr"] != "E80000Z" for row in payload["items"])
    assert set(alpha) == {
        "resident_id",
        "name",
        "mcr",
        "programme_code",
        "r_year",
        "current_posting_code",
        "current_posting_label",
        "attendance_count",
    }
    assert session.external_attendance
    assert session.committed is False
    assert session.add_called is False


def test_overview_multi_programme_filters_and_stable_pagination() -> None:
    session = FakeAdminResidentAttendanceSession()
    client = _client(session)
    headers = _headers(scope="DR,GERI")

    all_rows = client.get("/admin/resident-attendance", headers=headers)
    searched = client.get(
        "/admin/resident-attendance",
        headers=headers,
        params={"search": "m20000"},
    )
    programme = client.get(
        "/admin/resident-attendance",
        headers=headers,
        params={"programme_code": "GERI"},
    )
    posting = client.get(
        "/admin/resident-attendance",
        headers=headers,
        params={"posting_code": "TTSHGerMed"},
    )
    page = client.get(
        "/admin/resident-attendance",
        headers=headers,
        params={"limit": 1, "offset": 1},
    )

    assert all_rows.status_code == 200
    assert all_rows.json()["total"] == 3
    assert {row["programme_code"] for row in all_rows.json()["items"]} == {"DR", "GERI"}
    assert [row["resident_id"] for row in searched.json()["items"]] == [
        session.dr_no_posting_id
    ]
    assert [row["resident_id"] for row in programme.json()["items"]] == [
        session.geri_resident_id
    ]
    assert [row["resident_id"] for row in posting.json()["items"]] == [
        session.geri_resident_id
    ]
    assert page.json()["total"] == 3
    assert page.json()["limit"] == 1
    assert page.json()["offset"] == 1
    assert [row["resident_id"] for row in page.json()["items"]] == [
        session.dr_no_posting_id
    ]


def test_overview_scope_fails_closed_and_explicit_master_retains_read_access() -> None:
    session = FakeAdminResidentAttendanceSession()
    client = _client(session)

    empty = client.get("/admin/resident-attendance", headers=_headers(scope=""))
    null = client.get("/admin/resident-attendance", headers=_headers(scope=None))
    out_of_scope_filter = client.get(
        "/admin/resident-attendance",
        headers=_headers(scope="DR"),
        params={"programme_code": "GERI"},
    )
    hidden_search = client.get(
        "/admin/resident-attendance",
        headers=_headers(scope="DR"),
        params={"search": "Gamma"},
    )
    master = client.get(
        "/admin/resident-attendance",
        headers=_headers(scope=None, master=True),
    )
    master_detail = client.get(
        f"/admin/resident-attendance/{session.geri_resident_id}",
        headers=_headers(scope=None, master=True),
    )

    assert empty.status_code == 403
    assert null.status_code == 403
    assert out_of_scope_filter.status_code == 403
    assert hidden_search.status_code == 200
    assert hidden_search.json()["total"] == 0
    assert master.status_code == 200
    assert master.json()["total"] == 3
    assert master_detail.status_code == 200
    assert master_detail.json()["resident"]["resident_id"] == session.geri_resident_id


def test_detail_returns_only_native_history_with_three_authoritative_sources() -> None:
    session = FakeAdminResidentAttendanceSession()
    response = _client(session).get(
        f"/admin/resident-attendance/{session.dr_resident_id}",
        headers=_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["resident"] == {
        "resident_id": session.dr_resident_id,
        "name": "Alpha Resident",
        "mcr": "M10000A",
        "programme_code": "DR",
        "r_year": "R3",
        "current_posting_code": "TTSHCardio",
        "current_posting_label": "TTSH Cardiology",
    }
    assert payload["total"] == 6
    by_id = {row["attendance_id"]: row for row in payload["items"]}
    assert by_id[session.secretary_attendance_id]["source"] == "Department Secretary"
    assert by_id[session.pc_attendance_id]["source"] == "Programme PC"
    assert by_id[session.adhoc_attendance_id]["source"] == "Ad-hoc"
    assert by_id[session.adhoc_attendance_id]["status"] == "removed"
    assert by_id[session.adhoc_attendance_id]["details_of_session"] == (
        "Resident-submitted details"
    )
    assert by_id[session.pc_attendance_id]["teaching_name"] == "Programme Teaching"
    assert by_id[session.pc_attendance_id]["posting_code"] == "TTSHDR"
    assert by_id[session.pc_attendance_id]["posting_label"] == (
        "TTSH Diagnostic Radiology"
    )
    assert _uuid(900) not in by_id
    assert all(
        "edit" not in row and "delete" not in row and "remove" not in row
        for row in payload["items"]
    )
    tie_ids = [
        row["attendance_id"]
        for row in payload["items"]
        if row["teaching_name"] in {"Tie A", "Tie B"}
    ]
    assert tie_ids == sorted(tie_ids, reverse=True)
    history_sql = next(
        sql
        for sql in session.executed_sql
        if "/* admin_resident_attendance:history */" in sql
    )
    assert "ORDER BY te.event_date DESC, te.start_time DESC, ar.id DESC" in history_sql


def test_detail_empty_history_and_out_of_scope_uuid_are_safe() -> None:
    session = FakeAdminResidentAttendanceSession()
    client = _client(session)

    empty = client.get(
        f"/admin/resident-attendance/{session.dr_no_posting_id}",
        headers=_headers(),
    )
    out_of_scope = client.get(
        f"/admin/resident-attendance/{session.geri_resident_id}",
        headers=_headers(),
    )
    missing = client.get(
        f"/admin/resident-attendance/{uuid4()}",
        headers=_headers(),
    )
    empty_scope = client.get(
        f"/admin/resident-attendance/{session.dr_resident_id}",
        headers=_headers(scope=""),
    )

    assert empty.status_code == 200
    assert empty.json()["resident"]["current_posting_code"] is None
    assert empty.json()["items"] == []
    assert empty.json()["total"] == 0
    assert out_of_scope.status_code == 404
    assert missing.status_code == 404
    assert out_of_scope.json() == missing.json()
    assert "Gamma" not in str(out_of_scope.json())
    assert "M30000C" not in str(out_of_scope.json())
    assert empty_scope.status_code == 403


def test_detail_filters_reporting_period_posting_dates_source_and_status() -> None:
    session = FakeAdminResidentAttendanceSession()
    client = _client(session)
    path = f"/admin/resident-attendance/{session.dr_resident_id}"
    headers = _headers()

    historical = client.get(
        path,
        headers=headers,
        params={"reporting_period_id": session.historical_period_id},
    )
    current = client.get(
        path,
        headers=headers,
        params={"reporting_period_id": session.current_period_id},
    )
    posting = client.get(path, headers=headers, params={"posting_code": "TTSHDR"})
    date_filtered = client.get(
        path,
        headers=headers,
        params={
            "date_from": (TODAY - timedelta(days=2)).isoformat(),
            "date_to": (TODAY - timedelta(days=2)).isoformat(),
        },
    )
    secretary = client.get(
        path,
        headers=headers,
        params={"source": "department_secretary"},
    )
    programme_pc = client.get(
        path,
        headers=headers,
        params={"source": "programme_pc"},
    )
    adhoc = client.get(path, headers=headers, params={"source": "adhoc"})
    removed = client.get(path, headers=headers, params={"status": "removed"})

    assert [row["attendance_id"] for row in historical.json()["items"]] == [
        session.historical_attendance_id
    ]
    assert current.json()["total"] == 5
    assert [row["attendance_id"] for row in posting.json()["items"]] == [
        session.pc_attendance_id
    ]
    assert [row["attendance_id"] for row in date_filtered.json()["items"]] == [
        session.pc_attendance_id
    ]
    assert {row["source"] for row in secretary.json()["items"]} == {
        "Department Secretary"
    }
    assert [row["attendance_id"] for row in programme_pc.json()["items"]] == [
        session.pc_attendance_id
    ]
    assert [row["attendance_id"] for row in adhoc.json()["items"]] == [
        session.adhoc_attendance_id
    ]
    assert [row["attendance_id"] for row in removed.json()["items"]] == [
        session.adhoc_attendance_id
    ]


def test_detail_pagination_is_bounded_and_validation_is_controlled() -> None:
    session = FakeAdminResidentAttendanceSession()
    client = _client(session)
    path = f"/admin/resident-attendance/{session.dr_resident_id}"
    headers = _headers()

    full = client.get(path, headers=headers)
    page = client.get(path, headers=headers, params={"limit": 2, "offset": 1})
    too_large = client.get(path, headers=headers, params={"limit": 201})
    zero = client.get(path, headers=headers, params={"limit": 0})
    negative_offset = client.get(path, headers=headers, params={"offset": -1})
    reversed_dates = client.get(
        path,
        headers=headers,
        params={"date_from": TODAY.isoformat(), "date_to": (TODAY - timedelta(days=1)).isoformat()},
    )
    invalid_source = client.get(path, headers=headers, params={"source": "scheduled"})
    invalid_status = client.get(path, headers=headers, params={"status": "deleted"})

    assert page.status_code == 200
    assert page.json()["total"] == 6
    assert page.json()["limit"] == 2
    assert page.json()["offset"] == 1
    assert [row["attendance_id"] for row in page.json()["items"]] == [
        row["attendance_id"] for row in full.json()["items"][1:3]
    ]
    assert too_large.status_code == 422
    assert zero.status_code == 422
    assert negative_offset.status_code == 422
    assert reversed_dates.status_code == 422
    assert invalid_source.status_code == 422
    assert invalid_status.status_code == 422


def test_feature_introduces_get_routes_only_and_reuses_auth_posting_contract() -> None:
    session = FakeAdminResidentAttendanceSession()
    client = _client(session)
    relevant_routes = [
        route
        for route in client.app.routes
        if getattr(route, "path", "") in {
            "/admin/resident-attendance",
            "/admin/resident-attendance/{resident_id}",
        }
    ]
    assert len(relevant_routes) == 2
    assert all(route.methods == {"GET"} for route in relevant_routes)

    auth_source = (
        Path(__file__).resolve().parents[1] / "app" / "services" / "auth.py"
    ).read_text()
    feature_source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "admin_resident_attendance.py"
    ).read_text()
    assert "NATIVE_CURRENT_POSTING_JOIN_SQL" in auth_source
    assert "NATIVE_CURRENT_POSTING_JOIN_SQL" in feature_source
    assert "rp.status IN ('active', 'loa_working')" in NATIVE_CURRENT_POSTING_JOIN_SQL
    assert "WHEN rp.start_date <= CURRENT_DATE" in NATIVE_CURRENT_POSTING_JOIN_SQL
    assert "WHEN rp.start_date > CURRENT_DATE" in NATIVE_CURRENT_POSTING_JOIN_SQL
    assert "rp.start_date DESC" in NATIVE_CURRENT_POSTING_JOIN_SQL
    assert "rp.posting_code" in NATIVE_CURRENT_POSTING_JOIN_SQL
