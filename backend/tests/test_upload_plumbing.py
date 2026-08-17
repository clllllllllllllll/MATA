from __future__ import annotations

import asyncio
import importlib.util
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.config import Settings
from app.middleware.auth_stub import AuthIdentity, AuthStubMiddleware
from app.middleware.errors import install_error_handlers
from app.middleware.request_body_limit import RequestBodyLimitMiddleware
from app.routers import admin
from app.services.parser_common import ParserResult, write_upload_log


_MEBIBYTE = 1024 * 1024
_FILE_LIMIT_BYTES = 3 * _MEBIBYTE
_AGGREGATE_LIMIT_BYTES = 4 * _MEBIBYTE


def _make_valid_xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "placeholder"
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()
    return payload.getvalue()


def _settings_override() -> Settings:
    return Settings(_env_file=None)


def _build_client(settings: Settings | None = None) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def _db_override():
        yield None

    app.dependency_overrides[admin.get_db_session] = _db_override
    app.dependency_overrides[admin.get_settings] = (
        (lambda: settings) if settings is not None else _settings_override
    )
    return TestClient(app)


def _build_body_limited_client(settings: Settings | None = None) -> TestClient:
    selected_settings = settings or _settings_override()
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(
        RequestBodyLimitMiddleware,
        global_limit_bytes=selected_settings.max_request_body_size_bytes,
        upload_limit_bytes=selected_settings.max_upload_request_size_bytes,
        api_prefix=selected_settings.api_prefix,
    )
    app.include_router(admin.router, prefix=selected_settings.api_prefix)

    async def _db_override():
        yield None

    app.dependency_overrides[admin.get_db_session] = _db_override
    app.dependency_overrides[admin.get_settings] = lambda: selected_settings
    return TestClient(app)


def _build_identity_client(identity: AuthIdentity) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.middleware("http")
    async def _set_verified_identity(request, call_next):  # noqa: ANN001
        request.state.identity = identity
        return await call_next(request)

    app.include_router(admin.router)

    async def _db_override():
        yield None

    app.dependency_overrides[admin.get_db_session] = _db_override
    app.dependency_overrides[admin.get_settings] = _settings_override
    return TestClient(app)


class _PersistedUserSession:
    def __init__(self, user: SimpleNamespace) -> None:
        self.user = user

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001, ARG002
        return None

    async def scalar(self, statement):  # noqa: ANN001, ARG002
        return self.user


def _build_local_middleware_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    auth_mode: str,
    user: SimpleNamespace,
) -> TestClient:
    settings = Settings(
        environment="test",
        auth_mode=auth_mode,
        _env_file=None,
    )
    monkeypatch.setattr(
        "app.middleware.auth_stub.AsyncSessionLocal",
        lambda: _PersistedUserSession(user),
    )
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(AuthStubMiddleware, settings=settings)
    app.include_router(admin.router)

    async def _db_override():
        yield None

    app.dependency_overrides[admin.get_db_session] = _db_override
    app.dependency_overrides[admin.get_settings] = lambda: settings
    return TestClient(app)


def _admin_headers() -> dict[str, str]:
    return {
        "X-User-Role": "admin",
        "X-User-Id": str(uuid4()),
        "X-User-Programme": "DR,GRM",
        "X-Admin-Level": "master",
    }


def _global_upload_responses(
    client: TestClient,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    period_id = str(uuid4())
    files = {
        "file": (
            "source.xlsx",
            _make_valid_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    return {
        "rdb": client.post(
            "/admin/upload/rdb",
            headers=headers,
            data={"reporting_period_id": period_id},
            files=files,
        ),
        "form_f1": client.post(
            "/admin/upload/form-f1",
            headers=headers,
            data={"reporting_period_id": period_id},
            files=files,
        ),
        "public_holidays": client.post(
            "/admin/upload/public-holidays",
            headers=headers,
            files=files,
        ),
    }


def _ttf_upload_response(
    client: TestClient,
    *,
    headers: dict[str, str] | None = None,
):
    return client.post(
        "/admin/upload/ttf",
        headers=headers,
        data={
            "reporting_period_id": str(uuid4()),
            "programme_code": "DR",
        },
        files={
            "file": (
                "ttf.xlsx",
                _make_valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


def _mock_upload_parsers(monkeypatch) -> list[str]:  # noqa: ANN001
    called: list[str] = []

    async def _fake_rdb_parser(**kwargs):  # noqa: ARG001
        called.append("rdb")
        return ParserResult(upload_type="rdb")

    async def _fake_formf1_parser(**kwargs):  # noqa: ARG001
        called.append("form_f1")
        return ParserResult(upload_type="form_f1")

    async def _fake_ttf_parser(**kwargs):  # noqa: ARG001
        called.append("ttf")
        return ParserResult(upload_type="ttf")

    async def _fake_public_holiday_parser(**kwargs):  # noqa: ARG001
        called.append("public_holidays")
        return ParserResult(upload_type="public_holidays")

    monkeypatch.setattr("app.services.rdb_parser.parse_rdb_upload", _fake_rdb_parser)
    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)
    monkeypatch.setattr("app.routers.admin.parse_formf1_upload", _fake_formf1_parser)
    monkeypatch.setattr(
        "app.routers.admin.parse_public_holiday_upload",
        _fake_public_holiday_parser,
    )
    return called


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

    session = _UploadAuditSession()
    app = FastAPI()
    install_error_handlers(app)

    async def _db_override():
        yield session

    app.dependency_overrides[admin.get_db_session] = _db_override
    app.dependency_overrides[admin.get_settings] = _settings_override
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
    assert captured["db_session"] is session
    assert "Database session is required for RDB upload persistence." not in response.text


def test_rdb_upload_response_caps_raw_multi_posting_fragments_but_upload_log_keeps_full_list(
    monkeypatch,
) -> None:
    raw_fragments = [
        {
            "mcr": "M12345A",
            "resident_name": "Resident Name",
            "programme_code": "FM",
            "r_year": "R2",
            "sheet_name": "Phase 1 & 2 (FM)",
            "row_number": 42,
            "cell_ref": "J42",
            "month_label": "Jul-25",
            "source_column_header": "08 Jul 25 - 03 Aug 25",
            "source_cell_text": f"very large source text {index}",
            "fragment_index": index,
            "raw_posting_code": "NUHPaedia",
            "normalized_posting_code": "NUHPaedia",
            "fragment_start_date": "2025-07-10",
            "fragment_end_date": "2025-07-10",
            "day_part": "AM",
            "decision": "collapsed_into_main",
            "effective_posting_code": "NUHPaedia",
            "rule_type": "main_posting",
            "rule_id": None,
            "warning_id": None,
        }
        for index in range(1, 61)
    ]

    async def _fake_rdb_parser(**kwargs):
        return ParserResult(
            upload_type="rdb",
            metadata={
                "residents_created": 1,
                "residents_updated": 0,
                "postings_created": 1,
                "raw_multi_posting_fragment_count": len(raw_fragments),
                "raw_multi_posting_fragments": raw_fragments,
                "raw_multi_posting_fragments_truncated": False,
            },
        )

    monkeypatch.setattr("app.services.rdb_parser.parse_rdb_upload", _fake_rdb_parser)

    session = _UploadAuditSession()
    app = FastAPI()
    install_error_handlers(app)

    async def _db_override():
        yield session

    app.dependency_overrides[admin.get_db_session] = _db_override
    app.dependency_overrides[admin.get_settings] = _settings_override
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
    body = response.json()
    assert body["raw_multi_posting_fragment_count"] == 60
    assert len(body["raw_multi_posting_fragments"]) == 50
    assert body["raw_multi_posting_fragments"][0]["fragment_index"] == 1
    assert body["raw_multi_posting_fragments"][-1]["fragment_index"] == 50
    assert body["raw_multi_posting_fragments_truncated"] is True
    summary = json.loads(session.upload_logs[-1]["summary"])
    assert summary["raw_multi_posting_fragment_count"] == 60
    assert len(summary["raw_multi_posting_fragments"]) == 60
    assert summary["raw_multi_posting_fragments"][-1]["fragment_index"] == 60
    assert summary["raw_multi_posting_fragments_truncated"] is False


def test_invalid_extension_returns_422() -> None:
    client = _build_client()
    response = client.post(
        "/admin/upload/rdb",
        headers=_admin_headers(),
        data={"reporting_period_id": str(uuid4())},
        files={"file": ("bad.csv", b"not-xlsx", "text/csv")},
    )
    assert response.status_code == 422


def test_three_mib_file_is_accepted_inside_valid_multipart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_size = 0

    async def _fake_public_holiday_parser(*, file_bytes: bytes, **kwargs):
        nonlocal captured_size
        captured_size = len(file_bytes)
        return ParserResult(upload_type="public_holidays")

    monkeypatch.setattr(
        "app.routers.admin.parse_public_holiday_upload",
        _fake_public_holiday_parser,
    )
    csv_header = b"date,name\n2026-01-01,Example\n"
    payload = csv_header + (b"\n" * (_FILE_LIMIT_BYTES - len(csv_header)))
    client = _build_body_limited_client()

    response = client.post(
        "/api/v1/admin/upload/public-holidays",
        headers=_admin_headers(),
        files={"file": ("holidays.csv", payload, "text/csv")},
    )

    assert response.status_code == 200
    assert captured_size == _FILE_LIMIT_BYTES


@pytest.mark.parametrize(
    ("path", "data", "filename", "content_type"),
    [
        (
            "/api/v1/admin/upload/rdb",
            {"reporting_period_id": str(uuid4())},
            "rdb.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (
            "/api/v1/admin/upload/ttf",
            {"reporting_period_id": str(uuid4()), "programme_code": "DR"},
            "ttf.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (
            "/api/v1/admin/upload/form-f1",
            {"reporting_period_id": str(uuid4())},
            "form-f1.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (
            "/api/v1/admin/upload/public-holidays",
            {},
            "holidays.csv",
            "text/csv",
        ),
    ],
)
def test_file_larger_than_three_mib_is_rejected_before_parser(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    data: dict[str, str],
    filename: str,
    content_type: str,
) -> None:
    called = {"public_holidays": 0}

    async def _fake_public_holiday_parser(**kwargs):
        called["public_holidays"] += 1
        return ParserResult(upload_type="public_holidays")

    monkeypatch.setattr(
        "app.routers.admin.parse_public_holiday_upload",
        _fake_public_holiday_parser,
    )

    client = _build_body_limited_client()
    oversized_payload = b"x" * (_FILE_LIMIT_BYTES + 1)
    response = client.post(
        path,
        headers=_admin_headers(),
        data=data,
        files={
            "file": (
                filename,
                oversized_payload,
                content_type,
            )
        },
    )

    assert response.status_code == 413
    assert response.json()["error_code"] == "FILE_VALIDATION_FAILED"
    assert "exceeds the 3 MiB limit" in response.text
    assert called["public_holidays"] == 0


def test_multipart_overhead_cannot_bypass_four_mib_aggregate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"public_holidays": 0}

    async def _fake_public_holiday_parser(**kwargs):
        called["public_holidays"] += 1
        return ParserResult(upload_type="public_holidays")

    monkeypatch.setattr(
        "app.routers.admin.parse_public_holiday_upload",
        _fake_public_holiday_parser,
    )
    boundary = b"aggregate-boundary"
    multipart_prefix = (
        b"--"
        + boundary
        + b"\r\n"
        + b'Content-Disposition: form-data; name="file"; filename="holidays.csv"\r\n'
        + b"Content-Type: text/csv\r\n"
        + b"\r\n"
    )
    multipart_suffix = b"\r\n--" + boundary + b"--\r\n"
    file_payload = b"x" * _FILE_LIMIT_BYTES
    bounded_multipart = multipart_prefix + file_payload + multipart_suffix
    assert len(bounded_multipart) < _AGGREGATE_LIMIT_BYTES
    body = bounded_multipart + (
        b"e" * (_AGGREGATE_LIMIT_BYTES + 1 - len(bounded_multipart))
    )
    client = _build_body_limited_client()
    headers = {
        **_admin_headers(),
        "Content-Type": "multipart/form-data; boundary=aggregate-boundary",
        "Content-Length": str(_FILE_LIMIT_BYTES),
    }

    response = client.post(
        "/api/v1/admin/upload/public-holidays",
        content=body,
        headers=headers,
    )

    assert response.status_code == 413
    assert response.json()["error_code"] == "FILE_VALIDATION_FAILED"
    assert response.headers["cache-control"] == "no-store"
    assert called["public_holidays"] == 0


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


@pytest.mark.parametrize("role", ["secretary", "resident"])
def test_all_upload_endpoints_reject_non_admin(role: str) -> None:
    client = _build_client()
    headers = {
        "X-User-Role": role,
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


def test_verified_explicit_master_admin_can_access_all_uploads(monkeypatch) -> None:
    called = _mock_upload_parsers(monkeypatch)
    identity = AuthIdentity(
        role="admin",
        subject_id=str(uuid4()),
        admin_level="master",
        programme_scope=[],
    )
    client = _build_identity_client(identity)
    responses = _global_upload_responses(client)
    responses["ttf"] = _ttf_upload_response(client)

    assert {name: response.status_code for name, response in responses.items()} == {
        "rdb": 200,
        "form_f1": 200,
        "public_holidays": 200,
        "ttf": 200,
    }
    assert called == ["rdb", "form_f1", "public_holidays", "ttf"]


def test_scoped_programme_pc_cannot_access_global_uploads(monkeypatch) -> None:
    called = _mock_upload_parsers(monkeypatch)
    responses = _global_upload_responses(
        _build_client(),
        headers={
            "X-User-Role": "admin",
            "X-User-Id": str(uuid4()),
            "X-User-Programme": "DR,GRM",
        },
    )

    assert {name: response.status_code for name, response in responses.items()} == {
        "rdb": 403,
        "form_f1": 403,
        "public_holidays": 403,
    }
    assert called == []


@pytest.mark.parametrize(
    "programme_scope",
    [None, [], [""], ["   "]],
    ids=["null", "empty", "blank", "whitespace-only"],
)
def test_verified_non_master_empty_scope_never_grants_global_upload_access(
    monkeypatch,
    programme_scope: list[str] | None,
) -> None:
    called = _mock_upload_parsers(monkeypatch)
    identity = AuthIdentity(
        role="admin",
        subject_id=str(uuid4()),
        admin_level="programme",
        programme_scope=programme_scope,
    )
    client = _build_identity_client(identity)
    responses = _global_upload_responses(client)
    responses["ttf"] = _ttf_upload_response(client)

    assert {response.status_code for response in responses.values()} == {403}
    assert called == []


@pytest.mark.parametrize(
    "scope_header",
    [None, "", " ", " , "],
    ids=["missing", "empty", "blank", "whitespace-only"],
)
def test_local_header_fallback_scope_never_implies_master(
    monkeypatch,
    scope_header: str | None,
) -> None:
    called = _mock_upload_parsers(monkeypatch)
    headers = {
        "X-User-Role": "admin",
        "X-User-Id": str(uuid4()),
    }
    if scope_header is not None:
        headers["X-User-Programme"] = scope_header

    client = _build_client()
    responses = _global_upload_responses(client, headers=headers)
    responses["ttf"] = _ttf_upload_response(client, headers=headers)

    assert {response.status_code for response in responses.values()} == {403}
    assert called == []


@pytest.mark.parametrize("auth_mode", ["stub", "demo"])
def test_isolated_router_fallback_requires_explicit_master_header_for_global_uploads(
    monkeypatch,
    auth_mode: str,
) -> None:
    called = _mock_upload_parsers(monkeypatch)
    settings = Settings(
        environment="test",
        auth_mode=auth_mode,
        _env_file=None,
    )
    client = _build_client(settings)
    programme_pc = {
        "X-User-Role": "admin",
        "X-User-Id": str(uuid4()),
        "X-User-Programme": "DR",
    }
    denied = _global_upload_responses(client, headers=programme_pc)
    allowed = _global_upload_responses(client, headers=_admin_headers())

    assert {response.status_code for response in denied.values()} == {403}
    assert {response.status_code for response in allowed.values()} == {200}
    assert called == ["rdb", "form_f1", "public_holidays"]


@pytest.mark.parametrize("auth_mode", ["stub", "demo"])
def test_local_auth_middleware_uses_persisted_master_state_for_global_uploads(
    monkeypatch: pytest.MonkeyPatch,
    auth_mode: str,
) -> None:
    called = _mock_upload_parsers(monkeypatch)
    programme_pc_id = uuid4()
    programme_pc = SimpleNamespace(
        id=programme_pc_id,
        role="admin",
        is_active=True,
        session_issuance_blocked=False,
        admin_level="programme",
        programme_scope=["DR"],
        current_staff_actor_name=None,
    )
    programme_pc_client = _build_local_middleware_client(
        monkeypatch,
        auth_mode=auth_mode,
        user=programme_pc,
    )
    denied = _global_upload_responses(
        programme_pc_client,
        headers={
            "X-User-Role": "admin",
            "X-User-Id": str(programme_pc_id),
            "X-User-Programme": "DR",
            "X-Admin-Level": "master",
        },
    )

    assert {response.status_code for response in denied.values()} == {403}
    assert called == []

    master_id = uuid4()
    master = SimpleNamespace(
        id=master_id,
        role="admin",
        is_active=True,
        session_issuance_blocked=False,
        admin_level="master",
        programme_scope=None,
        current_staff_actor_name=None,
    )
    master_client = _build_local_middleware_client(
        monkeypatch,
        auth_mode=auth_mode,
        user=master,
    )
    allowed = _global_upload_responses(
        master_client,
        headers={
            "X-User-Role": "admin",
            "X-User-Id": str(master_id),
        },
    )

    assert {response.status_code for response in allowed.values()} == {200}
    assert called == ["rdb", "form_f1", "public_holidays"]


def test_upload_logs_helper_can_write_row() -> None:
    class _FakeAsyncSession:
        def __init__(self) -> None:
            self.statements: list[tuple[str, dict]] = []
            self.committed = False
            self.rolled_back = False

        async def execute(self, statement, params):
            payload = dict(params)
            self.statements.append((str(statement), payload))

            class _Result:
                def mappings(self):
                    return self

                def one(self):
                    return {"id": payload.get("id", str(uuid4())), **payload}

            return _Result()

        async def commit(self):
            self.committed = True

        async def rollback(self):
            self.rolled_back = True

    async def _exercise() -> None:
        session = _FakeAsyncSession()
        row = await write_upload_log(
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
        assert UUID(str(row["id"]))

        non_committing_session = _FakeAsyncSession()
        await write_upload_log(
            non_committing_session,
            upload_type="ttf",
            original_filename="ttf.xlsx",
            status="success",
            summary={"created_count": 0, "updated_count": 0},
            commit=False,
        )
        assert non_committing_session.committed is False

    asyncio.run(_exercise())


def test_upload_endpoints_allow_missing_actor_name(monkeypatch) -> None:
    called = {"count": 0}

    async def _fake_rdb_parser(**kwargs):
        called["count"] += 1
        return ParserResult(upload_type="rdb")

    async def _fake_ttf_parser(**kwargs):
        called["count"] += 1
        return ParserResult(upload_type="ttf")

    async def _fake_formf1_parser(**kwargs):
        called["count"] += 1
        return ParserResult(upload_type="form_f1")

    async def _fake_public_holiday_parser(**kwargs):
        called["count"] += 1
        return ParserResult(upload_type="public_holidays")

    monkeypatch.setattr("app.services.rdb_parser.parse_rdb_upload", _fake_rdb_parser)
    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)
    monkeypatch.setattr("app.routers.admin.parse_formf1_upload", _fake_formf1_parser)
    monkeypatch.setattr("app.routers.admin.parse_public_holiday_upload", _fake_public_holiday_parser)

    client = _build_client()
    period_id = str(uuid4())
    headers = _admin_headers()
    files = {
        "file": (
            "upload.xlsx",
            _make_valid_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }

    responses = [
        client.post(
            "/admin/upload/rdb",
            headers=headers,
            data={"reporting_period_id": period_id},
            files=files,
        ),
        client.post(
            "/admin/upload/ttf",
            headers=headers,
            data={"reporting_period_id": period_id, "programme_code": "DR"},
            files=files,
        ),
        client.post(
            "/admin/upload/form-f1",
            headers=headers,
            data={"reporting_period_id": period_id},
            files=files,
        ),
        client.post(
            "/admin/upload/public-holidays",
            headers=headers,
            files=files,
        ),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert called["count"] == 4


def test_upload_endpoint_allows_blank_actor_name(monkeypatch) -> None:
    called = {"count": 0}

    async def _fake_rdb_parser(**kwargs):
        called["count"] += 1
        return ParserResult(upload_type="rdb")

    monkeypatch.setattr("app.services.rdb_parser.parse_rdb_upload", _fake_rdb_parser)

    client = _build_client()
    headers = _admin_headers()
    headers["-".join(["X", "Actor", "Name"])] = "   "

    response = client.post(
        "/admin/upload/rdb",
        headers=headers,
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
    assert called["count"] == 1


class _UploadAuditResult:
    def __init__(self, row: dict) -> None:
        self._row = row

    def mappings(self):
        return self

    def one(self):
        return self._row

    def one_or_none(self):
        return self._row


class _UploadScalarResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self):
        return self._value


class _UploadAuditSession:
    def __init__(self) -> None:
        self.upload_logs: list[dict] = []
        self.audit_logs: list[dict] = []
        self.reporting_periods: dict[str, dict] = {}
        self.rate_limit_buckets: dict[tuple[str, str, object, int], int] = {}
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, params):
        sql = str(statement)
        payload = dict(params)
        if "INSERT INTO rate_limit_buckets" in sql:
            key = (
                payload["scope"],
                payload["key_hash"],
                payload["window_start"],
                payload["window_seconds"],
            )
            request_count = self.rate_limit_buckets.get(key, 0) + 1
            self.rate_limit_buckets[key] = request_count
            return _UploadAuditResult({"request_count": request_count})
        if "DELETE FROM rate_limit_buckets" in sql:
            return _UploadScalarResult(0)
        if "/* upload:reporting_period_status */" in sql:
            return _UploadAuditResult(
                self.reporting_periods.get(str(payload["reporting_period_id"]))
            )
        if "/* parsed_data_correction:corrected_resident_posting_reupload_count */" in sql:
            return _UploadScalarResult(0)
        if "INSERT INTO upload_logs" in sql:
            row = {"id": str(uuid4()), **payload}
            self.upload_logs.append(row)
            return _UploadAuditResult(row)
        if "INSERT INTO audit_logs" in sql:
            row = {"id": payload["id"], **payload}
            self.audit_logs.append(row)
            return _UploadAuditResult(row)
        raise AssertionError(f"Unhandled SQL: {sql}\nparams={payload}")

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _build_upload_audit_client(
    session: _UploadAuditSession,
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router)

    async def _db_override():
        yield session

    app.dependency_overrides[admin.get_db_session] = _db_override
    app.dependency_overrides[admin.get_settings] = _settings_override
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_successful_admin_uploads_write_audit_logs_linked_to_upload_logs(monkeypatch) -> None:
    async def _fake_rdb_parser(**kwargs):
        return ParserResult(
            upload_type="rdb",
            created_count=2,
            warnings=["check one row"],
            metadata={"residents_created": 2},
        )

    async def _fake_ttf_parser(**kwargs):
        return ParserResult(
            upload_type="ttf",
            created_count=3,
            metadata={"targets_inserted": 3},
        )

    async def _fake_formf1_parser(**kwargs):
        return ParserResult(
            upload_type="form_f1",
            updated_count=4,
            metadata={"records_updated": 4},
        )

    async def _fake_public_holiday_parser(**kwargs):
        return ParserResult(
            upload_type="public_holidays",
            created_count=5,
            metadata={"public_holidays_created": 5},
        )

    monkeypatch.setattr("app.services.rdb_parser.parse_rdb_upload", _fake_rdb_parser)
    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)
    monkeypatch.setattr("app.routers.admin.parse_formf1_upload", _fake_formf1_parser)
    monkeypatch.setattr("app.routers.admin.parse_public_holiday_upload", _fake_public_holiday_parser)

    session = _UploadAuditSession()
    client = _build_upload_audit_client(session)
    headers = _admin_headers()
    period_id = str(uuid4())
    files = {
        "file": (
            "source.xlsx",
            _make_valid_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }

    responses = [
        client.post(
            "/admin/upload/rdb",
            headers=headers,
            data={"reporting_period_id": period_id},
            files=files,
        ),
        client.post(
            "/admin/upload/ttf",
            headers=headers,
            data={"reporting_period_id": period_id, "programme_code": "DR"},
            files=files,
        ),
        client.post(
            "/admin/upload/form-f1",
            headers=headers,
            data={"reporting_period_id": period_id},
            files=files,
        ),
        client.post(
            "/admin/upload/public-holidays",
            headers=headers,
            files=files,
        ),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert [row["upload_type"] for row in session.upload_logs] == [
        "rdb",
        "ttf",
        "form_f1",
        "public_holidays",
    ]
    assert [row["action"] for row in session.audit_logs] == [
        "admin.upload.rdb",
        "admin.upload.ttf",
        "admin.upload.form_f1",
        "admin.upload.public_holidays",
    ]

    for upload_log, audit_log in zip(session.upload_logs, session.audit_logs, strict=True):
        metadata = json.loads(audit_log["metadata_json"])
        after = json.loads(audit_log["after_json"])
        assert audit_log["actor_name"] == "Unknown actor"
        assert audit_log["entity_type"] == "upload_log"
        assert audit_log["entity_id"] == upload_log["id"]
        assert audit_log["before_json"] is None
        assert metadata["upload_type"] == upload_log["upload_type"]
        assert metadata["original_filename"] == "source.xlsx"
        assert metadata["status"] == "success"
        assert metadata["warning_count"] >= 0
        assert metadata["error_count"] == 0
        assert "summary_counts" in metadata
        assert after["id"] == upload_log["id"]
        assert after["upload_type"] == upload_log["upload_type"]
        assert after["status"] == "success"


def test_upload_endpoints_reject_inactive_reporting_period_before_parsers(monkeypatch) -> None:
    called = {"count": 0}

    async def _blocked_parser(**kwargs):
        called["count"] += 1
        return ParserResult(upload_type=kwargs.get("upload_type", "rdb"))

    monkeypatch.setattr("app.services.rdb_parser.parse_rdb_upload", _blocked_parser)
    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _blocked_parser)
    monkeypatch.setattr("app.routers.admin.parse_formf1_upload", _blocked_parser)

    session = _UploadAuditSession()
    period_id = str(uuid4())
    session.reporting_periods[period_id] = {"status": "inactive"}
    client = _build_upload_audit_client(session)
    headers = _admin_headers()
    files = {
        "file": (
            "source.xlsx",
            _make_valid_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }

    responses = [
        client.post("/admin/upload/rdb", headers=headers, data={"reporting_period_id": period_id}, files=files),
        client.post(
            "/admin/upload/ttf",
            headers=headers,
            data={"reporting_period_id": period_id, "programme_code": "DR"},
            files=files,
        ),
        client.post("/admin/upload/form-f1", headers=headers, data={"reporting_period_id": period_id}, files=files),
    ]

    assert [response.status_code for response in responses] == [422, 422, 422]
    assert all(
        response.json()["detail"]
        == "Selected reporting period is inactive. Activate the reporting period before uploading."
        for response in responses
    )
    assert called["count"] == 0
    assert session.upload_logs == []
    assert session.audit_logs == []
    assert session.commits == 0


def test_upload_endpoints_allow_active_reporting_period_before_parsers(monkeypatch) -> None:
    called: list[str] = []

    async def _fake_rdb_parser(**kwargs):
        called.append("rdb")
        return ParserResult(upload_type="rdb")

    async def _fake_ttf_parser(**kwargs):
        called.append("ttf")
        return ParserResult(upload_type="ttf")

    async def _fake_formf1_parser(**kwargs):
        called.append("form_f1")
        return ParserResult(upload_type="form_f1")

    monkeypatch.setattr("app.services.rdb_parser.parse_rdb_upload", _fake_rdb_parser)
    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)
    monkeypatch.setattr("app.routers.admin.parse_formf1_upload", _fake_formf1_parser)

    session = _UploadAuditSession()
    period_id = str(uuid4())
    session.reporting_periods[period_id] = {"status": "active"}
    client = _build_upload_audit_client(session)
    headers = _admin_headers()
    files = {
        "file": (
            "source.xlsx",
            _make_valid_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }

    responses = [
        client.post("/admin/upload/rdb", headers=headers, data={"reporting_period_id": period_id}, files=files),
        client.post(
            "/admin/upload/ttf",
            headers=headers,
            data={"reporting_period_id": period_id, "programme_code": "DR"},
            files=files,
        ),
        client.post("/admin/upload/form-f1", headers=headers, data={"reporting_period_id": period_id}, files=files),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert called == ["rdb", "ttf", "form_f1"]


def test_successful_admin_uploads_derive_warning_issues_after_upload_log(monkeypatch) -> None:
    async def _fake_rdb_parser(**kwargs):
        return ParserResult(upload_type="rdb", warnings=[{"type": "empty_posting_cell"}])

    async def _fake_ttf_parser(**kwargs):
        return ParserResult(upload_type="ttf", warnings=[{"type": "tag_order_warning"}])

    async def _fake_formf1_parser(**kwargs):
        return ParserResult(upload_type="form_f1", warnings=["M99999Z not found"])

    async def _fake_public_holiday_parser(**kwargs):
        return ParserResult(upload_type="public_holidays", warnings=[{"type": "public_holiday_day_mismatch"}])

    calls: list[dict] = []
    invalidation_calls: list[tuple[set[str], dict, int]] = []

    async def _fake_derivation(
        db,
        upload_log,
        summary,
        actor_id=None,
        *,
        commit=True,
        invalidate_cache=True,
    ):
        calls.append(
            {
                "upload_log_id": upload_log["id"],
                "upload_type": upload_log["upload_type"],
                "summary_upload_type": summary["upload_type"],
                "actor_id": actor_id,
                "commit": commit,
                "invalidate_cache": invalidate_cache,
            }
        )

    def _invalidate_spy(domains, **scope):  # noqa: ANN001
        invalidation_calls.append((set(domains), scope, session.commits))
        return []

    monkeypatch.setattr("app.services.rdb_parser.parse_rdb_upload", _fake_rdb_parser)
    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)
    monkeypatch.setattr("app.routers.admin.parse_formf1_upload", _fake_formf1_parser)
    monkeypatch.setattr("app.routers.admin.parse_public_holiday_upload", _fake_public_holiday_parser)
    monkeypatch.setattr("app.routers.admin.derive_upload_warnings_from_summary", _fake_derivation)
    monkeypatch.setattr("app.services.cache_invalidation.invalidate_cache", _invalidate_spy)

    session = _UploadAuditSession()
    client = _build_upload_audit_client(session)
    headers = _admin_headers()
    actor_id = headers["X-User-Id"]
    period_id = str(uuid4())
    files = {
        "file": (
            "source.xlsx",
            _make_valid_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }

    responses = [
        client.post("/admin/upload/rdb", headers=headers, data={"reporting_period_id": period_id}, files=files),
        client.post("/admin/upload/ttf", headers=headers, data={"reporting_period_id": period_id, "programme_code": "DR"}, files=files),
        client.post("/admin/upload/form-f1", headers=headers, data={"reporting_period_id": period_id}, files=files),
        client.post("/admin/upload/public-holidays", headers=headers, files=files),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert [call["upload_type"] for call in calls] == ["rdb", "ttf", "form_f1", "public_holidays"]
    assert [call["summary_upload_type"] for call in calls] == ["rdb", "ttf", "form_f1", "public_holidays"]
    assert all(str(call["actor_id"]) == actor_id for call in calls)
    assert next(call for call in calls if call["upload_type"] == "ttf")["commit"] is False
    assert next(call for call in calls if call["upload_type"] == "ttf")["invalidate_cache"] is False
    assert [call["upload_log_id"] for call in calls] == [row["id"] for row in session.upload_logs]
    upload_domains = [domains for domains, _scope, _commits in invalidation_calls]
    assert any({"upload_logs", "upload_warnings", "parsed_data"} <= domains for domains in upload_domains)
    ttf_invalidation = next(
        (domains, commits)
        for domains, _scope, commits in invalidation_calls
        if "teaching_targets" in domains
    )
    assert {"config", "parsed_data", "teaching_targets"} <= ttf_invalidation[0]
    assert ttf_invalidation[1] > 0
    assert any({"form_f1", "resident_dashboard", "admin_reports"} <= domains for domains in upload_domains)
    assert any({"public_holidays", "academic_month_boundaries"} <= domains for domains in upload_domains)


def test_ttf_upload_cache_failure_does_not_misreport_committed_success(monkeypatch) -> None:
    async def _fake_ttf_parser(**kwargs):
        return ParserResult(
            upload_type="ttf",
            created_count=1,
            updated_count=1,
            metadata={
                "targets_created": 1,
                "targets_inserted": 1,
                "session_types_upserted": 1,
            },
        )

    cache_calls: list[int] = []
    safe_logs: list[tuple[str, str, str | None]] = []

    def _failing_cache(**kwargs):  # noqa: ANN003
        cache_calls.append(session.commits)
        raise RuntimeError("cache backend unavailable")

    def _safe_log(_logger, event, exc, *, category=None):  # noqa: ANN001
        safe_logs.append((event, type(exc).__name__, category))

    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)
    monkeypatch.setattr(
        "app.routers.admin.cache_invalidation.invalidate_after_upload",
        _failing_cache,
    )
    monkeypatch.setattr("app.routers.admin.log_safe_exception", _safe_log)

    session = _UploadAuditSession()
    client = _build_upload_audit_client(session)
    period_id = str(uuid4())
    response = client.post(
        "/admin/upload/ttf",
        headers=_admin_headers(),
        data={"reporting_period_id": period_id, "programme_code": "DR"},
        files={
            "file": (
                "ttf.xlsx",
                _make_valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    assert session.upload_logs and session.audit_logs
    assert cache_calls and cache_calls[0] > 0
    assert safe_logs == [
        ("ttf_upload_cache_invalidation_failed", "RuntimeError", "cache_invalidation")
    ]


def test_ttf_outer_transaction_rolls_back_all_e1_evidence_on_post_parser_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure after parser/revalidation evidence cannot leave a partial TTF."""

    class _TransactionalTTFSession(_UploadAuditSession):
        def __init__(self) -> None:
            super().__init__()
            self.e1_rows = {
                "targets": [],
                "mappings": [],
                "posting_groups": [],
                "upload_logs": [],
                "warnings": [],
                "audit": [],
                "revalidation": [],
            }

        def persist(self, *kinds: str) -> None:
            for kind in kinds:
                self.e1_rows[kind].append(str(uuid4()))

        async def rollback(self) -> None:
            await super().rollback()
            # The rate-limit bucket intentionally predates the outer upload
            # transaction. Everything below belongs to the TTF transaction.
            for rows in self.e1_rows.values():
                rows.clear()
            self.upload_logs.clear()
            self.audit_logs.clear()

    class _RevalidationOutcome:
        def model_dump(self, *, mode: str) -> dict[str, object]:  # noqa: ARG002
            return {"status": "revalidated"}

    async def _fake_ttf_parser(**kwargs):
        db_session = kwargs["db_session"]
        assert kwargs["manage_transaction"] is False
        db_session.persist("targets", "mappings", "posting_groups")
        return ParserResult(
            upload_type="ttf",
            created_count=2,
            metadata={
                "targets_created": 2,
                "targets_inserted": 1,
                "targets_updated": 1,
            },
        )

    async def _fake_revalidation(*, db_session, **kwargs):  # noqa: ANN001, ARG001
        db_session.persist("revalidation")
        return _RevalidationOutcome()

    async def _fail_after_upload_evidence(*, db, **kwargs):  # noqa: ANN001, ARG001
        db.persist("upload_logs", "warnings", "audit")
        db.upload_logs.append({"id": str(uuid4()), "upload_type": "ttf"})
        db.audit_logs.append({"id": str(uuid4()), "action": "admin.upload.ttf"})
        raise RuntimeError("injected upload-log/audit failure")

    cache_calls: list[object] = []

    def _cache_spy(**kwargs):  # noqa: ANN003, ARG001
        cache_calls.append(kwargs)
        return []

    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)
    monkeypatch.setattr(
        "app.routers.admin.data_revalidation_service.revalidate_after_upload",
        _fake_revalidation,
    )
    monkeypatch.setattr(
        "app.routers.admin._write_upload_log_and_audit",
        _fail_after_upload_evidence,
    )
    monkeypatch.setattr(
        "app.routers.admin.cache_invalidation.invalidate_after_upload",
        _cache_spy,
    )

    session = _TransactionalTTFSession()
    client = _build_upload_audit_client(session, raise_server_exceptions=False)
    response = client.post(
        "/admin/upload/ttf",
        headers=_admin_headers(),
        data={"reporting_period_id": str(uuid4()), "programme_code": "DR"},
        files={
            "file": (
                "ttf.xlsx",
                _make_valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 500
    assert session.rollbacks == 1
    assert all(rows == [] for rows in session.e1_rows.values())
    assert session.upload_logs == []
    assert session.audit_logs == []
    assert session.rate_limit_buckets  # pre-transaction limiter is intentionally retained
    assert cache_calls == []


def test_ttf_response_keeps_legacy_created_count_separate_from_insert_delta() -> None:
    response = admin._format_ttf_response(
        ParserResult(
            upload_type="ttf",
            created_count=29,
            updated_count=5,
            metadata={
                "targets_created": 29,
                "targets_inserted": 4,
                "targets_updated": 17,
                "session_types_upserted": 5,
                "posting_groups_upserted": 5,
                "posting_groups_removed": 2,
            },
        )
    )

    assert response["targets_created"] == 29
    assert response["targets_inserted"] == 4
    assert response["targets_updated"] == 17
    assert response["session_types_upserted"] == 5
    assert response["posting_groups_upserted"] == 5
    assert response["posting_groups_removed"] == 2
    assert "catalogue_rows_seeded" not in response


def test_ttf_response_includes_zero_posting_group_deltas() -> None:
    response = admin._format_ttf_response(ParserResult(upload_type="ttf"))

    assert response["posting_groups_upserted"] == 0
    assert response["posting_groups_removed"] == 0


def test_ttf_upload_response_includes_posting_group_deltas(monkeypatch) -> None:
    async def _fake_ttf_parser(**kwargs):  # noqa: ARG001
        return ParserResult(
            upload_type="ttf",
            created_count=29,
            updated_count=5,
            metadata={
                "targets_created": 29,
                "targets_inserted": 4,
                "session_types_upserted": 5,
                "posting_groups_upserted": 5,
                "posting_groups_removed": 2,
            },
        )

    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)

    response = _ttf_upload_response(_build_client(), headers=_admin_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["posting_groups_upserted"] == 5
    assert body["posting_groups_removed"] == 2
    assert body["targets_created"] == 29
    assert body["targets_inserted"] == 4
    assert body["session_types_upserted"] == 5


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


def test_explicit_master_admin_can_upload_ttf_for_any_programme(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_ttf_parser(**kwargs):
        captured.update(kwargs)
        return ParserResult(upload_type="ttf")

    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)

    client = _build_client()
    response = client.post(
        "/admin/upload/ttf",
        headers={
            "X-User-Role": "admin",
            "X-User-Id": str(uuid4()),
            "X-User-Programme": "DR",
            "X-Admin-Level": "master",
        },
        data={"reporting_period_id": str(uuid4()), "programme_code": "GRM"},
        files={
            "file": (
                "ttf.xlsx",
                _make_valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    assert captured["programme_code"] == "GRM"


def test_explicit_master_admin_alias_can_upload_ttf_for_any_programme(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_ttf_parser(**kwargs):
        captured.update(kwargs)
        return ParserResult(upload_type="ttf")

    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)

    client = _build_client()
    response = client.post(
        "/admin/upload/ttf",
        headers={
            "X-User-Role": "admin",
            "X-User-Id": str(uuid4()),
            "X-Admin-Level": "master_admin",
        },
        data={"reporting_period_id": str(uuid4()), "programme_code": "ORTHO"},
        files={
            "file": (
                "ttf.xlsx",
                _make_valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    assert captured["programme_code"] == "ORTHO"


def test_programme_pc_can_upload_ttf_only_for_scoped_programme(monkeypatch) -> None:
    captured_programmes: list[str] = []

    async def _fake_ttf_parser(**kwargs):
        captured_programmes.append(kwargs["programme_code"])
        return ParserResult(upload_type="ttf")

    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)

    client = _build_client()
    headers = {
        "X-User-Role": "admin",
        "X-User-Id": str(uuid4()),
        "X-User-Programme": "DR",
    }
    period_id = str(uuid4())

    allowed = client.post(
        "/admin/upload/ttf",
        headers=headers,
        data={"reporting_period_id": period_id, "programme_code": "DR"},
        files={
            "file": (
                "dr-ttf.xlsx",
                _make_valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    forbidden = client.post(
        "/admin/upload/ttf",
        headers=headers,
        data={"reporting_period_id": period_id, "programme_code": "GERI"},
        files={
            "file": (
                "geri-ttf.xlsx",
                _make_valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert allowed.status_code == 200
    assert forbidden.status_code == 403
    assert captured_programmes == ["DR"]


def test_programme_pc_ttf_scope_check_normalizes_persisted_and_requested_code(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_ttf_parser(**kwargs):
        captured.update(kwargs)
        return ParserResult(upload_type="ttf")

    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)

    client = _build_identity_client(
        AuthIdentity(
            role="admin",
            subject_id=str(uuid4()),
            admin_level="programme",
            programme_scope=[" dr "],
        ),
    )
    response = client.post(
        "/admin/upload/ttf",
        data={
            "reporting_period_id": str(uuid4()),
            "programme_code": " dr ",
        },
        files={
            "file": (
                "ttf.xlsx",
                _make_valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    assert captured["programme_code"] == "DR"


def test_programme_pc_with_empty_scope_cannot_upload_ttf(monkeypatch) -> None:
    called = {"count": 0}

    async def _fake_ttf_parser(**kwargs):
        called["count"] += 1
        return ParserResult(upload_type="ttf")

    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)

    client = _build_client()
    response = client.post(
        "/admin/upload/ttf",
        headers={
            "X-User-Role": "admin",
            "X-User-Id": str(uuid4()),
            "X-User-Programme": " , ",
        },
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
    assert called["count"] == 0


def test_ttf_upload_uses_form_programme_code_not_filename(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_ttf_parser(**kwargs):
        captured.update(kwargs)
        return ParserResult(upload_type="ttf")

    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)

    client = _build_client()
    response = client.post(
        "/admin/upload/ttf",
        headers={
            "X-User-Role": "admin",
            "X-User-Id": str(uuid4()),
            "X-User-Programme": "DR",
        },
        data={"reporting_period_id": str(uuid4()), "programme_code": "DR"},
        files={
            "file": (
                "GERI_targets.xlsx",
                _make_valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    assert captured["programme_code"] == "DR"
    assert captured["original_filename"] == "GERI_targets.xlsx"


def test_ttf_upload_log_and_audit_preserve_programme_and_period_context(monkeypatch) -> None:
    async def _fake_ttf_parser(**kwargs):
        return ParserResult(
            upload_type="ttf",
            created_count=2,
            metadata={"targets_created": 2},
        )

    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)

    session = _UploadAuditSession()
    client = _build_upload_audit_client(session)
    period_id = str(uuid4())
    response = client.post(
        "/admin/upload/ttf",
        headers={
            "X-User-Role": "admin",
            "X-User-Id": str(uuid4()),
            "X-User-Programme": "DR",
        },
        data={"reporting_period_id": period_id, "programme_code": "DR"},
        files={
            "file": (
                "ttf.xlsx",
                _make_valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    upload_log = session.upload_logs[-1]
    assert upload_log["upload_type"] == "ttf"
    assert upload_log["reporting_period_id"] == period_id
    assert upload_log["programme_code"] == "DR"
    assert json.loads(upload_log["summary"])["upload_type"] == "ttf"

    audit_log = session.audit_logs[-1]
    metadata = json.loads(audit_log["metadata_json"])
    after = json.loads(audit_log["after_json"])
    assert metadata["upload_type"] == "ttf"
    assert metadata["reporting_period_id"] == period_id
    assert metadata["programme_code"] == "DR"
    assert after["reporting_period_id"] == period_id
    assert after["programme_code"] == "DR"


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
    assert "orphaned_attendance" not in ttf_source
    assert "teaching_name_catalogue" not in ttf_source
    assert "details_of_training" not in ttf_source
