from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.errors import install_error_handlers
from app.routers import admin


class _FakeMappingResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_FakeMappingResult":
        return self

    def all(self) -> list[dict]:
        return self._rows


class FakeUploadWarningSession:
    def __init__(self) -> None:
        now = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
        self.period_id = str(uuid4())
        self.admin_id = str(uuid4())
        self.upload_logs = [
            {
                "id": str(uuid4()),
                "upload_type": "rdb",
                "uploaded_by": self.admin_id,
                "uploaded_by_name": "Master Admin",
                "uploaded_at": now,
                "reporting_period_id": self.period_id,
                "programme_code": None,
                "status": "success",
                "summary": {
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
                        },
                        {
                            "type": "generic_payload",
                            "mcr": "M00002B",
                            "message": "Unknown dict warning should remain visible.",
                        },
                    ],
                    "unknown_loa_types": ["Exam Leave"],
                    "duplicate_mcr_errors": [
                        {
                            "mcr": "M00003C",
                            "programme_code": "ENDO",
                            "sheet_name": "Phase 1",
                            "row_number": 12,
                            "cell_ref": "E12",
                            "message": "Duplicate MCR in RDB upload.",
                        }
                    ],
                },
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "upload_type": "form_f1",
                "uploaded_by": self.admin_id,
                "uploaded_by_name": "Master Admin",
                "uploaded_at": now,
                "reporting_period_id": self.period_id,
                "programme_code": None,
                "status": "partial",
                "summary": {
                    "mcr_not_found_warnings": ["M99999Z not found in residents"],
                    "skipped_mcr_warnings": ["row 19: blank MCR"],
                    "promotion_date_warnings": ["M00004D: unable to parse promotion date"],
                },
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "upload_type": "ttf",
                "uploaded_by": self.admin_id,
                "uploaded_by_name": "PC Admin",
                "uploaded_at": now,
                "reporting_period_id": self.period_id,
                "programme_code": "GRM",
                "status": "partial",
                "summary": {
                    "warnings": [
                        {
                            "type": "orphaned_attendance",
                            "session_type": "Case-based Teaching [1h]",
                            "posting_code": "TTSHGerMed",
                            "programme_code": "GRM",
                            "count": 3,
                            "message": "3 attendance records no longer map to any teaching target.",
                        }
                    ],
                    "tag_order_warnings": [
                        "Posting TTSHGerMed: tag A1 maps to [1h] but A2 maps to [2h]."
                    ],
                },
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "upload_type": "ttf",
                "uploaded_by": self.admin_id,
                "uploaded_by_name": "PC Admin",
                "uploaded_at": now,
                "reporting_period_id": self.period_id,
                "programme_code": "REH",
                "status": "partial",
                "summary": {"warnings": ["REH warning"]},
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid4()),
                "upload_type": "public_holidays",
                "uploaded_by": self.admin_id,
                "uploaded_by_name": "Master Admin",
                "uploaded_at": now,
                "reporting_period_id": None,
                "programme_code": None,
                "status": "partial",
                "summary": {"warnings": ["Global holiday warning"]},
                "created_at": now,
                "updated_at": now,
            },
        ]
        self.residents = [
            {"mcr": "M00002B", "programme_code": "GRM"},
            {"mcr": "M99999Z", "programme_code": "REH"},
            {"mcr": "M00004D", "programme_code": "GRM"},
        ]
        self.original_upload_logs = deepcopy(self.upload_logs)

    def add_upload_log(
        self,
        *,
        upload_type: str,
        uploaded_at: datetime,
        summary: dict,
        programme_code: str | None = None,
        reporting_period_id: str | None = None,
        status: str = "partial",
    ) -> dict:
        row = {
            "id": str(uuid4()),
            "upload_type": upload_type,
            "uploaded_by": self.admin_id,
            "uploaded_by_name": "Master Admin",
            "uploaded_at": uploaded_at,
            "reporting_period_id": reporting_period_id if reporting_period_id is not None else self.period_id,
            "programme_code": programme_code,
            "status": status,
            "summary": summary,
            "created_at": uploaded_at,
            "updated_at": uploaded_at,
        }
        self.upload_logs.append(row)
        self.original_upload_logs = deepcopy(self.upload_logs)
        return row

    async def execute(self, statement, params=None):
        sql = str(statement)
        payload = dict(params or {})

        if "FROM upload_logs" in sql:
            rows = list(self.upload_logs)
            if "upload_type" in payload:
                rows = [row for row in rows if row["upload_type"] == payload["upload_type"]]
            if "reporting_period_id" in payload:
                rows = [
                    row
                    for row in rows
                    if row["reporting_period_id"] == payload["reporting_period_id"]
                ]
            if "programme_code" in payload:
                rows = [row for row in rows if row["programme_code"] == payload["programme_code"]]
            return _FakeMappingResult(rows)

        if "FROM residents" in sql:
            mcr_values = set(payload.get("mcr_values") or [])
            return _FakeMappingResult(
                [row for row in self.residents if row["mcr"].upper() in mcr_values]
            )

        raise AssertionError(f"Unhandled SQL: {sql}")

    async def commit(self) -> None:
        raise AssertionError("upload warnings endpoint must not commit")

    async def rollback(self) -> None:
        raise AssertionError("upload warnings endpoint must not rollback")


def _build_client_with_session(session: FakeUploadWarningSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def _db_override():
        yield session

    app.dependency_overrides[admin.get_db_session] = _db_override
    return TestClient(app)


def _admin_headers(scope: str | None = "GRM", *, master: bool = False) -> dict[str, str]:
    headers = {
        "X-User-Role": "admin",
        "X-User-Id": str(uuid4()),
    }
    if scope is not None:
        headers["X-User-Programme"] = scope
    if master:
        headers["X-Admin-Level"] = "master"
    return headers


def test_master_admin_can_list_warnings_from_multiple_upload_types() -> None:
    client = _build_client_with_session(FakeUploadWarningSession())

    response = client.get("/admin/upload-warnings", headers=_admin_headers(scope=None, master=True))

    assert response.status_code == 200
    upload_types = {row["upload_type"] for row in response.json()}
    assert {"rdb", "ttf", "form_f1", "public_holidays"}.issubset(upload_types)


def test_programme_pc_scoped_to_grm_sees_grm_warnings_only() -> None:
    client = _build_client_with_session(FakeUploadWarningSession())

    response = client.get("/admin/upload-warnings", headers=_admin_headers("GRM"))

    assert response.status_code == 200
    rows = response.json()
    assert rows
    assert {row["programme_code"] for row in rows} == {"GRM"}
    assert all(row["upload_type"] != "public_holidays" for row in rows)


def test_programme_pc_scoped_to_grm_excludes_reh_endo_global_and_unscoped() -> None:
    client = _build_client_with_session(FakeUploadWarningSession())

    response = client.get("/admin/upload-warnings", headers=_admin_headers("GRM"))

    assert response.status_code == 200
    messages = {row["message"] for row in response.json()}
    assert "REH warning" not in messages
    assert "Duplicate MCR in RDB upload." not in messages
    assert "Global holiday warning" not in messages
    assert "row 19: blank MCR" not in messages


def test_programme_pc_with_null_or_empty_scope_sees_no_warnings() -> None:
    client = _build_client_with_session(FakeUploadWarningSession())

    missing_scope = client.get("/admin/upload-warnings", headers=_admin_headers(scope=None))
    empty_scope = client.get("/admin/upload-warnings", headers=_admin_headers(scope=""))

    assert missing_scope.status_code == 200
    assert missing_scope.json() == []
    assert empty_scope.status_code == 200
    assert empty_scope.json() == []


def test_master_admin_is_explicit_and_not_inferred_from_null_programme_scope() -> None:
    client = _build_client_with_session(FakeUploadWarningSession())

    response = client.get("/admin/upload-warnings", headers=_admin_headers(scope=None))

    assert response.status_code == 200
    assert response.json() == []


def test_unmatched_multi_posting_structured_payload_normalizes_traceability_fields() -> None:
    client = _build_client_with_session(FakeUploadWarningSession())

    response = client.get(
        "/admin/upload-warnings?warning_type=unmatched_multi_posting",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    row = response.json()[0]
    assert row["warning_type"] == "unmatched_multi_posting"
    assert row["severity"] == "critical"
    assert row["resident_name"] == "Resident A"
    assert row["mcr"] == "M00001A"
    assert row["programme_code"] == "GRM"
    assert row["posting_codes"] == ["TTSHGerMed", "KTPHGerMed"]
    assert row["month_label"] == "May-26"
    assert row["sheet_name"] == "Phase 3"
    assert row["row_number"] == 42
    assert row["cell_ref"] == "J42"
    assert row["source_label"] == "Sheet Phase 3:R42:J42"


def test_unknown_loa_types_string_array_normalizes_individual_warning_rows() -> None:
    client = _build_client_with_session(FakeUploadWarningSession())

    response = client.get(
        "/admin/upload-warnings?warning_type=unknown_loa_types",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["message"] == "Exam Leave"
    assert rows[0]["raw_payload"] == "Exam Leave"


def test_mcr_not_found_warnings_string_array_normalizes_individual_warning_rows() -> None:
    client = _build_client_with_session(FakeUploadWarningSession())

    response = client.get(
        "/admin/upload-warnings?warning_type=mcr_not_found",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["message"] == "M99999Z not found in residents"
    assert rows[0]["mcr"] == "M99999Z"


def test_orphaned_attendance_dict_payload_normalizes_relevant_fields() -> None:
    client = _build_client_with_session(FakeUploadWarningSession())

    response = client.get(
        "/admin/upload-warnings?warning_type=orphaned_attendance",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    row = response.json()[0]
    assert row["severity"] == "warning"
    assert row["programme_code"] == "GRM"
    assert row["session_type"] == "Case-based Teaching [1h]"
    assert row["count"] == 3


def test_duplicate_mcr_errors_normalizes_as_critical_severity() -> None:
    client = _build_client_with_session(FakeUploadWarningSession())

    response = client.get(
        "/admin/upload-warnings?warning_type=duplicate_mcr_error",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    row = response.json()[0]
    assert row["warning_type"] == "duplicate_mcr_error"
    assert row["severity"] == "critical"


def test_generic_summary_warnings_entries_are_not_dropped() -> None:
    client = _build_client_with_session(FakeUploadWarningSession())

    response = client.get(
        "/admin/upload-warnings?warning_type=generic_payload",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    assert response.json()[0]["message"] == "Unknown dict warning should remain visible."


def test_endpoint_does_not_mutate_upload_logs() -> None:
    session = FakeUploadWarningSession()
    client = _build_client_with_session(session)

    response = client.get("/admin/upload-warnings", headers=_admin_headers(scope=None, master=True))

    assert response.status_code == 200
    assert session.upload_logs == session.original_upload_logs


def test_warning_id_is_stable_across_repeated_calls() -> None:
    client = _build_client_with_session(FakeUploadWarningSession())
    headers = _admin_headers(scope=None, master=True)

    first = client.get("/admin/upload-warnings", headers=headers)
    second = client.get("/admin/upload-warnings", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert [row["warning_id"] for row in first.json()] == [
        row["warning_id"] for row in second.json()
    ]


def test_same_form_f1_mcr_not_found_across_upload_logs_returns_one_latest_row() -> None:
    session = FakeUploadWarningSession()
    session.upload_logs = []
    older_at = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    newer_at = datetime(2026, 5, 19, 11, 30, tzinfo=timezone.utc)
    older = session.add_upload_log(
        upload_type="form_f1",
        uploaded_at=older_at,
        summary={"mcr_not_found_warnings": ["M62988Z not found in residents"]},
    )
    newer = session.add_upload_log(
        upload_type="form_f1",
        uploaded_at=newer_at,
        summary={"mcr_not_found_warnings": ["M62988Z not found in residents"]},
    )
    client = _build_client_with_session(session)

    response = client.get(
        "/admin/upload-warnings?mode=history&warning_type=mcr_not_found",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["upload_log_id"] == newer["id"]
    assert rows[0]["warning_id"].startswith(newer["id"])
    assert rows[0]["dedupe_key"] == "mcr_not_found|form_f1|mcr_not_found|m62988z"
    assert rows[0]["seen_count"] == 2
    assert rows[0]["first_seen_at"] == older_at.isoformat().replace("+00:00", "Z")
    assert rows[0]["last_seen_at"] == newer_at.isoformat().replace("+00:00", "Z")
    assert rows[0]["upload_log_ids"] == [older["id"], newer["id"]]


def test_different_mcrs_and_warning_types_are_not_collapsed() -> None:
    session = FakeUploadWarningSession()
    session.upload_logs = []
    seen_at = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    session.add_upload_log(
        upload_type="form_f1",
        uploaded_at=seen_at,
        summary={
            "mcr_not_found_warnings": [
                "M62988Z not found in residents",
                "M11111A not found in residents",
            ],
            "duplicate_mcr_errors": ["M62988Z appears twice"],
        },
    )
    client = _build_client_with_session(session)

    response = client.get("/admin/upload-warnings", headers=_admin_headers(scope=None, master=True))

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 3
    assert {
        (row["warning_type"], row["mcr"], row["seen_count"])
        for row in rows
    } == {
        ("mcr_not_found", "M62988Z", 1),
        ("mcr_not_found", "M11111A", 1),
        ("duplicate_mcr_error", "M62988Z", 1),
    }


def test_same_unmatched_multi_posting_with_shifted_row_and_cell_collapses() -> None:
    session = FakeUploadWarningSession()
    session.upload_logs = []
    older_at = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    newer_at = datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)
    session.add_upload_log(
        upload_type="rdb",
        uploaded_at=older_at,
        summary={
            "warnings": [
                {
                    "type": "unmatched_multi_posting",
                    "mcr": "M12345A",
                    "programme_code": "GRM",
                    "month_label": "May-26",
                    "posting_codes": ["KTPHGerMed", "TTSHGerMed"],
                    "sheet_name": "Phase 3",
                    "row_number": 42,
                    "cell_ref": "J42",
                    "message": "No multi-posting rule found.",
                }
            ]
        },
    )
    session.add_upload_log(
        upload_type="rdb",
        uploaded_at=newer_at,
        summary={
            "warnings": [
                {
                    "type": "unmatched_multi_posting",
                    "mcr": "M12345A",
                    "programme_code": "GRM",
                    "month_label": "May-26",
                    "posting_codes": ["TTSHGerMed", "KTPHGerMed"],
                    "sheet_name": "Phase 3",
                    "row_number": 57,
                    "cell_ref": "J57",
                    "message": "No multi-posting rule found.",
                }
            ]
        },
    )
    client = _build_client_with_session(session)

    response = client.get(
        "/admin/upload-warnings?mode=history&warning_type=unmatched_multi_posting",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["seen_count"] == 2
    assert rows[0]["row_number"] == 57
    assert rows[0]["cell_ref"] == "J57"
    assert rows[0]["source_label"] == "Sheet Phase 3:R57:J57"


def test_different_unmatched_multi_posting_combinations_do_not_collapse() -> None:
    session = FakeUploadWarningSession()
    session.upload_logs = []
    seen_at = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    session.add_upload_log(
        upload_type="rdb",
        uploaded_at=seen_at,
        summary={
            "warnings": [
                {
                    "type": "unmatched_multi_posting",
                    "mcr": "M12345A",
                    "programme_code": "GRM",
                    "month_label": "May-26",
                    "posting_codes": ["KTPHGerMed", "TTSHGerMed"],
                    "message": "No multi-posting rule found.",
                },
                {
                    "type": "unmatched_multi_posting",
                    "mcr": "M12345A",
                    "programme_code": "GRM",
                    "month_label": "May-26",
                    "posting_codes": ["KTPHGerMed", "TTSHAnaes"],
                    "message": "No multi-posting rule found.",
                },
            ]
        },
    )
    client = _build_client_with_session(session)

    response = client.get(
        "/admin/upload-warnings?warning_type=unmatched_multi_posting",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_programme_pc_dedupes_only_visible_scoped_warnings() -> None:
    session = FakeUploadWarningSession()
    session.upload_logs = []
    older_at = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    newer_at = datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)
    session.add_upload_log(
        upload_type="ttf",
        uploaded_at=older_at,
        programme_code="GRM",
        summary={"warnings": ["Shared warning text"]},
    )
    session.add_upload_log(
        upload_type="ttf",
        uploaded_at=newer_at,
        programme_code="GRM",
        summary={"warnings": ["Shared warning text"]},
    )
    session.add_upload_log(
        upload_type="ttf",
        uploaded_at=newer_at,
        programme_code="REH",
        summary={"warnings": ["Shared warning text"]},
    )
    session.add_upload_log(
        upload_type="public_holidays",
        uploaded_at=newer_at,
        summary={"warnings": ["Shared warning text"]},
    )
    client = _build_client_with_session(session)

    response = client.get("/admin/upload-warnings?mode=history", headers=_admin_headers("GRM"))

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["programme_code"] == "GRM"
    assert rows[0]["seen_count"] == 2
    assert rows[0]["last_seen_at"] == newer_at.isoformat().replace("+00:00", "Z")


def test_master_admin_sees_deduped_global_view() -> None:
    session = FakeUploadWarningSession()
    session.upload_logs = []
    older_at = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    newer_at = datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)
    session.add_upload_log(
        upload_type="public_holidays",
        uploaded_at=older_at,
        summary={"warnings": ["Calendar warning"]},
    )
    session.add_upload_log(
        upload_type="public_holidays",
        uploaded_at=newer_at,
        summary={"warnings": ["Calendar warning"]},
    )
    client = _build_client_with_session(session)

    response = client.get(
        "/admin/upload-warnings?mode=history",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["upload_type"] == "public_holidays"
    assert rows[0]["seen_count"] == 2


def test_default_active_form_f1_returns_latest_upload_for_reporting_period() -> None:
    session = FakeUploadWarningSession()
    session.upload_logs = []
    older_at = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    newer_at = datetime(2026, 5, 19, 11, 30, tzinfo=timezone.utc)
    session.add_upload_log(
        upload_type="form_f1",
        uploaded_at=older_at,
        summary={
            "mcr_not_found_warnings": [
                f"M{number:05d}A not found in residents" for number in range(1, 734)
            ]
        },
    )
    latest = session.add_upload_log(
        upload_type="form_f1",
        uploaded_at=newer_at,
        summary={
            "mcr_not_found_warnings": [
                "M62988Z not found in residents",
                "M62989Z not found in residents",
            ]
        },
    )
    client = _build_client_with_session(session)

    response = client.get(
        "/admin/upload-warnings?upload_type=form_f1",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert {row["upload_log_id"] for row in rows} == {latest["id"]}
    assert {row["mcr"] for row in rows} == {"M62988Z", "M62989Z"}
    assert all(row["seen_count"] == 1 for row in rows)


def test_default_active_ttf_returns_latest_upload_per_period_and_programme() -> None:
    session = FakeUploadWarningSession()
    session.upload_logs = []
    older_at = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    newer_at = datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)
    session.add_upload_log(
        upload_type="ttf",
        uploaded_at=older_at,
        programme_code="GRM",
        summary={"warnings": ["Old GRM TTF warning"]},
    )
    latest_grm = session.add_upload_log(
        upload_type="ttf",
        uploaded_at=newer_at,
        programme_code="GRM",
        summary={"warnings": ["Latest GRM TTF warning"]},
    )
    latest_reh = session.add_upload_log(
        upload_type="ttf",
        uploaded_at=older_at,
        programme_code="REH",
        summary={"warnings": ["Latest REH TTF warning"]},
    )
    client = _build_client_with_session(session)

    response = client.get(
        "/admin/upload-warnings?upload_type=ttf",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    rows = response.json()
    assert {(row["programme_code"], row["message"], row["upload_log_id"]) for row in rows} == {
        ("GRM", "Latest GRM TTF warning", latest_grm["id"]),
        ("REH", "Latest REH TTF warning", latest_reh["id"]),
    }


def test_default_active_rdb_returns_latest_upload_per_reporting_period() -> None:
    session = FakeUploadWarningSession()
    session.upload_logs = []
    period_a = str(uuid4())
    period_b = str(uuid4())
    older_at = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    newer_at = datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)
    session.add_upload_log(
        upload_type="rdb",
        uploaded_at=older_at,
        reporting_period_id=period_a,
        summary={"warnings": ["Old period A RDB warning"]},
    )
    latest_a = session.add_upload_log(
        upload_type="rdb",
        uploaded_at=newer_at,
        reporting_period_id=period_a,
        summary={"warnings": ["Latest period A RDB warning"]},
    )
    latest_b = session.add_upload_log(
        upload_type="rdb",
        uploaded_at=older_at,
        reporting_period_id=period_b,
        summary={"warnings": ["Latest period B RDB warning"]},
    )
    client = _build_client_with_session(session)

    response = client.get(
        "/admin/upload-warnings?upload_type=rdb",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    rows = response.json()
    assert {(row["reporting_period_id"], row["message"], row["upload_log_id"]) for row in rows} == {
        (period_a, "Latest period A RDB warning", latest_a["id"]),
        (period_b, "Latest period B RDB warning", latest_b["id"]),
    }


def test_default_active_public_holidays_returns_latest_global_upload() -> None:
    session = FakeUploadWarningSession()
    session.upload_logs = []
    older_at = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    newer_at = datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)
    session.add_upload_log(
        upload_type="public_holidays",
        uploaded_at=older_at,
        summary={"warnings": ["Old calendar warning"]},
    )
    latest = session.add_upload_log(
        upload_type="public_holidays",
        uploaded_at=newer_at,
        summary={"warnings": ["Latest calendar warning"]},
    )
    client = _build_client_with_session(session)

    response = client.get(
        "/admin/upload-warnings?upload_type=public_holidays",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["message"] == "Latest calendar warning"
    assert rows[0]["upload_log_id"] == latest["id"]


def test_default_active_excludes_failed_upload_logs() -> None:
    session = FakeUploadWarningSession()
    session.upload_logs = []
    older_at = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    newer_at = datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)
    latest_success = session.add_upload_log(
        upload_type="form_f1",
        uploaded_at=older_at,
        status="success",
        summary={"mcr_not_found_warnings": ["M11111A not found in residents"]},
    )
    session.add_upload_log(
        upload_type="form_f1",
        uploaded_at=newer_at,
        status="failed",
        summary={"mcr_not_found_warnings": ["M22222B not found in residents"]},
    )
    client = _build_client_with_session(session)

    response = client.get(
        "/admin/upload-warnings?upload_type=form_f1",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["upload_log_id"] == latest_success["id"]
    assert rows[0]["mcr"] == "M11111A"


def test_history_mode_still_returns_all_deduped_historical_logical_warnings() -> None:
    session = FakeUploadWarningSession()
    session.upload_logs = []
    older_at = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    newer_at = datetime(2026, 5, 19, 11, 30, tzinfo=timezone.utc)
    session.add_upload_log(
        upload_type="form_f1",
        uploaded_at=older_at,
        summary={
            "mcr_not_found_warnings": [
                "M62988Z not found in residents",
                "M11111A not found in residents",
            ]
        },
    )
    session.add_upload_log(
        upload_type="form_f1",
        uploaded_at=newer_at,
        summary={"mcr_not_found_warnings": ["M62988Z not found in residents"]},
    )
    client = _build_client_with_session(session)

    response = client.get(
        "/admin/upload-warnings?mode=history&upload_type=form_f1",
        headers=_admin_headers(scope=None, master=True),
    )

    assert response.status_code == 200
    rows = response.json()
    assert {row["mcr"] for row in rows} == {"M62988Z", "M11111A"}
    assert {row["mcr"]: row["seen_count"] for row in rows} == {"M62988Z": 2, "M11111A": 1}


def test_programme_pc_sees_only_active_scoped_programme_warnings() -> None:
    session = FakeUploadWarningSession()
    session.upload_logs = []
    older_at = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    newer_at = datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)
    session.add_upload_log(
        upload_type="ttf",
        uploaded_at=older_at,
        programme_code="GRM",
        summary={"warnings": ["Old GRM TTF warning"]},
    )
    latest_grm = session.add_upload_log(
        upload_type="ttf",
        uploaded_at=newer_at,
        programme_code="GRM",
        summary={"warnings": ["Latest GRM TTF warning"]},
    )
    session.add_upload_log(
        upload_type="ttf",
        uploaded_at=newer_at,
        programme_code="REH",
        summary={"warnings": ["Latest REH TTF warning"]},
    )
    session.add_upload_log(
        upload_type="public_holidays",
        uploaded_at=newer_at,
        summary={"warnings": ["Global calendar warning"]},
    )
    client = _build_client_with_session(session)

    response = client.get("/admin/upload-warnings", headers=_admin_headers("GRM"))

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["programme_code"] == "GRM"
    assert rows[0]["message"] == "Latest GRM TTF warning"
    assert rows[0]["upload_log_id"] == latest_grm["id"]
    assert rows[0]["seen_count"] == 1
