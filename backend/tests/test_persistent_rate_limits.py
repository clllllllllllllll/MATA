from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from starlette.requests import Request
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.config import Settings
from app.dependencies import persistent_rate_limit as persistent_rate_limit_dependency
from app.middleware.errors import install_error_handlers
from app.middleware import rate_limit as rate_limit_middleware
from app.routers import admin, auth, external_residents
from app.services import persistent_rate_limit
from app.services.parser_common import ParserResult
from tests.resident_fakes import FakeResidentSession, FakeResult


def _settings() -> Settings:
    return Settings(
        environment="test",
        rate_limit_hash_secret="unit-test-rate-limit-hash-secret",
        _env_file=None,
    )


class _RateLimitSession:
    def __init__(self) -> None:
        self.rate_limit_buckets: dict[tuple[str, str, datetime, int], int] = {}
        self.rate_limit_rows: list[dict[str, object]] = []
        self.commits = 0
        self.cleanup_calls = 0
        self.last_sql = ""
        self.last_params: dict[str, object] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def execute(self, statement, params=None):
        sql = str(statement)
        payload = dict(params or {})
        self.last_sql = sql
        self.last_params = payload
        if "INSERT INTO rate_limit_buckets" in sql:
            assert "ON CONFLICT" in sql
            assert "DO UPDATE" in sql
            key = (
                payload["scope"],
                payload["key_hash"],
                payload["window_start"],
                payload["window_seconds"],
            )
            request_count = self.rate_limit_buckets.get(key, 0) + 1
            self.rate_limit_buckets[key] = request_count
            self.rate_limit_rows.append(
                {
                    "scope": payload["scope"],
                    "key_hash": payload["key_hash"],
                    "window_start": payload["window_start"],
                    "window_seconds": payload["window_seconds"],
                    "request_count": request_count,
                    "expires_at": payload["expires_at"],
                }
            )
            return FakeResult(rows=[{"request_count": request_count}])
        if "DELETE FROM rate_limit_buckets" in sql:
            self.cleanup_calls += 1
            return FakeResult(rowcount=0)
        raise AssertionError(f"Unhandled SQL: {sql}\nparams={payload}")

    async def commit(self) -> None:
        self.commits += 1


class _RateLimitResidentSession(FakeResidentSession):
    pass


class _UploadRateLimitSession(_RateLimitSession):
    def __init__(self) -> None:
        super().__init__()
        self.reporting_periods: dict[str, dict[str, object]] = {}
        self.upload_logs: list[dict[str, object]] = []
        self.audit_logs: list[dict[str, object]] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        payload = dict(params or {})
        if "rate_limit_buckets" in sql:
            return await super().execute(statement, params)
        if "/* upload:reporting_period_status */" in sql:
            return FakeResult(
                rows=[
                    self.reporting_periods[str(payload["reporting_period_id"])]
                ]
                if str(payload["reporting_period_id"]) in self.reporting_periods
                else [],
            )
        if "/* parsed_data_correction:corrected_resident_posting_reupload_count */" in sql:
            return FakeResult(scalar=0)
        if "INSERT INTO upload_logs" in sql:
            row = {"id": str(uuid4()), **payload}
            self.upload_logs.append(row)
            return FakeResult(rows=[row])
        if "INSERT INTO audit_logs" in sql:
            row = {"id": payload["id"], **payload}
            self.audit_logs.append(row)
            return FakeResult(rows=[row])
        raise AssertionError(f"Unhandled SQL: {sql}\nparams={payload}")


def _make_valid_xlsx_bytes() -> bytes:
    workbook = Workbook()
    workbook.active["A1"] = "placeholder"
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()
    return payload.getvalue()


def _auth_client(session: _RateLimitResidentSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    async def _db_override():
        yield session

    app.dependency_overrides[auth.get_db_session] = _db_override
    app.dependency_overrides[auth.get_auth_db_session] = _db_override
    app.dependency_overrides[auth.get_settings] = _settings
    app.include_router(auth.router)
    return TestClient(app)


def _external_client(session: _RateLimitResidentSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    async def _db_override():
        yield session

    app.dependency_overrides[external_residents.get_db_session] = _db_override
    app.dependency_overrides[external_residents.get_auth_db_session] = _db_override
    app.dependency_overrides[external_residents.get_settings] = _settings
    app.include_router(external_residents.router)
    return TestClient(app)


def _upload_client(session: _UploadRateLimitSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    async def _db_override():
        yield session

    app.dependency_overrides[admin.get_db_session] = _db_override
    app.dependency_overrides[admin.get_settings] = _settings
    app.include_router(admin.router)
    return TestClient(app)


def _admin_headers(
    user_id: str | None = None,
    programme_scope: str = "DR,GERI",
    *,
    master: bool = False,
) -> dict[str, str]:
    headers = {
        "X-User-Role": "admin",
        "X-User-Id": user_id or str(uuid4()),
        "X-User-Programme": programme_scope,
    }
    if master:
        headers["X-Admin-Level"] = "master"
    return headers


@pytest.mark.asyncio
async def test_service_allows_first_request_at_limit_and_blocks_above_limit() -> None:
    session = _RateLimitSession()
    policy = persistent_rate_limit.RateLimitPolicy(
        scope="auth_login_ip",
        limit=2,
        window_seconds=60,
        message="Too many attempts. Please try again later.",
    )
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)

    first = await persistent_rate_limit.check_rate_limit(
        session,
        settings=_settings(),
        policy=policy,
        identifier="203.0.113.10",
        now=now,
    )
    second = await persistent_rate_limit.check_rate_limit(
        session,
        settings=_settings(),
        policy=policy,
        identifier="203.0.113.10",
        now=now + timedelta(seconds=1),
    )
    third = await persistent_rate_limit.check_rate_limit(
        session,
        settings=_settings(),
        policy=policy,
        identifier="203.0.113.10",
        now=now + timedelta(seconds=2),
    )

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.request_count == 3
    assert 1 <= third.retry_after_seconds <= 60
    assert session.commits == 3


@pytest.mark.asyncio
async def test_service_separate_scopes_and_keys_do_not_collide() -> None:
    session = _RateLimitSession()
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    policy_one = persistent_rate_limit.RateLimitPolicy(
        scope="auth_login_ip",
        limit=1,
        window_seconds=60,
        message="Too many attempts. Please try again later.",
    )
    policy_two = persistent_rate_limit.RateLimitPolicy(
        scope="external_register_ip",
        limit=1,
        window_seconds=60,
        message="Too many registration attempts. Please try again later.",
    )

    await persistent_rate_limit.check_rate_limit(
        session,
        settings=_settings(),
        policy=policy_one,
        identifier="203.0.113.10",
        now=now,
    )

    separate_scope = await persistent_rate_limit.check_rate_limit(
        session,
        settings=_settings(),
        policy=policy_two,
        identifier="203.0.113.10",
        now=now,
    )
    separate_key = await persistent_rate_limit.check_rate_limit(
        session,
        settings=_settings(),
        policy=policy_one,
        identifier="203.0.113.11",
        now=now,
    )

    assert separate_scope.allowed is True
    assert separate_key.allowed is True


@pytest.mark.asyncio
async def test_service_different_fixed_windows_reset_counts() -> None:
    session = _RateLimitSession()
    policy = persistent_rate_limit.RateLimitPolicy(
        scope="auth_login_identifier",
        limit=1,
        window_seconds=60,
        message="Too many attempts. Please try again later.",
    )

    first = await persistent_rate_limit.check_rate_limit(
        session,
        settings=_settings(),
        policy=policy,
        identifier="resident:m12345a",
        now=datetime(2026, 7, 9, 12, 0, 59, tzinfo=UTC),
    )
    reset = await persistent_rate_limit.check_rate_limit(
        session,
        settings=_settings(),
        policy=policy,
        identifier="resident:m12345a",
        now=datetime(2026, 7, 9, 12, 1, 0, tzinfo=UTC),
    )

    assert first.allowed is True
    assert reset.allowed is True
    assert reset.request_count == 1


@pytest.mark.asyncio
async def test_service_hashing_does_not_store_raw_identifier() -> None:
    session = _RateLimitSession()
    raw_identifier = "resident:M12345A"
    policy = persistent_rate_limit.RateLimitPolicy(
        scope="auth_login_identifier",
        limit=10,
        window_seconds=3600,
        message="Too many attempts. Please try again later.",
    )

    result = await persistent_rate_limit.check_rate_limit(
        session,
        settings=_settings(),
        policy=policy,
        identifier=raw_identifier,
        now=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
    )

    assert result.allowed is True
    stored_payload = repr(session.rate_limit_rows)
    assert raw_identifier not in stored_payload
    assert "M12345A" not in stored_payload
    assert session.rate_limit_rows[0]["key_hash"] != raw_identifier


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_identifier",
    [
        "staff:email:coordinator@example.com",
        "anonymous-ip:203.0.113.77",
        "resident:mcr:M76543Z",
    ],
)
async def test_service_never_persists_raw_email_ip_or_mcr(raw_identifier: str) -> None:
    session = _RateLimitSession()

    await persistent_rate_limit.check_rate_limit(
        session,
        settings=_settings(),
        policy=persistent_rate_limit.RateLimitPolicy(
            scope="privacy_check",
            limit=5,
            window_seconds=60,
            message="Too many requests",
        ),
        identifier=raw_identifier,
        now=datetime(2026, 7, 9, 12, 0, tzinfo=UTC),
    )

    assert raw_identifier not in repr(session.rate_limit_rows)
    assert session.rate_limit_rows[0]["key_hash"] != raw_identifier


def test_auth_login_repeated_invalid_attempts_return_safe_429() -> None:
    session = _RateLimitResidentSession()
    client = _auth_client(session)

    responses = [
        client.post("/auth/login", json={"role": "resident", "mcr": "UNKNOWN"})
        for _ in range(6)
    ]

    assert [response.status_code for response in responses[:5]] == [401] * 5
    assert responses[5].status_code == 429
    assert responses[5].headers["Retry-After"]
    assert responses[5].json()["detail"] == "Too many requests"
    assert "UNKNOWN" not in responses[5].text
    assert "UNKNOWN" not in repr(session.rate_limit_rows)


def test_auth_login_resident_roles_share_one_identifier_allowance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        persistent_rate_limit_dependency,
        "AUTH_LOGIN_IP_POLICY",
        persistent_rate_limit.RateLimitPolicy(
            scope="auth_login_ip",
            limit=100,
            window_seconds=60,
            message="Too many attempts. Please try again later.",
        ),
    )
    session = _RateLimitResidentSession()
    client = _auth_client(session)
    shared_mcr_payloads = [
        {
            "role": "resident" if attempt % 2 == 0 else "external_resident",
            "mcr": "M90001Z" if attempt % 2 == 0 else "m90001z",
        }
        for attempt in range(11)
    ]

    identifiers = [
        persistent_rate_limit_dependency._login_identifier(payload)
        for payload in shared_mcr_payloads
    ]
    responses = [
        client.post("/auth/login", json=payload)
        for payload in shared_mcr_payloads
    ]

    assert identifiers == ["resident:mcr:M90001Z"] * 11
    assert [response.status_code for response in responses[:10]] == [401] * 10
    assert responses[10].status_code == 429
    assert responses[10].headers["Retry-After"]
    assert responses[10].json()["detail"] == "Too many requests"

    different_mcr_payload = {"role": "external_resident", "mcr": "M90002A"}
    assert (
        persistent_rate_limit_dependency._login_identifier(different_mcr_payload)
        == "resident:mcr:M90002A"
    )
    assert client.post("/auth/login", json=different_mcr_payload).status_code == 401
    assert (
        persistent_rate_limit_dependency._login_identifier(
            {"role": "staff", "email": " Staff@Example.com "},
        )
        == "staff:email:staff@example.com"
    )
    staff_alias_payloads = [
        {
            "role": ("staff", "admin", "secretary")[attempt % 3],
            "email": (
                " Coordinator@Example.com "
                if attempt % 2 == 0
                else "coordinator@example.com"
            ),
            "password": "invalid-password",
        }
        for attempt in range(11)
    ]
    staff_identifiers = [
        persistent_rate_limit_dependency._login_identifier(payload)
        for payload in staff_alias_payloads
    ]
    staff_responses = [
        client.post("/auth/login", json=payload)
        for payload in staff_alias_payloads
    ]

    assert staff_identifiers == ["staff:email:coordinator@example.com"] * 11
    assert [response.status_code for response in staff_responses[:10]] == [401] * 10
    assert staff_responses[10].status_code == 429
    assert staff_responses[10].headers["Retry-After"]
    assert "M90001Z" not in repr(session.rate_limit_rows)


def test_external_registration_invalid_probes_return_429_without_creating_resident() -> None:
    session = _RateLimitResidentSession()
    before = len(session.external_residents)
    client = _external_client(session)
    payload = {
        "name": "Probe Resident",
        "mcr": "E99999Z",
        "home_cluster": "Other",
        "current_nhg_posting_code": "TTSHCardio",
    }

    responses = [
        client.post("/external-residents/register", json=payload)
        for _ in range(4)
    ]

    assert [response.status_code for response in responses[:3]] == [422] * 3
    assert responses[3].status_code == 429
    assert responses[3].json()["detail"] == "Too many requests"
    assert len(session.external_residents) == before
    assert "E99999Z" not in repr(session.rate_limit_rows)


def test_external_registration_missing_mcr_still_gets_ip_protection() -> None:
    session = _RateLimitResidentSession()
    before = len(session.external_residents)
    client = _external_client(session)
    payload = {
        "name": "Missing MCR",
        "home_cluster": "NUH",
        "current_nhg_posting_code": "TTSHCardio",
    }

    responses = [
        client.post("/external-residents/register", json=payload)
        for _ in range(4)
    ]

    assert [response.status_code for response in responses[:3]] == [422] * 3
    assert responses[3].status_code == 429
    assert len(session.external_residents) == before


def test_upload_rate_limit_blocks_before_parser_work(monkeypatch: pytest.MonkeyPatch) -> None:
    parser_calls = 0

    async def _fake_rdb_parser(**kwargs):
        nonlocal parser_calls
        parser_calls += 1
        return ParserResult(upload_type="rdb")

    monkeypatch.setattr("app.services.rdb_parser.parse_rdb_upload", _fake_rdb_parser)

    session = _UploadRateLimitSession()
    period_id = str(uuid4())
    session.reporting_periods[period_id] = {"status": "active"}
    client = _upload_client(session)
    files = {
        "file": (
            "rdb.xlsx",
            _make_valid_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }

    responses = [
        client.post(
            "/admin/upload/rdb",
            headers=_admin_headers(
                user_id="11111111-1111-1111-1111-111111111111",
                master=True,
            ),
            data={"reporting_period_id": period_id},
            files=files,
        )
        for _ in range(11)
    ]

    assert [response.status_code for response in responses[:10]] == [200] * 10
    assert responses[10].status_code == 429
    assert responses[10].json()["detail"] == "Too many requests"
    assert parser_calls == 10


def test_ttf_upload_rate_limit_key_distinguishes_programme(monkeypatch: pytest.MonkeyPatch) -> None:
    parser_programmes: list[str] = []

    async def _fake_ttf_parser(**kwargs):
        parser_programmes.append(kwargs["programme_code"])
        return ParserResult(upload_type="ttf")

    monkeypatch.setattr("app.routers.admin.parse_ttf_upload", _fake_ttf_parser)

    session = _UploadRateLimitSession()
    period_id = str(uuid4())
    session.reporting_periods[period_id] = {"status": "active"}
    client = _upload_client(session)
    headers = _admin_headers(
        user_id="22222222-2222-2222-2222-222222222222",
        programme_scope="DR,GERI",
    )
    files = {
        "file": (
            "ttf.xlsx",
            _make_valid_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }

    dr_responses = [
        client.post(
            "/admin/upload/ttf",
            headers=headers,
            data={"reporting_period_id": period_id, "programme_code": "DR"},
            files=files,
        )
        for _ in range(11)
    ]
    geri_response = client.post(
        "/admin/upload/ttf",
        headers=headers,
        data={"reporting_period_id": period_id, "programme_code": "GERI"},
        files=files,
    )

    assert [response.status_code for response in dr_responses[:10]] == [200] * 10
    assert dr_responses[10].status_code == 429
    assert geri_response.status_code == 200
    assert parser_programmes == ["DR"] * 10 + ["GERI"]


@pytest.mark.asyncio
async def test_cleanup_is_retention_aware_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(persistent_rate_limit, "_cleanup_due", lambda _: True)
    session = _RateLimitSession()
    settings = Settings(
        environment="test",
        rate_limit_hash_secret="unit-test-rate-limit-hash-secret",
        rate_limit_cleanup_retention_seconds=1234,
        rate_limit_cleanup_batch_size=17,
        _env_file=None,
    )
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)

    await persistent_rate_limit.check_rate_limit(
        session,
        settings=settings,
        policy=persistent_rate_limit.RateLimitPolicy(
            scope="bounded_cleanup",
            limit=2,
            window_seconds=60,
            message="Too many requests",
        ),
        identifier="203.0.113.11",
        now=now,
    )

    assert session.cleanup_calls == 1
    assert "LIMIT :batch_size" in session.last_sql
    assert session.last_params["batch_size"] == 17
    assert session.last_params["cutoff"] == now - timedelta(seconds=1234)


def _request(path: str, method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("203.0.113.44", 50000),
            "server": ("testserver", 443),
        }
    )


def test_middleware_classifies_security_sensitive_route_groups() -> None:
    middleware = rate_limit_middleware.RateLimitMiddleware(
        FastAPI(),
        settings=_settings(),
    )

    assert middleware._resolve_limit_rule(
        _request("/api/v1/resident/attendance", "POST")
    )[2] == "resident_attendance"
    assert middleware._resolve_limit_rule(
        _request("/api/v1/admin/staff-accounts/000/reset-password", "POST")
    )[2] == "staff_account_mutation"
    assert middleware._resolve_limit_rule(
        _request("/api/v1/admin/upload/public-holidays", "POST")
    )[2] == "admin_upload"
    assert middleware._resolve_limit_rule(
        _request("/api/v1/secretary/teaching-events", "DELETE")
    )[2] == "mutation"
    assert middleware._resolve_limit_rule(
        _request("/api/v1/admin/external-attendance", "GET")
    )[2] == "report"
    assert middleware._resolve_limit_rule(
        _request("/api/v1/admin/external-attendance/export.xlsx", "GET")
    )[2] == "report"


def test_middleware_skips_only_routes_with_endpoint_persistent_dependencies() -> None:
    memory_middleware = rate_limit_middleware.RateLimitMiddleware(
        FastAPI(),
        settings=_settings(),
    )
    postgres_middleware = rate_limit_middleware.RateLimitMiddleware(
        FastAPI(),
        settings=Settings(
            environment="test",
            rate_limit_store="postgres",
            rate_limit_hash_secret="unit-test-rate-limit-hash-secret",
            _env_file=None,
        ),
    )

    assert memory_middleware._uses_endpoint_persistent_dependency(
        _request("/api/v1/auth/login", "POST")
    )
    assert memory_middleware._uses_endpoint_persistent_dependency(
        _request("/api/v1/admin/upload/rdb", "POST")
    )
    assert not postgres_middleware._uses_endpoint_persistent_dependency(
        _request("/api/v1/admin/upload/rdb", "POST")
    )
    assert postgres_middleware._uses_endpoint_persistent_dependency(
        _request("/api/v1/external-residents/register", "POST")
    )


@pytest.mark.asyncio
async def test_postgres_upload_endpoint_hook_does_not_double_count() -> None:
    class _UnexpectedSession:
        async def execute(self, *args, **kwargs):
            raise AssertionError("endpoint upload hook must not hit the route transaction")

    await persistent_rate_limit_dependency.enforce_upload_persistent_rate_limit(
        _UnexpectedSession(),  # type: ignore[arg-type]
        settings=Settings(
            environment="test",
            rate_limit_store="postgres",
            rate_limit_hash_secret="unit-test-rate-limit-hash-secret",
            _env_file=None,
        ),
        user_id=uuid4(),
        upload_type="rdb",
    )


@pytest.mark.asyncio
async def test_postgres_middleware_uses_isolated_session_and_hashed_verified_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _RateLimitSession()
    monkeypatch.setattr(rate_limit_middleware, "AsyncSessionLocal", lambda: session)
    settings = Settings(
        environment="test",
        rate_limit_store="postgres",
        rate_limit_hash_secret="unit-test-rate-limit-hash-secret",
        _env_file=None,
    )
    middleware = rate_limit_middleware.RateLimitMiddleware(FastAPI(), settings=settings)
    request = _request("/api/v1/resident/attendance", "POST")
    subject_id = "11111111-1111-1111-1111-111111111111"
    request.state.identity = SimpleNamespace(role="resident", subject_id=subject_id)

    allowed, _ = await middleware._allow_persistent_request(
        request,
        "resident_attendance",
        1,
        60,
    )
    blocked, retry_after = await middleware._allow_persistent_request(
        request,
        "resident_attendance",
        1,
        60,
    )

    assert allowed is True
    assert blocked is False
    assert retry_after >= 1
    stored = repr(session.rate_limit_rows)
    assert subject_id not in stored
    assert "203.0.113.44" not in stored
    assert session.commits == 2
