from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import admin


class _FakeScalarResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _FakeMappingResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_FakeMappingResult":
        return self

    def all(self) -> list[dict]:
        return self._rows


class FakeUploadLogSession:
    def __init__(self) -> None:
        now = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
        self.period_id = str(uuid4())
        self.other_period_id = str(uuid4())
        self.master_id = str(uuid4())
        self.pc_id = str(uuid4())
        self.logs = [
            self._log(
                upload_type="rdb",
                uploaded_at=now + timedelta(minutes=4),
                programme_code=None,
                status="success",
                uploaded_by=self.master_id,
                uploaded_by_name="Master Admin",
                reporting_period_label="H1 2026",
                summary={
                    "original_filename": "rdb.xlsx",
                    "residents_created": 2,
                    "residents_updated": 1,
                    "postings_created": 3,
                    "posting_codes_added": ["TTSHGerMed", "KTPHGerMed"],
                    "unmatched_multi_posting": [{"mcr": "M00001A"}, {"mcr": "M00002B"}],
                },
            ),
            self._log(
                upload_type="ttf",
                uploaded_at=now + timedelta(minutes=3),
                programme_code="GERI",
                status="partial",
                uploaded_by=self.pc_id,
                uploaded_by_name="Geri PC",
                reporting_period_label="H1 2026",
                summary={
                    "original_filename": "geri-ttf.xlsx",
                    "targets_created": 4,
                    "session_types_upserted": 3,
                    "posting_codes_added": ["TTSHGerMed"],
                    "catalogue_rows_seeded": 6,
                    "warnings": ["Tag order warning"],
                    "tag_order_warnings": ["A2 is longer than A1"],
                    "orphaned_attendance": [{"count": 2}],
                },
            ),
            self._log(
                upload_type="ttf",
                uploaded_at=now + timedelta(minutes=2),
                programme_code="DR",
                status="success",
                uploaded_by=self.pc_id,
                uploaded_by_name="DR PC",
                reporting_period_label="H1 2026",
                summary={
                    "original_filename": "dr-ttf.xlsx",
                    "targets_created": 1,
                    "warnings": ["DR-only warning"],
                },
            ),
            self._log(
                upload_type="form_f1",
                uploaded_at=now + timedelta(minutes=1),
                programme_code=None,
                status="failed",
                uploaded_by=self.master_id,
                uploaded_by_name="Master Admin",
                reporting_period_label="H1 2026",
                summary={
                    "original_filename": "formf1.xlsx",
                    "records_created": 8,
                    "records_updated": 2,
                    "active_count": 7,
                    "inactive_count": 3,
                    "mcr_not_found_warnings": ["M99999Z"],
                    "duplicate_mcr_errors": [{"mcr": "M00001A"}, {"mcr": "M00002B"}],
                    "errors": ["Fatal parse error"],
                },
            ),
            self._log(
                upload_type="public_holidays",
                uploaded_at=now,
                programme_code=None,
                status="success",
                uploaded_by=self.master_id,
                uploaded_by_name="Master Admin",
                reporting_period_id=None,
                reporting_period_label=None,
                summary={
                    "original_filename": "calendar.xlsx",
                    "public_holidays_created": 11,
                    "academic_month_boundaries_created": 24,
                    "warnings": ["Ignored Fr RMT"],
                },
            ),
        ]
        self.original_logs = deepcopy(self.logs)

    def _log(
        self,
        *,
        upload_type: str,
        uploaded_at: datetime,
        programme_code: str | None,
        status: str,
        uploaded_by: str,
        uploaded_by_name: str,
        reporting_period_label: str | None,
        summary: dict,
        reporting_period_id: str | None = "default",
    ) -> dict:
        return {
            "id": str(uuid4()),
            "upload_type": upload_type,
            "uploaded_by": uploaded_by,
            "uploaded_by_name": uploaded_by_name,
            "uploaded_at": uploaded_at,
            "reporting_period_id": self.period_id if reporting_period_id == "default" else reporting_period_id,
            "reporting_period_label": reporting_period_label,
            "programme_code": programme_code,
            "status": status,
            "summary": summary,
            "created_at": uploaded_at,
            "updated_at": uploaded_at,
        }

    async def execute(self, statement, params=None):
        sql = str(statement)
        payload = dict(params or {})
        if "FROM upload_logs" in sql:
            if "1 = 0" in sql:
                rows: list[dict] = []
                if "COUNT(*)" in sql:
                    return _FakeScalarResult(0)
                return _FakeMappingResult(rows)
            rows = self._filtered_rows(payload)
            if "COUNT(*)" in sql:
                return _FakeScalarResult(len(rows))
            limit = int(payload.get("limit", len(rows)))
            offset = int(payload.get("offset", 0))
            return _FakeMappingResult(rows[offset : offset + limit])
        raise AssertionError(f"Unhandled SQL in fake upload-log session: {sql}")

    def _filtered_rows(self, payload: dict) -> list[dict]:
        rows = sorted(
            self.logs,
            key=lambda row: (row["uploaded_at"], row["id"]),
            reverse=True,
        )
        if "upload_log_id" in payload:
            rows = [row for row in rows if row["id"] == payload["upload_log_id"]]
        if "upload_type" in payload:
            rows = [row for row in rows if row["upload_type"] == payload["upload_type"]]
        if "status" in payload:
            rows = [row for row in rows if row["status"] == payload["status"]]
        if "programme_code" in payload:
            rows = [row for row in rows if row["programme_code"] == payload["programme_code"]]
        if "reporting_period_id" in payload:
            rows = [
                row
                for row in rows
                if row["reporting_period_id"] == payload["reporting_period_id"]
            ]
        scope_codes = {
            value
            for key, value in payload.items()
            if key.startswith("scope_programme_code_")
        }
        if scope_codes:
            rows = [
                row
                for row in rows
                if row["upload_type"] == "ttf" and row["programme_code"] in scope_codes
            ]
        return rows

    async def commit(self) -> None:
        raise AssertionError("upload log read endpoints must not commit")

    async def rollback(self) -> None:
        raise AssertionError("upload log read endpoints must not rollback")


def _build_client_with_session(session: FakeUploadLogSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def _db_override():
        yield session

    app.dependency_overrides[admin.get_db_session] = _db_override
    return TestClient(app)


def _admin_headers(scope: str | None = "GERI", *, master: bool = False) -> dict[str, str]:
    headers = {
        "X-User-Role": "admin",
        "X-User-Id": str(uuid4()),
    }
    if scope is not None:
        headers["X-User-Programme"] = scope
    if master:
        headers["X-Admin-Level"] = "master"
    return headers


def test_master_admin_can_list_all_upload_logs() -> None:
    client = _build_client_with_session(FakeUploadLogSession())

    response = client.get("/admin/upload-logs", headers=_admin_headers(scope=None, master=True))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert {item["upload_type"] for item in body["items"]} == {
        "rdb",
        "ttf",
        "form_f1",
        "public_holidays",
    }


def test_list_endpoint_orders_newest_first() -> None:
    client = _build_client_with_session(FakeUploadLogSession())

    response = client.get("/admin/upload-logs", headers=_admin_headers(scope=None, master=True))

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["upload_type"] for item in items[:2]] == ["rdb", "ttf"]


def test_list_endpoint_supports_upload_type_filter() -> None:
    client = _build_client_with_session(FakeUploadLogSession())

    response = client.get(
        "/admin/upload-logs",
        headers=_admin_headers(scope=None, master=True),
        params={"upload_type": "form_f1"},
    )

    assert response.status_code == 200
    assert [item["upload_type"] for item in response.json()["items"]] == ["form_f1"]


def test_list_endpoint_supports_status_filter() -> None:
    client = _build_client_with_session(FakeUploadLogSession())

    response = client.get(
        "/admin/upload-logs",
        headers=_admin_headers(scope=None, master=True),
        params={"status": "failed"},
    )

    assert response.status_code == 200
    assert [item["status"] for item in response.json()["items"]] == ["failed"]


def test_list_endpoint_supports_programme_code_filter_safely() -> None:
    client = _build_client_with_session(FakeUploadLogSession())

    allowed = client.get(
        "/admin/upload-logs",
        headers=_admin_headers("GERI"),
        params={"programme_code": "GERI"},
    )
    forbidden = client.get(
        "/admin/upload-logs",
        headers=_admin_headers("GERI"),
        params={"programme_code": "DR"},
    )

    assert allowed.status_code == 200
    assert [item["programme_code"] for item in allowed.json()["items"]] == ["GERI"]
    assert forbidden.status_code == 403


def test_master_admin_can_read_upload_log_detail() -> None:
    session = FakeUploadLogSession()
    client = _build_client_with_session(session)
    log_id = session.logs[1]["id"]

    response = client.get(
        f"/admin/upload-logs/{log_id}",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == log_id
    assert body["summary"] == session.logs[1]["summary"]
    assert body["original_filename"] == "geri-ttf.xlsx"


def test_programme_pc_scoped_to_geri_can_see_geri_ttf_upload_logs() -> None:
    client = _build_client_with_session(FakeUploadLogSession())

    response = client.get("/admin/upload-logs", headers=_admin_headers("GERI"))

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["upload_type"] == "ttf"
    assert items[0]["programme_code"] == "GERI"


def test_programme_pc_scoped_to_geri_cannot_see_other_programme_ttf_logs() -> None:
    client = _build_client_with_session(FakeUploadLogSession())

    response = client.get("/admin/upload-logs", headers=_admin_headers("GERI"))

    assert response.status_code == 200
    assert {item["programme_code"] for item in response.json()["items"]} == {"GERI"}


def test_programme_pc_cannot_see_global_rdb_formf1_or_public_holiday_logs() -> None:
    client = _build_client_with_session(FakeUploadLogSession())

    response = client.get("/admin/upload-logs", headers=_admin_headers("GERI"))

    assert response.status_code == 200
    assert {item["upload_type"] for item in response.json()["items"]} == {"ttf"}


def test_programme_pc_with_null_or_empty_scope_sees_no_logs() -> None:
    client = _build_client_with_session(FakeUploadLogSession())

    missing_scope = client.get("/admin/upload-logs", headers=_admin_headers(scope=None))
    empty_scope = client.get("/admin/upload-logs", headers=_admin_headers(scope=""))

    assert missing_scope.status_code == 200
    assert missing_scope.json()["items"] == []
    assert missing_scope.json()["total"] == 0
    assert empty_scope.status_code == 200
    assert empty_scope.json()["items"] == []
    assert empty_scope.json()["total"] == 0


def test_master_admin_is_explicit_and_not_inferred_from_null_programme_scope() -> None:
    client = _build_client_with_session(FakeUploadLogSession())

    response = client.get("/admin/upload-logs", headers=_admin_headers(scope=None))

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0


def test_warning_count_counts_warning_occurrences_from_summary() -> None:
    client = _build_client_with_session(FakeUploadLogSession())

    response = client.get(
        "/admin/upload-logs",
        headers=_admin_headers(scope=None, master=True),
        params={"upload_type": "ttf", "programme_code": "GERI"},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["warning_count"] == 3


def test_error_count_counts_error_occurrences_from_summary() -> None:
    client = _build_client_with_session(FakeUploadLogSession())

    response = client.get(
        "/admin/upload-logs",
        headers=_admin_headers(scope=None, master=True),
        params={"upload_type": "form_f1"},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["error_count"] == 3


def test_summary_counts_extracts_numbers_and_avoids_raw_large_arrays() -> None:
    client = _build_client_with_session(FakeUploadLogSession())

    response = client.get(
        "/admin/upload-logs",
        headers=_admin_headers(scope=None, master=True),
        params={"upload_type": "rdb"},
    )

    assert response.status_code == 200
    counts = response.json()["items"][0]["summary_counts"]
    assert counts["residents_created"] == 2
    assert counts["residents_updated"] == 1
    assert counts["postings_created"] == 3
    assert counts["posting_codes_added"] == 2
    assert "unmatched_multi_posting" not in counts


def test_detail_endpoint_returns_full_summary() -> None:
    session = FakeUploadLogSession()
    client = _build_client_with_session(session)
    log_id = session.logs[0]["id"]

    response = client.get(
        f"/admin/upload-logs/{log_id}",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    assert response.json()["summary"] == session.logs[0]["summary"]


def test_detail_endpoint_enforces_scope_safely_for_unauthorized_log_access() -> None:
    session = FakeUploadLogSession()
    client = _build_client_with_session(session)
    rdb_id = session.logs[0]["id"]
    dr_ttf_id = session.logs[2]["id"]

    rdb_response = client.get(f"/admin/upload-logs/{rdb_id}", headers=_admin_headers("GERI"))
    dr_response = client.get(f"/admin/upload-logs/{dr_ttf_id}", headers=_admin_headers("GERI"))

    assert rdb_response.status_code == 404
    assert dr_response.status_code == 404


def test_upload_log_read_endpoints_do_not_mutate_upload_logs() -> None:
    session = FakeUploadLogSession()
    client = _build_client_with_session(session)

    client.get("/admin/upload-logs", headers=_admin_headers(scope=None, master=True))
    client.get(
        f"/admin/upload-logs/{session.logs[0]['id']}",
        headers=_admin_headers(scope=None, master=True),
    )

    assert session.logs == session.original_logs
