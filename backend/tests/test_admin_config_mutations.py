from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.middleware.errors import install_error_handlers
from app.routers import admin
from app.schemas.data_revalidation import (
    DataRevalidationImpactSummary,
    DataRevalidationOutcome,
)
from app.services import data_revalidation_service


class _FakeMutationResult:
    def __init__(
        self,
        rows: list[dict] | None = None,
        scalar: object | None = None,
        rowcount: int = 0,
    ) -> None:
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self) -> "_FakeMutationResult":
        return self

    def all(self) -> list[dict]:
        return list(self._rows)

    def one(self) -> dict:
        if len(self._rows) != 1:
            raise AssertionError("Expected exactly one row")
        return self._rows[0]

    def one_or_none(self) -> dict | None:
        if len(self._rows) > 1:
            raise AssertionError("Expected at most one row")
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._scalar


class FakeMutationSession:
    def __init__(self) -> None:
        self.now = datetime(2026, 5, 18, 10, 0, tzinfo=timezone.utc)

        self.reporting_periods: list[dict] = [
            {
                "id": str(uuid4()),
                "label": "Jan - June 2026",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 6, 30),
                "status": "active",
                "activate_on": None,
                "deactivate_on": None,
                "created_at": self.now,
                "updated_at": self.now,
            }
        ]
        self.reporting_period_dependencies: dict[str, dict[str, int]] = {}
        self.public_holidays: list[dict] = []
        self.programmes: list[dict] = [
            {
                "id": str(uuid4()),
                "code": "DR",
                "name": "Diagnostic Radiology",
                "classification": "senior",
                "ay_date_category": "non_im_subspec",
                "r_year_required": True,
                "is_subspecialty": False,
                "rdb_alias": None,
                "created_at": self.now,
                "updated_at": self.now,
            },
            {
                "id": str(uuid4()),
                "code": "GRM",
                "name": "Geriatric Medicine",
                "classification": "senior",
                "ay_date_category": "im_subspec",
                "r_year_required": False,
                "is_subspecialty": False,
                "rdb_alias": None,
                "created_at": self.now,
                "updated_at": self.now,
            },
        ]
        self.loa_types: list[dict] = []
        self.posting_codes = {"TTSHDR", "KTPHDR", "TTSHRespi", "TTSHRespi(MICU)"}
        self.session_type_ids = {str(uuid4())}
        self.multi_posting_rules: list[dict] = []
        self.posting_groups: list[dict] = []
        self.weekend_exceptions: list[dict] = []
        self.global_session_types: list[dict] = [
            {
                "id": str(uuid4()),
                "name": "Department Meeting [1h]",
                "duration_hours": Decimal("1.0"),
                "is_active": True,
                "created_at": self.now,
                "updated_at": self.now,
            }
        ]
        self.warning_issues: list[dict] = []
        self.upload_warnings: list[dict] = []
        self.resident_postings: list[dict] = []
        self.teaching_events: list[dict] = [
            {
                "id": str(uuid4()),
                "teaching_name": "Department Meeting [1h]",
                "posting_code": "TTSHDR",
                "event_date": date(2026, 5, 23),
            }
        ]
        self.attendance_records: list[dict] = []
        self.audit_logs: list[dict] = []

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def execute(self, statement, params=None):  # noqa: C901, PLR0912, PLR0915
        sql = str(statement)
        payload = dict(params or {})

        if "/* data_revalidation:warning_candidates */" in sql:
            statuses = set(payload.get("statuses") or [])
            warning_types = set(payload.get("warning_types") or [])
            programme_code = payload.get("programme_code")
            reporting_period_id = payload.get("reporting_period_id")
            rows = []
            for issue in self.warning_issues:
                if statuses and issue.get("status") not in statuses:
                    continue
                if warning_types and issue.get("warning_type") not in warning_types:
                    continue
                if programme_code is not None and issue.get("programme_code") != programme_code:
                    continue
                if reporting_period_id is not None and str(issue.get("reporting_period_id")) != str(reporting_period_id):
                    continue
                occurrences = [
                    warning
                    for warning in self.upload_warnings
                    if str(warning.get("issue_id")) == str(issue["id"])
                ]
                latest = occurrences[-1] if occurrences else {}
                rows.append(
                    {
                        "issue_id": issue["id"],
                        "fingerprint": issue.get("fingerprint"),
                        "warning_type": issue.get("warning_type"),
                        "status": issue.get("status"),
                        "severity": issue.get("severity"),
                        "reporting_period_id": issue.get("reporting_period_id"),
                        "programme_code": issue.get("programme_code"),
                        "mcr": issue.get("mcr"),
                        "month_label": issue.get("month_label"),
                        "last_seen_at": issue.get("last_seen_at"),
                        "latest_upload_warning_id": latest.get("id"),
                        "source_payload": latest.get("source_payload") or {},
                        "message": latest.get("message"),
                        "suggested_action": latest.get("suggested_action"),
                    }
                )
            return _FakeMutationResult(rows=rows[: payload.get("limit", len(rows))])

        if "/* data_revalidation:count_resident_postings */" in sql:
            count = 0
            for row in self.resident_postings:
                if payload.get("programme_code") is not None and row.get("programme_code") != payload["programme_code"]:
                    continue
                if payload.get("posting_code") is not None and row.get("posting_code") != payload["posting_code"]:
                    continue
                if payload.get("reporting_period_id") is not None and str(row.get("reporting_period_id")) != str(payload["reporting_period_id"]):
                    continue
                count += 1
            return _FakeMutationResult(rows=[{"count": count}])

        if "/* data_revalidation:count_teaching_events */" in sql:
            count = 0
            for row in self.teaching_events:
                if payload.get("teaching_name") is not None and row.get("teaching_name") != payload["teaching_name"]:
                    continue
                if payload.get("posting_code") is not None and row.get("posting_code") != payload["posting_code"]:
                    continue
                if payload.get("holiday_date") is not None and row.get("event_date") != payload["holiday_date"]:
                    continue
                pattern = payload.get("session_name_pattern")
                if pattern is not None and pattern.strip("%").lower() not in row.get("teaching_name", "").lower():
                    continue
                count += 1
            return _FakeMutationResult(rows=[{"count": count}])

        if "/* data_revalidation:count_attendance_records */" in sql:
            event_by_id = {str(row.get("id")): row for row in self.teaching_events}
            count = 0
            for row in self.attendance_records:
                event = event_by_id.get(str(row.get("event_id"))) or row
                if payload.get("teaching_name") is not None and event.get("teaching_name") != payload["teaching_name"]:
                    continue
                if payload.get("posting_code") is not None and event.get("posting_code") != payload["posting_code"]:
                    continue
                pattern = payload.get("session_name_pattern")
                if pattern is not None and pattern.strip("%").lower() not in event.get("teaching_name", "").lower():
                    continue
                count += 1
            return _FakeMutationResult(rows=[{"count": count}])

        if "/* data_revalidation:count_period_" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["reporting_period_id"], {})
            if "count_period_upload_logs" in sql:
                table = "upload_logs"
            elif "count_period_resident_postings" in sql:
                table = "resident_postings"
            elif "count_period_teaching_targets" in sql:
                table = "teaching_targets"
            elif "count_period_form_f1_records" in sql:
                table = "form_f1_records"
            else:
                table = ""
            return _FakeMutationResult(rows=[{"count": period_counts.get(table, 0)}])

        if "SELECT 1 FROM posting_codes" in sql:
            code = payload["code"]
            return _FakeMutationResult(scalar=1 if code in self.posting_codes else None)

        if "INSERT INTO posting_codes" in sql:
            self.posting_codes.add(payload["code"])
            return _FakeMutationResult()

        if "SELECT 1 FROM programmes" in sql:
            code = payload["code"]
            return _FakeMutationResult(scalar=1 if code in {row["code"] for row in self.programmes} else None)

        if "SELECT 1 FROM session_types" in sql:
            sid = payload["session_type_id"]
            return _FakeMutationResult(scalar=1 if sid in self.session_type_ids else None)

        if "INSERT INTO audit_logs" in sql:
            row = dict(payload)
            row["created_at"] = self.now
            self.audit_logs.append(row)
            return _FakeMutationResult(rows=[row])

        if "/* audit_snapshot:reporting_period */" in sql:
            row = next((r for r in self.reporting_periods if r["id"] == payload["id"]), None)
            return _FakeMutationResult(rows=[dict(row)] if row else [])

        if "/* audit_snapshot:public_holiday */" in sql:
            row = next((r for r in self.public_holidays if r["id"] == payload["id"]), None)
            return _FakeMutationResult(rows=[dict(row)] if row else [])

        if "/* audit_snapshot:programme */" in sql:
            row = next((r for r in self.programmes if r["code"] == payload["code"]), None)
            return _FakeMutationResult(rows=[dict(row)] if row else [])

        if "/* audit_snapshot:loa_type */" in sql:
            row = next((r for r in self.loa_types if r["id"] == payload["id"]), None)
            return _FakeMutationResult(rows=[dict(row)] if row else [])

        if "/* audit_snapshot:multi_posting_rule */" in sql:
            row = next((r for r in self.multi_posting_rules if r["id"] == payload["id"]), None)
            return _FakeMutationResult(rows=[dict(row)] if row else [])

        if "/* audit_snapshot:posting_group */" in sql:
            row = next((r for r in self.posting_groups if r["id"] == payload["id"]), None)
            return _FakeMutationResult(rows=[dict(row)] if row else [])

        if "/* audit_snapshot:weekend_exception */" in sql:
            row = next((r for r in self.weekend_exceptions if r["id"] == payload["id"]), None)
            return _FakeMutationResult(rows=[dict(row)] if row else [])

        if "/* audit_snapshot:global_session_type */" in sql:
            row = next((r for r in self.global_session_types if r["id"] == payload["id"]), None)
            return _FakeMutationResult(rows=[dict(row)] if row else [])

        if "INSERT INTO reporting_periods" in sql:
            if any(row["label"] == payload["label"] for row in self.reporting_periods):
                raise IntegrityError("insert reporting_periods", payload, None)
            row = {
                "id": str(uuid4()),
                "label": payload["label"],
                "start_date": payload["start_date"],
                "end_date": payload["end_date"],
                "status": payload.get("status") or "active",
                "activate_on": payload.get("activate_on"),
                "deactivate_on": payload.get("deactivate_on"),
                "created_at": self.now,
                "updated_at": self.now,
            }
            self.reporting_periods.append(row)
            return _FakeMutationResult(rows=[row])

        if (
            "SELECT" in sql
            and "FROM reporting_periods" in sql
            and "WHERE id = :id" in sql
        ):
            period = next(
                (row for row in self.reporting_periods if row["id"] == payload["id"]),
                None,
            )
            return _FakeMutationResult(rows=[period] if period else [])

        if "FROM reporting_periods" in sql and "ORDER BY start_date" in sql:
            return _FakeMutationResult(rows=list(self.reporting_periods))

        if "SELECT id, holiday_date, name, day_of_week, year, created_at, updated_at" in sql and "FROM public_holidays" in sql:
            return _FakeMutationResult(rows=list(self.public_holidays))

        if "classification" in sql and "FROM programmes" in sql:
            return _FakeMutationResult(rows=list(self.programmes))

        if "SELECT id, code, description, created_at, updated_at" in sql and "FROM loa_types" in sql:
            return _FakeMutationResult(rows=list(self.loa_types))

        if "FROM multi_posting_rules" in sql and "ORDER BY programme_code ASC, rule_type ASC" in sql:
            return _FakeMutationResult(rows=list(self.multi_posting_rules))

        if "SELECT id, group_code, posting_code, programme_code, created_at, updated_at" in sql and "FROM posting_groups" in sql:
            return _FakeMutationResult(rows=list(self.posting_groups))

        if "FROM weekend_exceptions we" in sql:
            return _FakeMutationResult(rows=list(self.weekend_exceptions))

        if "SELECT id, name, duration_hours, is_active, created_at, updated_at" in sql and "FROM global_session_types" in sql:
            return _FakeMutationResult(rows=list(self.global_session_types))

        if "UPDATE reporting_periods" in sql:
            period = next(
                (row for row in self.reporting_periods if row["id"] == payload["id"]),
                None,
            )
            if period is None:
                return _FakeMutationResult(rows=[])
            if payload.get("label") is not None:
                duplicate = any(
                    row["label"] == payload["label"] and row["id"] != period["id"]
                    for row in self.reporting_periods
                )
                if duplicate:
                    raise IntegrityError("update reporting_periods", payload, None)
                period["label"] = payload["label"]
            if payload.get("start_date") is not None:
                period["start_date"] = payload["start_date"]
            if payload.get("end_date") is not None:
                period["end_date"] = payload["end_date"]
            if payload.get("status") is not None:
                period["status"] = payload["status"]
            if payload.get("activate_on_set"):
                period["activate_on"] = payload.get("activate_on")
            if payload.get("deactivate_on_set"):
                period["deactivate_on"] = payload.get("deactivate_on")
            period["updated_at"] = self.now
            return _FakeMutationResult(rows=[period])

        if "SELECT id FROM reporting_periods" in sql:
            period = next(
                (row for row in self.reporting_periods if row["id"] == payload["id"]),
                None,
            )
            return _FakeMutationResult(rows=[{"id": period["id"]}] if period else [])

        if "FROM upload_logs" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("upload_logs", 0)}])

        if "FROM resident_postings" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("resident_postings", 0)}])

        if "FROM teaching_targets" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("teaching_targets", 0)}])

        if "FROM teaching_name_catalogue" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("teaching_name_catalogue", 0)}])

        if "FROM form_f1_records" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("form_f1_records", 0)}])

        if "FROM academic_month_boundaries" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("academic_month_boundaries", 0)}])

        if "FROM period_snapshots" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("period_snapshots", 0)}])

        if "FROM clawback_records" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("clawback_records", 0)}])

        if "FROM surplus_ledger" in sql and "reporting_period_id = :id" in sql:
            period_counts = self.reporting_period_dependencies.get(payload["id"], {})
            return _FakeMutationResult(rows=[{"count": period_counts.get("surplus_ledger", 0)}])

        if "DELETE FROM reporting_periods" in sql:
            before = len(self.reporting_periods)
            self.reporting_periods = [r for r in self.reporting_periods if r["id"] != payload["id"]]
            return _FakeMutationResult(rowcount=before - len(self.reporting_periods))

        if "INSERT INTO public_holidays" in sql:
            existing = next(
                (
                    row
                    for row in self.public_holidays
                    if row["holiday_date"] == payload["holiday_date"]
                ),
                None,
            )
            if existing is None:
                existing = {
                    "id": str(uuid4()),
                    "holiday_date": payload["holiday_date"],
                    "name": payload["name"],
                    "day_of_week": payload["day_of_week"],
                    "year": payload["year"],
                    "created_at": self.now,
                    "updated_at": self.now,
                }
                self.public_holidays.append(existing)
            else:
                existing["name"] = payload["name"]
                existing["day_of_week"] = payload["day_of_week"]
                existing["year"] = payload["year"]
                existing["updated_at"] = self.now
            return _FakeMutationResult(rows=[existing])

        if "UPDATE public_holidays" in sql:
            existing = next(
                (row for row in self.public_holidays if row["id"] == payload["id"]),
                None,
            )
            if existing is None:
                return _FakeMutationResult(rows=[])
            duplicate = any(
                row["holiday_date"] == payload["holiday_date"] and row["id"] != existing["id"]
                for row in self.public_holidays
            )
            if duplicate:
                raise IntegrityError("update public_holidays", payload, None)
            existing["holiday_date"] = payload["holiday_date"]
            existing["name"] = payload["name"]
            existing["day_of_week"] = payload["day_of_week"]
            existing["year"] = payload["year"]
            existing["updated_at"] = self.now
            return _FakeMutationResult(rows=[existing])

        if "DELETE FROM public_holidays" in sql:
            before = len(self.public_holidays)
            self.public_holidays = [r for r in self.public_holidays if r["id"] != payload["id"]]
            return _FakeMutationResult(rowcount=before - len(self.public_holidays))

        if "UPDATE programmes" in sql:
            programme = next(
                (row for row in self.programmes if row["code"] == payload["programme_code"]),
                None,
            )
            if programme is None:
                return _FakeMutationResult(rows=[])
            if payload.get("r_year_required") is not None:
                programme["r_year_required"] = payload["r_year_required"]
            if payload.get("is_subspecialty") is not None:
                programme["is_subspecialty"] = payload["is_subspecialty"]
            if payload.get("rdb_alias_is_set"):
                programme["rdb_alias"] = payload.get("rdb_alias")
            programme["updated_at"] = self.now
            return _FakeMutationResult(rows=[programme])

        if "INSERT INTO loa_types" in sql:
            if any(row["code"] == payload["code"] for row in self.loa_types):
                raise IntegrityError("insert loa_types", payload, None)
            row = {
                "id": str(uuid4()),
                "code": payload["code"],
                "description": payload["description"],
                "created_at": self.now,
                "updated_at": self.now,
            }
            self.loa_types.append(row)
            return _FakeMutationResult(rows=[row])

        if "UPDATE loa_types" in sql:
            row = next((item for item in self.loa_types if item["id"] == payload["id"]), None)
            if row is None:
                return _FakeMutationResult(rows=[])
            if payload.get("code") is not None and any(
                item["code"] == payload["code"] and item["id"] != row["id"]
                for item in self.loa_types
            ):
                raise IntegrityError("update loa_types", payload, None)
            if payload.get("code") is not None:
                row["code"] = payload["code"]
            row["description"] = payload.get("description")
            row["updated_at"] = self.now
            return _FakeMutationResult(rows=[row])

        if "DELETE FROM loa_types" in sql:
            before = len(self.loa_types)
            self.loa_types = [r for r in self.loa_types if r["id"] != payload["id"]]
            return _FakeMutationResult(rowcount=before - len(self.loa_types))

        if "SELECT 1" in sql and "FROM multi_posting_rules" in sql:
            found = next(
                (
                    row
                    for row in self.multi_posting_rules
                    if row["programme_code"] == payload["programme_code"]
                    and row["posting_code_1"] == payload["posting_code_1"]
                    and row["posting_code_2"] == payload["posting_code_2"]
                    and row["rule_type"] == payload["rule_type"]
                    and (payload.get("exclude_id") is None or row["id"] != payload.get("exclude_id"))
                ),
                None,
            )
            return _FakeMutationResult(scalar=1 if found else None)

        if "INSERT INTO multi_posting_rules" in sql:
            row = {
                "id": str(uuid4()),
                "programme_code": payload["programme_code"],
                "posting_code_1": payload["posting_code_1"],
                "posting_code_2": payload["posting_code_2"],
                "rule_type": payload["rule_type"],
                "combined_label": payload["combined_label"],
                "main_posting_code": payload["main_posting_code"],
                "exclusion_code": payload["exclusion_code"],
                "created_at": self.now,
                "updated_at": self.now,
            }
            self.multi_posting_rules.append(row)
            return _FakeMutationResult(rows=[row])

        if "SELECT id, programme_code FROM multi_posting_rules" in sql:
            row = next((r for r in self.multi_posting_rules if r["id"] == payload["id"]), None)
            return _FakeMutationResult(rows=[row] if row else [])

        if "UPDATE multi_posting_rules" in sql:
            row = next((r for r in self.multi_posting_rules if r["id"] == payload["id"]), None)
            if row is None:
                return _FakeMutationResult(rows=[])
            row.update(
                {
                    "programme_code": payload["programme_code"],
                    "posting_code_1": payload["posting_code_1"],
                    "posting_code_2": payload["posting_code_2"],
                    "rule_type": payload["rule_type"],
                    "combined_label": payload["combined_label"],
                    "main_posting_code": payload["main_posting_code"],
                    "exclusion_code": payload["exclusion_code"],
                    "updated_at": self.now,
                }
            )
            return _FakeMutationResult(rows=[row])

        if "DELETE FROM multi_posting_rules" in sql:
            before = len(self.multi_posting_rules)
            self.multi_posting_rules = [r for r in self.multi_posting_rules if r["id"] != payload["id"]]
            return _FakeMutationResult(rowcount=before - len(self.multi_posting_rules))

        if "INSERT INTO posting_groups" in sql:
            duplicate = any(
                row["posting_code"] == payload["posting_code"]
                and row["programme_code"] == payload["programme_code"]
                for row in self.posting_groups
            )
            if duplicate:
                raise IntegrityError("insert posting_groups", payload, None)
            row = {
                "id": str(uuid4()),
                "group_code": payload["group_code"],
                "posting_code": payload["posting_code"],
                "programme_code": payload["programme_code"],
                "created_at": self.now,
                "updated_at": self.now,
            }
            self.posting_groups.append(row)
            return _FakeMutationResult(rows=[row])

        if "SELECT id, programme_code FROM posting_groups" in sql:
            row = next((r for r in self.posting_groups if r["id"] == payload["id"]), None)
            return _FakeMutationResult(rows=[row] if row else [])

        if "UPDATE posting_groups" in sql:
            row = next((r for r in self.posting_groups if r["id"] == payload["id"]), None)
            if row is None:
                return _FakeMutationResult(rows=[])
            duplicate = any(
                item["posting_code"] == payload["posting_code"]
                and item["programme_code"] == payload["programme_code"]
                and item["id"] != payload["id"]
                for item in self.posting_groups
            )
            if duplicate:
                raise IntegrityError("update posting_groups", payload, None)
            row.update(
                {
                    "group_code": payload["group_code"],
                    "posting_code": payload["posting_code"],
                    "programme_code": payload["programme_code"],
                    "updated_at": self.now,
                }
            )
            return _FakeMutationResult(rows=[row])

        if "DELETE FROM posting_groups" in sql:
            before = len(self.posting_groups)
            self.posting_groups = [r for r in self.posting_groups if r["id"] != payload["id"]]
            return _FakeMutationResult(rowcount=before - len(self.posting_groups))

        if "INSERT INTO weekend_exceptions" in sql:
            row = {
                "id": str(uuid4()),
                "programme_code": payload["programme_code"],
                "posting_code": payload["posting_code"],
                "day_type": payload["day_type"],
                "start_time_min": payload["start_time_min"],
                "end_time_max": payload["end_time_max"],
                "session_type_id": payload["session_type_id"],
                "session_name_pattern": payload["session_name_pattern"],
                "mutates_to_session_type_id": payload["mutates_to_session_type_id"],
                "adjusted_duration_hours": payload["adjusted_duration_hours"],
                "created_at": self.now,
                "updated_at": self.now,
            }
            self.weekend_exceptions.append(row)
            return _FakeMutationResult(rows=[row])

        if "SELECT id, programme_code FROM weekend_exceptions" in sql:
            row = next((r for r in self.weekend_exceptions if r["id"] == payload["id"]), None)
            return _FakeMutationResult(rows=[row] if row else [])

        if "UPDATE weekend_exceptions" in sql:
            row = next((r for r in self.weekend_exceptions if r["id"] == payload["id"]), None)
            if row is None:
                return _FakeMutationResult(rows=[])
            row.update(
                {
                    "programme_code": payload["programme_code"],
                    "posting_code": payload["posting_code"],
                    "day_type": payload["day_type"],
                    "start_time_min": payload["start_time_min"],
                    "end_time_max": payload["end_time_max"],
                    "session_type_id": payload["session_type_id"],
                    "session_name_pattern": payload["session_name_pattern"],
                    "mutates_to_session_type_id": payload["mutates_to_session_type_id"],
                    "adjusted_duration_hours": payload["adjusted_duration_hours"],
                    "updated_at": self.now,
                }
            )
            return _FakeMutationResult(rows=[row])

        if "DELETE FROM weekend_exceptions" in sql:
            before = len(self.weekend_exceptions)
            self.weekend_exceptions = [r for r in self.weekend_exceptions if r["id"] != payload["id"]]
            return _FakeMutationResult(rowcount=before - len(self.weekend_exceptions))

        if "INSERT INTO global_session_types" in sql:
            if any(row["name"] == payload["name"] for row in self.global_session_types):
                raise IntegrityError("insert global_session_types", payload, None)
            row = {
                "id": str(uuid4()),
                "name": payload["name"],
                "duration_hours": payload["duration_hours"],
                "is_active": payload["is_active"],
                "created_at": self.now,
                "updated_at": self.now,
            }
            self.global_session_types.append(row)
            return _FakeMutationResult(rows=[row])

        if "UPDATE global_session_types" in sql:
            row = next((r for r in self.global_session_types if r["id"] == payload["id"]), None)
            if row is None:
                return _FakeMutationResult(rows=[])
            new_name = payload["name"] if payload.get("name") is not None else row["name"]
            if any(
                item["name"] == new_name and item["id"] != payload["id"]
                for item in self.global_session_types
            ):
                raise IntegrityError("update global_session_types", payload, None)
            if payload.get("name") is not None:
                row["name"] = payload["name"]
            if payload.get("duration_hours") is not None:
                row["duration_hours"] = payload["duration_hours"]
            if payload.get("is_active") is not None:
                row["is_active"] = payload["is_active"]
            row["updated_at"] = self.now
            return _FakeMutationResult(rows=[row])

        if "SELECT id, name FROM global_session_types" in sql:
            row = next((r for r in self.global_session_types if r["id"] == payload["id"]), None)
            return _FakeMutationResult(rows=[row] if row else [])

        if "SELECT 1" in sql and "FROM teaching_events" in sql:
            found = any(row["teaching_name"] == payload["name"] for row in self.teaching_events)
            return _FakeMutationResult(scalar=1 if found else None)

        if "DELETE FROM global_session_types" in sql:
            before = len(self.global_session_types)
            self.global_session_types = [r for r in self.global_session_types if r["id"] != payload["id"]]
            return _FakeMutationResult(rowcount=before - len(self.global_session_types))

        raise AssertionError(f"Unhandled SQL: {sql}")


class StrictWarningCandidateSqlSession(FakeMutationSession):
    async def execute(self, statement, params=None):  # noqa: C901, PLR0912, PLR0915
        sql = str(statement)
        payload = dict(params or {})
        if "/* data_revalidation:warning_candidates */" in sql:
            if payload.get("programme_code") is None and ":programme_code IS NULL" in sql:
                raise AssertionError(
                    "programme_code None must not be used in an untyped nullable SQL predicate"
                )
            if payload.get("reporting_period_id") is None and ":reporting_period_id IS NULL" in sql:
                raise AssertionError(
                    "reporting_period_id None must not be used in an untyped nullable SQL predicate"
                )
        return await super().execute(statement, params)


def _build_client_with_session(session: FakeMutationSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def _db_override():
        yield session

    app.dependency_overrides[admin.get_db_session] = _db_override
    return TestClient(app)


def _admin_headers(scope: str | None = "DR,GRM") -> dict[str, str]:
    headers = {
        "X-User-Role": "admin",
        "X-User-Id": str(uuid4()),
    }
    if scope is not None:
        headers["X-User-Programme"] = scope
    return headers


def _master_admin_headers(scope: str | None = "DR,GRM") -> dict[str, str]:
    headers = _admin_headers(scope)
    headers["X-Admin-Level"] = "master"
    return headers


def _audit_json(row: dict, field: str) -> dict | None:
    value = row[field]
    if value is None:
        return None
    return json.loads(value)


def _add_warning_issue(
    session: FakeMutationSession,
    *,
    warning_type: str,
    programme_code: str | None = "DR",
    reporting_period_id: str | None = None,
    status: str = "unresolved",
    source_payload: dict | None = None,
    message: str | None = None,
) -> str:
    issue_id = str(uuid4())
    fingerprint = f"{warning_type}|{programme_code}|{issue_id}"
    issue = {
        "id": issue_id,
        "fingerprint": fingerprint,
        "warning_type": warning_type,
        "severity": "warning",
        "status": status,
        "reporting_period_id": reporting_period_id or session.reporting_periods[0]["id"],
        "programme_code": programme_code,
        "mcr": "M12345A",
        "month_label": "May-26",
        "last_seen_at": session.now,
    }
    occurrence = {
        "id": str(uuid4()),
        "issue_id": issue_id,
        "upload_log_id": str(uuid4()),
        "warning_type": warning_type,
        "severity": "warning",
        "reporting_period_id": issue["reporting_period_id"],
        "programme_code": programme_code,
        "mcr": issue["mcr"],
        "month_label": issue["month_label"],
        "source_payload": source_payload or {},
        "message": message or f"{warning_type} warning",
        "suggested_action": None,
        "fingerprint": fingerprint,
        "created_at": session.now,
    }
    session.warning_issues.append(issue)
    session.upload_warnings.append(occurrence)
    return issue_id


def _assert_config_impact(
    body: dict,
    *,
    changed_entity: str,
    action: str,
    outcome: str = "future_compliance_impact",
) -> dict:
    impact = body["data_revalidation"]
    assert impact["trigger_source"] in {"admin_config_change", "pc_config_change"}
    assert impact["changed_entity"] == changed_entity
    assert impact["action"] == action
    assert impact["outcome"] == outcome
    assert impact["rows_examined"] >= 0
    assert impact["rows_updated"] == 0
    assert impact["warnings_created"] == 0
    assert impact["warnings_updated"] == 0
    assert impact["warnings_resolved"] == 0
    return impact


def test_admin_only_mutation_access_rejects_non_admin() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/loa-types",
        headers={
            "X-User-Role": "resident",
            "X-User-Id": str(uuid4()),
        },
        json={"code": "Study Leave", "description": "x"},
    )
    assert response.status_code == 403


def test_all_phase3_mutation_endpoints_reject_non_admin() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    headers = {
        "X-User-Role": "resident",
        "X-User-Id": str(uuid4()),
    }
    period_id = session.reporting_periods[0]["id"]
    global_type_id = session.global_session_types[0]["id"]
    paths_with_payloads = [
        ("POST", "/admin/reporting-periods", {"label": "Jul - Dec 2026", "start_date": "2026-07-01", "end_date": "2026-12-31"}),
        ("PUT", f"/admin/reporting-periods/{period_id}", {"status": "inactive"}),
        ("PUT", f"/admin/reporting-periods/{period_id}/activate", {}),
        ("PUT", f"/admin/reporting-periods/{period_id}/deactivate", {}),
        ("DELETE", f"/admin/reporting-periods/{period_id}", None),
        ("POST", "/admin/public-holidays", {"holiday_date": "2026-08-09", "name": "National Day", "day_of_week": "Sunday", "year": 2026}),
        ("PUT", f"/admin/public-holidays/{uuid4()}", {"holiday_date": "2026-08-09", "name": "National Day", "day_of_week": "Sunday", "year": 2026}),
        ("DELETE", f"/admin/public-holidays/{uuid4()}", None),
        ("PUT", "/admin/programmes/DR", {"r_year_required": True}),
        ("POST", "/admin/loa-types", {"code": "Study Leave", "description": "x"}),
        ("PUT", f"/admin/loa-types/{uuid4()}", {"code": "Study Leave", "description": "x"}),
        ("DELETE", f"/admin/loa-types/{uuid4()}", None),
        ("POST", "/admin/multi-posting-rules", {"programme_code": "DR", "posting_code_1": "TTSHDR", "posting_code_2": "KTPHDR", "rule_type": "combine", "combined_label": "TTSHDR & KTPHDR"}),
        ("PUT", f"/admin/multi-posting-rules/{uuid4()}", {"programme_code": "DR", "posting_code_1": "TTSHDR", "posting_code_2": "KTPHDR", "rule_type": "combine", "combined_label": "TTSHDR & KTPHDR"}),
        ("DELETE", f"/admin/multi-posting-rules/{uuid4()}", None),
        ("POST", "/admin/posting-groups", {"group_code": "DR-GROUP", "posting_code": "TTSHRespi", "programme_code": "DR"}),
        ("PUT", f"/admin/posting-groups/{uuid4()}", {"group_code": "DR-GROUP", "posting_code": "TTSHRespi", "programme_code": "DR"}),
        ("DELETE", f"/admin/posting-groups/{uuid4()}", None),
        ("POST", "/admin/weekend-exceptions", {"programme_code": "DR", "posting_code": "TTSHDR", "day_type": "sat"}),
        ("PUT", f"/admin/weekend-exceptions/{uuid4()}", {"programme_code": "DR", "posting_code": "TTSHDR", "day_type": "sat"}),
        ("DELETE", f"/admin/weekend-exceptions/{uuid4()}", None),
        ("POST", "/admin/global-session-types", {"name": "Dept Meeting [1h]", "duration_hours": 1.0, "is_active": True}),
        ("PUT", f"/admin/global-session-types/{global_type_id}", {"is_active": False}),
        ("DELETE", f"/admin/global-session-types/{global_type_id}", None),
    ]

    for method, path, payload in paths_with_payloads:
        if method == "POST":
            response = client.post(path, headers=headers, json=payload or {})
        elif method == "PUT":
            response = client.put(path, headers=headers, json=payload or {})
        else:
            response = client.delete(path, headers=headers)
        assert response.status_code == 403


def test_config_mutation_endpoint_uses_fallback_actor_name_and_writes_audit() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)

    response = client.post(
        "/admin/loa-types",
        headers=_master_admin_headers("DR"),
        json={"code": "Temporary Leave", "description": "Temporary leave"},
    )

    assert response.status_code == 200
    assert session.audit_logs[-1]["actor_name"] == "Unknown actor"
    assert session.audit_logs[-1]["action"] == "admin.config.loa_type.create"


def test_config_mutation_endpoint_allows_blank_actor_name() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    headers = _master_admin_headers("DR")
    headers["-".join(["X", "Actor", "Name"])] = "   "

    response = client.post(
        "/admin/loa-types",
        headers=headers,
        json={"code": "Study Leave", "description": "Academic study leave"},
    )

    assert response.status_code == 200
    assert session.audit_logs[-1]["actor_name"] == "Unknown actor"


def test_data_revalidation_runs_only_after_successful_config_mutation(monkeypatch) -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    contexts = []

    async def _spy_revalidate_after_config_change(*, context, db_session):
        contexts.append(context)
        return DataRevalidationImpactSummary(
            outcome=DataRevalidationOutcome.FUTURE_COMPLIANCE_IMPACT,
            trigger_source=context.trigger_source,
            changed_entity=context.changed_entity,
            action=context.action,
            scope=context.scope,
            summary="spy config impact summary",
            details={"changed_fields": list(context.changed_fields)},
        )

    monkeypatch.setattr(
        data_revalidation_service,
        "revalidate_after_config_change",
        _spy_revalidate_after_config_change,
    )

    global_type_id = session.global_session_types[0]["id"]
    succeeded = client.put(
        f"/admin/global-session-types/{global_type_id}",
        headers=_master_admin_headers("DR"),
        json={"is_active": False},
    )
    protected_delete = client.delete(
        f"/admin/global-session-types/{global_type_id}",
        headers=_master_admin_headers("DR"),
    )
    invalid_weekend_exception = client.post(
        "/admin/weekend-exceptions",
        headers=_master_admin_headers("DR"),
        json={"programme_code": "DR", "posting_code": "UNKNOWN", "day_type": "sat"},
    )
    out_of_scope_rule = client.post(
        "/admin/multi-posting-rules",
        headers=_admin_headers("DR"),
        json={
            "programme_code": "GRM",
            "posting_code_1": "TTSHDR",
            "posting_code_2": "KTPHDR",
            "rule_type": "combine",
            "combined_label": "TTSHDR & KTPHDR",
        },
    )
    missing_reporting_period_activate = client.put(
        f"/admin/reporting-periods/{uuid4()}/activate",
        headers=_master_admin_headers("DR"),
    )

    assert succeeded.status_code == 200
    assert protected_delete.status_code == 409
    assert invalid_weekend_exception.status_code == 422
    assert out_of_scope_rule.status_code == 403
    assert missing_reporting_period_activate.status_code == 404
    assert len(contexts) == 1
    assert contexts[0].changed_entity.value == "global_session_type"
    assert contexts[0].action.value == "update"
    assert contexts[0].changed_fields == ["is_active"]


def test_config_list_endpoints_do_not_require_actor_name() -> None:
    client = _build_client_with_session(FakeMutationSession())
    master_headers = _master_admin_headers("DR")
    pc_headers = _admin_headers("DR")
    paths_with_headers = [
        ("/admin/reporting-periods", master_headers),
        ("/admin/public-holidays", master_headers),
        ("/admin/programmes", master_headers),
        ("/admin/loa-types", master_headers),
        ("/admin/multi-posting-rules", pc_headers),
        ("/admin/posting-groups", pc_headers),
        ("/admin/weekend-exceptions", master_headers),
        ("/admin/global-session-types", master_headers),
    ]

    for path, headers in paths_with_headers:
        response = client.get(path, headers=headers)
        assert response.status_code == 200, path


def test_admin_config_crud_mutations_write_audit_logs() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    master_headers = _master_admin_headers("DR")
    pc_headers = _admin_headers("DR")

    reporting_period = client.post(
        "/admin/reporting-periods",
        headers=master_headers,
        json={"label": "Jul - Dec 2026", "start_date": "2026-07-01", "end_date": "2026-12-31"},
    )
    assert reporting_period.status_code == 200
    reporting_period_body = reporting_period.json()
    reporting_period_id = reporting_period_body["id"]
    _assert_config_impact(
        reporting_period_body,
        changed_entity="reporting_period",
        action="create",
    )
    reporting_period_update = client.put(
        f"/admin/reporting-periods/{reporting_period_id}",
        headers=master_headers,
        json={
            "label": "H2 2026",
            "status": "inactive",
            "activate_on": "2026-07-01",
            "deactivate_on": "2026-12-31",
        },
    )
    assert reporting_period_update.status_code == 200
    reporting_period_update_body = reporting_period_update.json()
    assert reporting_period_update_body["activate_on"] == "2026-07-01"
    assert reporting_period_update_body["deactivate_on"] == "2026-12-31"
    reporting_period_impact = _assert_config_impact(
        reporting_period_update_body,
        changed_entity="reporting_period",
        action="update",
    )
    assert reporting_period_impact["details"]["changed_fields"] == [
        "activate_on",
        "deactivate_on",
        "label",
        "status",
    ]
    reporting_period_deactivate = client.put(
        f"/admin/reporting-periods/{reporting_period_id}/deactivate",
        headers=master_headers,
    )
    assert reporting_period_deactivate.status_code == 200
    assert reporting_period_deactivate.json()["status"] == "inactive"
    _assert_config_impact(
        reporting_period_deactivate.json(),
        changed_entity="reporting_period",
        action="deactivate",
    )
    reporting_period_activate = client.put(
        f"/admin/reporting-periods/{reporting_period_id}/activate",
        headers=master_headers,
    )
    assert reporting_period_activate.status_code == 200
    assert reporting_period_activate.json()["status"] == "active"
    _assert_config_impact(
        reporting_period_activate.json(),
        changed_entity="reporting_period",
        action="activate",
    )
    reporting_period_delete = client.delete(
        f"/admin/reporting-periods/{reporting_period_id}",
        headers=master_headers,
    )
    assert reporting_period_delete.status_code == 200
    _assert_config_impact(
        reporting_period_delete.json(),
        changed_entity="reporting_period",
        action="delete",
    )

    holiday = client.post(
        "/admin/public-holidays",
        headers=master_headers,
        json={"holiday_date": "2026-08-09", "name": "National Day"},
    )
    assert holiday.status_code == 200
    holiday_body = holiday.json()
    holiday_id = holiday_body["id"]
    _assert_config_impact(
        holiday_body,
        changed_entity="public_holiday",
        action="create",
    )
    holiday_update = client.put(
        f"/admin/public-holidays/{holiday_id}",
        headers=master_headers,
        json={"holiday_date": "2026-08-10", "name": "National Day observed"},
    )
    assert holiday_update.status_code == 200
    _assert_config_impact(
        holiday_update.json(),
        changed_entity="public_holiday",
        action="update",
    )
    holiday_delete = client.delete(f"/admin/public-holidays/{holiday_id}", headers=master_headers)
    assert holiday_delete.status_code == 200
    _assert_config_impact(
        holiday_delete.json(),
        changed_entity="public_holiday",
        action="delete",
    )

    programme_update = client.put(
        "/admin/programmes/DR",
        headers=master_headers,
        json={"r_year_required": False, "is_subspecialty": True},
    )
    assert programme_update.status_code == 200
    programme_impact = _assert_config_impact(
        programme_update.json(),
        changed_entity="programme",
        action="update",
    )
    assert programme_impact["details"]["changed_fields"] == [
        "is_subspecialty",
        "r_year_required",
    ]

    loa_type = client.post(
        "/admin/loa-types",
        headers=master_headers,
        json={"code": "Study Leave", "description": "Academic study leave"},
    )
    assert loa_type.status_code == 200
    loa_type_body = loa_type.json()
    loa_type_id = loa_type_body["id"]
    _assert_config_impact(loa_type_body, changed_entity="loa_type", action="create")
    loa_type_update = client.put(
        f"/admin/loa-types/{loa_type_id}",
        headers=master_headers,
        json={"code": "Exam Leave", "description": ""},
    )
    assert loa_type_update.status_code == 200
    _assert_config_impact(
        loa_type_update.json(),
        changed_entity="loa_type",
        action="update",
    )
    loa_type_delete = client.delete(f"/admin/loa-types/{loa_type_id}", headers=master_headers)
    assert loa_type_delete.status_code == 200
    _assert_config_impact(
        loa_type_delete.json(),
        changed_entity="loa_type",
        action="delete",
    )

    multi_rule_payload = {
        "programme_code": "DR",
        "posting_code_1": "TTSHDR",
        "posting_code_2": "KTPHDR",
        "rule_type": "combine",
        "combined_label": "TTSHDR & KTPHDR",
        "main_posting_code": None,
        "exclusion_code": None,
    }
    multi_rule = client.post("/admin/multi-posting-rules", headers=pc_headers, json=multi_rule_payload)
    assert multi_rule.status_code == 200
    multi_rule_body = multi_rule.json()
    multi_rule_id = multi_rule_body["id"]
    multi_create_impact = _assert_config_impact(
        multi_rule_body,
        changed_entity="multi_posting_rule",
        action="create",
        outcome="manual_revalidation_required",
    )
    assert multi_create_impact["details"]["source_metadata"]["rule_type"] == "combine"
    updated_multi_rule_payload = dict(multi_rule_payload)
    updated_multi_rule_payload["combined_label"] = "TTSHDR-KTPHDR"
    multi_rule_update = client.put(
        f"/admin/multi-posting-rules/{multi_rule_id}",
        headers=pc_headers,
        json=updated_multi_rule_payload,
    )
    assert multi_rule_update.status_code == 200
    _assert_config_impact(
        multi_rule_update.json(),
        changed_entity="multi_posting_rule",
        action="update",
        outcome="manual_revalidation_required",
    )
    multi_rule_delete = client.delete(
        f"/admin/multi-posting-rules/{multi_rule_id}",
        headers=pc_headers,
    )
    assert multi_rule_delete.status_code == 200
    _assert_config_impact(
        multi_rule_delete.json(),
        changed_entity="multi_posting_rule",
        action="delete",
        outcome="manual_revalidation_required",
    )

    posting_group = client.post(
        "/admin/posting-groups",
        headers=pc_headers,
        json={"group_code": "DR-GROUP", "posting_code": "TTSHRespi", "programme_code": "DR"},
    )
    assert posting_group.status_code == 200
    posting_group_body = posting_group.json()
    posting_group_id = posting_group_body["id"]
    _assert_config_impact(
        posting_group_body,
        changed_entity="posting_group",
        action="create",
    )
    posting_group_update = client.put(
        f"/admin/posting-groups/{posting_group_id}",
        headers=pc_headers,
        json={"group_code": "DR-GROUP-UPDATED", "posting_code": "TTSHRespi(MICU)", "programme_code": "DR"},
    )
    assert posting_group_update.status_code == 200
    _assert_config_impact(
        posting_group_update.json(),
        changed_entity="posting_group",
        action="update",
    )
    posting_group_delete = client.delete(
        f"/admin/posting-groups/{posting_group_id}",
        headers=pc_headers,
    )
    assert posting_group_delete.status_code == 200
    _assert_config_impact(
        posting_group_delete.json(),
        changed_entity="posting_group",
        action="delete",
    )

    weekend_exception = client.post(
        "/admin/weekend-exceptions",
        headers=master_headers,
        json={"programme_code": "DR", "posting_code": "TTSHDR", "day_type": "sat"},
    )
    assert weekend_exception.status_code == 200
    weekend_exception_body = weekend_exception.json()
    weekend_exception_id = weekend_exception_body["id"]
    _assert_config_impact(
        weekend_exception_body,
        changed_entity="weekend_exception",
        action="create",
    )
    weekend_exception_update = client.put(
        f"/admin/weekend-exceptions/{weekend_exception_id}",
        headers=master_headers,
        json={"programme_code": "DR", "posting_code": "TTSHDR", "day_type": "sun"},
    )
    assert weekend_exception_update.status_code == 200
    _assert_config_impact(
        weekend_exception_update.json(),
        changed_entity="weekend_exception",
        action="update",
    )
    weekend_exception_delete = client.delete(
        f"/admin/weekend-exceptions/{weekend_exception_id}",
        headers=master_headers,
    )
    assert weekend_exception_delete.status_code == 200
    _assert_config_impact(
        weekend_exception_delete.json(),
        changed_entity="weekend_exception",
        action="delete",
    )

    global_session_type = client.post(
        "/admin/global-session-types",
        headers=master_headers,
        json={"name": "Smoke Global Teaching [1h]", "duration_hours": "1.0", "is_active": True},
    )
    assert global_session_type.status_code == 200
    global_session_type_body = global_session_type.json()
    global_session_type_id = global_session_type_body["id"]
    _assert_config_impact(
        global_session_type_body,
        changed_entity="global_session_type",
        action="create",
    )
    global_session_type_update = client.put(
        f"/admin/global-session-types/{global_session_type_id}",
        headers=master_headers,
        json={"duration_hours": "1.5", "is_active": False},
    )
    assert global_session_type_update.status_code == 200
    _assert_config_impact(
        global_session_type_update.json(),
        changed_entity="global_session_type",
        action="update",
    )
    global_session_type_delete = client.delete(
        f"/admin/global-session-types/{global_session_type_id}",
        headers=master_headers,
    )
    assert global_session_type_delete.status_code == 200
    _assert_config_impact(
        global_session_type_delete.json(),
        changed_entity="global_session_type",
        action="delete",
    )

    assert [row["action"] for row in session.audit_logs] == [
        "admin.config.reporting_period.create",
        "admin.config.reporting_period.update",
        "admin.config.reporting_period.deactivate",
        "admin.config.reporting_period.activate",
        "admin.config.reporting_period.delete",
        "admin.config.public_holiday.create",
        "admin.config.public_holiday.update",
        "admin.config.public_holiday.delete",
        "admin.config.programme.update",
        "admin.config.loa_type.create",
        "admin.config.loa_type.update",
        "admin.config.loa_type.delete",
        "admin.config.multi_posting_rule.create",
        "admin.config.multi_posting_rule.update",
        "admin.config.multi_posting_rule.delete",
        "admin.config.posting_group.create",
        "admin.config.posting_group.update",
        "admin.config.posting_group.delete",
        "admin.config.weekend_exception.create",
        "admin.config.weekend_exception.update",
        "admin.config.weekend_exception.delete",
        "admin.config.global_session_type.create",
        "admin.config.global_session_type.update",
        "admin.config.global_session_type.delete",
    ]
    assert {row["actor_name"] for row in session.audit_logs} == {"Unknown actor"}
    assert session.audit_logs[0]["entity_type"] == "reporting_period"
    assert session.audit_logs[0]["entity_id"] == reporting_period_id
    assert _audit_json(session.audit_logs[0], "before_json") is None
    assert _audit_json(session.audit_logs[0], "after_json")["label"] == "Jul - Dec 2026"
    assert _audit_json(session.audit_logs[1], "before_json")["status"] == "active"
    assert _audit_json(session.audit_logs[1], "after_json")["status"] == "inactive"
    assert _audit_json(session.audit_logs[2], "metadata_json")["mutation"] == "deactivate"
    assert _audit_json(session.audit_logs[3], "metadata_json")["mutation"] == "activate"
    assert _audit_json(session.audit_logs[4], "before_json")["label"] == "H2 2026"
    assert _audit_json(session.audit_logs[4], "after_json") is None
    assert _audit_json(session.audit_logs[8], "metadata_json")["programme_code"] == "DR"
    assert _audit_json(session.audit_logs[12], "metadata_json")["rule_type"] == "combine"
    assert _audit_json(session.audit_logs[15], "metadata_json")["posting_code"] == "TTSHRespi"
    assert _audit_json(session.audit_logs[18], "metadata_json")["posting_code"] == "TTSHDR"
    for audit_row in session.audit_logs:
        metadata = _audit_json(audit_row, "metadata_json")
        assert metadata["data_revalidation"]["changed_entity"] == metadata["config_entity"]
        assert metadata["data_revalidation"]["trigger_source"] in {
            "admin_config_change",
            "pc_config_change",
        }


@pytest.mark.parametrize(
    ("rule_payload", "warning_posting_codes"),
    [
        (
            {
                "programme_code": "DR",
                "posting_code_1": "TTSHDR",
                "posting_code_2": "KTPHDR",
                "rule_type": "combine",
                "combined_label": "TTSHDR-KTPHDR",
                "main_posting_code": None,
                "exclusion_code": None,
            },
            ["KTPHDR", "TTSHDR"],
        ),
        (
            {
                "programme_code": "DR",
                "posting_code_1": "TTSHDR",
                "posting_code_2": "KTPHDR",
                "rule_type": "half_month",
                "combined_label": None,
                "main_posting_code": None,
                "exclusion_code": None,
            },
            ["KTPHDR", "TTSHDR"],
        ),
        (
            {
                "programme_code": "DR",
                "posting_code_1": "TTSHDR",
                "posting_code_2": "KTPHDR",
                "rule_type": "main_posting",
                "combined_label": None,
                "main_posting_code": "TTSHDR",
                "exclusion_code": None,
            },
            ["KTPHDR", "TTSHDR"],
        ),
        (
            {
                "programme_code": "DR",
                "posting_code_1": "TTSHDR",
                "posting_code_2": None,
                "rule_type": "main_posting",
                "combined_label": None,
                "main_posting_code": "TTSHDR",
                "exclusion_code": "KTPHDR",
            },
            ["TTSHDR", "KTPHDR"],
        ),
    ],
)
def test_multi_posting_rule_mutation_enriches_matching_unmatched_warning_summary(
    rule_payload: dict,
    warning_posting_codes: list[str],
) -> None:
    session = FakeMutationSession()
    issue_id = _add_warning_issue(
        session,
        warning_type="unmatched_multi_posting",
        programme_code="DR",
        status="reappeared",
        source_payload={
            "type": "unmatched_multi_posting",
            "posting_codes": warning_posting_codes,
        },
        message="No matching multi-posting rule found",
    )
    _add_warning_issue(
        session,
        warning_type="unmatched_multi_posting",
        programme_code="GRM",
        source_payload={"posting_codes": warning_posting_codes},
    )
    _add_warning_issue(
        session,
        warning_type="unmatched_multi_posting",
        programme_code="DR",
        status="resolved",
        source_payload={"posting_codes": warning_posting_codes},
    )
    client = _build_client_with_session(session)

    response = client.post(
        "/admin/multi-posting-rules",
        headers=_admin_headers("DR"),
        json=rule_payload,
    )

    assert response.status_code == 200
    impact = _assert_config_impact(
        response.json(),
        changed_entity="multi_posting_rule",
        action="create",
        outcome="manual_revalidation_required",
    )
    assert impact["warnings_remaining"] == 1
    assert impact["affected_warning_ids"] == [issue_id]
    assert impact["affected_warning_count"] == 1
    assert impact["affected_warning_issue_ids"] == [issue_id]
    assert impact["affected_warning_summaries"][0]["warning_type"] == "unmatched_multi_posting"
    assert impact["affected_warning_count_is_partial"] is False
    assert impact["affected_warning_details_are_partial"] is False
    assert impact["warning_candidate_limit"] == data_revalidation_service._WARNING_QUERY_LIMIT
    assert impact["warning_candidate_limit_reached"] is False
    assert impact["enrichment_version"] == "3H-E4"
    assert "source-cell preview/apply" in " ".join(impact["next_actions"])
    details = impact["details"]
    assert details["affected_warning_count"] == 1
    assert details["affected_warning_issue_ids"] == [issue_id]
    assert details["affected_warning_summaries"][0]["warning_type"] == "unmatched_multi_posting"
    assert details["affected_warning_summaries"][0]["posting_codes"] == warning_posting_codes
    assert details["affected_scope"]["programme_code"] == "DR"
    assert details["affected_scope"]["rule_type"] == rule_payload["rule_type"]
    assert "source-cell preview/apply" in " ".join(details["next_actions"])
    assert session.warning_issues[0]["status"] == "reappeared"


def test_loa_type_create_enriches_unknown_loa_warning_without_auto_resolve() -> None:
    session = FakeMutationSession()
    issue_id = _add_warning_issue(
        session,
        warning_type="unknown_loa_type",
        programme_code="DR",
        source_payload={"loa_type": "Study Leave"},
        message="Unknown LOA type: Study Leave",
    )
    _add_warning_issue(
        session,
        warning_type="unknown_loa_type",
        programme_code="DR",
        status="dismissed",
        source_payload={"loa_type": "Study Leave"},
    )
    client = _build_client_with_session(session)

    response = client.post(
        "/admin/loa-types",
        headers=_master_admin_headers("DR"),
        json={"code": "Study Leave", "description": "Academic study leave"},
    )

    assert response.status_code == 200
    impact = _assert_config_impact(
        response.json(),
        changed_entity="loa_type",
        action="create",
        outcome="manual_revalidation_required",
    )
    assert impact["warnings_remaining"] == 1
    assert impact["affected_warning_ids"] == [issue_id]
    assert impact["details"]["affected_warning_count"] == 1
    assert impact["details"]["affected_warning_summaries"][0]["loa_type"] == "Study Leave"
    assert "manual" in " ".join(impact["details"]["next_actions"]).lower()
    assert session.warning_issues[0]["status"] == "unresolved"


def test_programme_update_includes_parser_warning_summary_for_programme_scope() -> None:
    session = FakeMutationSession()
    issue_id = _add_warning_issue(
        session,
        warning_type="unmatched_multi_posting",
        programme_code="DR",
        source_payload={"posting_codes": ["TTSHDR", "KTPHDR"]},
    )
    _add_warning_issue(
        session,
        warning_type="unknown_loa_type",
        programme_code="GRM",
        source_payload={"loa_type": "Study Leave"},
    )
    client = _build_client_with_session(session)

    response = client.put(
        "/admin/programmes/DR",
        headers=_master_admin_headers("DR"),
        json={"r_year_required": False, "rdb_alias": "Diagnostic Radiology"},
    )

    assert response.status_code == 200
    impact = _assert_config_impact(
        response.json(),
        changed_entity="programme",
        action="update",
        outcome="manual_revalidation_required",
    )
    assert impact["affected_warning_ids"] == [issue_id]
    assert impact["details"]["affected_warning_count"] == 1
    assert impact["details"]["affected_scope"]["programme_code"] == "DR"
    assert "no source data was reprocessed" in impact["summary"].lower()


def test_posting_group_enrichment_is_compliance_only_and_does_not_claim_unmatched_fix() -> None:
    session = FakeMutationSession()
    _add_warning_issue(
        session,
        warning_type="unmatched_multi_posting",
        programme_code="DR",
        source_payload={"posting_codes": ["TTSHRespi", "TTSHRespi(MICU)"]},
    )
    session.resident_postings.extend(
        [
            {"programme_code": "DR", "posting_code": "TTSHRespi"},
            {"programme_code": "DR", "posting_code": "TTSHRespi"},
            {"programme_code": "GRM", "posting_code": "TTSHRespi"},
        ]
    )
    client = _build_client_with_session(session)

    response = client.post(
        "/admin/posting-groups",
        headers=_admin_headers("DR"),
        json={"group_code": "DR-GROUP", "posting_code": "TTSHRespi", "programme_code": "DR"},
    )

    assert response.status_code == 200
    impact = _assert_config_impact(
        response.json(),
        changed_entity="posting_group",
        action="create",
    )
    assert impact["affected_warning_ids"] == []
    assert impact["details"]["affected_warning_count"] == 0
    assert impact["details"]["affected_entity_counts"]["resident_postings"] == 2
    assert impact["details"]["affected_scope"]["posting_code"] == "TTSHRespi"
    assert "compliance aggregation" in " ".join(impact["details"]["next_actions"]).lower()


def test_config_enrichment_reports_lightweight_counts_for_workflow_tables() -> None:
    session = FakeMutationSession()
    period_id = session.reporting_periods[0]["id"]
    session.reporting_period_dependencies[period_id] = {
        "upload_logs": 2,
        "resident_postings": 3,
        "teaching_targets": 4,
        "form_f1_records": 5,
    }
    session.teaching_events.append(
        {
            "id": str(uuid4()),
            "teaching_name": "Weekend Teaching",
            "posting_code": "TTSHDR",
            "event_date": date(2026, 8, 9),
        }
    )
    session.attendance_records.append({"event_id": session.teaching_events[0]["id"]})
    session.attendance_records.append({"event_id": session.teaching_events[-1]["id"]})
    client = _build_client_with_session(session)

    holiday = client.post(
        "/admin/public-holidays",
        headers=_master_admin_headers("DR"),
        json={"holiday_date": "2026-08-09", "name": "National Day"},
    )
    global_update = client.put(
        f"/admin/global-session-types/{session.global_session_types[0]['id']}",
        headers=_master_admin_headers("DR"),
        json={"is_active": False},
    )
    weekend = client.post(
        "/admin/weekend-exceptions",
        headers=_master_admin_headers("DR"),
        json={
            "programme_code": "DR",
            "posting_code": "TTSHDR",
            "day_type": "sat",
            "session_name_pattern": "Weekend",
        },
    )
    reporting_period = client.put(
        f"/admin/reporting-periods/{period_id}",
        headers=_master_admin_headers("DR"),
        json={"label": "H1 2026 Updated"},
    )

    assert holiday.status_code == 200
    holiday_counts = holiday.json()["data_revalidation"]["details"]["affected_entity_counts"]
    assert holiday_counts["teaching_events"] == 1

    assert global_update.status_code == 200
    global_counts = global_update.json()["data_revalidation"]["details"]["affected_entity_counts"]
    assert global_counts["teaching_events"] == 1
    assert global_counts["attendance_records"] == 1

    assert weekend.status_code == 200
    weekend_counts = weekend.json()["data_revalidation"]["details"]["affected_entity_counts"]
    assert weekend_counts["teaching_events"] == 1
    assert weekend_counts["attendance_records"] == 1

    assert reporting_period.status_code == 200
    period_counts = reporting_period.json()["data_revalidation"]["details"]["affected_entity_counts"]
    assert period_counts == {
        "upload_logs": 2,
        "resident_postings": 3,
        "teaching_targets": 4,
        "form_f1_records": 5,
    }


def test_programme_scope_enforced_for_scoped_mutations() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/multi-posting-rules",
        headers=_admin_headers("DR"),
        json={
            "programme_code": "GRM",
            "posting_code_1": "TTSHDR",
            "posting_code_2": "KTPHDR",
            "rule_type": "combine",
            "combined_label": "TTSHDR & KTPHDR",
            "main_posting_code": None,
            "exclusion_code": None,
        },
    )
    assert response.status_code == 403


def test_null_scope_cannot_mutate_scoped_resources() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/posting-groups",
        headers=_admin_headers(scope=None),
        json={
            "group_code": "DR-GROUP",
            "posting_code": "TTSHRespi",
            "programme_code": "DR",
        },
    )
    assert response.status_code == 403


def test_master_admin_can_mutate_posting_groups_without_programme_scope() -> None:
    client = _build_client_with_session(FakeMutationSession())
    created = client.post(
        "/admin/posting-groups",
        headers=_master_admin_headers(scope=None),
        json={
            "group_code": "DR-GROUP",
            "posting_code": "TTSHRespi",
            "programme_code": "DR",
        },
    )
    assert created.status_code == 200
    posting_group_id = created.json()["id"]

    updated = client.put(
        f"/admin/posting-groups/{posting_group_id}",
        headers=_master_admin_headers(scope=None),
        json={
            "group_code": "DR-GROUP-UPDATED",
            "posting_code": "TTSHRespi(MICU)",
            "programme_code": "DR",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["group_code"] == "DR-GROUP-UPDATED"
    assert updated.json()["posting_code"] == "TTSHRespi(MICU)"

    deleted = client.delete(
        f"/admin/posting-groups/{posting_group_id}",
        headers=_master_admin_headers(scope=None),
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_null_scope_cannot_mutate_reporting_periods() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/reporting-periods",
        headers=_admin_headers(scope=None),
        json={
            "label": "Jul - Dec 2026",
            "start_date": "2026-07-01",
            "end_date": "2026-12-31",
            "activate_on": "2026-07-01",
        },
    )
    assert response.status_code == 403


def test_reporting_period_create_update_delete_crud() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    created = client.post(
        "/admin/reporting-periods",
        headers=_master_admin_headers("DR"),
        json={
            "label": "Jul - Dec 2026",
            "start_date": "2026-07-01",
            "end_date": "2026-12-31",
            "activate_on": "2026-07-01",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["label"] == "Jul - Dec 2026"
    assert body["status"] == "active"
    assert body["activate_on"] == "2026-07-01"
    assert body["deactivate_on"] is None

    duplicate = client.post(
        "/admin/reporting-periods",
        headers=_master_admin_headers("DR"),
        json={
            "label": "Jul - Dec 2026",
            "start_date": "2026-07-01",
            "end_date": "2026-12-31",
            "activate_on": "2026-07-01",
        },
    )
    assert duplicate.status_code == 409

    updated = client.put(
        f"/admin/reporting-periods/{body['id']}",
        headers=_master_admin_headers("DR"),
        json={
            "label": "H2 2026",
            "status": "inactive",
            "activate_on": "2026-07-01",
            "deactivate_on": "2026-12-31",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["label"] == "H2 2026"
    assert updated.json()["status"] == "inactive"
    assert updated.json()["activate_on"] == "2026-07-01"
    assert updated.json()["deactivate_on"] == "2026-12-31"

    stale_status = client.put(
        f"/admin/reporting-periods/{body['id']}",
        headers=_master_admin_headers("DR"),
        json={"status": "closed"},
    )
    assert stale_status.status_code == 422

    invalid_transition_order = client.put(
        f"/admin/reporting-periods/{body['id']}",
        headers=_master_admin_headers("DR"),
        json={"activate_on": "2026-12-31", "deactivate_on": "2026-07-01"},
    )
    assert invalid_transition_order.status_code == 422

    deleted = client.delete(
        f"/admin/reporting-periods/{body['id']}",
        headers=_master_admin_headers("DR"),
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_reporting_period_delete_returns_dependency_counts() -> None:
    session = FakeMutationSession()
    period_id = session.reporting_periods[0]["id"]
    session.reporting_period_dependencies[period_id] = {
        "upload_logs": 2,
        "resident_postings": 3,
        "teaching_targets": 1,
        "academic_month_boundaries": 4,
    }
    client = _build_client_with_session(session)

    response = client.delete(
        f"/admin/reporting-periods/{period_id}",
        headers=_master_admin_headers("DR"),
    )

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "Reporting period is in use and cannot be deleted"
    assert body["metadata"]["dependencies"] == {
        "upload_logs": 2,
        "resident_postings": 3,
        "teaching_targets": 1,
        "academic_month_boundaries": 4,
    }


def test_public_holiday_upsert_is_idempotent() -> None:
    client = _build_client_with_session(FakeMutationSession())
    payload = {
        "holiday_date": "2026-08-09",
        "name": "National Day",
        "day_of_week": "Sunday",
        "year": 2026,
    }
    first = client.post("/admin/public-holidays", headers=_master_admin_headers("DR"), json=payload)
    assert first.status_code == 200
    first_id = first.json()["id"]

    payload["name"] = "National Day Updated"
    second = client.post("/admin/public-holidays", headers=_master_admin_headers("DR"), json=payload)
    assert second.status_code == 200
    assert second.json()["id"] == first_id
    assert second.json()["name"] == "National Day Updated"
    assert second.json()["day_of_week"] == "Sunday"
    assert second.json()["year"] == 2026


def test_public_holiday_update_recomputes_day_and_year() -> None:
    client = _build_client_with_session(FakeMutationSession())
    created = client.post(
        "/admin/public-holidays",
        headers=_master_admin_headers("DR"),
        json={
            "holiday_date": "2026-08-09",
            "name": "National Day",
            "day_of_week": "Wrong",
            "year": 1999,
        },
    )
    assert created.status_code == 200
    holiday_id = created.json()["id"]
    assert created.json()["day_of_week"] == "Sunday"
    assert created.json()["year"] == 2026

    updated = client.put(
        f"/admin/public-holidays/{holiday_id}",
        headers=_master_admin_headers("DR"),
        json={
            "holiday_date": "2026-08-10",
            "name": "National Day observed",
            "day_of_week": "Wrong",
            "year": 1999,
        },
    )

    assert updated.status_code == 200
    body = updated.json()
    assert body["name"] == "National Day observed"
    assert body["holiday_date"] == "2026-08-10"
    assert body["day_of_week"] == "Monday"
    assert body["year"] == 2026


def test_public_holiday_empty_name_rejected() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/public-holidays",
        headers=_master_admin_headers("DR"),
        json={"holiday_date": "2026-08-09", "name": "   "},
    )

    assert response.status_code == 422


def test_public_holiday_delete_succeeds() -> None:
    client = _build_client_with_session(FakeMutationSession())
    created = client.post(
        "/admin/public-holidays",
        headers=_master_admin_headers("DR"),
        json={"holiday_date": "2026-08-09", "name": "National Day"},
    )
    assert created.status_code == 200

    deleted = client.delete(
        f"/admin/public-holidays/{created.json()['id']}",
        headers=_master_admin_headers("DR"),
    )

    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_null_scope_cannot_mutate_public_holidays() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/public-holidays",
        headers=_admin_headers(scope=None),
        json={"holiday_date": "2026-08-09", "name": "National Day"},
    )
    assert response.status_code == 403


def test_null_scope_cannot_mutate_loa_types() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    loa_id = str(uuid4())

    create_response = client.post(
        "/admin/loa-types",
        headers=_admin_headers(scope=None),
        json={"code": "Study Leave", "description": "Academic study leave"},
    )
    update_response = client.put(
        f"/admin/loa-types/{loa_id}",
        headers=_admin_headers(scope=None),
        json={"code": "Study Leave", "description": "Academic study leave"},
    )
    delete_response = client.delete(
        f"/admin/loa-types/{loa_id}",
        headers=_admin_headers(scope=None),
    )

    assert create_response.status_code == 403
    assert update_response.status_code == 403
    assert delete_response.status_code == 403


def test_programme_pc_cannot_mutate_global_config_endpoints() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    period_id = session.reporting_periods[0]["id"]
    global_type_id = session.global_session_types[0]["id"]

    attempts = [
        client.post(
            "/admin/reporting-periods",
            headers=_admin_headers("DR"),
            json={"label": "Jul - Dec 2026", "start_date": "2026-07-01", "end_date": "2026-12-31"},
        ),
        client.post(
            "/admin/public-holidays",
            headers=_admin_headers("DR"),
            json={"holiday_date": "2026-08-09", "name": "National Day"},
        ),
        client.put(
            "/admin/programmes/DR",
            headers=_admin_headers("DR"),
            json={"r_year_required": False},
        ),
        client.post(
            "/admin/loa-types",
            headers=_admin_headers("DR"),
            json={"code": "Study Leave", "description": "Academic study leave"},
        ),
        client.post(
            "/admin/weekend-exceptions",
            headers=_admin_headers("DR"),
            json={"programme_code": "DR", "posting_code": "TTSHDR", "day_type": "sat"},
        ),
        client.put(
            f"/admin/global-session-types/{global_type_id}",
            headers=_admin_headers("DR"),
            json={"is_active": False},
        ),
        client.delete(f"/admin/reporting-periods/{period_id}", headers=_admin_headers("DR")),
    ]

    assert [response.status_code for response in attempts] == [403, 403, 403, 403, 403, 403, 403]


def test_programme_pc_cannot_mutate_reporting_periods() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    period_id = session.reporting_periods[0]["id"]

    attempts = [
        client.post(
            "/admin/reporting-periods",
            headers=_admin_headers("DR"),
            json={"label": "Jul - Dec 2026", "start_date": "2026-07-01", "end_date": "2026-12-31"},
        ),
        client.put(
            f"/admin/reporting-periods/{period_id}",
            headers=_admin_headers("DR"),
            json={"label": "Renamed"},
        ),
        client.put(
            f"/admin/reporting-periods/{period_id}/activate",
            headers=_admin_headers("DR"),
        ),
        client.put(
            f"/admin/reporting-periods/{period_id}/deactivate",
            headers=_admin_headers("DR"),
        ),
        client.delete(f"/admin/reporting-periods/{period_id}", headers=_admin_headers("DR")),
    ]

    assert [response.status_code for response in attempts] == [403, 403, 403, 403, 403]


def test_weekend_exception_crud_allows_nullable_clears_and_both_day_type() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    session_type_id = next(iter(session.session_type_ids))

    created = client.post(
        "/admin/weekend-exceptions",
        headers=_master_admin_headers("DR"),
        json={
            "programme_code": "DR",
            "posting_code": "TTSHDR",
            "day_type": "both",
            "start_time_min": "08:30:00",
            "end_time_max": "10:30:00",
            "session_type_id": session_type_id,
            "session_name_pattern": "Weekend Teaching",
            "mutates_to_session_type_id": session_type_id,
            "adjusted_duration_hours": "1.0",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["day_type"] == "both"
    assert body["session_name_pattern"] == "Weekend Teaching"

    updated = client.put(
        f"/admin/weekend-exceptions/{body['id']}",
        headers=_master_admin_headers("DR"),
        json={
            "programme_code": None,
            "posting_code": None,
            "day_type": "sun",
            "start_time_min": None,
            "end_time_max": None,
            "session_type_id": None,
            "session_name_pattern": "   ",
            "mutates_to_session_type_id": None,
            "adjusted_duration_hours": None,
        },
    )
    assert updated.status_code == 200
    cleared = updated.json()
    assert cleared["programme_code"] is None
    assert cleared["posting_code"] is None
    assert cleared["session_name_pattern"] is None
    assert cleared["session_type_id"] is None
    assert cleared["mutates_to_session_type_id"] is None
    assert cleared["adjusted_duration_hours"] is None

    deleted = client.delete(
        f"/admin/weekend-exceptions/{body['id']}",
        headers=_master_admin_headers("DR"),
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert session.weekend_exceptions == []


def test_weekend_exception_validation_rejects_bad_references_and_mutation_shape() -> None:
    client = _build_client_with_session(FakeMutationSession())

    bad_day = client.post(
        "/admin/weekend-exceptions",
        headers=_master_admin_headers("DR"),
        json={"programme_code": "DR", "posting_code": "TTSHDR", "day_type": "fri"},
    )
    bad_programme = client.post(
        "/admin/weekend-exceptions",
        headers=_master_admin_headers("DR"),
        json={"programme_code": "NOPE", "posting_code": "TTSHDR", "day_type": "sat"},
    )
    bad_posting = client.post(
        "/admin/weekend-exceptions",
        headers=_master_admin_headers("DR"),
        json={"programme_code": "DR", "posting_code": "UNKNOWN", "day_type": "sat"},
    )
    missing_mutation_target = client.post(
        "/admin/weekend-exceptions",
        headers=_master_admin_headers("DR"),
        json={
            "programme_code": "DR",
            "posting_code": "TTSHDR",
            "day_type": "sat",
            "adjusted_duration_hours": "1.0",
        },
    )

    assert bad_day.status_code == 422
    assert bad_programme.status_code == 422
    assert bad_posting.status_code == 422
    assert missing_mutation_target.status_code == 422


def test_global_session_type_crud_duplicate_delete_guard_and_inactive_update() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)

    created = client.post(
        "/admin/global-session-types",
        headers=_master_admin_headers("DR"),
        json={"name": "Smoke Global Teaching [1h]", "duration_hours": "1.0", "is_active": True},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["name"] == "Smoke Global Teaching [1h]"
    assert body["is_active"] is True

    duplicate = client.post(
        "/admin/global-session-types",
        headers=_master_admin_headers("DR"),
        json={"name": "Smoke Global Teaching [1h]", "duration_hours": "1.0", "is_active": True},
    )
    assert duplicate.status_code == 409

    updated = client.put(
        f"/admin/global-session-types/{body['id']}",
        headers=_master_admin_headers("DR"),
        json={"duration_hours": "1.5", "is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["duration_hours"] == "1.5"
    assert updated.json()["is_active"] is False

    session.teaching_events.append({"teaching_name": "Smoke Global Teaching [1h]"})
    blocked = client.delete(
        f"/admin/global-session-types/{body['id']}",
        headers=_master_admin_headers("DR"),
    )
    assert blocked.status_code == 409

    session.teaching_events = [
        row for row in session.teaching_events if row["teaching_name"] != "Smoke Global Teaching [1h]"
    ]
    deleted = client.delete(
        f"/admin/global-session-types/{body['id']}",
        headers=_master_admin_headers("DR"),
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_global_session_type_rejects_blank_name_and_invalid_duration() -> None:
    client = _build_client_with_session(FakeMutationSession())

    blank_name = client.post(
        "/admin/global-session-types",
        headers=_master_admin_headers("DR"),
        json={"name": "   ", "duration_hours": "1.0", "is_active": True},
    )
    invalid_duration = client.post(
        "/admin/global-session-types",
        headers=_master_admin_headers("DR"),
        json={"name": "Smoke Global Teaching [1h]", "duration_hours": "0", "is_active": True},
    )

    assert blank_name.status_code == 422
    assert invalid_duration.status_code == 422


def test_programme_update_respects_scope_and_editable_fields() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.put(
        "/admin/programmes/DR",
        headers=_master_admin_headers("DR"),
        json={
            "r_year_required": False,
            "is_subspecialty": True,
            "rdb_alias": "Diagnostic Radiology Alias",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "DR"
    assert body["name"] == "Diagnostic Radiology"
    assert body["classification"] == "senior"
    assert body["ay_date_category"] == "non_im_subspec"
    assert body["r_year_required"] is False
    assert body["is_subspecialty"] is True
    assert body["rdb_alias"] == "Diagnostic Radiology Alias"


def test_programme_update_can_clear_rdb_alias_and_persist_false_booleans() -> None:
    client = _build_client_with_session(FakeMutationSession())
    set_response = client.put(
        "/admin/programmes/DR",
        headers=_master_admin_headers("DR"),
        json={
            "r_year_required": False,
            "is_subspecialty": True,
            "rdb_alias": "Diagnostic Radiology Alias",
        },
    )
    assert set_response.status_code == 200
    assert set_response.json()["rdb_alias"] == "Diagnostic Radiology Alias"

    clear_response = client.put(
        "/admin/programmes/DR",
        headers=_master_admin_headers("DR"),
        json={
            "r_year_required": False,
            "is_subspecialty": False,
            "rdb_alias": None,
        },
    )
    assert clear_response.status_code == 200
    body = clear_response.json()
    assert body["rdb_alias"] is None
    assert body["r_year_required"] is False
    assert body["is_subspecialty"] is False

    set_again = client.put(
        "/admin/programmes/DR",
        headers=_master_admin_headers("DR"),
        json={"rdb_alias": "Alias to trim"},
    )
    assert set_again.status_code == 200

    whitespace_clear = client.put(
        "/admin/programmes/DR",
        headers=_master_admin_headers("DR"),
        json={"rdb_alias": "   "},
    )
    assert whitespace_clear.status_code == 200
    assert whitespace_clear.json()["rdb_alias"] is None


def test_programme_update_out_of_scope_rejected() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.put(
        "/admin/programmes/GRM",
        headers=_admin_headers("DR"),
        json={"r_year_required": True},
    )

    assert response.status_code == 403


def test_programme_locked_fields_return_422() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.put(
        "/admin/programmes/DR",
        headers=_master_admin_headers("DR"),
        json={"code": "X", "r_year_required": False},
    )
    assert response.status_code == 422


def test_reporting_period_update_rejects_empty_required_values() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    period_id = session.reporting_periods[0]["id"]

    label_response = client.put(
        f"/admin/reporting-periods/{period_id}",
        headers=_master_admin_headers("DR"),
        json={"label": "   "},
    )
    assert label_response.status_code == 422

    status_response = client.put(
        f"/admin/reporting-periods/{period_id}",
        headers=_master_admin_headers("DR"),
        json={"status": "paused"},
    )
    assert status_response.status_code == 422


def test_reporting_period_update_with_revalidation_handles_global_warning_scope() -> None:
    session = StrictWarningCandidateSqlSession()
    period_id = session.reporting_periods[0]["id"]
    issue_id = _add_warning_issue(
        session,
        warning_type="unmatched_multi_posting",
        programme_code="DR",
        reporting_period_id=period_id,
        source_payload={"posting_codes": ["A", "B"]},
    )
    _add_warning_issue(
        session,
        warning_type="unmatched_multi_posting",
        programme_code="GRM",
        reporting_period_id=str(uuid4()),
        source_payload={"posting_codes": ["C", "D"]},
    )
    client = _build_client_with_session(session)

    response = client.put(
        f"/admin/reporting-periods/{period_id}",
        headers=_master_admin_headers("DR"),
        json={
            "label": "Jul 25 - Dec 25",
            "start_date": "2025-07-08",
            "end_date": "2026-01-05",
            "status": "inactive",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "inactive"
    impact = _assert_config_impact(
        body,
        changed_entity="reporting_period",
        action="update",
        outcome="future_compliance_impact",
    )
    assert impact["affected_warning_ids"] == [issue_id]
    assert impact["warnings_remaining"] == 1


def test_loa_type_crud_and_duplicate_conflict() -> None:
    client = _build_client_with_session(FakeMutationSession())

    created = client.post(
        "/admin/loa-types",
        headers=_master_admin_headers("DR"),
        json={"code": "Study Leave", "description": "Academic study leave"},
    )
    duplicate = client.post(
        "/admin/loa-types",
        headers=_master_admin_headers("DR"),
        json={"code": "Study Leave", "description": "Duplicate"},
    )

    assert created.status_code == 200
    assert duplicate.status_code == 409

    loa_id = created.json()["id"]
    updated = client.put(
        f"/admin/loa-types/{loa_id}",
        headers=_master_admin_headers("DR"),
        json={"code": "Exam Leave", "description": ""},
    )
    deleted = client.delete(f"/admin/loa-types/{loa_id}", headers=_master_admin_headers("DR"))

    assert updated.status_code == 200
    assert updated.json()["code"] == "Exam Leave"
    assert updated.json()["description"] is None
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_loa_type_empty_code_rejected() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/loa-types",
        headers=_master_admin_headers("DR"),
        json={"code": "   ", "description": "Blank code should fail"},
    )

    assert response.status_code == 422


def test_multi_posting_rule_rejects_invalid_rule_type() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/multi-posting-rules",
        headers=_admin_headers("DR"),
        json={
            "programme_code": "DR",
            "posting_code_1": "TTSHDR",
            "posting_code_2": "KTPHDR",
            "rule_type": "unsupported",
            "combined_label": "x",
            "main_posting_code": None,
            "exclusion_code": None,
        },
    )
    assert response.status_code == 422


def test_multi_posting_rule_duplicate_and_reverse_conflict_returns_409() -> None:
    client = _build_client_with_session(FakeMutationSession())
    payload = {
        "programme_code": "DR",
        "posting_code_1": "TTSHDR",
        "posting_code_2": "KTPHDR",
        "rule_type": "combine",
        "combined_label": "TTSHDR & KTPHDR",
        "main_posting_code": None,
        "exclusion_code": None,
    }
    created = client.post("/admin/multi-posting-rules", headers=_admin_headers("DR"), json=payload)
    assert created.status_code == 200

    duplicate = client.post("/admin/multi-posting-rules", headers=_admin_headers("DR"), json=payload)
    assert duplicate.status_code == 409

    reverse_payload = dict(payload)
    reverse_payload["posting_code_1"] = payload["posting_code_2"]
    reverse_payload["posting_code_2"] = payload["posting_code_1"]
    reverse = client.post("/admin/multi-posting-rules", headers=_admin_headers("DR"), json=reverse_payload)
    assert reverse.status_code == 409


def test_master_admin_can_create_multi_posting_rule_without_scope() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/multi-posting-rules",
        headers=_master_admin_headers(scope=None),
        json={
            "programme_code": "DR",
            "posting_code_1": "TTSHDR",
            "posting_code_2": "KTPHDR",
            "rule_type": "combine",
            "combined_label": "TTSHDR-KTPHDR",
            "main_posting_code": None,
            "exclusion_code": None,
        },
    )

    assert response.status_code == 200
    assert response.json()["combined_label"] == "TTSHDR-KTPHDR"


def test_multi_posting_main_posting_allows_explicit_second_posting() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/multi-posting-rules",
        headers=_admin_headers("DR"),
        json={
            "programme_code": "DR",
            "posting_code_1": "TTSHDR",
            "posting_code_2": "KTPHDR",
            "rule_type": "main_posting",
            "combined_label": None,
            "main_posting_code": "TTSHDR",
            "exclusion_code": "KTPHDR",
        },
    )

    assert response.status_code == 200
    assert response.json()["posting_code_2"] == "KTPHDR"


def test_multi_posting_combine_rejects_main_posting_outputs() -> None:
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/multi-posting-rules",
        headers=_admin_headers("DR"),
        json={
            "programme_code": "DR",
            "posting_code_1": "TTSHDR",
            "posting_code_2": "KTPHDR",
            "rule_type": "combine",
            "combined_label": "TTSHDR-KTPHDR",
            "main_posting_code": "TTSHDR",
            "exclusion_code": None,
        },
    )

    assert response.status_code == 422


def test_multi_posting_rule_update_scope_safety() -> None:
    client = _build_client_with_session(FakeMutationSession())
    created = client.post(
        "/admin/multi-posting-rules",
        headers=_admin_headers("DR"),
        json={
            "programme_code": "DR",
            "posting_code_1": "TTSHDR",
            "posting_code_2": "KTPHDR",
            "rule_type": "combine",
            "combined_label": "TTSHDR & KTPHDR",
            "main_posting_code": None,
            "exclusion_code": None,
        },
    )
    assert created.status_code == 200
    rule_id = created.json()["id"]

    response = client.put(
        f"/admin/multi-posting-rules/{rule_id}",
        headers=_admin_headers("DR"),
        json={
            "programme_code": "GRM",
            "posting_code_1": "TTSHDR",
            "posting_code_2": "KTPHDR",
            "rule_type": "combine",
            "combined_label": "TTSHDR & KTPHDR",
            "main_posting_code": None,
            "exclusion_code": None,
        },
    )
    assert response.status_code == 403


def test_posting_groups_uniqueness_conflict_returns_409() -> None:
    client = _build_client_with_session(FakeMutationSession())
    payload = {
        "group_code": "DR-GROUP",
        "posting_code": "TTSHRespi",
        "programme_code": "DR",
    }
    first = client.post("/admin/posting-groups", headers=_admin_headers("DR"), json=payload)
    assert first.status_code == 200
    second = client.post("/admin/posting-groups", headers=_admin_headers("DR"), json=payload)
    assert second.status_code == 409


def test_global_session_type_delete_returns_409_when_referenced() -> None:
    session = FakeMutationSession()
    client = _build_client_with_session(session)
    target_id = session.global_session_types[0]["id"]
    response = client.delete(
        f"/admin/global-session-types/{target_id}",
        headers=_master_admin_headers("DR"),
    )
    assert response.status_code == 409


def test_upload_logs_mutation_endpoints_not_allowed() -> None:
    client = _build_client_with_session(FakeMutationSession())
    headers = _admin_headers("DR")
    assert client.post("/admin/upload-logs", headers=headers, json={}).status_code in {404, 405}
    assert client.put("/admin/upload-logs/abc", headers=headers, json={}).status_code in {404, 405}
    assert client.delete("/admin/upload-logs/abc", headers=headers).status_code in {404, 405}


def test_form_f1_records_mutation_endpoints_not_allowed() -> None:
    client = _build_client_with_session(FakeMutationSession())
    headers = _admin_headers("DR")
    assert client.post("/admin/form-f1-records", headers=headers, json={}).status_code in {404, 405}
    assert client.put("/admin/form-f1-records/abc", headers=headers, json={}).status_code in {404, 405}
    assert client.delete("/admin/form-f1-records/abc", headers=headers).status_code in {404, 405}


def test_cache_invalidation_called_after_successful_mutation(monkeypatch) -> None:
    calls: list[str] = []

    def _spy(prefix: str) -> int:
        calls.append(prefix)
        return 0

    monkeypatch.setattr("app.services.admin_config.cache.invalidate_prefix", _spy)
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/loa-types",
        headers=_master_admin_headers("DR"),
        json={"code": "Study Leave", "description": "Academic study leave"},
    )
    assert response.status_code == 200
    assert calls


def test_config_crud_triggers_scoped_cache_invalidation_domains(monkeypatch) -> None:
    calls: list[tuple[set[str], dict]] = []

    def _spy(domains, **scope):  # noqa: ANN001
        calls.append((set(domains), scope))
        return []

    monkeypatch.setattr("app.services.cache_invalidation.invalidate_cache", _spy)
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/loa-types",
        headers=_master_admin_headers("DR"),
        json={"code": "Study Leave", "description": "Academic study leave"},
    )

    assert response.status_code == 200
    assert calls
    domains, scope = calls[-1]
    assert {"config", "parsed_data", "upload_warnings"} <= domains
    assert scope["entity_type"] == "loa_type"


def test_mutation_responses_are_not_cached(monkeypatch) -> None:
    calls: list[str] = []

    def _forbid_cache_set(*args, **kwargs):  # noqa: ANN002, ANN003
        calls.append("set")
        raise AssertionError("cache.set should not be used for mutation responses")

    monkeypatch.setattr("app.services.admin_config.cache.set", _forbid_cache_set)
    client = _build_client_with_session(FakeMutationSession())
    response = client.post(
        "/admin/loa-types",
        headers=_master_admin_headers("DR"),
        json={"code": "Family Care Leave", "description": "Family care leave"},
    )
    assert response.status_code == 200
    assert calls == []
