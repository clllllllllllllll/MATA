from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import admin


NOW = datetime(2026, 1, 15, 8, 30, tzinfo=timezone.utc)
INVALID_WARNING_SQL_COLUMNS = (
    "wi.first_upload_log_id",
    "wi.last_upload_log_id",
    "wi.resolution_action",
    "latest_uw.column_name",
)


class _FakeMappingResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def one_or_none(self):
        if not self._rows:
            return None
        return self._rows[0]

    def one(self):
        if not self._rows:
            raise AssertionError("Expected one row")
        return self._rows[0]


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _FakeMappingResult(self._rows)


class FakeAdminLogsSession:
    def __init__(self) -> None:
        self.rdb_upload_id = uuid4()
        self.ttf_upload_id = uuid4()
        self.other_ttf_upload_id = uuid4()
        self.warning_issue_id = uuid4()
        self.rdb_warning_issue_id = uuid4()
        self.upload_warning_id = uuid4()
        self.rdb_upload_warning_id = uuid4()
        self.warning_action_id = uuid4()
        self.source_cell_audit_id = uuid4()
        self.parsed_data_audit_id = uuid4()
        self.config_audit_id = uuid4()
        self.global_config_audit_id = uuid4()
        self.revalidation_audit_id = uuid4()
        self.reporting_period_id = uuid4()
        self.actor_id = uuid4()
        self.large_summary = {"large_blob": "x" * 5000, "counts": {"created": 2}}
        self.upload_logs = [
            {
                "id": self.rdb_upload_id,
                "upload_type": "rdb",
                "uploaded_by": self.actor_id,
                "uploaded_by_name": "Master Admin",
                "uploaded_at": NOW,
                "reporting_period_id": self.reporting_period_id,
                "programme_code": None,
                "status": "success",
                "summary": self.large_summary,
            },
            {
                "id": self.ttf_upload_id,
                "upload_type": "ttf",
                "uploaded_by": self.actor_id,
                "uploaded_by_name": "Programme PC",
                "uploaded_at": NOW.replace(hour=7),
                "reporting_period_id": self.reporting_period_id,
                "programme_code": "DR",
                "status": "success",
                "summary": {"large_blob": "ttf-raw", "counts": {"warnings": 1}},
            },
            {
                "id": self.other_ttf_upload_id,
                "upload_type": "ttf",
                "uploaded_by": self.actor_id,
                "uploaded_by_name": "Other PC",
                "uploaded_at": NOW.replace(hour=6),
                "reporting_period_id": self.reporting_period_id,
                "programme_code": "GRM",
                "status": "success",
                "summary": {"large_blob": "other-raw"},
            },
        ]
        self.warning_issues = [
            {
                "id": self.warning_issue_id,
                "fingerprint": "fp-dr",
                "warning_type": "unmatched_multi_posting",
                "severity": "warning",
                "status": "unresolved",
                "first_upload_log_id": self.ttf_upload_id,
                "last_upload_log_id": self.ttf_upload_id,
                "first_seen_at": NOW.replace(hour=7),
                "last_seen_at": NOW.replace(hour=7, minute=20),
                "reporting_period_id": self.reporting_period_id,
                "programme_code": "DR",
                "resident_id": None,
                "mcr": "M12345A",
                "month_label": "2026-01",
                "resolution_action": None,
                "resolution_note": None,
                "resolved_by": None,
                "resolved_at": None,
                "latest_upload_warning_id": self.upload_warning_id,
                "latest_upload_log_id": self.ttf_upload_id,
                "message": "Unmatched multi-posting cell",
                "suggested_action": "Review source cell",
                "sheet_name": "DR",
                "row_number": 12,
                "column_name": "Jan",
                "cell_ref": "C12",
                "source_payload": {"posting_codes": ["A", "B"]},
                "latest_warning_created_at": NOW.replace(hour=7, minute=20),
            },
            {
                "id": self.rdb_warning_issue_id,
                "fingerprint": "fp-rdb",
                "warning_type": "empty_posting_cell",
                "severity": "info",
                "status": "unresolved",
                "first_upload_log_id": self.rdb_upload_id,
                "last_upload_log_id": self.rdb_upload_id,
                "first_seen_at": NOW.replace(hour=8),
                "last_seen_at": NOW.replace(hour=8, minute=10),
                "reporting_period_id": self.reporting_period_id,
                "programme_code": "DR",
                "resident_id": None,
                "mcr": "M12345A",
                "month_label": "2026-01",
                "resolution_action": None,
                "resolution_note": None,
                "resolved_by": None,
                "resolved_at": None,
                "latest_upload_warning_id": self.rdb_upload_warning_id,
                "latest_upload_log_id": self.rdb_upload_id,
                "message": "Empty RDB posting cell",
                "suggested_action": "Review RDB source cell",
                "sheet_name": "DR",
                "row_number": 14,
                "column_name": "Jan",
                "cell_ref": "D14",
                "source_payload": {"raw_value": None},
                "latest_warning_created_at": NOW.replace(hour=8, minute=10),
            }
        ]
        self.audit_logs = [
            {
                "id": self.warning_action_id,
                "actor_user_id": self.actor_id,
                "actor_role": "admin",
                "actor_name": "Programme PC",
                "actor_site": None,
                "actor_programme": "DR",
                "actor_admin_level": None,
                "action": "admin.upload_warning.resolve",
                "entity_type": "warning_issue",
                "entity_id": self.warning_issue_id,
                "before_json": {"status": "unresolved"},
                "after_json": {"status": "resolved"},
                "metadata_json": {
                    "programme_code": "GRM",
                    "reporting_period_id": str(self.reporting_period_id),
                    "warning_type": "unmatched_multi_posting",
                },
                "canonical_warning_programme_code": "DR",
                "canonical_warning_issue_id": self.warning_issue_id,
                "created_at": NOW.replace(hour=9),
            },
            {
                "id": self.source_cell_audit_id,
                "actor_user_id": self.actor_id,
                "actor_role": "admin",
                "actor_name": "Programme PC",
                "actor_site": None,
                "actor_programme": "DR",
                "actor_admin_level": None,
                "action": "admin.parsed_data.resident_posting.source_cell_replace",
                "entity_type": "resident_posting",
                "entity_id": uuid4(),
                "before_json": {"posting_code": "OLD"},
                "after_json": {"posting_code": "NEW"},
                "metadata_json": {
                    "programme_code": "GRM",
                    "reporting_period_id": str(self.reporting_period_id),
                    "warning_issue_id": str(self.warning_issue_id),
                    "upload_warning_id": str(self.upload_warning_id),
                    "source_cell": {"sheet_name": "DR", "row_number": 12, "cell_ref": "C12"},
                    "data_revalidation": {
                        "outcome": "targeted_revalidation",
                        "summary": "Targeted rows were refreshed.",
                    },
                },
                "canonical_warning_programme_code": "DR",
                "canonical_warning_issue_id": self.warning_issue_id,
                "created_at": NOW.replace(hour=10),
            },
            {
                "id": self.parsed_data_audit_id,
                "actor_user_id": self.actor_id,
                "actor_role": "admin",
                "actor_name": "Programme PC",
                "actor_site": None,
                "actor_programme": "DR",
                "actor_admin_level": None,
                "action": "admin.parsed_data.resident.update",
                "entity_type": "resident",
                "entity_id": uuid4(),
                "before_json": {"name": "Old"},
                "after_json": {"name": "New"},
                "metadata_json": {
                    "programme_code": "DR",
                    "data_revalidation": {
                        "outcome": "future_compliance_impact",
                        "summary": "Resident correction may affect reads.",
                    },
                },
                "created_at": NOW.replace(hour=11),
            },
            {
                "id": self.config_audit_id,
                "actor_user_id": self.actor_id,
                "actor_role": "admin",
                "actor_name": "Programme PC",
                "actor_site": None,
                "actor_programme": "DR",
                "actor_admin_level": None,
                "action": "admin.config.programme.update",
                "entity_type": "programme",
                "entity_id": "DR",
                "before_json": {"r_year_required": True},
                "after_json": {"r_year_required": False},
                "metadata_json": {
                    "programme_code": "DR",
                    "data_revalidation": {
                        "outcome": "future_compliance_impact",
                        "summary": "Config may affect future reads.",
                    },
                },
                "created_at": NOW.replace(hour=12),
            },
            {
                "id": self.global_config_audit_id,
                "actor_user_id": self.actor_id,
                "actor_role": "admin",
                "actor_name": "Master Admin",
                "actor_site": None,
                "actor_programme": None,
                "actor_admin_level": "master",
                "action": "admin.config.reporting_period.create",
                "entity_type": "reporting_period",
                "entity_id": self.reporting_period_id,
                "before_json": None,
                "after_json": {"label": "2026 H1"},
                "metadata_json": {
                    "data_revalidation": {
                        "outcome": "future_compliance_impact",
                        "summary": "Global config changed.",
                    },
                },
                "created_at": NOW.replace(hour=13),
            },
            {
                "id": self.revalidation_audit_id,
                "actor_user_id": self.actor_id,
                "actor_role": "admin",
                "actor_name": "Programme PC",
                "actor_site": None,
                "actor_programme": "DR",
                "actor_admin_level": None,
                "action": "admin.config.posting_group.update",
                "entity_type": "posting_group",
                "entity_id": uuid4(),
                "before_json": {"group_code": "OLD"},
                "after_json": {"group_code": "NEW"},
                "metadata_json": {
                    "programme_code": "DR",
                    "data_revalidation": {
                        "outcome": "manual_revalidation_required",
                        "summary": "Posting group may make warnings actionable.",
                    },
                },
                "created_at": NOW.replace(hour=14),
            },
        ]
        self.committed = False
        self.rolled_back = False

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        if "/* admin_logs:upload_rows */" in sql:
            return _FakeResult(self._filter_uploads(params, include_summary=False))
        if "/* admin_logs:warning_rows */" in sql:
            self._assert_real_warning_schema_sql(sql)
            return _FakeResult(self._filter_warnings(params))
        if "/* admin_logs:audit_rows */" in sql:
            self._assert_linked_audit_scope_sql(sql)
            return _FakeResult(self._filter_audit_rows(params))
        if "/* admin_logs:upload_detail */" in sql:
            include_summary = bool(params.get("include_raw_summary"))
            if include_summary:
                assert "ul.summary" in sql
            else:
                assert "ul.summary" not in sql, "Default Admin Logs upload detail must not select raw summary"
            return _FakeResult(self._upload_detail(params))
        if "/* admin_logs:warning_detail */" in sql:
            self._assert_real_warning_schema_sql(sql)
            return _FakeResult(self._warning_detail(params))
        if "/* admin_logs:audit_detail */" in sql:
            self._assert_linked_audit_scope_sql(sql)
            return _FakeResult(self._audit_detail(params))
        raise AssertionError(f"Unexpected SQL: {sql}")

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, _obj):
        return None

    def add(self, _obj):
        raise AssertionError("Admin Logs endpoints must be read-only")

    def _assert_real_warning_schema_sql(self, sql):
        for invalid_column in INVALID_WARNING_SQL_COLUMNS:
            assert invalid_column not in sql, f"Admin Logs SQL references nonexistent column {invalid_column}"
        assert "wi.first_seen_upload_log_id" in sql
        assert "wi.last_seen_upload_log_id" in sql
        assert "wi.resolution_source_type" in sql
        assert "wi.resolution_source_id" in sql

    def _assert_linked_audit_scope_sql(self, sql):
        assert "linked_wi.programme_code" in sql
        assert "linked_wi.id AS linked_warning_issue_id" in sql

    def _matches_common(self, row, params):
        if params.get("date_from") is not None and row["occurred_at"] < params["date_from"]:
            return False
        if params.get("date_to") is not None and row["occurred_at"] > params["date_to"]:
            return False
        if params.get("actor_user_id") is not None and str(row.get("actor_user_id")) != str(params["actor_user_id"]):
            return False
        if params.get("programme_code") is not None and row.get("programme_code") != params["programme_code"]:
            return False
        if params.get("reporting_period_id") is not None and str(row.get("reporting_period_id")) != str(params["reporting_period_id"]):
            return False
        if params.get("entity_type") is not None and row.get("entity_type") != params["entity_type"]:
            return False
        if params.get("entity_id") is not None and str(row.get("entity_id")) != str(params["entity_id"]):
            return False
        return True

    def _filter_uploads(self, params, *, include_summary):
        rows = []
        for upload in self.upload_logs:
            row = {
                "id": upload["id"],
                "upload_type": upload["upload_type"],
                "uploaded_by": upload["uploaded_by"],
                "uploaded_by_name": upload["uploaded_by_name"],
                "uploaded_at": upload["uploaded_at"],
                "occurred_at": upload["uploaded_at"],
                "actor_user_id": upload["uploaded_by"],
                "programme_code": upload["programme_code"],
                "reporting_period_id": upload["reporting_period_id"],
                "entity_type": "upload_log",
                "entity_id": upload["id"],
                "status": upload["status"],
            }
            if include_summary:
                row["summary"] = upload["summary"]
            if params.get("upload_type") is not None and upload["upload_type"] != params["upload_type"]:
                continue
            if params.get("status") is not None and upload["status"] != params["status"]:
                continue
            if self._matches_common(row, params):
                rows.append(row)
        return rows

    def _filter_warnings(self, params):
        rows = []
        upload_type_by_id = {upload["id"]: upload["upload_type"] for upload in self.upload_logs}
        for warning in self.warning_issues:
            row = {
                **warning,
                "occurred_at": warning["last_seen_at"],
                "actor_user_id": None,
                "entity_type": "warning_issue",
                "entity_id": warning["id"],
            }
            if (
                params.get("upload_type") is not None
                and upload_type_by_id.get(warning["last_upload_log_id"]) != params["upload_type"]
            ):
                continue
            if params.get("warning_type") is not None and warning["warning_type"] != params["warning_type"]:
                continue
            if params.get("status") is not None and warning["status"] != params["status"]:
                continue
            if self._matches_common(row, params):
                rows.append(row)
        return rows

    def _filter_audit_rows(self, params):
        rows = []
        for audit in self.audit_logs:
            row = {
                **audit,
                "occurred_at": audit["created_at"],
                "programme_code": audit["metadata_json"].get("programme_code"),
                "reporting_period_id": audit["metadata_json"].get("reporting_period_id"),
                "linked_warning_programme_code": audit.get("canonical_warning_programme_code"),
                "linked_warning_issue_id": audit.get("canonical_warning_issue_id"),
            }
            if params.get("actor_role") == "master_admin":
                if audit["actor_role"] != "admin" or audit.get("actor_admin_level") not in {
                    "master",
                    "master_admin",
                }:
                    continue
            elif params.get("actor_role") is not None and audit["actor_role"] != params["actor_role"]:
                continue
            if params.get("programme_scope") is not None:
                scope = set(params["programme_scope"])
                canonical_programme = audit.get("canonical_warning_programme_code")
                metadata_programme = audit["metadata_json"].get("programme_code")
                if (canonical_programme or metadata_programme) not in scope:
                    continue
            if params.get("outcome") is not None:
                data_revalidation = audit["metadata_json"].get("data_revalidation") or {}
                if data_revalidation.get("outcome") != params["outcome"]:
                    continue
            if self._matches_common(row, params):
                rows.append(row)
        return rows

    def _upload_detail(self, params):
        upload_id = UUID(str(params["log_uuid"]))
        return self._filter_uploads({"entity_id": upload_id}, include_summary=True)

    def _warning_detail(self, params):
        warning_id = UUID(str(params["log_uuid"]))
        return [row for row in self._filter_warnings({}) if row["id"] == warning_id]

    def _audit_detail(self, params):
        audit_id = UUID(str(params["log_uuid"]))
        return [row for row in self._filter_audit_rows({}) if row["id"] == audit_id]


def _build_client(session: FakeAdminLogsSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def override_db():
        yield session

    app.dependency_overrides[admin.get_db_session] = override_db
    return TestClient(app)


def _headers(*, scope: str = "DR", master: bool = False, user_id: UUID | None = None) -> dict[str, str]:
    headers = {
        "X-User-Role": "admin",
        "X-User-Id": str(user_id or uuid4()),
        "X-User-Programme": scope,
    }
    if master:
        headers["X-Admin-Level"] = "master"
    return headers


def test_admin_logs_master_list_returns_unified_compact_projection() -> None:
    session = FakeAdminLogsSession()
    client = _build_client(session)

    response = client.get("/admin/logs", headers=_headers(master=True))

    assert response.status_code == 200
    payload = response.json()
    log_types = {item["log_type"] for item in payload["items"]}
    assert {
        "upload",
        "warning",
        "warning_action",
        "source_cell_correction",
        "parsed_data_correction",
        "config_mutation",
        "data_revalidation",
    }.issubset(log_types)
    assert payload["total"] == len(payload["items"])
    assert all(item["id"].count(":") == 1 for item in payload["items"])
    assert all("immutable_evidence" not in item for item in payload["items"])
    assert all(isinstance(item["summary"], str) for item in payload["items"])
    assert "large_blob" not in json.dumps(payload)
    assert session.committed is False
    assert session.rolled_back is False


def test_admin_logs_programme_pc_scope_and_master_only_upload_rules() -> None:
    session = FakeAdminLogsSession()
    client = _build_client(session)

    response = client.get("/admin/logs", headers=_headers(scope="DR"))

    assert response.status_code == 200
    items = response.json()["items"]
    ids = {item["id"] for item in items}
    assert f"upload:{session.ttf_upload_id}" in ids
    assert f"warning_action:{session.warning_action_id}" in ids
    assert f"source_cell_correction:{session.source_cell_audit_id}" in ids
    assert f"upload:{session.rdb_upload_id}" not in ids
    assert f"upload:{session.other_ttf_upload_id}" not in ids
    assert f"config_mutation:{session.global_config_audit_id}" not in ids
    assert all(item["programme_code"] in ("DR", None) for item in items)

    empty_scope_response = client.get("/admin/logs", headers=_headers(scope=""))
    assert empty_scope_response.status_code == 200
    assert empty_scope_response.json()["items"] == []

    forbidden = client.get(
        f"/admin/logs/upload:{session.rdb_upload_id}",
        headers=_headers(scope="DR"),
    )
    assert forbidden.status_code == 403


def test_admin_log_upload_detail_is_bounded_by_default_and_raw_summary_is_explicit() -> None:
    session = FakeAdminLogsSession()
    client = _build_client(session)

    detail = client.get(
        f"/admin/logs/upload:{session.rdb_upload_id}",
        headers=_headers(master=True),
    )

    assert detail.status_code == 200
    payload = detail.json()
    assert payload["id"] == f"upload:{session.rdb_upload_id}"
    assert payload["list_item"]["log_type"] == "upload"
    assert "summary" not in payload["immutable_evidence"]
    assert isinstance(payload["related_entities"], list)
    assert any(entity["relationship"] == "upload_log" for entity in payload["related_entities"])
    assert "large_blob" not in json.dumps(payload)

    raw_detail = client.get(
        f"/admin/logs/upload:{session.rdb_upload_id}?include_raw_summary=true",
        headers=_headers(master=True),
    )
    assert raw_detail.status_code == 200
    raw_payload = raw_detail.json()
    assert raw_payload["immutable_evidence"]["summary"]["large_blob"].startswith("x")


def test_admin_log_warning_detail_includes_workflow_status_and_source_trace() -> None:
    session = FakeAdminLogsSession()
    client = _build_client(session)

    response = client.get(
        f"/admin/logs/warning:{session.warning_issue_id}",
        headers=_headers(scope="DR"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workflow_status"]["status"] == "unresolved"
    assert payload["source_ref"]["sheet_name"] == "DR"
    assert payload["source_ref"]["cell_ref"] == "C12"
    assert isinstance(payload["related_entities"], list)
    assert any(
        entity["relationship"] == "upload_log"
        and entity["entity_id"] == str(session.ttf_upload_id)
        for entity in payload["related_entities"]
    )
    assert session.committed is False


def test_admin_log_upload_type_filter_applies_to_warning_upload_context() -> None:
    session = FakeAdminLogsSession()
    client = _build_client(session)

    ttf_response = client.get(
        "/admin/logs?log_type=warning&upload_type=ttf",
        headers=_headers(master=True),
    )
    rdb_response = client.get(
        "/admin/logs?log_type=warning&upload_type=rdb",
        headers=_headers(master=True),
    )

    assert ttf_response.status_code == 200
    assert rdb_response.status_code == 200
    ttf_ids = {item["id"] for item in ttf_response.json()["items"]}
    rdb_ids = {item["id"] for item in rdb_response.json()["items"]}
    assert f"warning:{session.warning_issue_id}" in ttf_ids
    assert f"warning:{session.rdb_warning_issue_id}" not in ttf_ids
    assert f"warning:{session.rdb_warning_issue_id}" in rdb_ids
    assert f"warning:{session.warning_issue_id}" not in rdb_ids


def test_admin_log_audit_details_project_mutation_and_revalidation_rows() -> None:
    session = FakeAdminLogsSession()
    client = _build_client(session)

    config_detail = client.get(
        f"/admin/logs/config_mutation:{session.config_audit_id}",
        headers=_headers(scope="DR"),
    )

    assert config_detail.status_code == 200
    config_payload = config_detail.json()
    assert config_payload["list_item"]["log_type"] == "config_mutation"
    assert config_payload["immutable_evidence"]["action"] == "admin.config.programme.update"
    assert config_payload["immutable_evidence"]["before_json"]["r_year_required"] is True
    assert config_payload["immutable_evidence"]["after_json"]["r_year_required"] is False
    assert isinstance(config_payload["related_entities"], list)
    assert any(entity["relationship"] == "audit_log" for entity in config_payload["related_entities"])

    source_cell_detail = client.get(
        f"/admin/logs/source_cell_correction:{session.source_cell_audit_id}",
        headers=_headers(scope="DR"),
    )
    assert source_cell_detail.status_code == 200
    source_cell_payload = source_cell_detail.json()
    assert source_cell_payload["list_item"]["programme_code"] == "DR"
    assert source_cell_payload["list_item"]["warning_issue_id"] == str(session.warning_issue_id)
    assert source_cell_payload["list_item"]["upload_warning_id"] == str(session.upload_warning_id)

    revalidation_detail = client.get(
        f"/admin/logs/data_revalidation:{session.revalidation_audit_id}",
        headers=_headers(scope="DR"),
    )
    assert revalidation_detail.status_code == 200
    revalidation_payload = revalidation_detail.json()
    assert revalidation_payload["list_item"]["log_type"] == "data_revalidation"
    assert revalidation_payload["workflow_status"]["outcome"] == "manual_revalidation_required"
    assert revalidation_payload["list_item"]["outcome"] == "manual_revalidation_required"

    forbidden_global = client.get(
        f"/admin/logs/config_mutation:{session.global_config_audit_id}",
        headers=_headers(scope="DR"),
    )
    assert forbidden_global.status_code == 403


def test_admin_log_filters_validate_enums_and_bounds() -> None:
    session = FakeAdminLogsSession()
    client = _build_client(session)

    invalid_type = client.get(
        "/admin/logs?log_type=not_real",
        headers=_headers(master=True),
    )
    assert invalid_type.status_code == 422

    invalid_limit = client.get(
        "/admin/logs?limit=201",
        headers=_headers(master=True),
    )
    assert invalid_limit.status_code == 422


def test_admin_log_actor_role_filter_uses_normalized_master_admin_role() -> None:
    session = FakeAdminLogsSession()
    client = _build_client(session)

    response = client.get(
        "/admin/logs?actor_role=master_admin",
        headers=_headers(master=True),
    )

    assert response.status_code == 200
    items = response.json()["items"]
    ids = {item["id"] for item in items}
    assert f"config_mutation:{session.global_config_audit_id}" in ids
    assert all(item["actor_role"] == "master_admin" for item in items)
