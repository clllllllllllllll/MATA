from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import admin


class _FakeResult:
    def __init__(self, rows: list[dict] | None = None, scalar: object | None = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict]:
        return list(self._rows)

    def one_or_none(self) -> dict | None:
        if len(self._rows) > 1:
            raise AssertionError("Expected at most one row")
        return self._rows[0] if self._rows else None

    def one(self) -> dict:
        if len(self._rows) != 1:
            raise AssertionError(f"Expected exactly one row, got {len(self._rows)}")
        return self._rows[0]

    def scalar_one_or_none(self) -> object | None:
        return self._scalar

    def scalar_one(self) -> object:
        return self._scalar


class FakeRdbSourceCellWarningSession:
    def __init__(self) -> None:
        self.now = datetime(2026, 6, 18, 9, 0, tzinfo=timezone.utc)
        self.after_now = datetime(2026, 6, 18, 9, 5, tzinfo=timezone.utc)
        self.period_id = str(uuid4())
        self.upload_log_id = str(uuid4())
        self.warning_issue_id = str(uuid4())
        self.upload_warning_id = str(uuid4())
        self.resident_id = str(uuid4())
        self.other_resident_id = str(uuid4())
        self.posting_id = str(uuid4())
        self.other_posting_id = str(uuid4())
        self.posting_codes = {"OldPosting", "TTSHGerMed", "TTSHCardio", "TTSHAnaes"}
        self.programmes = {
            "GERI": {
                "code": "GERI",
                "name": "Geriatric Medicine",
                "r_year_required": False,
                "is_subspecialty": False,
                "rdb_alias": None,
                "ay_date_category": "im_subspec",
            },
            "DR": {
                "code": "DR",
                "name": "Diagnostic Radiology",
                "r_year_required": True,
                "is_subspecialty": False,
                "rdb_alias": None,
                "ay_date_category": "non_im_subspec",
            },
        }
        self.loa_types = [
            {"code": "Maternity Leave"},
            {"code": "Annual Leaves"},
            {"code": "Medical Leave"},
        ]
        self.multi_posting_rules: list[dict] = []
        self.reporting_periods = [
            {
                "id": self.period_id,
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 6, 30),
            }
        ]
        self.academic_month_boundaries = [
            {
                "ay_date_category": "im_subspec",
                "month_label": "Jan-26",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 1, 31),
            },
            {
                "ay_date_category": "non_im_subspec",
                "month_label": "Jan-26",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 1, 31),
            },
        ]
        self.residents = [
            {
                "id": self.resident_id,
                "name": "Geri Resident",
                "mcr": "M11111A",
                "programme_code": "GERI",
                "r_year": "R3",
                "employer_tag": None,
            },
            {
                "id": self.other_resident_id,
                "name": "DR Resident",
                "mcr": "M22222B",
                "programme_code": "DR",
                "r_year": "R2",
                "employer_tag": None,
            },
        ]
        self.resident_postings = [
            self._posting(self.posting_id, self.resident_id, "OldPosting", date(2026, 1, 1), date(2026, 1, 31), None),
            self._posting(self.other_posting_id, self.other_resident_id, "OldPosting", date(2026, 1, 1), date(2026, 1, 31), None),
        ]
        self.warning_issues = [
            {
                "id": self.warning_issue_id,
                "fingerprint": f"empty_posting_cell|{self.period_id}|GERI|M11111A|Jan-26",
                "warning_type": "empty_posting_cell",
                "severity": "info",
                "status": "unresolved",
                "first_seen_upload_log_id": self.upload_log_id,
                "last_seen_upload_log_id": self.upload_log_id,
                "first_seen_at": self.now,
                "last_seen_at": self.now,
                "reporting_period_id": self.period_id,
                "programme_code": "GERI",
                "resident_id": self.resident_id,
                "mcr": "M11111A",
                "month_label": "Jan-26",
                "resolution_note": None,
                "resolution_source_type": None,
                "resolution_source_id": None,
                "resolved_by": None,
                "resolved_at": None,
                "created_at": self.now,
                "updated_at": self.now,
            }
        ]
        self.upload_logs = [
            {
                "id": self.upload_log_id,
                "upload_type": "rdb",
                "uploaded_at": self.now,
                "reporting_period_id": self.period_id,
                "programme_code": None,
                "summary": {"warnings": ["immutable"]},
            }
        ]
        self.upload_warnings = [
            {
                "id": self.upload_warning_id,
                "issue_id": self.warning_issue_id,
                "upload_log_id": self.upload_log_id,
                "warning_type": "empty_posting_cell",
                "severity": "info",
                "reporting_period_id": self.period_id,
                "programme_code": "GERI",
                "resident_id": self.resident_id,
                "mcr": "M11111A",
                "resident_name": "Geri Resident",
                "month_label": "Jan-26",
                "sheet_name": "Phase 1",
                "row_number": 3,
                "cell_ref": "I3",
                "source_table": None,
                "source_record_id": None,
                "source_payload": {"type": "empty_posting_cell", "raw_value": None},
                "message": "No posting value found.",
                "suggested_action": "Review the RDB source cell.",
                "fingerprint": f"empty_posting_cell|{self.period_id}|GERI|M11111A|Jan-26",
                "created_at": self.now,
            }
        ]
        self.original_upload_logs = deepcopy(self.upload_logs)
        self.audit_logs: list[dict] = []
        self.teaching_name_reconciliations: list[dict[str, str]] = []
        self.new_posting_ids: list[str] = []
        self.executed_sql: list[str] = []
        self.commits = 0

    def _posting(
        self,
        row_id: str,
        resident_id: str,
        posting_code: str | None,
        start: date,
        end: date,
        day_part: str | None,
        *,
        month_label: str = "Jan-26",
        weight: Decimal = Decimal("1.0"),
    ) -> dict:
        return {
            "id": row_id,
            "resident_id": resident_id,
            "posting_code": posting_code,
            "reporting_period_id": self.period_id,
            "start_date": start,
            "end_date": end,
            "day_part": day_part,
            "month_label": month_label,
            "r_year": "ALL",
            "status": "active",
            "loa_type": None,
            "loa_start_date": None,
            "loa_end_date": None,
            "refresher_training_type": None,
            "refresher_training_start": None,
            "refresher_training_end": None,
            "active_months_weight": weight,
            "working_days_in_month": 31,
            "created_at": self.now,
            "updated_at": self.now,
        }

    def set_unmatched_warning(self) -> None:
        self.warning_issues[0].update(
            {
                "fingerprint": f"unmatched_multi_posting|{self.period_id}|GERI|M11111A|Jan-26|ttshanaes,ttshcardio",
                "warning_type": "unmatched_multi_posting",
            }
        )
        self.upload_warnings[0].update(
            {
                "warning_type": "unmatched_multi_posting",
                "severity": "critical",
                "source_payload": {
                    "type": "unmatched_multi_posting",
                    "posting_codes": ["TTSHCardio", "TTSHAnaes"],
                },
                "fingerprint": self.warning_issues[0]["fingerprint"],
            }
        )
        self.resident_postings = [
            self._posting(str(uuid4()), self.resident_id, "TTSHCardio", date(2026, 1, 1), date(2026, 1, 15), None),
            self._posting(str(uuid4()), self.resident_id, "TTSHAnaes", date(2026, 1, 16), date(2026, 1, 31), None),
            self._posting(self.other_posting_id, self.other_resident_id, "OldPosting", date(2026, 1, 1), date(2026, 1, 31), None),
        ]

    def add_combine_rule(self) -> None:
        self.posting_codes.add("TTSHCardio & TTSHAnaes")
        self.multi_posting_rules.append(
            {
                "id": str(uuid4()),
                "programme_code": "GERI",
                "posting_code_1": "TTSHCardio",
                "posting_code_2": "TTSHAnaes",
                "rule_type": "combine",
                "combined_label": "TTSHCardio & TTSHAnaes",
                "main_posting_code": None,
                "exclusion_code": None,
            }
        )

    def _resident(self, resident_id: str) -> dict:
        return next(row for row in self.residents if row["id"] == resident_id)

    def _with_resident_context(self, posting: dict) -> dict:
        resident = self._resident(posting["resident_id"])
        return {
            **posting,
            "resident_name": resident["name"],
            "mcr": resident["mcr"],
            "programme_code": resident["programme_code"],
        }

    def _scope_allows(self, programme_code: str | None, payload: dict) -> bool:
        scope = {
            value
            for key, value in payload.items()
            if key.startswith("scope_programme_code_")
        }
        return not scope or programme_code in scope

    async def execute(self, statement, params=None):  # noqa: C901, PLR0912, PLR0915
        sql = str(statement)
        payload = dict(params or {})
        self.executed_sql.append(sql)

        if "mata_rls.reclassify_native_attendance_loa" in sql:
            return _FakeResult(
                rows=[
                    {
                        "affected_count": 0,
                        "during_loa_count": 0,
                        "non_loa_count": 0,
                    }
                ]
            )

        if "/* rdb_source_cell_warning:context */" in sql:
            if "1 = 0" in sql:
                return _FakeResult(rows=[])
            issue_id = str(payload["warning_issue_id"])
            issue = next((row for row in self.warning_issues if row["id"] == issue_id), None)
            if issue is None or not self._scope_allows(issue["programme_code"], payload):
                return _FakeResult(rows=[])
            occurrences = [row for row in self.upload_warnings if row["issue_id"] == issue_id]
            occurrences.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
            latest = occurrences[0]
            upload_log = next(row for row in self.upload_logs if row["id"] == latest["upload_log_id"])
            row = {
                **{f"issue_{key}": value for key, value in issue.items()},
                **{f"warning_{key}": value for key, value in latest.items()},
                "upload_type": upload_log["upload_type"],
                "uploaded_at": upload_log["uploaded_at"],
                "upload_summary": upload_log["summary"],
            }
            return _FakeResult(rows=[deepcopy(row)])

        if "/* rdb_source_cell_warning:resident_by_mcr */" in sql:
            if "1 = 0" in sql:
                return _FakeResult(rows=[])
            rows = [
                row
                for row in self.residents
                if row["mcr"].upper() == str(payload["mcr"]).upper()
                and row["programme_code"] == payload["programme_code"]
                and self._scope_allows(row["programme_code"], payload)
            ]
            return _FakeResult(rows=deepcopy(rows))

        if "/* rdb_source_cell_warning:phase_from_rows */" in sql:
            rows = [
                row
                for row in self.resident_postings
                if row["resident_id"] == payload["resident_id"]
                and row["reporting_period_id"] == payload["reporting_period_id"]
                and row["month_label"] == payload["month_label"]
            ]
            if not rows:
                return _FakeResult(rows=[])
            return _FakeResult(
                rows=[
                    {
                        "start_date": min(row["start_date"] for row in rows),
                        "end_date": max(row["end_date"] for row in rows),
                        "r_year": rows[0]["r_year"],
                    }
                ]
            )

        if "/* rdb_source_cell_warning:phase_from_academic_boundary */" in sql:
            programme = self.programmes[payload["programme_code"]]
            rows = [
                row
                for row in self.academic_month_boundaries
                if row["ay_date_category"] == programme["ay_date_category"]
                and row["month_label"] == payload["month_label"]
            ]
            if not rows:
                return _FakeResult(rows=[])
            return _FakeResult(rows=[deepcopy(rows[0])])

        if "FROM programmes" in sql:
            if "WHERE code = :programme_code" in sql:
                row = self.programmes.get(payload["programme_code"])
                return _FakeResult(rows=[deepcopy(row)] if row else [])
            return _FakeResult(rows=[deepcopy(row) for row in self.programmes.values()])

        if "SELECT code FROM loa_types" in sql:
            return _FakeResult(rows=deepcopy(self.loa_types))

        if "FROM multi_posting_rules" in sql:
            return _FakeResult(
                rows=[
                    deepcopy(row)
                    for row in self.multi_posting_rules
                    if row["programme_code"] == payload["programme_code"]
                ]
            )

        if "SELECT code" in sql and "FROM posting_codes" in sql:
            if "codes" in payload:
                codes = set(payload["codes"])
                return _FakeResult(rows=[{"code": code} for code in sorted(self.posting_codes & codes)])
            return _FakeResult(rows=[{"code": payload["code"]}] if payload["code"] in self.posting_codes else [])

        if "INSERT INTO posting_codes" in sql:
            self.posting_codes.add(payload["code"])
            return _FakeResult(rowcount=1)

        if "/* rdb_source_cell_warning:affected_rows */" in sql:
            posting_codes = set(payload.get("posting_codes") or [])
            rows = []
            for row in self.resident_postings:
                if row["resident_id"] != payload["resident_id"]:
                    continue
                if row["reporting_period_id"] != payload["reporting_period_id"]:
                    continue
                if row["month_label"] != payload["month_label"]:
                    continue
                if payload.get("phase_start") is not None and row["start_date"] != payload["phase_start"]:
                    continue
                if payload.get("phase_end") is not None and row["end_date"] != payload["phase_end"]:
                    continue
                if posting_codes and row.get("posting_code") not in posting_codes:
                    continue
                rows.append(self._with_resident_context(row))
            return _FakeResult(rows=deepcopy(rows))

        if "/* rdb_source_cell_warning:lock_resident_month */" in sql:
            return _FakeResult(rows=[])

        if "/* parsed_data_validation:posting_code_exists */" in sql:
            return _FakeResult(scalar=1 if payload["code"] in self.posting_codes else None)

        if "/* parsed_data_validation:reporting_period_exists */" in sql:
            return _FakeResult(scalar=1)

        if "/* parsed_data_validation:resident_exists */" in sql:
            rows = [
                row
                for row in self.residents
                if row["id"] == payload["resident_id"]
                and self._scope_allows(row["programme_code"], payload)
            ]
            return _FakeResult(rows=deepcopy(rows))

        if "/* parsed_data_validation:resident_posting_replacement_unique */" in sql:
            affected_ids = {str(value) for value in payload["affected_ids"]}
            duplicate = any(
                row["id"] not in affected_ids
                and row["resident_id"] == payload["resident_id"]
                and row["reporting_period_id"] == payload["reporting_period_id"]
                and row["start_date"] == payload["start_date"]
                and row["day_part"] == payload.get("day_part")
                for row in self.resident_postings
            )
            return _FakeResult(scalar=1 if duplicate else None)

        if "/* parsed_data_reconciliation:resident_programme_periods */" in sql:
            rows = []
            seen: set[tuple[str, str]] = set()
            for posting in self.resident_postings:
                if str(posting["resident_id"]) != str(payload["resident_id"]):
                    continue
                if (
                    payload.get("reporting_period_id") is not None
                    and str(posting["reporting_period_id"])
                    != str(payload["reporting_period_id"])
                ):
                    continue
                resident = next(
                    item
                    for item in self.residents
                    if str(item["id"]) == str(posting["resident_id"])
                )
                key = (str(posting["reporting_period_id"]), resident["programme_code"])
                if key not in seen:
                    seen.add(key)
                    rows.append(
                        {
                            "reporting_period_id": key[0],
                            "programme_code": key[1],
                        }
                    )
            return _FakeResult(rows=rows)

        if "/* teaching_name_scopes:admit_owner */" in sql:
            self.teaching_name_reconciliations.append(
                {
                    "reporting_period_id": str(payload["reporting_period_id"]),
                    "programme_code": payload["programme_code"],
                }
            )
            return _FakeResult(rowcount=0)

        if "/* teaching_name_scopes:admit_resident_host */" in sql:
            return _FakeResult(rowcount=0)

        if "/* teaching_name_scopes:provision_mappings */" in sql:
            return _FakeResult(rowcount=0)

        if "DELETE FROM resident_postings" in sql:
            ids = {str(value) for value in payload["ids"]}
            self.resident_postings = [row for row in self.resident_postings if row["id"] not in ids]
            return _FakeResult(rowcount=len(ids))

        if "INSERT INTO resident_postings" in sql:
            row = {
                "id": payload["id"],
                "resident_id": payload["resident_id"],
                "posting_code": payload["posting_code"],
                "reporting_period_id": payload["reporting_period_id"],
                "start_date": payload["start_date"],
                "end_date": payload["end_date"],
                "day_part": payload["day_part"],
                "month_label": payload["month_label"],
                "r_year": payload["r_year"],
                "status": payload["status"],
                "loa_type": payload.get("loa_type"),
                "loa_start_date": payload.get("loa_start_date"),
                "loa_end_date": payload.get("loa_end_date"),
                "refresher_training_type": payload.get("refresher_training_type"),
                "refresher_training_start": payload.get("refresher_training_start"),
                "refresher_training_end": payload.get("refresher_training_end"),
                "active_months_weight": payload["active_months_weight"],
                "working_days_in_month": payload.get("working_days_in_month"),
                "created_at": self.after_now,
                "updated_at": self.after_now,
            }
            self.new_posting_ids.append(row["id"])
            self.resident_postings.append(row)
            return _FakeResult(rowcount=1)

        if "/* parsed_data_correction:resident_posting_rows_by_ids */" in sql:
            ids = {str(value) for value in payload["ids"]}
            rows = [
                self._with_resident_context(row)
                for row in self.resident_postings
                if row["id"] in ids
            ]
            return _FakeResult(rows=deepcopy(rows))

        if "INSERT INTO audit_logs" in sql:
            row = {"id": payload["id"], "created_at": self.after_now, **payload}
            self.audit_logs.append(row)
            return _FakeResult(rows=[row])

        raise AssertionError(f"Unhandled SQL in source-cell warning fake: {sql}\nparams={payload}")

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


def _client(session: FakeRdbSourceCellWarningSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def _db_override():
        yield session

    app.dependency_overrides[admin.get_db_session] = _db_override
    return TestClient(app)


def _headers(scope: str | None = "GERI", *, master: bool = False) -> dict[str, str]:
    headers = {
        "X-User-Role": "admin",
        "X-User-Id": str(uuid4()),
    }
    if scope is not None:
        headers["X-User-Programme"] = scope
    if master:
        headers["X-Admin-Level"] = "master"
    return headers


def _preview(session: FakeRdbSourceCellWarningSession, raw_value, *, headers: dict[str, str] | None = None):
    return _client(session).post(
        f"/admin/upload-warnings/{session.warning_issue_id}/source-cell-replace/preview",
        headers=headers or _headers(),
        json={"replacement_raw_cell_value": raw_value},
    )


def _apply(
    session: FakeRdbSourceCellWarningSession,
    raw_value,
    *,
    expected_latest_upload_warning_id: str | None = None,
    headers: dict[str, str] | None = None,
):
    body = {
        "replacement_raw_cell_value": raw_value,
        "correction_reason": "Correct source RDB cell from durable warning",
    }
    if expected_latest_upload_warning_id is not None:
        body["expected_latest_upload_warning_id"] = expected_latest_upload_warning_id
    return _client(session).post(
        f"/admin/upload-warnings/{session.warning_issue_id}/source-cell-replace/apply",
        headers=headers or _headers(),
        json=body,
    )


def _audit_json(row: dict, key: str):
    value = row[key]
    if value is None or isinstance(value, dict):
        return value
    return json.loads(value)


def test_preview_simple_posting_replacement_from_warning_does_not_write() -> None:
    session = FakeRdbSourceCellWarningSession()

    response = _preview(session, "TTSHGerMed")

    assert response.status_code == 200
    body = response.json()
    assert body["warning_issue_id"] == session.warning_issue_id
    assert body["upload_warning_id"] == session.upload_warning_id
    assert body["latest_upload_warning_id"] == session.upload_warning_id
    assert body["fingerprint"] == session.warning_issues[0]["fingerprint"]
    assert body["source_trace"]["cell_ref"] == "I3"
    assert body["source_payload"]["type"] == "empty_posting_cell"
    assert body["replacement_raw_cell_value"] == "TTSHGerMed"
    assert body["normalized_cell_value"] == "TTSHGerMed"
    assert body["apply_allowed"] is True
    assert body["parsed_candidate_rows"][0]["posting_code"] == "TTSHGerMed"
    assert body["parsed_candidate_rows"][0]["status"] == "active"
    assert body["parser_warnings"] == []
    assert body["parser_errors"] == []
    assert body["data_revalidation"]["outcome"] == "warning_only"
    assert body["next_actions"] == [body["suggested_next_action"]]
    assert session.audit_logs == []
    assert session.new_posting_ids == []
    assert session.upload_logs == session.original_upload_logs


def test_preview_source_cell_replacement_does_not_invalidate_caches(monkeypatch) -> None:
    calls: list[tuple[set[str], dict]] = []

    def _spy(domains, **scope):  # noqa: ANN001
        calls.append((set(domains), scope))
        return []

    monkeypatch.setattr("app.services.cache_invalidation.invalidate_cache", _spy)
    session = FakeRdbSourceCellWarningSession()

    response = _preview(session, "TTSHGerMed")

    assert response.status_code == 200
    assert calls == []


def test_preview_empty_cell_replacement_returns_no_candidate_rows() -> None:
    session = FakeRdbSourceCellWarningSession()

    response = _preview(session, "  \r\n ")

    assert response.status_code == 200
    body = response.json()
    assert body["normalized_cell_value"] == ""
    assert body["parsed_candidate_rows"] == []
    assert body["apply_allowed"] is True
    assert "manual" in body["suggested_next_action"].lower()


def test_preview_pure_loa_replacement() -> None:
    session = FakeRdbSourceCellWarningSession()

    response = _preview(session, "LOA (Maternity Leave from 01-Jan-2026 to 31-Jan-2026)")

    assert response.status_code == 200
    row = response.json()["parsed_candidate_rows"][0]
    assert row["posting_code"] is None
    assert row["status"] == "loa"
    assert row["loa_type"] == "Maternity Leave"
    assert row["working_days_in_month"] == 0


def test_preview_hybrid_loa_continue_working_replacement() -> None:
    session = FakeRdbSourceCellWarningSession()

    response = _preview(
        session,
        "TTSHGerMed\nLOA (Maternity Leave from 10-Jan-2026 to 12-Jan-2026)",
    )

    assert response.status_code == 200
    row = response.json()["parsed_candidate_rows"][0]
    assert row["posting_code"] == "TTSHGerMed"
    assert row["status"] == "loa_working"
    assert row["loa_start_date"] == "2026-01-10"
    assert row["loa_end_date"] == "2026-01-12"
    assert row["working_days_in_month"] == 28


def test_preview_explicit_multi_posting_date_range_returns_independent_rows_and_warning() -> None:
    session = FakeRdbSourceCellWarningSession()
    session.set_unmatched_warning()

    response = _preview(
        session,
        "\n".join(
            [
                "TTSHCardio",
                "(from 01-Jan-2026 to 15-Jan-2026 )",
                "TTSHAnaes",
                "(from 16-Jan-2026 to 31-Jan-2026 )",
            ]
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert [row["posting_code"] for row in body["parsed_candidate_rows"]] == ["TTSHCardio", "TTSHAnaes"]
    assert body["parser_warnings"][0]["type"] == "unmatched_multi_posting"
    assert body["apply_allowed"] is True


def test_preview_parser_error_returns_errors_without_writes() -> None:
    session = FakeRdbSourceCellWarningSession()

    response = _preview(session, "LOA (Maternity Leave from 31-Feb-2026 to 31-Feb-2026)")

    assert response.status_code == 200
    body = response.json()
    assert body["apply_allowed"] is False
    assert body["parser_errors"]
    assert session.audit_logs == []
    assert session.new_posting_ids == []


def test_preview_employed_marker_replacement_is_not_applyable() -> None:
    session = FakeRdbSourceCellWarningSession()

    response = _preview(session, "SAF-Employed")

    assert response.status_code == 200
    body = response.json()
    assert body["normalized_cell_value"] == "SAF-Employed"
    assert body["parsed_candidate_rows"] == []
    assert body["apply_allowed"] is False
    assert body["parser_errors"][0]["type"] == "employed_marker_not_applyable"
    assert "employer_tag" in body["parser_errors"][0]["message"]
    assert "profile" in body["parser_errors"][0]["message"].lower()
    assert session.resident_postings[0]["id"] == session.posting_id
    assert session.residents[0]["employer_tag"] is None


def test_preview_future_employed_marker_replacement_is_not_applyable() -> None:
    session = FakeRdbSourceCellWarningSession()

    response = _preview(session, "ABC-Employed")

    assert response.status_code == 200
    body = response.json()
    assert body["normalized_cell_value"] == "ABC-Employed"
    assert body["apply_allowed"] is False
    assert body["parser_errors"][0]["type"] == "employed_marker_not_applyable"
    assert "future audited profile-aware correction flow" in body["parser_errors"][0]["message"]


def test_apply_employed_marker_replacement_rejects_before_mutating() -> None:
    session = FakeRdbSourceCellWarningSession()
    before_postings = deepcopy(session.resident_postings)

    response = _apply(session, "SAF-Employed")

    assert response.status_code == 422
    assert "could not be parsed" in response.json()["detail"]
    assert session.resident_postings == before_postings
    assert session.residents[0]["employer_tag"] is None
    assert session.audit_logs == []
    assert session.new_posting_ids == []
    assert session.upload_logs == session.original_upload_logs


def test_apply_simple_posting_replacement_is_narrow_audited_and_keeps_warning_unresolved() -> None:
    session = FakeRdbSourceCellWarningSession()
    same_resident_other_phase_id = str(uuid4())
    session.resident_postings.append(
        session._posting(
            same_resident_other_phase_id,
            session.resident_id,
            "TTSHCardio",
            date(2026, 1, 15),
            date(2026, 1, 31),
            None,
        )
    )

    response = _apply(session, "TTSHGerMed")

    assert response.status_code == 200
    body = response.json()
    assert body["warning_issue_id"] == session.warning_issue_id
    assert body["upload_warning_id"] == session.upload_warning_id
    assert body["latest_upload_warning_id"] == session.upload_warning_id
    assert body["fingerprint"] == session.warning_issues[0]["fingerprint"]
    assert body["source_trace"]["cell_ref"] == "I3"
    assert body["source_payload"]["type"] == "empty_posting_cell"
    assert len(body["before_rows"]) == 1
    assert body["before_rows"][0]["id"] == session.posting_id
    assert len(body["after_rows"]) == 1
    assert body["after_rows"][0]["posting_code"] == "TTSHGerMed"
    assert body["replacement_summary"] == {
        "rows_deleted": 1,
        "rows_inserted": 1,
    }
    assert body["warning_issue_status"] == "unresolved"
    assert body["data_revalidation"]["outcome"] == "targeted_revalidation"
    assert body["next_actions"] == [body["suggested_next_action"]]
    assert session.warning_issues[0]["status"] == "unresolved"
    assert session.upload_logs == session.original_upload_logs
    assert {row["resident_id"] for row in session.resident_postings} == {session.resident_id, session.other_resident_id}
    assert any(row["resident_id"] == session.other_resident_id for row in session.resident_postings)
    assert any(row["id"] == same_resident_other_phase_id for row in session.resident_postings)
    metadata = _audit_json(session.audit_logs[0], "metadata_json")
    assert metadata["warning_issue_id"] == session.warning_issue_id
    assert metadata["upload_warning_id"] == session.upload_warning_id
    assert metadata["fingerprint"] == session.warning_issues[0]["fingerprint"]
    assert metadata["after_raw_cell_value"] == "TTSHGerMed"
    assert metadata["teaching_name_reconciliation"]["reconciled_programme_periods"] == 1
    assert session.teaching_name_reconciliations == [
        {
            "reporting_period_id": session.period_id,
            "programme_code": "GERI",
        }
    ]


def test_apply_source_cell_replacement_invalidates_scoped_caches(monkeypatch) -> None:
    calls: list[tuple[set[str], dict]] = []

    def _spy(domains, **scope):  # noqa: ANN001
        calls.append((set(domains), scope))
        return []

    monkeypatch.setattr("app.services.cache_invalidation.invalidate_cache", _spy)
    session = FakeRdbSourceCellWarningSession()

    response = _apply(session, "TTSHGerMed")

    assert response.status_code == 200
    assert calls
    domains, scope = calls[-1]
    assert {
        "parsed_data",
        "resident_postings",
        "upload_warnings",
        "admin_reports",
        "resident_dashboard",
    } <= domains
    assert scope["resident_id"] == session.resident_id
    assert str(scope["warning_issue_id"]) == session.warning_issue_id


def test_apply_empty_cell_removes_scoped_rows_and_creates_no_posting_row() -> None:
    session = FakeRdbSourceCellWarningSession()

    response = _apply(session, "")

    assert response.status_code == 200
    body = response.json()
    assert len(body["before_rows"]) == 1
    assert body["after_rows"] == []
    assert session.new_posting_ids == []
    assert all(row["resident_id"] != session.resident_id for row in session.resident_postings)
    assert any(row["resident_id"] == session.other_resident_id for row in session.resident_postings)


def test_apply_unmatched_multi_posting_persists_independent_rows_and_returns_warning() -> None:
    session = FakeRdbSourceCellWarningSession()
    session.set_unmatched_warning()

    response = _apply(
        session,
        "\n".join(
            [
                "TTSHCardio",
                "(from 01-Jan-2026 to 15-Jan-2026 )",
                "TTSHAnaes",
                "(from 16-Jan-2026 to 31-Jan-2026 )",
            ]
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert [row["posting_code"] for row in body["after_rows"]] == ["TTSHCardio", "TTSHAnaes"]
    assert body["parser_warnings"][0]["type"] == "unmatched_multi_posting"


def test_apply_matched_multi_posting_uses_configured_rule() -> None:
    session = FakeRdbSourceCellWarningSession()
    session.set_unmatched_warning()
    session.add_combine_rule()

    response = _apply(
        session,
        "\n".join(
            [
                "TTSHCardio",
                "(from 01-Jan-2026 to 15-Jan-2026 )",
                "TTSHAnaes",
                "(from 16-Jan-2026 to 31-Jan-2026 )",
            ]
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["after_rows"]) == 1
    assert body["after_rows"][0]["posting_code"] == "TTSHCardio & TTSHAnaes"
    assert body["parser_warnings"] == []


def test_warning_source_cell_scope_rules_require_in_scope_or_explicit_master() -> None:
    scoped_session = FakeRdbSourceCellWarningSession()
    out_of_scope = _preview(scoped_session, "TTSHGerMed", headers=_headers("DR"))
    null_scope = _preview(FakeRdbSourceCellWarningSession(), "TTSHGerMed", headers=_headers(scope=None))
    master = _preview(FakeRdbSourceCellWarningSession(), "TTSHGerMed", headers=_headers(scope=None, master=True))

    assert out_of_scope.status_code == 404
    assert null_scope.status_code == 404
    assert master.status_code == 200


def test_apply_stale_latest_warning_conflict_does_not_mutate() -> None:
    session = FakeRdbSourceCellWarningSession()

    response = _apply(session, "TTSHGerMed", expected_latest_upload_warning_id=str(uuid4()))

    assert response.status_code == 409
    assert session.audit_logs == []
    assert session.new_posting_ids == []
    assert len(session.resident_postings) == 2


def test_apply_source_cell_does_not_touch_compliance_snapshots_clawback_or_frontend() -> None:
    session = FakeRdbSourceCellWarningSession()

    response = _apply(session, "TTSHGerMed")

    assert response.status_code == 200
    executed = "\n".join(session.executed_sql).lower()
    assert "compliance" not in executed
    assert "period_snapshots" not in executed
    assert "clawback" not in executed
    assert "surplus" not in executed
