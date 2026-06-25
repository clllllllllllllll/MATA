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


class FakeAdminResidentSubmissionSession:
    def __init__(self) -> None:
        self.reporting_period_id = str(uuid4())
        self.other_reporting_period_id = str(uuid4())
        self.dr_resident_id = str(uuid4())
        self.geri_resident_id = str(uuid4())
        self.session_type_id = str(uuid4())
        self.other_session_type_id = str(uuid4())
        self.scheduled_event_id = str(uuid4())
        self.adhoc_event_id = str(uuid4())
        self.flagged_event_id = str(uuid4())
        self.removed_event_id = str(uuid4())
        self.geri_event_id = str(uuid4())
        self.scheduled_submission_id = str(uuid4())
        self.adhoc_submission_id = str(uuid4())
        self.flagged_submission_id = str(uuid4())
        self.removed_submission_id = str(uuid4())
        self.geri_submission_id = str(uuid4())
        self.executed_sql: list[str] = []
        self.committed = False
        self.add_called = False
        self.external_attendance = [
            {
                "id": str(uuid4()),
                "external_resident_id": str(uuid4()),
                "teaching_event_id": self.scheduled_event_id,
                "status": "submitted",
            }
        ]
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
            "TTSHGerMed": {
                "code": "TTSHGerMed",
                "display_name": "TTSH Geriatric Medicine",
                "institution": "TTSH",
                "department": "Geriatric Medicine",
            },
        }
        self.session_types = {
            self.session_type_id: {
                "id": self.session_type_id,
                "name": "Department Teaching [1h]",
            },
            self.other_session_type_id: {
                "id": self.other_session_type_id,
                "name": "Case-based Teaching [2h]",
            },
        }
        self.residents = {
            self.dr_resident_id: {
                "id": self.dr_resident_id,
                "name": "DR Resident One",
                "mcr": "M12345A",
                "programme_code": "DR",
                "r_year": "R3",
                "classification": "Junior Resident",
                "status": "active",
            },
            self.geri_resident_id: {
                "id": self.geri_resident_id,
                "name": "GERI Resident One",
                "mcr": "M54321B",
                "programme_code": "GERI",
                "r_year": "ALL",
                "classification": "Senior Resident",
                "status": "active",
            },
        }
        self.events = {
            self.scheduled_event_id: self._event(
                self.scheduled_event_id,
                "TTSHCardio",
                "Journal Club",
                date(2026, 5, 6),
                time(10, 0),
                time(11, 0),
                self.session_type_id,
                False,
                "secretary",
                True,
                "SMC-CARD-1",
            ),
            self.adhoc_event_id: self._event(
                self.adhoc_event_id,
                "TTSHCardio",
                "Resident Case Review",
                date(2026, 5, 8),
                time(14, 0),
                time(15, 0),
                self.session_type_id,
                True,
                "resident",
                False,
                None,
            ),
            self.flagged_event_id: self._event(
                self.flagged_event_id,
                "TTSHCardio",
                "Flagged Teaching",
                date(2026, 5, 9),
                time(12, 0),
                time(13, 0),
                self.other_session_type_id,
                False,
                "secretary",
                False,
                None,
            ),
            self.removed_event_id: self._event(
                self.removed_event_id,
                "TTSHCardio",
                "Removed Teaching",
                date(2026, 5, 10),
                time(9, 0),
                time(10, 0),
                self.session_type_id,
                False,
                "secretary",
                False,
                None,
            ),
            self.geri_event_id: self._event(
                self.geri_event_id,
                "TTSHGerMed",
                "Geri Teaching",
                date(2026, 5, 11),
                time(8, 30),
                time(9, 30),
                self.session_type_id,
                False,
                "secretary",
                False,
                None,
            ),
        }
        self.attendance = [
            self._attendance(self.scheduled_submission_id, self.dr_resident_id, self.scheduled_event_id, "submitted"),
            self._attendance(self.adhoc_submission_id, self.dr_resident_id, self.adhoc_event_id, "submitted"),
            self._attendance(self.flagged_submission_id, self.dr_resident_id, self.flagged_event_id, "flagged"),
            self._attendance(self.removed_submission_id, self.dr_resident_id, self.removed_event_id, "removed"),
            self._attendance(self.geri_submission_id, self.geri_resident_id, self.geri_event_id, "submitted"),
        ]

    def _event(
        self,
        event_id: str,
        posting_code: str,
        teaching_name: str,
        event_date: date,
        start_time: time,
        end_time: time,
        session_type_id: str,
        is_adhoc: bool,
        created_by_role: str,
        cme_points_awarded: bool,
        smc_event_code: str | None,
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
            "is_adhoc": is_adhoc,
            "created_by_role": created_by_role,
            "cme_points_awarded": cme_points_awarded,
            "smc_event_code": smc_event_code,
            "created_at": NOW,
            "updated_at": NOW,
        }

    def _attendance(
        self,
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
            "posting_code": "AUDIT_COPY",
            "submitted_at": NOW,
            "created_at": NOW,
            "updated_at": NOW,
        }

    async def execute(self, statement, params=None):  # noqa: C901
        sql = str(statement)
        self.executed_sql.append(sql)
        payload = dict(params or {})
        self._assert_read_only_guardrails(sql)

        if "/* admin_resident_submissions:list */" in sql:
            rows = self._filtered_rows(payload)
            total = len(rows)
            offset = int(payload.get("offset") or 0)
            limit = int(payload.get("limit") or total)
            return _FakeResult(rows=[{**row, "total": total} for row in rows[offset : offset + limit]])

        if "/* admin_resident_submissions:summary */" in sql:
            rows = self._filtered_rows(payload)
            return _FakeResult(
                rows=[
                    {
                        "total_submissions": len(rows),
                        "submitted_count": sum(1 for row in rows if row["status"] == "submitted"),
                        "flagged_count": sum(1 for row in rows if row["status"] == "flagged"),
                        "removed_count": sum(1 for row in rows if row["status"] == "removed"),
                        "secretary_event_count": sum(1 for row in rows if not row["is_adhoc"]),
                        "adhoc_count": sum(1 for row in rows if row["is_adhoc"]),
                    }
                ]
            )

        if "/* admin_resident_submissions:detail */" in sql:
            row = next(
                (
                    row
                    for row in self._filtered_rows(payload, include_removed_default=True)
                    if row["id"] == str(payload["submission_id"])
                ),
                None,
            )
            return _FakeResult(rows=[row] if row else [])

        raise AssertionError(f"Unexpected SQL: {sql}\nparams={payload}")

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
        assert "external_attendance_records" not in lowered
        assert "calculate_compliance" not in lowered
        assert "period_snapshots" not in lowered
        assert "clawback" not in lowered
        assert "hibernate_stale_surplus" not in lowered
        assert "surplus_ledger" not in lowered
        assert "insert into" not in lowered
        assert "update " not in lowered
        assert "delete from" not in lowered

    def _projected_rows(self) -> list[dict]:
        rows = []
        for attendance in self.attendance:
            event = self.events[attendance["teaching_event_id"]]
            resident = self.residents[attendance["resident_id"]]
            posting = self.posting_codes[event["posting_code"]]
            session_type = self.session_types[event["session_type_id"]]
            rows.append(
                {
                    "id": attendance["id"],
                    "resident_id": resident["id"],
                    "resident_name": resident["name"],
                    "mcr": resident["mcr"],
                    "programme_code": resident["programme_code"],
                    "resident_r_year": resident["r_year"],
                    "resident_classification": resident["classification"],
                    "resident_status": resident["status"],
                    "attendance_posting_code": attendance["posting_code"],
                    "teaching_event_id": event["id"],
                    "posting_code": event["posting_code"],
                    "posting_display_name": posting["display_name"],
                    "posting_institution": posting["institution"],
                    "posting_department": posting["department"],
                    "teaching_name": event["teaching_name"],
                    "event_date": event["event_date"],
                    "start_time": event["start_time"],
                    "end_time": event["end_time"],
                    "duration_hours": event["duration_hours"],
                    "session_type_id": event["session_type_id"],
                    "session_type_name": session_type["name"],
                    "is_adhoc": event["is_adhoc"],
                    "source": "Ad-hoc" if event["is_adhoc"] else "Secretary Event",
                    "status": attendance["status"],
                    "submitted_at": attendance["submitted_at"],
                    "cme_points_awarded": event["cme_points_awarded"],
                    "smc_event_code": event["smc_event_code"],
                    "created_by_role": event["created_by_role"],
                    "attendance_created_at": attendance["created_at"],
                    "attendance_updated_at": attendance["updated_at"],
                    "event_created_at": event["created_at"],
                    "event_updated_at": event["updated_at"],
                }
            )
        return rows

    def _filtered_rows(self, payload: dict, *, include_removed_default: bool = False) -> list[dict]:
        rows = self._projected_rows()
        if payload.get("programme_code"):
            rows = [row for row in rows if row["programme_code"] == payload["programme_code"]]
        if payload.get("programme_scope"):
            rows = [row for row in rows if row["programme_code"] in set(payload["programme_scope"])]
        if payload.get("reporting_period_id"):
            period = self.periods[str(payload["reporting_period_id"])]
            rows = [
                row
                for row in rows
                if period["start_date"] <= row["event_date"] <= period["end_date"]
            ]
        if payload.get("posting_code"):
            rows = [row for row in rows if row["posting_code"] == payload["posting_code"]]
        if payload.get("resident_id"):
            rows = [row for row in rows if row["resident_id"] == str(payload["resident_id"])]
        if payload.get("mcr"):
            rows = [row for row in rows if row["mcr"].casefold() == str(payload["mcr"]).casefold()]
        if payload.get("teaching_event_id"):
            rows = [row for row in rows if row["teaching_event_id"] == str(payload["teaching_event_id"])]
        if payload.get("teaching_name_pattern"):
            needle = str(payload["teaching_name_pattern"]).replace("%", "").casefold()
            rows = [row for row in rows if needle in row["teaching_name"].casefold()]
        if payload.get("session_type_id"):
            rows = [row for row in rows if row["session_type_id"] == str(payload["session_type_id"])]
        if payload.get("date_from"):
            rows = [row for row in rows if row["event_date"] >= payload["date_from"]]
        if payload.get("date_to"):
            rows = [row for row in rows if row["event_date"] <= payload["date_to"]]
        if payload.get("submitted_from"):
            rows = [row for row in rows if row["submitted_at"] >= payload["submitted_from"]]
        if payload.get("submitted_to"):
            rows = [row for row in rows if row["submitted_at"] <= payload["submitted_to"]]
        if "is_adhoc" in payload:
            rows = [row for row in rows if row["is_adhoc"] is payload["is_adhoc"]]
        if payload.get("status"):
            rows = [row for row in rows if row["status"] == payload["status"]]
        elif not include_removed_default:
            rows = [row for row in rows if row["status"] != "removed"]
        if payload.get("search_pattern"):
            needle = str(payload["search_pattern"]).replace("%", "").casefold()
            rows = [
                row
                for row in rows
                if needle in row["resident_name"].casefold()
                or needle in row["mcr"].casefold()
                or needle in row["programme_code"].casefold()
                or needle in row["posting_code"].casefold()
                or needle in (row["posting_display_name"] or "").casefold()
                or needle in row["teaching_name"].casefold()
                or needle in (row["smc_event_code"] or "").casefold()
            ]
        rows.sort(key=lambda row: (row["event_date"], row["start_time"], row["submitted_at"]), reverse=True)
        return rows


def _client(session: FakeAdminResidentSubmissionSession) -> TestClient:
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
    scope: str | None = "DR,GERI",
    master: bool = False,
    include_site: bool = False,
    include_actor_name: bool = False,
) -> dict[str, str]:
    headers = {
        "X-User-Role": role,
        "X-User-Id": str(uuid4()),
    }
    if scope is not None:
        headers["X-User-Programme"] = scope
    if master:
        headers["X-Admin-Level"] = "master"
    if include_site:
        headers["-".join(["X", "User", "Site"])] = "TTSHCardio"
    if include_actor_name:
        headers["-".join(["X", "Actor", "Name"])] = "Legacy Actor"
    return headers


def test_master_admin_can_list_nhg_resident_submissions() -> None:
    session = FakeAdminResidentSubmissionSession()
    client = _client(session)

    response = client.get(
        "/admin/resident-submissions",
        headers=_headers(scope=None, master=True),
        params={"reporting_period_id": session.reporting_period_id},
    )

    assert response.status_code == 200
    payload = response.json()
    ids = {row["id"] for row in payload["items"]}
    assert session.scheduled_submission_id in ids
    assert session.adhoc_submission_id in ids
    assert session.flagged_submission_id in ids
    assert session.geri_submission_id in ids
    assert session.removed_submission_id not in ids
    scheduled = next(row for row in payload["items"] if row["id"] == session.scheduled_submission_id)
    assert scheduled["resident_name"] == "DR Resident One"
    assert scheduled["mcr"] == "M12345A"
    assert scheduled["programme_code"] == "DR"
    assert scheduled["posting_code"] == "TTSHCardio"
    assert scheduled["attendance_posting_code"] == "AUDIT_COPY"
    assert scheduled["source"] == "Secretary Event"
    assert scheduled["session_type_name"] == "Department Teaching [1h]"
    assert scheduled["cme_points_awarded"] is True
    assert payload["summary"]["total_submissions"] == 4
    assert payload["summary"]["submitted_count"] == 3
    assert payload["summary"]["flagged_count"] == 1
    assert payload["summary"]["removed_count"] == 0
    assert payload["summary"]["adhoc_count"] == 1
    assert session.external_attendance
    assert all("external" not in row for row in payload["items"])
    assert session.committed is False
    assert session.add_called is False


def test_programme_pc_scope_is_enforced_for_lists() -> None:
    session = FakeAdminResidentSubmissionSession()
    client = _client(session)

    scoped = client.get("/admin/resident-submissions", headers=_headers(scope="DR"))
    other_programme = client.get(
        "/admin/resident-submissions",
        headers=_headers(scope="DR"),
        params={"programme_code": "GERI"},
    )
    empty_scope = client.get("/admin/resident-submissions", headers=_headers(scope=""))

    assert scoped.status_code == 200
    assert {row["programme_code"] for row in scoped.json()["items"]} == {"DR"}
    assert session.geri_submission_id not in {row["id"] for row in scoped.json()["items"]}
    assert other_programme.status_code == 403
    assert empty_scope.status_code == 403


def test_resident_submission_filters_include_source_status_and_search() -> None:
    session = FakeAdminResidentSubmissionSession()
    client = _client(session)

    adhoc = client.get(
        "/admin/resident-submissions",
        headers=_headers(scope="DR"),
        params={"source": "adhoc", "search": "case", "limit": "10", "offset": "0"},
    )
    flagged = client.get(
        "/admin/resident-submissions",
        headers=_headers(scope="DR"),
        params={"status": "flagged", "session_type_id": session.other_session_type_id},
    )
    removed = client.get(
        "/admin/resident-submissions",
        headers=_headers(scope="DR"),
        params={"status": "removed"},
    )

    assert adhoc.status_code == 200
    assert [row["id"] for row in adhoc.json()["items"]] == [session.adhoc_submission_id]
    assert adhoc.json()["items"][0]["source"] == "Ad-hoc"
    assert flagged.status_code == 200
    assert [row["id"] for row in flagged.json()["items"]] == [session.flagged_submission_id]
    assert removed.status_code == 200
    assert [row["id"] for row in removed.json()["items"]] == [session.removed_submission_id]


def test_submission_detail_returns_bounded_metadata() -> None:
    session = FakeAdminResidentSubmissionSession()
    client = _client(session)

    response = client.get(
        f"/admin/resident-submissions/{session.scheduled_submission_id}",
        headers=_headers(scope="DR"),
    )
    out_of_scope = client.get(
        f"/admin/resident-submissions/{session.geri_submission_id}",
        headers=_headers(scope="DR"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == session.scheduled_submission_id
    assert payload["attendance_record"]["id"] == session.scheduled_submission_id
    assert payload["resident"]["id"] == session.dr_resident_id
    assert payload["resident"]["identity_label"] == "NHG Resident"
    assert payload["event"]["id"] == session.scheduled_event_id
    assert payload["posting"]["code"] == "TTSHCardio"
    assert payload["notes"]["session_type_authority"] == "display_only"
    assert payload["notes"]["compliance_included"] is None
    assert "summary" not in payload
    assert "upload_summary" not in payload
    assert "compliance" not in payload
    assert "attendance_records" not in payload
    assert out_of_scope.status_code == 404


def test_roles_are_denied_and_secretary_headers_are_not_required_or_used() -> None:
    session = FakeAdminResidentSubmissionSession()
    client = _client(session)
    site_header = "-".join(["X", "User", "Site"])
    actor_header = "-".join(["X", "Actor", "Name"])

    secretary = client.get("/admin/resident-submissions", headers=_headers(role="secretary"))
    resident = client.get("/admin/resident-submissions", headers=_headers(role="resident"))
    external = client.get("/admin/resident-submissions", headers=_headers(role="external_resident"))
    with_legacy_headers = client.get(
        "/admin/resident-submissions",
        headers=_headers(scope="DR", include_site=True, include_actor_name=True),
    )

    assert secretary.status_code == 403
    assert resident.status_code == 403
    assert external.status_code == 403
    assert with_legacy_headers.status_code == 200
    assert any("/* admin_resident_submissions:list */" in sql for sql in session.executed_sql)
    assert all(site_header.lower() not in sql.lower() for sql in session.executed_sql)
    assert all(actor_header.lower() not in sql.lower() for sql in session.executed_sql)
