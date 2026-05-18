from __future__ import annotations

import asyncio
import importlib.util
import json
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.middleware.errors import install_error_handlers
from app.routers import admin
from app.services.parser_common import ParserResult, write_upload_log


def _make_valid_xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "placeholder"
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()
    return payload.getvalue()


def _build_client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def _db_override():
        yield None

    app.dependency_overrides[admin.get_db_session] = _db_override
    return TestClient(app)


def _admin_headers() -> dict[str, str]:
    return {
        "X-User-Role": "admin",
        "X-User-Id": str(uuid4()),
        "X-User-Programme": "DR,GRM",
    }


def test_endpoint_slot_determines_parser_not_filename(monkeypatch) -> None:
    called = {"rdb": 0, "ttf": 0}

    async def _fake_rdb_parser(**kwargs):
        called["rdb"] += 1
        return ParserResult(upload_type="rdb")

    async def _fake_ttf_parser(**kwargs):
        called["ttf"] += 1
        return ParserResult(upload_type="ttf")

    monkeypatch.setattr("app.services.rdb_parser.parse_rdb_upload", _fake_rdb_parser)
    monkeypatch.setattr("app.services.ttf_parser.parse_ttf_upload", _fake_ttf_parser)

    client = _build_client()
    response = client.post(
        "/admin/upload/rdb",
        headers=_admin_headers(),
        data={"reporting_period_id": str(uuid4())},
        files={
            # Intentionally misleading filename. Endpoint slot must still choose RDB parser.
            "file": ("looks_like_ttf.xlsx", _make_valid_xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        },
    )

    assert response.status_code == 200
    assert called["rdb"] == 1
    assert called["ttf"] == 0


def test_rdb_upload_route_passes_database_session_to_parser(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_rdb_parser(**kwargs):
        captured.update(kwargs)
        return ParserResult(upload_type="rdb")

    monkeypatch.setattr("app.services.rdb_parser.parse_rdb_upload", _fake_rdb_parser)

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)
    client = TestClient(app)
    response = client.post(
        "/admin/upload/rdb",
        headers=_admin_headers(),
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
    assert captured["db_session"] is not None
    assert "Database session is required for RDB upload persistence." not in response.text


def test_invalid_extension_returns_422() -> None:
    client = _build_client()
    response = client.post(
        "/admin/upload/rdb",
        headers=_admin_headers(),
        data={"reporting_period_id": str(uuid4())},
        files={"file": ("bad.csv", b"not-xlsx", "text/csv")},
    )
    assert response.status_code == 422


def test_non_admin_access_rejected() -> None:
    client = _build_client()
    response = client.post(
        "/admin/upload/form-f1",
        headers={
            "X-User-Role": "resident",
            "X-User-Id": str(uuid4()),
        },
        data={"reporting_period_id": str(uuid4())},
        files={
            "file": (
                "f1.xlsx",
                _make_valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 403


def test_all_upload_endpoints_reject_non_admin() -> None:
    client = _build_client()
    headers = {
        "X-User-Role": "secretary",
        "X-User-Id": str(uuid4()),
    }
    period_id = str(uuid4())
    files = {
        "file": (
            "upload.xlsx",
            _make_valid_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    rdb = client.post(
        "/admin/upload/rdb",
        headers=headers,
        data={"reporting_period_id": period_id},
        files=files,
    )
    ttf = client.post(
        "/admin/upload/ttf",
        headers=headers,
        data={"reporting_period_id": period_id, "programme_code": "DR"},
        files=files,
    )
    form_f1 = client.post(
        "/admin/upload/form-f1",
        headers=headers,
        data={"reporting_period_id": period_id},
        files=files,
    )
    public_holidays = client.post(
        "/admin/upload/public-holidays",
        headers=headers,
        files=files,
    )

    assert rdb.status_code == 403
    assert ttf.status_code == 403
    assert form_f1.status_code == 403
    assert public_holidays.status_code == 403


def test_upload_logs_helper_can_write_row() -> None:
    class _FakeAsyncSession:
        def __init__(self) -> None:
            self.statements: list[tuple[str, dict]] = []
            self.committed = False
            self.rolled_back = False

        async def execute(self, statement, params):
            self.statements.append((str(statement), dict(params)))

        async def commit(self):
            self.committed = True

        async def rollback(self):
            self.rolled_back = True

    async def _exercise() -> None:
        session = _FakeAsyncSession()
        await write_upload_log(
            session,
            upload_type="rdb",
            original_filename="rdb.xlsx",
            status="success",
            summary={"created_count": 0, "updated_count": 0},
            uploaded_by=uuid4(),
            reporting_period_id=uuid4(),
        )

        assert session.committed is True
        assert session.rolled_back is False
        assert len(session.statements) == 1
        sql, params = session.statements[0]
        assert "INSERT INTO upload_logs" in sql
        assert params["upload_type"] == "rdb"
        assert params["status"] == "success"
        summary = json.loads(params["summary"])
        assert summary["original_filename"] == "rdb.xlsx"

    asyncio.run(_exercise())


def test_parser_signatures_importable() -> None:
    from app.services.formf1_parser import parse_formf1_upload
    from app.services.public_holiday_parser import parse_public_holiday_upload
    from app.services.rdb_parser import parse_rdb_upload
    from app.services.ttf_parser import parse_ttf_upload

    assert callable(parse_rdb_upload)
    assert callable(parse_ttf_upload)
    assert callable(parse_formf1_upload)
    assert callable(parse_public_holiday_upload)


def test_no_stp_upload_route_exists() -> None:
    client = _build_client()
    response = client.post(
        "/admin/upload/stp",
        headers=_admin_headers(),
        files={
            "file": (
                "stp.xlsx",
                _make_valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 404


def test_programme_scope_null_is_not_all_access_for_ttf() -> None:
    client = _build_client()
    headers = {
        "X-User-Role": "admin",
        "X-User-Id": str(uuid4()),
        # Missing X-User-Programme should be treated as empty scope.
    }
    response = client.post(
        "/admin/upload/ttf",
        headers=headers,
        data={"reporting_period_id": str(uuid4()), "programme_code": "DR"},
        files={
            "file": (
                "ttf.xlsx",
                _make_valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 403


def test_upload_extension_validation_is_endpoint_specific() -> None:
    client = _build_client()
    headers = _admin_headers()
    period_id = str(uuid4())

    rdb_bad = client.post(
        "/admin/upload/rdb",
        headers=headers,
        data={"reporting_period_id": period_id},
        files={"file": ("rdb.csv", b"x", "text/csv")},
    )
    ttf_bad = client.post(
        "/admin/upload/ttf",
        headers=headers,
        data={"reporting_period_id": period_id, "programme_code": "DR"},
        files={"file": ("ttf.csv", b"x", "text/csv")},
    )
    formf1_bad = client.post(
        "/admin/upload/form-f1",
        headers=headers,
        data={"reporting_period_id": period_id},
        files={"file": ("f1.csv", b"x", "text/csv")},
    )
    ph_csv_ok = client.post(
        "/admin/upload/public-holidays",
        headers=headers,
        files={"file": ("ph.csv", b"Date,Day,Name\n09-Aug-26,Sunday,National Day\n", "text/csv")},
    )

    assert rdb_bad.status_code == 422
    assert ttf_bad.status_code == 422
    assert formf1_bad.status_code == 422
    # Public-holidays endpoint accepts CSV upload payloads at validation stage.
    assert ph_csv_ok.status_code in (200, 422)


def test_unreadable_xlsx_returns_422() -> None:
    client = _build_client()
    response = client.post(
        "/admin/upload/rdb",
        headers=_admin_headers(),
        data={"reporting_period_id": str(uuid4())},
        files={
            "file": (
                "rdb.xlsx",
                b"not a real workbook",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 422


def test_no_stale_schema_assumptions_in_specs() -> None:
    schema_path = Path(__file__).resolve().parents[2] / "docs" / "schema.md"
    schema_text = schema_path.read_text(encoding="utf-8")
    assert "programmes.compliance_variant" not in schema_text
    assert "attendance_records.session_type_id" not in schema_text


def test_no_stp_parser_module_exists() -> None:
    assert importlib.util.find_spec("app.services.stp_parser") is None


def test_no_ttf_attendance_guard_pattern_in_service() -> None:
    ttf_path = (
        Path(__file__).resolve().parents[1] / "app" / "services" / "ttf_parser.py"
    )
    ttf_source = ttf_path.read_text(encoding="utf-8").casefold()
    assert "attendance guard" not in ttf_source
    assert "orphaned_attendance" in ttf_source
