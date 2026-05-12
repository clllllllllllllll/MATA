from __future__ import annotations

import asyncio
import json
from io import BytesIO
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

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
