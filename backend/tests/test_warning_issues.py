from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import CheckConstraint
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.reporting import UploadWarning, WarningIssue
from app.middleware.errors import install_error_handlers
from app.routers import admin
from app.services.warning_issues import (
    compute_warning_fingerprint,
    derive_upload_warnings_from_summary,
    list_warning_issues,
)


class _FakeMappingResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_FakeMappingResult":
        return self

    def all(self) -> list[dict]:
        return self._rows

    def one_or_none(self) -> dict | None:
        return self._rows[0] if self._rows else None

    def one(self) -> dict:
        return self._rows[0]


class _FakeScalarResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one(self):
        return self._value


class FakeWarningIssueSession:
    def __init__(self) -> None:
        self.now = datetime(2026, 6, 17, 9, 0, tzinfo=timezone.utc)
        self.period_id = str(uuid4())
        self.user_id = str(uuid4())
        self.upload_logs: list[dict] = []
        self.warning_issues: list[dict] = []
        self.upload_warnings: list[dict] = []
        self.audit_logs: list[dict] = []
        self.commits = 0
        self.original_upload_logs = deepcopy(self.upload_logs)

    def add_upload_log(
        self,
        *,
        summary: dict,
        upload_type: str = "rdb",
        upload_log_id: str | None = None,
        uploaded_at: datetime | None = None,
        reporting_period_id: str | None = None,
        programme_code: str | None = None,
        status: str = "success",
    ) -> dict:
        row = {
            "id": upload_log_id or str(uuid4()),
            "upload_type": upload_type,
            "uploaded_by": self.user_id,
            "uploaded_by_name": "Admin User",
            "uploaded_at": uploaded_at or self.now,
            "reporting_period_id": reporting_period_id if reporting_period_id is not None else self.period_id,
            "programme_code": programme_code,
            "status": status,
            "summary": deepcopy(summary),
            "created_at": uploaded_at or self.now,
            "updated_at": uploaded_at or self.now,
        }
        self.upload_logs.append(row)
        self.original_upload_logs = deepcopy(self.upload_logs)
        return row

    async def execute(self, statement, params=None):
        sql = str(statement)
        payload = dict(params or {})

        if "FROM upload_logs" in sql:
            rows = list(self.upload_logs)
            if "upload_log_id" in payload:
                rows = [row for row in rows if row["id"] == str(payload["upload_log_id"])]
            if "upload_type" in payload:
                rows = [row for row in rows if row["upload_type"] == payload["upload_type"]]
            if "reporting_period_id" in payload:
                rows = [row for row in rows if row["reporting_period_id"] == str(payload["reporting_period_id"])]
            return _FakeMappingResult(rows)

        if "FROM warning_issues" in sql and "COUNT(*)" in sql:
            return _FakeScalarResult(len(self.warning_issues))

        if "FROM warning_issues" in sql and "fingerprint = :fingerprint" in sql:
            rows = [row for row in self.warning_issues if row["fingerprint"] == payload["fingerprint"]]
            return _FakeMappingResult(rows)

        if "FROM warning_issues" in sql and "wi.id = :issue_id" in sql:
            issue_id = str(payload["issue_id"])
            rows = [row for row in self.warning_issues if row["id"] == issue_id]
            return _FakeMappingResult(rows)

        if "FROM warning_issues" in sql:
            rows = list(self.warning_issues)
            if "programme_scope" in payload:
                scope = set(payload["programme_scope"])
                rows = [row for row in rows if row["programme_code"] in scope]
            if "status" in payload:
                rows = [row for row in rows if row["status"] == payload["status"]]
            if "warning_type" in payload:
                rows = [row for row in rows if row["warning_type"] == payload["warning_type"]]
            if "programme_code" in payload:
                rows = [row for row in rows if row["programme_code"] == payload["programme_code"]]
            if "reporting_period_id" in payload:
                rows = [row for row in rows if row["reporting_period_id"] == str(payload["reporting_period_id"])]
            if "mcr" in payload:
                rows = [row for row in rows if row["mcr"] == payload["mcr"]]
            if "ORDER BY wi.last_seen_at DESC" in sql:
                rows.sort(key=lambda row: (row["last_seen_at"], row["id"]), reverse=True)
            if "limit" in payload:
                offset = int(payload.get("offset") or 0)
                limit = int(payload["limit"])
                rows = rows[offset : offset + limit]
            return _FakeMappingResult(rows)

        if "INSERT INTO warning_issues" in sql:
            row = {
                "id": payload["id"],
                "fingerprint": payload["fingerprint"],
                "warning_type": payload["warning_type"],
                "severity": payload["severity"],
                "status": payload["status"],
                "first_seen_upload_log_id": payload.get("first_seen_upload_log_id"),
                "last_seen_upload_log_id": payload.get("last_seen_upload_log_id"),
                "first_seen_at": payload.get("first_seen_at"),
                "last_seen_at": payload.get("last_seen_at"),
                "reporting_period_id": payload.get("reporting_period_id"),
                "programme_code": payload.get("programme_code"),
                "resident_id": payload.get("resident_id"),
                "mcr": payload.get("mcr"),
                "month_label": payload.get("month_label"),
                "resolution_note": payload.get("resolution_note"),
                "resolution_source_type": payload.get("resolution_source_type"),
                "resolution_source_id": payload.get("resolution_source_id"),
                "resolved_by": payload.get("resolved_by"),
                "resolved_at": payload.get("resolved_at"),
                "created_at": self.now,
                "updated_at": self.now,
            }
            self.warning_issues.append(row)
            return _FakeMappingResult([row])

        if "UPDATE warning_issues" in sql:
            issue_id = str(payload.get("issue_id"))
            issue = next(row for row in self.warning_issues if row["id"] == issue_id)
            for key, value in payload.items():
                if key != "issue_id" and key in issue:
                    issue[key] = value
            issue["updated_at"] = self.now
            return _FakeMappingResult([issue])

        if "FROM upload_warnings" in sql and "issue_id = :issue_id" in sql:
            rows = [row for row in self.upload_warnings if row["issue_id"] == str(payload["issue_id"])]
            rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
            return _FakeMappingResult(rows)

        if "FROM upload_warnings" in sql:
            rows = list(self.upload_warnings)
            if "upload_log_id" in payload:
                rows = [row for row in rows if row["upload_log_id"] == str(payload["upload_log_id"])]
            return _FakeMappingResult(rows)

        if "INSERT INTO upload_warnings" in sql:
            if any(
                row["upload_log_id"] == payload["upload_log_id"]
                and row["fingerprint"] == payload["fingerprint"]
                for row in self.upload_warnings
            ):
                return _FakeMappingResult([])
            row = {
                "id": payload["id"],
                "issue_id": payload["issue_id"],
                "upload_log_id": payload["upload_log_id"],
                "warning_type": payload["warning_type"],
                "severity": payload["severity"],
                "reporting_period_id": payload.get("reporting_period_id"),
                "programme_code": payload.get("programme_code"),
                "resident_id": payload.get("resident_id"),
                "mcr": payload.get("mcr"),
                "resident_name": payload.get("resident_name"),
                "month_label": payload.get("month_label"),
                "sheet_name": payload.get("sheet_name"),
                "row_number": payload.get("row_number"),
                "cell_ref": payload.get("cell_ref"),
                "source_table": payload.get("source_table"),
                "source_record_id": payload.get("source_record_id"),
                "source_payload": json.loads(payload["source_payload"]),
                "message": payload["message"],
                "suggested_action": payload.get("suggested_action"),
                "fingerprint": payload["fingerprint"],
                "created_at": self.now,
            }
            self.upload_warnings.append(row)
            return _FakeMappingResult([row])

        if "INSERT INTO audit_logs" in sql:
            self.audit_logs.append(dict(payload))
            return _FakeMappingResult([dict(payload)])

        raise AssertionError(f"Unhandled SQL: {sql}\nparams={payload}")

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        raise AssertionError("rollback should not be needed")


def _run(coro):
    return asyncio.run(coro)


def _headers(scope: str | None = "GRM", *, master: bool = False, role: str = "admin", user_id: str | None = None):
    headers = {
        "X-User-Role": role,
        "X-User-Id": user_id or str(uuid4()),
    }
    if scope is not None:
        headers["X-User-Programme"] = scope
    if master:
        headers["X-Admin-Level"] = "master"
    return headers


def _client(session: FakeWarningIssueSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def _db_override():
        yield session

    app.dependency_overrides[admin.get_db_session] = _db_override
    return TestClient(app)


def _add_warning_issue(
    session: FakeWarningIssueSession,
    *,
    programme_code: str | None,
    message: str,
    last_seen_at: datetime,
    warning_type: str = "warning",
    severity: str = "warning",
    status: str = "unresolved",
    mcr: str | None = None,
    month_label: str | None = None,
) -> dict:
    issue_id = str(uuid4())
    upload_log_id = str(uuid4())
    fingerprint = f"{warning_type}|{programme_code or '-'}|{message}"
    issue = {
        "id": issue_id,
        "fingerprint": fingerprint,
        "warning_type": warning_type,
        "severity": severity,
        "status": status,
        "first_seen_upload_log_id": upload_log_id,
        "last_seen_upload_log_id": upload_log_id,
        "first_seen_at": last_seen_at,
        "last_seen_at": last_seen_at,
        "reporting_period_id": session.period_id,
        "programme_code": programme_code,
        "resident_id": None,
        "mcr": mcr,
        "month_label": month_label,
        "resolution_note": None,
        "resolution_source_type": None,
        "resolution_source_id": None,
        "resolved_by": None,
        "resolved_at": None,
        "created_at": last_seen_at,
        "updated_at": last_seen_at,
    }
    occurrence = {
        "id": str(uuid4()),
        "issue_id": issue_id,
        "upload_log_id": upload_log_id,
        "warning_type": warning_type,
        "severity": severity,
        "reporting_period_id": session.period_id,
        "programme_code": programme_code,
        "resident_id": None,
        "mcr": mcr,
        "resident_name": None,
        "month_label": month_label,
        "sheet_name": None,
        "row_number": None,
        "cell_ref": None,
        "source_table": None,
        "source_record_id": None,
        "source_payload": {"message": message},
        "message": message,
        "suggested_action": None,
        "fingerprint": fingerprint,
        "created_at": last_seen_at,
    }
    session.warning_issues.append(issue)
    session.upload_warnings.append(occurrence)
    return issue


def _constraint_sql(model, name: str) -> str:
    constraint = next(
        item
        for item in model.__table__.constraints
        if isinstance(item, CheckConstraint) and item.name == name
    )
    return str(constraint.sqltext)


def test_fingerprint_for_unmatched_multi_posting_sorts_posting_codes() -> None:
    base = {
        "warning_type": "unmatched_multi_posting",
        "reporting_period_id": "period-1",
        "programme_code": "GRM",
        "mcr": "M00001A",
        "month_label": "May-26",
        "posting_codes": ["TTSHGerMed", "KTPHGerMed"],
        "raw_payload": {"posting_codes": ["TTSHGerMed", "KTPHGerMed"]},
    }

    first = compute_warning_fingerprint(base)
    second = compute_warning_fingerprint(
        {**base, "posting_codes": ["KTPHGerMed", "TTSHGerMed"], "raw_payload": {"posting_codes": ["KTPHGerMed", "TTSHGerMed"]}}
    )

    assert first == second
    assert first == "unmatched_multi_posting|period-1|GRM|M00001A|May-26|ktphgermed,ttshgermed"


def test_fingerprint_for_tag_order_warning_uses_tag_family_not_message() -> None:
    base = {
        "warning_type": "tag_order_warning",
        "reporting_period_id": "period-1",
        "programme_code": "GRM",
        "raw_payload": {
            "posting_code": "TTSHGerMed",
            "r_year": "R2",
            "tag_family": "A",
            "message": "Tag order A1->A2 maps 1h->2h.",
        },
    }

    first = compute_warning_fingerprint(base)
    second = compute_warning_fingerprint(
        {
            **base,
            "raw_payload": {
                "posting_code": "TTSHGerMed",
                "r_year": "R2",
                "tag_family": "A",
                "message": "Reworded warning text.",
            },
        }
    )

    assert first == second
    assert first == "tag_order_warning|period-1|GRM|TTSHGerMed|R2|a"


def test_derive_upload_warnings_is_idempotent_for_same_upload() -> None:
    session = FakeWarningIssueSession()
    upload_log = session.add_upload_log(
        summary={
            "warnings": [
                {
                    "type": "unmatched_multi_posting",
                    "mcr": "M00001A",
                    "resident_name": "Resident A",
                    "programme_code": "GRM",
                    "posting_codes": ["TTSHGerMed", "KTPHGerMed"],
                    "month_label": "May-26",
                    "sheet_name": "Phase 3",
                    "row_number": 42,
                    "cell_ref": "J42",
                    "message": "No multi-posting rule found.",
                }
            ]
        }
    )

    first = _run(derive_upload_warnings_from_summary(session, upload_log, upload_log["summary"]))
    second = _run(derive_upload_warnings_from_summary(session, upload_log, upload_log["summary"]))

    assert first.issues_created == 1
    assert first.occurrences_created == 1
    assert second.issues_created == 0
    assert second.occurrences_created == 0
    assert len(session.warning_issues) == 1
    assert len(session.upload_warnings) == 1
    assert session.upload_logs == session.original_upload_logs


def test_derive_upload_warnings_persists_overlapping_resident_posting_phase() -> None:
    session = FakeWarningIssueSession()
    upload_log = session.add_upload_log(
        summary={
            "warnings": [
                {
                    "type": "overlapping_resident_posting_phase",
                    "severity": "warning",
                    "mcr": "M00001A",
                    "resident_name": "Resident A",
                    "programme_code": "GRM",
                    "month_label": "May-26",
                    "posting_codes": ["TTSHGerMed", "KTPHGerMed"],
                    "message": "Resident posting phases overlap across distinct RDB phases.",
                }
            ]
        }
    )

    result = _run(
        derive_upload_warnings_from_summary(session, upload_log, upload_log["summary"])
    )

    assert result.issues_created == 1
    assert result.occurrences_created == 1
    assert session.warning_issues[0]["warning_type"] == "overlapping_resident_posting_phase"
    assert session.upload_warnings[0]["warning_type"] == "overlapping_resident_posting_phase"


@pytest.mark.parametrize("status", ["resolved", "dismissed", "superseded"])
def test_resolved_dismissed_or_superseded_issue_becomes_reappeared(status: str) -> None:
    session = FakeWarningIssueSession()
    summary = {"mcr_not_found_warnings": ["M99999Z not found in residents"]}
    first_upload = session.add_upload_log(summary=summary, upload_type="form_f1")
    _run(derive_upload_warnings_from_summary(session, first_upload, first_upload["summary"]))
    issue = session.warning_issues[0]
    issue["status"] = status
    issue["resolution_note"] = "Handled in MATA"
    issue["resolved_by"] = session.user_id
    issue["resolved_at"] = session.now

    second_upload = session.add_upload_log(summary=summary, upload_type="form_f1")
    result = _run(derive_upload_warnings_from_summary(session, second_upload, second_upload["summary"]))

    assert result.issues_reappeared == 1
    assert issue["status"] == "reappeared"
    assert issue["resolution_note"] == "Handled in MATA"
    assert issue["resolved_by"] == session.user_id
    assert len(session.warning_issues) == 1
    assert len(session.upload_warnings) == 2


def test_upload_warning_issue_list_and_detail_are_issue_centric() -> None:
    session = FakeWarningIssueSession()
    upload_log = session.add_upload_log(
        summary={
            "warnings": [
                {
                    "type": "empty_posting_cell",
                    "severity": "info",
                    "mcr": "M00001A",
                    "resident_name": "Resident A",
                    "programme_code": "GRM",
                    "month_label": "Aug-25",
                    "sheet_name": "Phase 1",
                    "row_number": 3,
                    "cell_ref": "I3",
                    "message": "No posting value found for this resident/month cell. No resident posting row was created.",
                    "suggested_action": "Check whether the RDB source cell is intentionally blank. If not, update the RDB source file and re-upload.",
                }
            ]
        }
    )
    _run(derive_upload_warnings_from_summary(session, upload_log, upload_log["summary"]))
    client = _client(session)

    response = client.get("/admin/upload-warnings?status=unresolved", headers=_headers("GRM"))

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["issue_id"] == session.warning_issues[0]["id"]
    assert rows[0]["warning_issue_id"] == session.warning_issues[0]["id"]
    assert rows[0]["status"] == "unresolved"
    assert rows[0]["warning_id"] == session.upload_warnings[0]["id"]
    assert rows[0]["upload_warning_id"] == session.upload_warnings[0]["id"]
    assert rows[0]["latest_upload_warning_id"] == session.upload_warnings[0]["id"]
    assert rows[0]["latest_source_trace"] == {
        "sheet_name": "Phase 1",
        "row_number": 3,
        "cell_ref": "I3",
    }

    detail = client.get(f"/admin/upload-warnings/{rows[0]['issue_id']}", headers=_headers("GRM"))

    assert detail.status_code == 200
    body = detail.json()
    assert body["issue_id"] == rows[0]["issue_id"]
    assert body["warning_issue_id"] == rows[0]["issue_id"]
    assert body["latest_upload_warning_id"] == session.upload_warnings[0]["id"]
    assert body["latest_source_trace"] == {
        "sheet_name": "Phase 1",
        "row_number": 3,
        "cell_ref": "I3",
    }
    assert body["latest_source_payload"]["type"] == "empty_posting_cell"
    assert body["message"] == rows[0]["message"]
    assert body["suggested_action"] == rows[0]["suggested_action"]
    assert body["reappeared"] is False
    assert len(body["occurrences"]) == 1
    assert body["occurrences"][0]["source_payload"]["type"] == "empty_posting_cell"
    assert body["occurrences"][0]["source_trace"] == {
        "sheet_name": "Phase 1",
        "row_number": 3,
        "cell_ref": "I3",
    }


def test_warning_issue_actions_record_note_actor_and_do_not_mutate_upload_log_summary() -> None:
    session = FakeWarningIssueSession()
    upload_log = session.add_upload_log(summary={"mcr_not_found_warnings": ["M99999Z not found"]})
    _run(derive_upload_warnings_from_summary(session, upload_log, upload_log["summary"]))
    issue_id = session.warning_issues[0]["id"]
    actor_id = str(uuid4())
    client = _client(session)

    response = client.post(
        f"/admin/upload-warnings/{issue_id}/resolve",
        headers=_headers(scope=None, master=True, user_id=actor_id),
        json={"note": "Resolved after adding resident to RDB"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["previous_status"] == "unresolved"
    assert body["new_status"] == "resolved"
    assert body["actor_user_id"] == actor_id
    assert body["note"] == "Resolved after adding resident to RDB"
    assert session.warning_issues[0]["resolution_note"] == "Resolved after adding resident to RDB"
    assert session.warning_issues[0]["resolved_by"] == actor_id
    assert session.warning_issues[0]["resolved_at"] is not None
    assert session.upload_logs == session.original_upload_logs
    assert session.audit_logs


def test_warning_issue_action_invalidates_warning_caches(monkeypatch) -> None:
    calls: list[tuple[set[str], dict]] = []

    def _spy(domains, **scope):  # noqa: ANN001
        calls.append((set(domains), scope))
        return []

    monkeypatch.setattr("app.services.cache_invalidation.invalidate_cache", _spy)
    session = FakeWarningIssueSession()
    upload_log = session.add_upload_log(summary={"mcr_not_found_warnings": ["M99999Z not found"]})
    _run(derive_upload_warnings_from_summary(session, upload_log, upload_log["summary"]))
    calls.clear()
    issue_id = session.warning_issues[0]["id"]
    client = _client(session)

    response = client.post(
        f"/admin/upload-warnings/{issue_id}/dismiss",
        headers=_headers(scope=None, master=True, user_id=str(uuid4())),
        json={"note": "Handled manually"},
    )

    assert response.status_code == 200
    assert calls
    domains, scope = calls[-1]
    assert {"upload_warnings", "admin_reports"} <= domains
    assert str(scope["warning_issue_id"]) == issue_id


def test_non_admin_cannot_mutate_warning_status() -> None:
    session = FakeWarningIssueSession()
    upload_log = session.add_upload_log(summary={"mcr_not_found_warnings": ["M99999Z not found"]})
    _run(derive_upload_warnings_from_summary(session, upload_log, upload_log["summary"]))
    client = _client(session)

    response = client.post(
        f"/admin/upload-warnings/{session.warning_issues[0]['id']}/dismiss",
        headers=_headers(role="resident"),
        json={"note": "not allowed"},
    )

    assert response.status_code == 403


def test_scoped_admin_cannot_access_out_of_scope_warning_issue() -> None:
    session = FakeWarningIssueSession()
    upload_log = session.add_upload_log(
        summary={
            "warnings": [
                {
                    "type": "unmatched_multi_posting",
                    "programme_code": "REH",
                    "mcr": "M00009Z",
                    "month_label": "May-26",
                    "posting_codes": ["A", "B"],
                    "message": "No multi-posting rule found.",
                }
            ]
        }
    )
    _run(derive_upload_warnings_from_summary(session, upload_log, upload_log["summary"]))
    client = _client(session)

    response = client.get(
        f"/admin/upload-warnings/{session.warning_issues[0]['id']}",
        headers=_headers("GRM"),
    )

    assert response.status_code == 404


def test_warning_issue_detail_serializes_uuid_occurrence_ids_for_unmatched_multi_posting() -> None:
    class UuidOccurrenceSession(FakeWarningIssueSession):
        async def execute(self, statement, params=None):
            sql = str(statement)
            payload = dict(params or {})
            if "FROM upload_warnings" in sql and "issue_id = :issue_id" in sql:
                rows = [
                    row
                    for row in self.upload_warnings
                    if str(row["issue_id"]) == str(payload["issue_id"])
                ]
                rows.sort(key=lambda row: (row["created_at"], str(row["id"])), reverse=True)
                uuid_rows = []
                for row in rows:
                    next_row = dict(row)
                    for key in ("id", "issue_id", "upload_log_id", "reporting_period_id"):
                        if next_row.get(key):
                            next_row[key] = UUID(str(next_row[key]))
                    uuid_rows.append(next_row)
                return _FakeMappingResult(uuid_rows)
            return await super().execute(statement, params)

    session = UuidOccurrenceSession()
    upload_log = session.add_upload_log(
        summary={
            "warnings": [
                {
                    "type": "unmatched_multi_posting",
                    "programme_code": "GRM",
                    "mcr": "M00009Z",
                    "month_label": "May-26",
                    "posting_codes": ["TTSHGerMed", "KTPHGerMed"],
                    "message": "No matching multi-posting rule found.",
                }
            ]
        }
    )
    _run(derive_upload_warnings_from_summary(session, upload_log, upload_log["summary"]))
    client = _client(session)
    issue_id = session.warning_issues[0]["id"]

    response = client.get(f"/admin/upload-warnings/{issue_id}", headers=_headers("GRM"))

    assert response.status_code == 200
    body = response.json()
    assert body["warning_type"] == "unmatched_multi_posting"
    assert body["occurrences"][0]["id"] == session.upload_warnings[0]["id"]
    assert body["occurrences"][0]["issue_id"] == issue_id
    assert body["occurrences"][0]["upload_log_id"] == upload_log["id"]
    assert body["latest_source_payload"]["type"] == "unmatched_multi_posting"


def test_unexpected_warning_table_probe_error_surfaces() -> None:
    class UnexpectedProbeError(Exception):
        pass

    class BrokenProbeSession(FakeWarningIssueSession):
        async def execute(self, statement, params=None):
            if "SELECT 1 FROM warning_issues" in str(statement):
                raise UnexpectedProbeError("database connection exploded")
            return await super().execute(statement, params)

    session = BrokenProbeSession()

    with pytest.raises(UnexpectedProbeError, match="database connection exploded"):
        _run(
            list_warning_issues(
                session,
                programme_scope={"GRM"},
                master_admin=False,
            )
        )


def test_programme_scoped_issue_list_applies_scope_before_limit() -> None:
    session = FakeWarningIssueSession()
    _add_warning_issue(
        session,
        programme_code="REH",
        message="out of scope newest",
        last_seen_at=datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc),
    )
    _add_warning_issue(
        session,
        programme_code="GRM",
        message="in scope first",
        last_seen_at=datetime(2026, 6, 17, 11, 0, tzinfo=timezone.utc),
    )
    _add_warning_issue(
        session,
        programme_code="GRM",
        message="in scope second",
        last_seen_at=datetime(2026, 6, 17, 10, 0, tzinfo=timezone.utc),
    )
    client = _client(session)

    response = client.get("/admin/upload-warnings?limit=2", headers=_headers("GRM"))

    assert response.status_code == 200
    rows = response.json()
    assert [row["message"] for row in rows] == ["in scope first", "in scope second"]
    assert {row["programme_code"] for row in rows} == {"GRM"}


def test_programme_scoped_issue_list_offset_uses_scoped_order() -> None:
    session = FakeWarningIssueSession()
    _add_warning_issue(
        session,
        programme_code="REH",
        message="out of scope newest",
        last_seen_at=datetime(2026, 6, 17, 14, 0, tzinfo=timezone.utc),
    )
    _add_warning_issue(
        session,
        programme_code="GRM",
        message="in scope first",
        last_seen_at=datetime(2026, 6, 17, 13, 0, tzinfo=timezone.utc),
    )
    _add_warning_issue(
        session,
        programme_code="REH",
        message="out of scope middle",
        last_seen_at=datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc),
    )
    _add_warning_issue(
        session,
        programme_code="GRM",
        message="in scope second",
        last_seen_at=datetime(2026, 6, 17, 11, 0, tzinfo=timezone.utc),
    )
    _add_warning_issue(
        session,
        programme_code="GRM",
        message="in scope third",
        last_seen_at=datetime(2026, 6, 17, 10, 0, tzinfo=timezone.utc),
    )
    client = _client(session)

    response = client.get(
        "/admin/upload-warnings?limit=2&offset=1",
        headers=_headers("GRM"),
    )

    assert response.status_code == 200
    assert [row["message"] for row in response.json()] == [
        "in scope second",
        "in scope third",
    ]


def test_non_master_with_null_programme_scope_sees_no_warning_issues() -> None:
    session = FakeWarningIssueSession()
    _add_warning_issue(
        session,
        programme_code="GRM",
        message="invisible without explicit scope",
        last_seen_at=datetime(2026, 6, 17, 9, 0, tzinfo=timezone.utc),
    )
    client = _client(session)

    response = client.get("/admin/upload-warnings", headers=_headers(scope=None))

    assert response.status_code == 200
    assert response.json() == []


def test_warning_models_define_status_and_severity_check_constraints() -> None:
    assert _constraint_sql(WarningIssue, "ck_warning_issues_status") == (
        "status IN ('unresolved', 'resolved', 'dismissed', 'superseded', 'reappeared')"
    )
    assert _constraint_sql(WarningIssue, "ck_warning_issues_severity") == (
        "severity IN ('critical', 'warning', 'info')"
    )
    assert _constraint_sql(UploadWarning, "ck_upload_warnings_severity") == (
        "severity IN ('critical', 'warning', 'info')"
    )
