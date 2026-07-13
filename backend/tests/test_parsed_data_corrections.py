from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.middleware.errors import install_error_handlers
from app.routers import admin
from app.schemas.data_revalidation import (
    DataRevalidationAction,
    DataRevalidationChangedEntity,
    DataRevalidationImpactSummary,
    DataRevalidationOutcome,
    DataRevalidationScope,
    DataRevalidationTriggerSource,
)
from app.services import data_revalidation_service
from app.services.parser_common import ParserResult


class _FakeResult:
    def __init__(self, rows: list[dict] | None = None, scalar: object | None = None, rowcount: int = 0) -> None:
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
            raise AssertionError("Expected at most one row")
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> object:
        return self._scalar

    def scalar_one_or_none(self) -> object | None:
        return self._scalar


class FakeParsedDataCorrectionSession:
    def __init__(self) -> None:
        self.now = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
        self.after_now = datetime(2026, 5, 18, 9, 5, tzinfo=timezone.utc)
        self.period_id = str(uuid4())
        self.upload_id = str(uuid4())
        self.resident_id = str(uuid4())
        self.other_resident_id = str(uuid4())
        self.posting_ids = [str(uuid4()), str(uuid4())]
        self.target_id = str(uuid4())
        self.session_type_id = str(uuid4())
        self.form_f1_id = str(uuid4())
        self.boundary_id = str(uuid4())
        self.new_posting_ids: list[str] = []
        self.commits = 0
        self.audit_logs: list[dict] = []
        self.programme_codes = {"GERI", "DR"}
        self.upload_logs = [
            {
                "id": self.upload_id,
                "reporting_period_id": self.period_id,
                "summary": {
                    "raw_multi_posting_fragments": [
                        {
                            "mcr": "M11111A",
                            "resident_name": "Geri Resident",
                            "programme_code": "GERI",
                            "r_year": "ALL",
                            "sheet_name": "Phase 1 & 2",
                            "row_number": 42,
                            "cell_ref": "J42",
                            "month_label": "Jan-26",
                            "source_column_header": "Jan-26",
                            "source_cell_text": "TTSHGerMed (from 01-Jan-2026 to 31-Jan-2026)",
                        }
                    ]
                },
            }
        ]
        self.catalogue_rows: list[dict] = [
            {
                "id": str(uuid4()),
                "keyword": "Journal Club",
                "session_type_id": self.session_type_id,
                "posting_code": "TTSHGerMed",
                "programme_code": "GERI",
                "r_year": "ALL",
                "reporting_period_id": self.period_id,
                "duration_hours": Decimal("1.00"),
                "is_tracked": True,
                "created_at": self.now,
                "updated_at": self.now,
            }
        ]
        self.session_types = {
            self.session_type_id: {
                "id": self.session_type_id,
                "name": "Department Teaching [1h]",
                "duration_hours": Decimal("1.00"),
            }
        }
        self.residents = [
            {
                "id": self.resident_id,
                "employee_code": "E001",
                "name": "Geri Resident",
                "mcr": "M11111A",
                "classification": "Senior Resident",
                "programme_code": "GERI",
                "r_year": "R3",
                "reg_type": "Full",
                "base_institution": "TTSH",
                "email": "geri@example.test",
                "phone": None,
                "status": "active",
                "employer_tag": None,
                "created_at": self.now,
                "updated_at": self.now,
            },
            {
                "id": self.other_resident_id,
                "employee_code": "E002",
                "name": "DR Resident",
                "mcr": "M22222B",
                "classification": "Junior Resident",
                "programme_code": "DR",
                "r_year": "R2",
                "reg_type": "Full",
                "base_institution": "KTPH",
                "email": "dr@example.test",
                "phone": None,
                "status": "active",
                "employer_tag": None,
                "created_at": self.now,
                "updated_at": self.now,
            },
        ]
        self.resident_postings = [
            self._posting_row(self.posting_ids[0], "TTSHGerMed", date(2026, 1, 1), date(2026, 1, 15), "AM"),
            self._posting_row(self.posting_ids[1], "TTSHGerMed", date(2026, 1, 16), date(2026, 1, 31), "PM"),
        ]
        self.teaching_targets = [
            {
                "id": self.target_id,
                "reporting_period_id": self.period_id,
                "programme_code": "GERI",
                "r_year": "ALL",
                "posting_code": "TTSHGerMed",
                "session_type_id": self.session_type_id,
                "monthly_target": 4,
                "is_tracked": True,
                "is_reallocatable": True,
                "tag": "A1",
                "details_of_training": "Journal Club",
                "created_at": self.now,
                "updated_at": self.now,
            }
        ]
        self.form_f1_records = [
            {
                "id": self.form_f1_id,
                "reporting_period_id": self.period_id,
                "mcr": "M11111A",
                "month_label": "Jan-26",
                "status_raw": "Active",
                "is_active": True,
                "promotion_date": None,
                "upload_id": self.upload_id,
                "created_at": self.now,
                "updated_at": self.now,
            }
        ]
        self.academic_month_boundaries = [
            {
                "id": self.boundary_id,
                "academic_year_label": "AY2026",
                "ay_date_category": "im_subspec",
                "month_label": "Jan-26",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 1, 31),
                "upload_id": self.upload_id,
                "created_at": self.now,
                "updated_at": self.now,
            }
        ]

    def _posting_row(self, row_id: str, posting_code: str, start: date, end: date, day_part: str | None) -> dict:
        return {
            "id": row_id,
            "resident_id": self.resident_id,
            "posting_code": posting_code,
            "reporting_period_id": self.period_id,
            "start_date": start,
            "end_date": end,
            "day_part": day_part,
            "month_label": "Jan-26",
            "r_year": "ALL",
            "status": "active",
            "loa_type": None,
            "loa_start_date": None,
            "loa_end_date": None,
            "refresher_training_type": None,
            "refresher_training_start": None,
            "refresher_training_end": None,
            "active_months_weight": Decimal("0.5"),
            "working_days_in_month": 11,
            "created_at": self.now,
            "updated_at": self.now,
        }

    def _resident_for_mcr(self, mcr: str) -> dict | None:
        return next((row for row in self.residents if row["mcr"].upper() == mcr.upper()), None)

    def _with_resident_context(self, posting: dict) -> dict:
        resident = next(row for row in self.residents if row["id"] == posting["resident_id"])
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

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None

    async def execute(self, statement, params=None):  # noqa: C901, PLR0912, PLR0915
        sql = str(statement)
        payload = dict(params or {})

        if "INSERT INTO audit_logs" in sql:
            row = {"id": payload["id"], "created_at": self.after_now, **payload}
            self.audit_logs.append(row)
            return _FakeResult(rows=[row])

        if "/* parsed_data_correction:resident_snapshot */" in sql:
            row = next((item for item in self.residents if item["id"] == payload["id"]), None)
            if row is None or not self._scope_allows(row["programme_code"], payload):
                return _FakeResult(rows=[])
            return _FakeResult(rows=[deepcopy(row)])

        if "/* parsed_data_validation:resident_mcr_unique */" in sql:
            duplicate = any(
                row["id"] != payload["id"] and row["mcr"].upper() == str(payload["mcr"]).upper()
                for row in self.residents
            )
            return _FakeResult(scalar=1 if duplicate else None)

        if "/* parsed_data_validation:external_mcr_unique */" in sql:
            return _FakeResult(scalar=None)

        if "/* parsed_data_validation:employee_code_unique */" in sql:
            duplicate = any(
                row["id"] != payload["id"] and row["employee_code"] == payload["employee_code"]
                for row in self.residents
            )
            return _FakeResult(scalar=1 if duplicate else None)

        if "/* parsed_data_validation:programme_exists */" in sql:
            return _FakeResult(scalar=1 if payload["programme_code"] in self.programme_codes else None)

        if "UPDATE residents SET" in sql:
            row = next(item for item in self.residents if item["id"] == payload["id"])
            for key in (
                "employee_code",
                "name",
                "mcr",
                "programme_code",
                "r_year",
                "classification",
                "reg_type",
                "base_institution",
                "email",
                "phone",
                "status",
                "employer_tag",
            ):
                if key in payload:
                    row[key] = payload[key]
            row["updated_at"] = self.after_now
            return _FakeResult(rowcount=1)

        if "/* parsed_data_correction:resident_posting_snapshot */" in sql:
            rows = [
                self._with_resident_context(row)
                for row in self.resident_postings
                if row["id"] == payload["id"]
            ]
            rows = [row for row in rows if self._scope_allows(row["programme_code"], payload)]
            return _FakeResult(rows=deepcopy(rows))

        if "/* parsed_data_correction:resident_posting_source_rows */" in sql:
            ids = {str(value) for value in payload["ids"]}
            rows = [
                self._with_resident_context(row)
                for row in self.resident_postings
                if row["id"] in ids
            ]
            rows = [row for row in rows if self._scope_allows(row["programme_code"], payload)]
            return _FakeResult(rows=deepcopy(rows))

        if "/* parsed_data_validation:resident_exists */" in sql:
            row = next((item for item in self.residents if item["id"] == payload["resident_id"]), None)
            if row is None or not self._scope_allows(row["programme_code"], payload):
                return _FakeResult(rows=[])
            return _FakeResult(rows=[{"id": row["id"], "programme_code": row["programme_code"], "mcr": row["mcr"], "name": row["name"]}])

        if "/* parsed_data_validation:posting_code_exists */" in sql:
            return _FakeResult(scalar=1)

        if "/* parsed_data_validation:reporting_period_exists */" in sql:
            return _FakeResult(scalar=1)

        if "/* parsed_data_validation:resident_posting_replacement_unique */" in sql:
            affected_ids = {str(value) for value in payload["affected_ids"]}
            duplicate = any(
                row["id"] not in affected_ids
                and str(row["resident_id"]) == str(payload["resident_id"])
                and str(row["reporting_period_id"]) == str(payload["reporting_period_id"])
                and row["start_date"] == payload["start_date"]
                and row.get("day_part") == payload.get("day_part")
                for row in self.resident_postings
            )
            return _FakeResult(scalar=1 if duplicate else None)

        if "/* parsed_data_validation:resident_posting_update_unique */" in sql:
            duplicate = any(
                row["id"] != payload["id"]
                and str(row["resident_id"]) == str(payload["resident_id"])
                and str(row["reporting_period_id"]) == str(payload["reporting_period_id"])
                and row["start_date"] == payload["start_date"]
                and row.get("day_part") == payload.get("day_part")
                for row in self.resident_postings
            )
            return _FakeResult(scalar=1 if duplicate else None)

        if "UPDATE resident_postings SET" in sql:
            row = next(item for item in self.resident_postings if item["id"] == payload["id"])
            for key in (
                "posting_code",
                "start_date",
                "end_date",
                "day_part",
                "month_label",
                "r_year",
                "status",
                "loa_type",
                "loa_start_date",
                "loa_end_date",
                "refresher_training_type",
                "refresher_training_start",
                "refresher_training_end",
                "active_months_weight",
                "working_days_in_month",
            ):
                if key in payload:
                    row[key] = payload[key]
            row["updated_at"] = self.after_now
            return _FakeResult(rowcount=1)

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

        if "/* parsed_data_correction:source_upload_log */" in sql:
            row = next((item for item in self.upload_logs if item["id"] == payload["upload_log_id"]), None)
            return _FakeResult(rows=[deepcopy(row)] if row else [])

        if "/* parsed_data_correction:teaching_target_snapshot */" in sql:
            rows = [row for row in self.teaching_targets if row["id"] == payload["id"]]
            rows = [row for row in rows if self._scope_allows(row["programme_code"], payload)]
            for row in rows:
                session_type = self.session_types[row["session_type_id"]]
                row["session_type_name"] = session_type["name"]
                row["duration_hours"] = session_type["duration_hours"]
            return _FakeResult(rows=deepcopy(rows))

        if "/* parsed_data_validation:session_type_duration */" in sql:
            session_type = self.session_types.get(payload["session_type_id"])
            return _FakeResult(rows=[deepcopy(session_type)] if session_type else [])

        if "/* parsed_data_validation:catalogue_keyword_conflict */" in sql:
            return _FakeResult(scalar=None)

        if "UPDATE teaching_targets SET" in sql:
            row = next(item for item in self.teaching_targets if item["id"] == payload["id"])
            for key in (
                "reporting_period_id",
                "programme_code",
                "r_year",
                "posting_code",
                "session_type_id",
                "monthly_target",
                "is_tracked",
                "is_reallocatable",
                "tag",
                "details_of_training",
            ):
                if key in payload:
                    row[key] = payload[key]
            row["updated_at"] = self.after_now
            return _FakeResult(rowcount=1)

        if "DELETE FROM teaching_name_catalogue" in sql:
            target = next(row for row in self.teaching_targets if row["id"] == payload["target_id"])
            self.catalogue_rows = [
                row
                for row in self.catalogue_rows
                if not (
                    row["reporting_period_id"] == target["reporting_period_id"]
                    and row["programme_code"] == target["programme_code"]
                    and row["posting_code"] == target["posting_code"]
                    and row["r_year"] == target["r_year"]
                    and row["session_type_id"] == target["session_type_id"]
                )
            ]
            return _FakeResult(rowcount=1)

        if "INSERT INTO teaching_name_catalogue" in sql:
            self.catalogue_rows.append(
                {
                    "id": str(uuid4()),
                    "keyword": payload["keyword"],
                    "session_type_id": payload["session_type_id"],
                    "posting_code": payload["posting_code"],
                    "programme_code": payload["programme_code"],
                    "r_year": payload["r_year"],
                    "reporting_period_id": payload["reporting_period_id"],
                    "duration_hours": payload["duration_hours"],
                    "is_tracked": payload["is_tracked"],
                    "created_at": self.after_now,
                    "updated_at": self.after_now,
                }
            )
            return _FakeResult(rowcount=1)

        if "/* parsed_data_correction:form_f1_record_snapshot */" in sql:
            rows = []
            for record in self.form_f1_records:
                if record["id"] != payload["id"]:
                    continue
                resident = self._resident_for_mcr(record["mcr"])
                row = {
                    **record,
                    "programme_code": resident["programme_code"] if resident else None,
                    "resident_name": resident["name"] if resident else None,
                }
                if self._scope_allows(row["programme_code"], payload):
                    rows.append(row)
            return _FakeResult(rows=deepcopy(rows))

        if "UPDATE form_f1_records SET" in sql:
            row = next(item for item in self.form_f1_records if item["id"] == payload["id"])
            for key in ("status_raw", "is_active", "promotion_date"):
                if key in payload:
                    row[key] = payload[key]
            row["updated_at"] = self.after_now
            return _FakeResult(rowcount=1)

        if "/* parsed_data_correction:academic_month_boundary_snapshot */" in sql:
            rows = [row for row in self.academic_month_boundaries if row["id"] == payload["id"]]
            return _FakeResult(rows=deepcopy(rows))

        if "/* parsed_data_validation:academic_month_boundary_unique */" in sql:
            duplicate = any(
                row["id"] != payload["id"]
                and row["academic_year_label"] == payload["academic_year_label"]
                and row["ay_date_category"] == payload["ay_date_category"]
                and row["month_label"] == payload["month_label"]
                for row in self.academic_month_boundaries
            )
            return _FakeResult(scalar=1 if duplicate else None)

        if "/* parsed_data_validation:academic_month_boundary_overlap */" in sql:
            return _FakeResult(scalar=None)

        if "UPDATE academic_month_boundaries SET" in sql:
            row = next(item for item in self.academic_month_boundaries if item["id"] == payload["id"])
            for key in ("academic_year_label", "ay_date_category", "month_label", "start_date", "end_date"):
                if key in payload:
                    row[key] = payload[key]
            row["updated_at"] = self.after_now
            return _FakeResult(rowcount=1)

        if "/* parsed_data_correction:corrections_history */" in sql:
            def _metadata_source(row: dict) -> dict:
                metadata = _audit_json(row, "metadata_json")
                return metadata.get("source") if isinstance(metadata, dict) and isinstance(metadata.get("source"), dict) else {}

            def _metadata_programme(row: dict) -> str | None:
                metadata = _audit_json(row, "metadata_json")
                if not isinstance(metadata, dict):
                    return None
                return metadata.get("programme_code")

            scope = {
                value
                for key, value in payload.items()
                if key.startswith("scope_programme_code_")
            }
            rows = [
                row
                for row in self.audit_logs
                if row["action"].startswith("admin.parsed_data.")
                and (payload.get("entity_type") is None or row["entity_type"] == payload["entity_type"])
                and (payload.get("entity_id") is None or str(row["entity_id"]) == str(payload["entity_id"]))
                and (not scope or _metadata_programme(row) in scope)
                and (
                    payload.get("upload_log_id") is None
                    or str(_metadata_source(row).get("upload_log_id")) == str(payload["upload_log_id"])
                )
                and (
                    payload.get("sheet_name") is None
                    or _metadata_source(row).get("sheet_name") == payload["sheet_name"]
                )
                and (
                    payload.get("row_number") is None
                    or str(_metadata_source(row).get("row_number")) == str(payload["row_number"])
                )
                and (
                    payload.get("cell_ref") is None
                    or _metadata_source(row).get("cell_ref") == payload["cell_ref"]
                )
            ]
            return _FakeResult(rows=deepcopy(rows), scalar=len(rows))

        raise AssertionError(f"Unhandled SQL in correction fake: {sql}\nparams={payload}")


class FakeRdbUploadCorrectionWarningSession:
    def __init__(self) -> None:
        self.upload_logs: list[dict] = []
        self.audit_logs: list[dict] = []
        self.commits = 0
        self.corrected_reupload_count = 3

    async def execute(self, statement, params=None):
        sql = str(statement)
        payload = dict(params or {})
        if "/* upload:reporting_period_status */" in sql:
            return _FakeResult(rows=[{"status": "active"}])
        if "INSERT INTO rate_limit_buckets" in sql and "RETURNING request_count" in sql:
            return _FakeResult(rows=[{"request_count": 1}])
        if "/* parsed_data_correction:corrected_resident_posting_reupload_count */" in sql:
            return _FakeResult(scalar=self.corrected_reupload_count)
        if "INSERT INTO upload_logs" in sql:
            row = {"id": payload["id"], **payload}
            self.upload_logs.append(row)
            return _FakeResult(rows=[row])
        if "INSERT INTO audit_logs" in sql:
            row = {"id": payload["id"], **payload}
            self.audit_logs.append(row)
            return _FakeResult(rows=[row])
        raise AssertionError(f"Unhandled SQL in upload fake: {sql}\nparams={payload}")

    async def commit(self):
        self.commits += 1


def _build_client_with_session(session) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def _db_override():
        yield session

    app.dependency_overrides[admin.get_db_session] = _db_override
    return TestClient(app)


def _make_valid_xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "placeholder"
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()
    return payload.getvalue()


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


def _audit_json(row: dict, key: str):
    value = row[key]
    if value is None or isinstance(value, dict):
        return value
    return json.loads(value)


def _impact(body: dict) -> dict:
    impact = body["data_revalidation"]
    assert impact["trigger_source"] == "live_data_correction"
    assert impact["rows_examined"] == 0
    assert impact["rows_updated"] == 0
    assert impact["warnings_created"] == 0
    assert impact["warnings_updated"] == 0
    assert impact["warnings_resolved"] == 0
    assert impact["warnings_remaining"] == 0
    return impact


def _posting_unique_key(row: dict) -> tuple[str, str, str, str | None]:
    return (
        str(row["resident_id"]),
        str(row["reporting_period_id"]),
        str(row["start_date"]),
        row.get("day_part"),
    )


def test_resident_correction_updates_live_row_and_writes_audit_log() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)

    response = client.patch(
        f"/admin/parsed-data/residents/{session.resident_id}",
        headers=_headers(),
        json={
            "correction_reason": "RDB row had a typo",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"name": "Geriatrics Resident", "mcr": "M11111Z"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["item"]["name"] == "Geriatrics Resident"
    assert body["updated_fields"] == ["mcr", "name"]
    impact = _impact(body)
    assert impact["outcome"] == "future_compliance_impact"
    assert impact["changed_entity"] == "resident"
    assert impact["action"] == "update"
    assert impact["scope"] == "single_row"
    assert impact["details"]["changed_fields"] == ["mcr", "name"]
    assert session.residents[0]["mcr"] == "M11111Z"
    assert session.commits == 1
    assert len(session.audit_logs) == 1
    audit_row = session.audit_logs[0]
    assert audit_row["action"] == "admin.parsed_data.resident.update"
    assert audit_row["entity_type"] == "resident"
    assert _audit_json(audit_row, "before_json")["mcr"] == "M11111A"
    assert _audit_json(audit_row, "after_json")["mcr"] == "M11111Z"
    metadata = _audit_json(audit_row, "metadata_json")
    assert metadata["correction_reason"] == "RDB row had a typo"
    assert metadata["programme_code"] == "GERI"
    assert metadata["source_page"] == "parsed_data"
    assert metadata["data_revalidation"]["changed_entity"] == "resident"
    assert metadata["data_revalidation"]["details"]["changed_fields"] == ["mcr", "name"]


def test_correction_uses_fallback_actor_and_requires_reason_and_allowlisted_fields() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)

    missing_actor = client.patch(
        f"/admin/parsed-data/residents/{session.resident_id}",
        headers=_headers(),
        json={"correction_reason": "typo", "changes": {"name": "New Name"}},
    )
    forbidden_field = client.patch(
        f"/admin/parsed-data/residents/{session.resident_id}",
        headers=_headers(),
        json={"correction_reason": "typo", "changes": {"source_cell_text": "never edit raw cells"}},
    )
    missing_reason = client.patch(
        f"/admin/parsed-data/residents/{session.resident_id}",
        headers=_headers(),
        json={"changes": {"name": "New Name"}},
    )

    assert missing_actor.status_code == 200
    assert forbidden_field.status_code == 422
    assert missing_reason.status_code == 422
    assert len(session.audit_logs) == 1
    assert session.audit_logs[0]["actor_name"] == "Unknown actor"


def test_identity_fields_are_rejected_for_patch_corrections() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)
    headers = _headers()

    resident_posting_resident = client.patch(
        f"/admin/parsed-data/resident-postings/{session.posting_ids[0]}",
        headers=headers,
        json={
            "correction_reason": "locked field",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"resident_id": session.other_resident_id},
        },
    )
    resident_posting_period = client.patch(
        f"/admin/parsed-data/resident-postings/{session.posting_ids[0]}",
        headers=headers,
        json={
            "correction_reason": "locked field",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"reporting_period_id": str(uuid4())},
        },
    )
    teaching_target_identity = client.patch(
        f"/admin/parsed-data/teaching-targets/{session.target_id}",
        headers=headers,
        json={
            "correction_reason": "locked field",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {
                "reporting_period_id": str(uuid4()),
                "programme_code": "DR",
                "r_year": "R2",
                "posting_code": "KTPHDiagRd",
                "session_type_id": str(uuid4()),
            },
        },
    )
    form_f1_identity = client.patch(
        f"/admin/parsed-data/form-f1-records/{session.form_f1_id}",
        headers=headers,
        json={
            "correction_reason": "locked field",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {
                "reporting_period_id": str(uuid4()),
                "mcr": "M22222B",
                "month_label": "Feb-26",
            },
        },
    )

    assert resident_posting_resident.status_code == 422
    assert resident_posting_period.status_code == 422
    assert teaching_target_identity.status_code == 422
    assert form_f1_identity.status_code == 422
    assert session.audit_logs == []


def test_resident_programme_change_requires_existing_programme_in_admin_scope() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)

    missing_programme = client.patch(
        f"/admin/parsed-data/residents/{session.resident_id}",
        headers=_headers(),
        json={
            "correction_reason": "correct programme",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"programme_code": "NOPE"},
        },
    )
    out_of_scope = client.patch(
        f"/admin/parsed-data/residents/{session.resident_id}",
        headers=_headers(scope="GERI"),
        json={
            "correction_reason": "correct programme",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"programme_code": "DR"},
        },
    )
    master_allowed = client.patch(
        f"/admin/parsed-data/residents/{session.resident_id}",
        headers=_headers(scope=None, master=True),
        json={
            "correction_reason": "correct programme",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"programme_code": "DR"},
        },
    )

    assert missing_programme.status_code == 422
    assert out_of_scope.status_code == 403
    assert master_allowed.status_code == 200
    assert session.residents[0]["programme_code"] == "DR"


def test_correction_rejects_stale_last_seen_timestamp() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)

    response = client.patch(
        f"/admin/parsed-data/residents/{session.resident_id}",
        headers=_headers(),
        json={
            "correction_reason": "typo",
            "last_seen_updated_at": datetime(2026, 5, 18, 8, 59, tzinfo=timezone.utc).isoformat(),
            "changes": {"name": "Stale Edit"},
        },
    )

    assert response.status_code == 409
    assert session.residents[0]["name"] == "Geri Resident"
    assert session.audit_logs == []


def test_resident_posting_patch_uses_documented_status_values() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)

    allowed = client.patch(
        f"/admin/parsed-data/resident-postings/{session.posting_ids[0]}",
        headers=_headers(),
        json={
            "correction_reason": "Resident continues working during LOA",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"status": "loa_working"},
        },
    )
    blocked = client.patch(
        f"/admin/parsed-data/resident-postings/{session.posting_ids[1]}",
        headers=_headers(),
        json={
            "correction_reason": "Undocumented status should not be accepted",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"status": "inactive"},
        },
    )

    assert allowed.status_code == 200
    impact = _impact(allowed.json())
    assert impact["changed_entity"] == "resident_posting"
    assert impact["scope"] == "resident_month"
    assert impact["warnings_created"] == 0
    assert session.resident_postings[0]["status"] == "loa_working"
    assert blocked.status_code == 422
    assert session.resident_postings[1]["status"] == "active"
    assert len(session.audit_logs) == 1


def test_resident_posting_patch_rejects_unique_conflict_before_update() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)

    conflict = client.patch(
        f"/admin/parsed-data/resident-postings/{session.posting_ids[1]}",
        headers=_headers(),
        json={
            "correction_reason": "Duplicate phase",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"start_date": "2026-01-01", "day_part": "AM"},
        },
    )

    assert conflict.status_code == 409
    assert session.resident_postings[1]["start_date"] == date(2026, 1, 16)
    assert session.resident_postings[1]["day_part"] == "PM"
    assert session.audit_logs == []


def test_resident_posting_patch_rejects_null_day_part_unique_conflict_before_update() -> None:
    session = FakeParsedDataCorrectionSession()
    existing_id = str(uuid4())
    session.resident_postings.append(
        session._posting_row(existing_id, "TTSHGerMed", date(2026, 2, 1), date(2026, 2, 28), None)
    )
    client = _build_client_with_session(session)

    conflict = client.patch(
        f"/admin/parsed-data/resident-postings/{session.posting_ids[0]}",
        headers=_headers(),
        json={
            "correction_reason": "Duplicate whole-month phase",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"start_date": "2026-02-01", "end_date": "2026-02-28", "day_part": None},
        },
    )

    assert conflict.status_code == 409
    assert session.resident_postings[0]["start_date"] == date(2026, 1, 1)
    assert session.resident_postings[0]["day_part"] == "AM"
    assert {row["id"] for row in session.resident_postings} == {*session.posting_ids, existing_id}
    assert session.audit_logs == []


def _source_cell_replace_payload(session: FakeParsedDataCorrectionSession) -> dict:
    return {
        "correction_reason": "Split source cell should be a whole-month posting",
        "source": {
            "upload_log_id": session.upload_id,
            "sheet_name": "Phase 1 & 2",
            "row_number": 42,
            "cell_ref": "J42",
            "source_column_header": "Jan-26",
            "source_cell_text": "TTSHGerMed (from 01-Jan-2026 to 31-Jan-2026)",
        },
        "affected_resident_posting_ids": session.posting_ids,
        "last_seen_rows": [
            {"id": session.posting_ids[0], "updated_at": session.now.isoformat()},
            {"id": session.posting_ids[1], "updated_at": session.now.isoformat()},
        ],
        "replacement_rows": [
            {
                "resident_id": session.resident_id,
                "posting_code": "TTSHGerMed",
                "reporting_period_id": session.period_id,
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "day_part": None,
                "month_label": "Jan-26",
                "r_year": "ALL",
                "status": "active",
                "active_months_weight": "1.0",
                "working_days_in_month": 22,
            }
        ],
    }


def test_source_cell_replace_requires_concurrency_token_for_every_affected_row() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)
    payload = _source_cell_replace_payload(session)
    without_tokens = dict(payload)
    without_tokens.pop("last_seen_rows")
    missing_one_token = dict(payload)
    missing_one_token["last_seen_rows"] = payload["last_seen_rows"][:1]

    no_tokens_response = client.post(
        "/admin/parsed-data/resident-postings/source-cell-replace",
        headers=_headers(),
        json=without_tokens,
    )
    missing_token_response = client.post(
        "/admin/parsed-data/resident-postings/source-cell-replace",
        headers=_headers(),
        json=missing_one_token,
    )

    assert no_tokens_response.status_code == 422
    assert missing_token_response.status_code == 422
    assert {row["id"] for row in session.resident_postings} == set(session.posting_ids)
    assert session.audit_logs == []


def test_source_cell_replace_rejects_stale_affected_row_before_delete() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)
    payload = _source_cell_replace_payload(session)
    payload["last_seen_rows"][1]["updated_at"] = datetime(
        2026, 5, 18, 8, 59, tzinfo=timezone.utc
    ).isoformat()

    response = client.post(
        "/admin/parsed-data/resident-postings/source-cell-replace",
        headers=_headers(),
        json=payload,
    )

    assert response.status_code == 409
    assert {row["id"] for row in session.resident_postings} == set(session.posting_ids)
    assert session.audit_logs == []


def test_source_cell_replace_rejects_unverified_source_metadata() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)
    payload = _source_cell_replace_payload(session)
    payload["source"]["cell_ref"] = "Z99"

    response = client.post(
        "/admin/parsed-data/resident-postings/source-cell-replace",
        headers=_headers(),
        json=payload,
    )

    assert response.status_code == 422
    assert {row["id"] for row in session.resident_postings} == set(session.posting_ids)
    assert session.audit_logs == []


def test_source_cell_replace_rejects_mismatched_source_cell_text_before_delete() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)
    payload = _source_cell_replace_payload(session)
    payload["source"]["source_cell_text"] = "TTSHGerMed edited text"

    response = client.post(
        "/admin/parsed-data/resident-postings/source-cell-replace",
        headers=_headers(),
        json=payload,
    )

    assert response.status_code == 422
    assert {row["id"] for row in session.resident_postings} == set(session.posting_ids)
    assert session.new_posting_ids == []
    assert session.audit_logs == []


def test_source_cell_replace_rejects_duplicate_replacement_rows_before_delete() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)
    payload = _source_cell_replace_payload(session)
    payload["replacement_rows"].append(dict(payload["replacement_rows"][0]))

    response = client.post(
        "/admin/parsed-data/resident-postings/source-cell-replace",
        headers=_headers(),
        json=payload,
    )

    assert response.status_code == 409
    assert {row["id"] for row in session.resident_postings} == set(session.posting_ids)
    assert session.new_posting_ids == []
    assert session.audit_logs == []


def test_source_cell_replace_rejects_conflict_with_unaffected_row_before_delete() -> None:
    session = FakeParsedDataCorrectionSession()
    unaffected_id = str(uuid4())
    session.resident_postings.append(
        session._posting_row(
            unaffected_id,
            "TTSHGerMed",
            date(2026, 1, 1),
            date(2026, 1, 31),
            None,
        )
    )
    client = _build_client_with_session(session)
    payload = _source_cell_replace_payload(session)
    before_keys = {_posting_unique_key(row) for row in session.resident_postings}

    response = client.post(
        "/admin/parsed-data/resident-postings/source-cell-replace",
        headers=_headers(),
        json=payload,
    )

    assert response.status_code == 409
    assert {row["id"] for row in session.resident_postings} == {*session.posting_ids, unaffected_id}
    assert {_posting_unique_key(row) for row in session.resident_postings} == before_keys
    assert session.new_posting_ids == []
    assert session.audit_logs == []


def test_resident_posting_source_cell_replace_rewrites_rows_and_audits_original_group() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)

    response = client.post(
        "/admin/parsed-data/resident-postings/source-cell-replace",
        headers=_headers(),
        json=_source_cell_replace_payload(session),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["before_rows"]) == 2
    assert len(body["after_rows"]) == 1
    assert body["after_rows"][0]["start_date"] == "2026-01-01"
    impact = _impact(body)
    assert impact["outcome"] == "targeted_revalidation"
    assert impact["changed_entity"] == "resident_posting_source_fragment"
    assert impact["action"] == "replace"
    assert impact["details"]["backend_handler_available"] is True
    assert impact["details"]["business_tables_mutated"] is True
    assert impact["details"]["affected_row_count"] == 2
    assert impact["details"]["replacement_row_count"] == 1
    assert impact["details"]["source_metadata"]["cell_ref"] == "J42"
    assert {row["id"] for row in session.resident_postings} == set(session.new_posting_ids)
    audit_row = session.audit_logs[0]
    assert audit_row["action"] == "admin.parsed_data.resident_posting.source_cell_replace"
    assert audit_row["entity_type"] == "resident_posting_source_cell"
    assert len(_audit_json(audit_row, "before_json")["before_rows"]) == 2
    assert len(_audit_json(audit_row, "after_json")["after_rows"]) == 1
    metadata = _audit_json(audit_row, "metadata_json")
    assert metadata["source_page"] == "parsed_data"
    assert metadata["source_metadata_verified"] is True
    assert metadata["source"]["cell_ref"] == "J42"
    assert metadata["source"]["source_cell_text"] == "TTSHGerMed (from 01-Jan-2026 to 31-Jan-2026)"
    assert metadata["verified_source_metadata"]["cell_ref"] == "J42"
    assert metadata["data_revalidation"]["changed_entity"] == "resident_posting_source_fragment"
    assert metadata["data_revalidation"]["details"]["replacement_row_count"] == 1


def test_source_cell_replace_uses_documented_status_values() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)
    allowed_payload = _source_cell_replace_payload(session)
    allowed_payload["replacement_rows"][0]["status"] = "loa_working"

    allowed = client.post(
        "/admin/parsed-data/resident-postings/source-cell-replace",
        headers=_headers(),
        json=allowed_payload,
    )

    assert allowed.status_code == 200
    assert session.resident_postings[0]["status"] == "loa_working"

    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)
    blocked_payload = _source_cell_replace_payload(session)
    blocked_payload["replacement_rows"][0]["status"] = "inactive"

    blocked = client.post(
        "/admin/parsed-data/resident-postings/source-cell-replace",
        headers=_headers(),
        json=blocked_payload,
    )

    assert blocked.status_code == 422
    assert {row["id"] for row in session.resident_postings} == set(session.posting_ids)
    assert session.audit_logs == []


def test_teaching_target_correction_regenerates_catalogue_from_details_of_training() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)

    response = client.patch(
        f"/admin/parsed-data/teaching-targets/{session.target_id}",
        headers=_headers(),
        json={
            "correction_reason": "TTF column K was corrected",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"details_of_training": "Journal Club, Grand Round"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["item"]["details_of_training"] == "Journal Club, Grand Round"
    impact = _impact(body)
    assert impact["changed_entity"] == "teaching_target"
    assert impact["affected_models"] == ["teaching_targets", "teaching_name_catalogue"]
    assert {row["keyword"] for row in session.catalogue_rows} == {"Journal Club", "Grand Round"}
    audit_row = session.audit_logs[0]
    assert audit_row["action"] == "admin.parsed_data.teaching_target.update"
    assert _audit_json(audit_row, "metadata_json")["catalogue_keywords"] == ["Journal Club", "Grand Round"]


def test_form_f1_custom_status_requires_explicit_is_active() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)

    response = client.patch(
        f"/admin/parsed-data/form-f1-records/{session.form_f1_id}",
        headers=_headers(),
        json={
            "correction_reason": "Unrecognised label from source file",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"status_raw": "Special Leave"},
        },
    )

    assert response.status_code == 422
    assert session.audit_logs == []


def test_form_f1_known_status_rejects_inconsistent_is_active_only_patch() -> None:
    for status_raw, starting_active, patched_active in (
        ("Active", True, False),
        ("Extension", True, False),
        ("Inactive", False, True),
    ):
        session = FakeParsedDataCorrectionSession()
        session.form_f1_records[0]["status_raw"] = status_raw
        session.form_f1_records[0]["is_active"] = starting_active
        client = _build_client_with_session(session)

        response = client.patch(
            f"/admin/parsed-data/form-f1-records/{session.form_f1_id}",
            headers=_headers(),
            json={
                "correction_reason": "Keep status and activity consistent",
                "last_seen_updated_at": session.now.isoformat(),
                "changes": {"is_active": patched_active},
            },
        )

        assert response.status_code == 422
        assert session.form_f1_records[0]["status_raw"] == status_raw
        assert session.form_f1_records[0]["is_active"] is starting_active
        assert session.audit_logs == []


def test_form_f1_known_status_valid_pairs_succeed() -> None:
    for initial_status, initial_active, status_raw, is_active in (
        ("Active", True, "Inactive", False),
        ("Inactive", False, "Active", True),
        ("Inactive", False, "Extension", True),
    ):
        session = FakeParsedDataCorrectionSession()
        session.form_f1_records[0]["status_raw"] = initial_status
        session.form_f1_records[0]["is_active"] = initial_active
        client = _build_client_with_session(session)

        response = client.patch(
            f"/admin/parsed-data/form-f1-records/{session.form_f1_id}",
            headers=_headers(),
            json={
                "correction_reason": "Correct FormF1 status",
                "last_seen_updated_at": session.now.isoformat(),
                "changes": {"status_raw": status_raw, "is_active": is_active},
            },
        )

        assert response.status_code == 200
        impact = _impact(response.json())
        assert impact["changed_entity"] == "form_f1_record"
        assert impact["scope"] == "resident_reporting_period"
        assert session.form_f1_records[0]["status_raw"] == status_raw
        assert session.form_f1_records[0]["is_active"] is is_active
        assert len(session.audit_logs) == 1


def test_academic_month_boundary_correction_is_master_only() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)

    forbidden = client.patch(
        f"/admin/parsed-data/academic-month-boundaries/{session.boundary_id}",
        headers=_headers(),
        json={
            "correction_reason": "AY date shifted",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"end_date": "2026-02-01"},
        },
    )
    allowed = client.patch(
        f"/admin/parsed-data/academic-month-boundaries/{session.boundary_id}",
        headers=_headers(scope=None, master=True),
        json={
            "correction_reason": "AY date shifted",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"end_date": "2026-02-01"},
        },
    )

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["item"]["end_date"] == "2026-02-01"


def test_academic_month_boundary_rejects_duplicate_month_tuple_before_update() -> None:
    session = FakeParsedDataCorrectionSession()
    duplicate_id = str(uuid4())
    session.academic_month_boundaries.append(
        {
            "id": duplicate_id,
            "academic_year_label": "AY2026",
            "ay_date_category": "im_subspec",
            "month_label": "Feb-26",
            "start_date": date(2026, 2, 1),
            "end_date": date(2026, 2, 28),
            "upload_id": session.upload_id,
            "created_at": session.now,
            "updated_at": session.now,
        }
    )
    client = _build_client_with_session(session)

    response = client.patch(
        f"/admin/parsed-data/academic-month-boundaries/{session.boundary_id}",
        headers=_headers(scope=None, master=True),
        json={
            "correction_reason": "Duplicate month label",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"month_label": "Feb-26"},
        },
    )

    assert response.status_code == 409
    assert session.academic_month_boundaries[0]["month_label"] == "Jan-26"
    assert {row["id"] for row in session.academic_month_boundaries} == {session.boundary_id, duplicate_id}
    assert session.audit_logs == []


def test_academic_month_boundary_non_conflicting_tuple_update_still_succeeds() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)

    response = client.patch(
        f"/admin/parsed-data/academic-month-boundaries/{session.boundary_id}",
        headers=_headers(scope=None, master=True),
        json={
            "correction_reason": "Correct month label",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"month_label": "Jan-2026"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data_revalidation"]["changed_entity"] == "academic_month_boundary"
    assert body["data_revalidation"]["scope"] == "global"
    assert session.academic_month_boundaries[0]["month_label"] == "Jan-2026"
    assert len(session.audit_logs) == 1


def test_data_revalidation_runs_only_after_successful_live_data_mutation(monkeypatch) -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)
    contexts = []

    async def _spy_revalidate_after_live_data_correction(*, context, db_session):
        contexts.append(context)
        return DataRevalidationImpactSummary(
            outcome=DataRevalidationOutcome.FUTURE_COMPLIANCE_IMPACT,
            trigger_source=context.trigger_source,
            changed_entity=context.changed_entity,
            action=context.action,
            scope=context.scope,
            summary="spy impact summary",
            details={"changed_fields": list(context.changed_fields)},
        )

    monkeypatch.setattr(
        data_revalidation_service,
        "revalidate_after_live_data_correction",
        _spy_revalidate_after_live_data_correction,
    )

    failed = client.patch(
        f"/admin/parsed-data/residents/{session.resident_id}",
        headers=_headers(scope="DR"),
        json={
            "correction_reason": "out of scope",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"name": "Blocked"},
        },
    )
    succeeded = client.patch(
        f"/admin/parsed-data/residents/{session.resident_id}",
        headers=_headers(),
        json={
            "correction_reason": "valid correction",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"name": "Allowed"},
        },
    )

    assert failed.status_code == 404
    assert succeeded.status_code == 200
    assert len(contexts) == 1
    assert contexts[0].trigger_source == DataRevalidationTriggerSource.LIVE_DATA_CORRECTION
    assert contexts[0].changed_entity == DataRevalidationChangedEntity.RESIDENT
    assert contexts[0].action == DataRevalidationAction.UPDATE
    assert contexts[0].scope == DataRevalidationScope.SINGLE_ROW
    assert contexts[0].changed_fields == ["name"]


def test_corrections_history_returns_audit_rows_scoped_by_programme() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)
    client.patch(
        f"/admin/parsed-data/residents/{session.resident_id}",
        headers=_headers(),
        json={
            "correction_reason": "RDB row had a typo",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"name": "Geriatrics Resident"},
        },
    )

    response = client.get(
        "/admin/parsed-data/corrections",
        headers=_headers(),
        params={"entity_type": "resident"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["correction_reason"] == "RDB row had a typo"
    assert body["items"][0]["entity_type"] == "resident"


def test_corrections_history_returns_resident_posting_update_by_entity_id() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)
    response = client.patch(
        f"/admin/parsed-data/resident-postings/{session.posting_ids[0]}",
        headers=_headers(scope="GERI"),
        json={
            "correction_reason": "RDB posting date was corrected",
            "last_seen_updated_at": session.now.isoformat(),
            "changes": {"end_date": "2026-01-14"},
        },
    )
    assert response.status_code == 200

    history = client.get(
        "/admin/parsed-data/corrections",
        headers=_headers(scope="GERI"),
        params={"entity_id": session.posting_ids[0]},
    )

    assert history.status_code == 200
    body = history.json()
    assert body["total"] == 1
    assert body["items"][0]["entity_type"] == "resident_posting"
    assert body["items"][0]["entity_id"] == session.posting_ids[0]
    assert body["items"][0]["correction_reason"] == "RDB posting date was corrected"


def test_corrections_history_source_filters_return_source_cell_replacement() -> None:
    session = FakeParsedDataCorrectionSession()
    client = _build_client_with_session(session)
    replace_response = client.post(
        "/admin/parsed-data/resident-postings/source-cell-replace",
        headers=_headers(),
        json=_source_cell_replace_payload(session),
    )
    assert replace_response.status_code == 200

    response = client.get(
        "/admin/parsed-data/corrections",
        headers=_headers(),
        params={
            "upload_log_id": session.upload_id,
            "sheet_name": "Phase 1 & 2",
            "row_number": 42,
            "cell_ref": "J42",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["entity_type"] == "resident_posting_source_cell"
    assert body["items"][0]["metadata_json"]["source_page"] == "parsed_data"
    assert body["items"][0]["metadata_json"]["source_metadata_verified"] is True


def test_rdb_upload_warns_when_it_will_overwrite_corrected_resident_postings(monkeypatch) -> None:
    async def _fake_rdb_parser(**kwargs):
        return ParserResult(
            upload_type="rdb",
            created_count=2,
            metadata={"residents_created": 1, "residents_updated": 0, "postings_created": 2},
        )

    monkeypatch.setattr("app.services.rdb_parser.parse_rdb_upload", _fake_rdb_parser)
    session = FakeRdbUploadCorrectionWarningSession()
    client = _build_client_with_session(session)

    response = client.post(
        "/admin/upload/rdb",
        headers=_headers(),
        data={"reporting_period_id": str(uuid4())},
        files={
            "file": (
                "rdb.xlsx",
                _make_valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    warning = response.json()["warnings"][0]
    assert warning["warning_type"] == "corrected_rows_replaced"
    assert warning["entity_type"] == "resident_postings"
    assert warning["count"] == 3
    summary = json.loads(session.upload_logs[-1]["summary"])
    assert summary["warnings"][0]["warning_type"] == "corrected_rows_replaced"
