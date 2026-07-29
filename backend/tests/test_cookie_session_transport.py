from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
import re
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import Response

from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.middleware.auth_stub import AuthIdentity, AuthStubMiddleware
from app.middleware.errors import install_error_handlers
from app.middleware.security import (
    SecurityHeadersMiddleware,
    configure_cors,
    configure_trusted_hosts,
)
from app.routers import auth
from app.services.app_sessions import AppSessionInvalidError, CreatedSession
from app.services.auth import AuthenticatedSubject
from app.services.session_transport import (
    AUTH_COOKIE_COORDINATION_HEADER_NAME,
    AUTH_COOKIE_COORDINATION_PROTOCOL,
    clear_session_cookie,
    session_cookie_name,
    set_session_cookie,
)
from tests.resident_fakes import FakeResidentSession


SESSION_KEY = "unit-test-session-hash-key-at-least-32-characters"
RATE_KEY = "unit-test-rate-limit-key-at-least-32-characters"
SUBJECT_ID = UUID("00000000-0000-0000-0000-000000000123")
COORDINATION_HEADERS = {
    AUTH_COOKIE_COORDINATION_HEADER_NAME: AUTH_COOKIE_COORDINATION_PROTOCOL,
}


def _production_settings(**overrides) -> Settings:
    values = {
        "environment": "production",
        "auth_mode": "supabase",
        "auth_transport": "cookie",
        "supabase_url": "https://project.supabase.co",
        "supabase_publishable_key": "sb_publishable_test_key",
        "database_url": (
            "postgresql+asyncpg://runtime@db.example.invalid:5432/mata"
        ),
        "auth_database_url": (
            "postgresql+asyncpg://auth@db.example.invalid:5432/mata"
        ),
        "sync_database_url": (
            "postgresql+psycopg2://migration@db.example.invalid:5432/mata"
        ),
        "database_rls_enabled": True,
        "mata_session_hash_key": SESSION_KEY,
        "rate_limit_store": "postgres",
        "rate_limit_hash_secret": RATE_KEY,
        "cors_origins": ["https://mata.example.com"],
        "allowed_hosts": ["mata.example.com", "mata-backend.vercel.app"],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _active_session(*, subject_type: str = "staff") -> SimpleNamespace:
    now = datetime.now(UTC)
    session_id = uuid4()
    return SimpleNamespace(
        id=session_id,
        subject_type=subject_type,
        subject_id=SUBJECT_ID,
        subject_session_generation=0,
        session_family_id=session_id,
        created_at=now,
        last_seen_at=now,
        idle_expires_at=now + timedelta(hours=1),
        absolute_expires_at=now + timedelta(hours=8),
        revoked_at=None,
        csrf_token_digest=b"x" * 32,
    )


def test_production_cookie_is_host_only_secure_http_only_and_strict() -> None:
    settings = _production_settings()
    response = Response()

    set_session_cookie(
        response,
        settings=settings,
        session_token="opaque-session-value",
    )

    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-mata_session=opaque-session-value;")
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/" in cookie
    assert "Max-Age=" not in cookie
    assert "Expires=" not in cookie
    assert "Domain=" not in cookie


def test_local_cookie_has_separate_name_and_secure_is_off() -> None:
    settings = Settings(environment="test", _env_file=None)
    response = Response()

    set_session_cookie(
        response,
        settings=settings,
        session_token="local-session-value",
    )
    cookie = response.headers["set-cookie"]

    assert cookie.startswith("mata_session_local=local-session-value;")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Secure" not in cookie
    assert "Domain=" not in cookie
    assert "Max-Age=" not in cookie
    assert "Expires=" not in cookie

    clear_session_cookie(response, settings=settings)
    clearing_cookie = response.headers.getlist("set-cookie")[-1]
    assert clearing_cookie.startswith("mata_session_local=")
    assert "Max-Age=0" in clearing_cookie


def test_production_configuration_rejects_insecure_transport_and_origin_shortcuts() -> None:
    with pytest.raises(ValueError, match="cookie session transport"):
        _production_settings(auth_transport="bearer_compat")
    with pytest.raises(ValueError, match="origins"):
        _production_settings(cors_origins=["*"])
    with pytest.raises(ValueError, match="hosts"):
        _production_settings(allowed_hosts=["*.vercel.app"])
    with pytest.raises(ValueError, match="AUTH_MODE"):
        _production_settings(auth_mode="stub")
    with pytest.raises(ValueError, match="DATABASE_URL"):
        _production_settings(
            database_url="postgresql+asyncpg://postgres@localhost:5432/mata"
        )
    with pytest.raises(ValueError, match="SYNC_DATABASE_URL"):
        _production_settings(
            sync_database_url=(
                "postgresql+psycopg2://migration@other.example.invalid:5432/mata"
            )
        )
    with pytest.raises(ValueError, match="SYNC_DATABASE_URL"):
        _production_settings(
            sync_database_url=(
                "postgresql+psycopg://migration@db.example.invalid:5432/mata"
            )
        )
    with pytest.raises(ValueError, match="distinct credentialed roles"):
        _production_settings(
            sync_database_url=(
                "postgresql+psycopg2://runtime@db.example.invalid:5432/mata"
            )
        )
    with pytest.raises(ValueError, match="cookie session transport"):
        _production_settings(
            auth_transport="bearer_compat",
            enable_production_bearer_rollback=True,
            mata_resident_session_secret="too-short",
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"supabase_url": "http://project.supabase.co"}, "SUPABASE_URL"),
        ({"supabase_url": "https://localhost"}, "SUPABASE_URL"),
        ({"supabase_url": "https://identity.example.invalid"}, "SUPABASE_URL"),
        (
            {"supabase_url": "https://project.supabase.co.example.invalid"},
            "SUPABASE_URL",
        ),
        ({"supabase_url": "https://user@project.supabase.co"}, "SUPABASE_URL"),
        ({"supabase_url": "https://project.supabase.co/tenant"}, "SUPABASE_URL"),
        ({"supabase_url": "https://project.supabase.co?tenant=other"}, "SUPABASE_URL"),
        ({"supabase_url": "https://project.supabase.co#other"}, "SUPABASE_URL"),
        ({"supabase_url": "https://project.supabase.co:444"}, "SUPABASE_URL"),
        (
            {
                "supabase_jwt_issuer": (
                    "https://unrelated.supabase.co/auth/v1"
                )
            },
            "SUPABASE_JWT_ISSUER",
        ),
        (
            {"supabase_jwt_issuer": "https://project.supabase.co/auth/v2"},
            "SUPABASE_JWT_ISSUER",
        ),
        (
            {
                "supabase_jwks_url": (
                    "https://unrelated.supabase.co/auth/v1/.well-known/jwks.json"
                )
            },
            "SUPABASE_JWKS_URL",
        ),
        (
            {
                "supabase_jwks_url": (
                    "https://project.supabase.co/.well-known/jwks.json"
                )
            },
            "SUPABASE_JWKS_URL",
        ),
    ],
)
def test_production_rejects_unapproved_supabase_urls(
    overrides: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _production_settings(**overrides)


def test_production_accepts_consistent_supabase_project_urls() -> None:
    settings = _production_settings(
        supabase_url="https://project.supabase.co/",
        supabase_jwt_issuer="https://project.supabase.co/auth/v1/",
        supabase_jwks_url=(
            "https://project.supabase.co/auth/v1/.well-known/jwks.json"
        ),
    )

    assert settings.supabase_url == "https://project.supabase.co/"
    assert settings.supabase_jwt_issuer == "https://project.supabase.co/auth/v1/"
    assert settings.supabase_jwks_url == (
        "https://project.supabase.co/auth/v1/.well-known/jwks.json"
    )


class _RouterDb:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _auth_router_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    settings: Settings | None = None,
    identity: AuthIdentity | None = None,
    app_session: SimpleNamespace | None = None,
    session_token: str | None = None,
    db_override_value=None,
) -> tuple[TestClient, object]:
    app = FastAPI()
    install_error_handlers(app)
    selected_settings = settings or Settings(environment="test", _env_file=None)
    db = db_override_value or _RouterDb()

    @app.middleware("http")
    async def inject_session(request: Request, call_next):
        if identity is not None:
            request.state.identity = identity
        if app_session is not None:
            request.state.app_session = app_session
        if session_token is not None:
            request.state.session_token = session_token
        return await call_next(request)

    async def db_override():
        yield db

    async def no_rate_limit() -> None:
        return None

    for dependency in (
        auth.get_db_session,
        auth.get_auth_db_session,
        auth.get_exclusive_db_session,
        auth.get_logout_db_session,
    ):
        app.dependency_overrides[dependency] = db_override
    app.dependency_overrides[auth.get_settings] = lambda: selected_settings
    app.dependency_overrides[auth._persistent_login_rate_limit] = no_rate_limit
    app.include_router(auth.router, prefix="/api/v1")
    return TestClient(app), db


def test_production_auth_routes_require_cookie_coordination_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _production_settings()
    client, _ = _auth_router_client(
        monkeypatch,
        settings=settings,
        identity=AuthIdentity(role="resident", subject_id=str(SUBJECT_ID)),
        app_session=_active_session(subject_type="resident"),
        session_token="presented-session",
    )

    responses = [
        client.post(
            "/api/v1/auth/login",
            json={"role": "resident", "mcr": "M10000A"},
        ),
        client.post("/api/v1/auth/session/refresh"),
        client.post("/api/v1/auth/logout"),
        client.post(
            "/api/v1/auth/logout",
            headers={AUTH_COOKIE_COORDINATION_HEADER_NAME: "wrong-version"},
        ),
    ]

    assert [response.status_code for response in responses] == [409, 409, 409, 409]
    assert all(response.json()["error_code"] == ErrorCode.CONFLICT.value for response in responses)
    assert all("set-cookie" not in response.headers for response in responses)


def test_cookie_login_returns_identity_and_csrf_without_upstream_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(environment="test", auth_mode="stub", _env_file=None)
    created_session = _active_session(subject_type="staff")

    async def authenticate(*args, **kwargs):
        return AuthenticatedSubject(
            subject_type="staff",
            subject_id=SUBJECT_ID,
            auth_source="supabase_staff",
            session_generation=0,
            user={
                "id": str(SUBJECT_ID),
                "role": "admin",
                "admin_level": "master",
                "programme_scope": [],
            },
        )

    async def create(*args, **kwargs):
        assert kwargs["expected_subject_session_generation"] == 0
        return CreatedSession(
            session=created_session,
            session_token="opaque-browser-session",
            csrf_token="csrf-token-returned-in-json-memory-only",
        )

    monkeypatch.setattr(auth.auth_service, "authenticate_for_app_session", authenticate)
    monkeypatch.setattr(auth, "create_session", create)
    client, db = _auth_router_client(monkeypatch, settings=settings)

    response = client.post(
        "/api/v1/auth/login",
        json={"role": "staff", "email": "staff@example.com", "password": "password"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "user": {
            "id": str(SUBJECT_ID),
            "role": "admin",
            "admin_level": "master",
            "programme_scope": [],
        },
        "csrf_token": "csrf-token-returned-in-json-memory-only",
        "session_refresh_required": False,
    }
    assert "access_token" not in response.text
    assert "refresh_token" not in response.text
    assert "opaque-browser-session" in response.headers["set-cookie"]
    assert db.commits == 1


@pytest.mark.parametrize(
    ("mcr", "expected_subject_type"),
    [("M12345A", "resident"), ("E12345A", "external_resident")],
)
def test_neutral_resident_login_issues_native_or_non_nhg_cookie_session(
    monkeypatch: pytest.MonkeyPatch,
    mcr: str,
    expected_subject_type: str,
) -> None:
    fake_db = FakeResidentSession()
    captured_subject_types: list[str] = []

    async def create(_db, _settings, subject_type, subject_id, auth_source, **kwargs):
        captured_subject_types.append(subject_type)
        return CreatedSession(
            session=_active_session(subject_type=subject_type),
            session_token="resident-opaque-browser-session",
            csrf_token="resident-csrf-token-returned-in-memory-only",
        )

    monkeypatch.setattr(auth, "create_session", create)
    client, _ = _auth_router_client(
        monkeypatch,
        settings=Settings(environment="test", auth_mode="stub", _env_file=None),
        db_override_value=fake_db,
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"role": "resident", "mcr": mcr},
    )

    assert response.status_code == 200
    assert response.json()["user"]["role"] == expected_subject_type
    assert captured_subject_types == [expected_subject_type]
    assert "resident-opaque-browser-session" in response.headers["set-cookie"]
    assert "access_token" not in response.text


def test_cookie_resident_login_denies_cross_table_duplicate_with_generic_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = FakeResidentSession()
    duplicate_mcr = fake_db.residents[0]["mcr"]
    fake_db.external_residents[0]["mcr"] = duplicate_mcr
    client, _ = _auth_router_client(
        monkeypatch,
        settings=Settings(environment="test", auth_mode="stub", _env_file=None),
        db_override_value=fake_db,
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"role": "resident", "mcr": duplicate_mcr},
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Unauthorized",
        "error_code": "UNAUTHORIZED",
        "errors": [],
        "warnings": [],
        "metadata": {},
    }
    assert duplicate_mcr not in response.text
    assert "residents" not in response.text


class _MappingResult:
    def __init__(self, row: dict | None) -> None:
        self.row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row


class _StaffLoginDb:
    def __init__(self, row: dict | None, subsequent_row: dict | None = None) -> None:
        self.row = row
        self.subsequent_row = subsequent_row
        self.execute_count = 0
        self.rollbacks = 0

    async def execute(self, statement, params=None):
        self.execute_count += 1
        if self.execute_count > 1 and self.subsequent_row is not None:
            row = self.subsequent_row
        else:
            row = self.row
        if row is None:
            return _MappingResult(None)
        projection = str(statement).partition("FROM")[0]
        return _MappingResult(
            {
                key: value
                for key, value in row.items()
                if re.search(rf"\b{re.escape(key)}\b", projection)
            }
        )

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_backend_staff_login_uses_only_supabase_subject_and_db_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supabase_subject = uuid4()
    persisted_user_id = uuid4()

    async def upstream_authenticate(**kwargs):
        return {
            "sub": str(supabase_subject),
            "user_metadata": {
                "role": "admin",
                "admin_level": "master",
                "programme_scope": ["ALL"],
            },
        }

    monkeypatch.setattr(
        "app.services.auth.authenticate_supabase_password",
        upstream_authenticate,
    )
    db = _StaffLoginDb(
        {
            "id": str(persisted_user_id),
            "email": "secretary@example.com",
            "supabase_user_id": supabase_subject,
            "password_hash": "not-used-for-supabase",
            "role": "secretary",
            "name": "Secretary",
            "posting_code": "TTSHCardio",
            "programme_scope": None,
            "admin_level": "programme",
            "is_active": True,
            "session_generation": 0,
            "session_issuance_blocked": False,
            "current_staff_actor_name": None,
            "staff_actor_name_updated_at": None,
            "staff_actor_name_updated_by_user_id": None,
        }
    )
    result = await auth.auth_service.authenticate_for_app_session(
        db,
        role="staff",
        email="secretary@example.com",
        password="password-never-logged",
        mcr=None,
        settings=Settings(
            environment="test",
            auth_mode="supabase",
            supabase_url="https://project.supabase.co",
            _env_file=None,
        ),
    )

    assert result.subject_id == persisted_user_id
    assert result.subject_type == "staff"
    assert result.session_generation == 0
    assert result.user["role"] == "secretary"
    assert result.user["posting_code"] == "TTSHCardio"
    assert "programme_scope" not in result.user or result.user["programme_scope"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("next_generation", "issuance_blocked"),
    [(1, False), (0, True)],
)
async def test_backend_staff_login_rejects_changed_or_blocked_subject_after_upstream_auth(
    monkeypatch: pytest.MonkeyPatch,
    next_generation: int,
    issuance_blocked: bool,
) -> None:
    supabase_subject = uuid4()
    persisted_user_id = uuid4()

    async def upstream_authenticate(**kwargs):
        return {"sub": str(supabase_subject)}

    monkeypatch.setattr(
        "app.services.auth.authenticate_supabase_password",
        upstream_authenticate,
    )
    base_row = {
        "id": str(persisted_user_id),
        "email": "staff@example.com",
        "supabase_user_id": supabase_subject,
        "password_hash": "not-used-for-supabase",
        "role": "admin",
        "name": "Programme PC",
        "posting_code": None,
        "programme_scope": ["DR"],
        "admin_level": "programme",
        "is_active": True,
        "session_generation": 0,
        "session_issuance_blocked": False,
        "current_staff_actor_name": None,
        "staff_actor_name_updated_at": None,
        "staff_actor_name_updated_by_user_id": None,
    }
    next_row = {
        **base_row,
        "session_generation": next_generation,
        "session_issuance_blocked": issuance_blocked,
    }

    with pytest.raises(ApiError) as exc_info:
        await auth.auth_service.authenticate_for_app_session(
            _StaffLoginDb(base_row, next_row),
            role="staff",
            email="staff@example.com",
            password="credential-not-returned",
            mcr=None,
            settings=Settings(
                environment="test",
                auth_mode="supabase",
                supabase_url="https://project.supabase.co",
                _env_file=None,
            ),
        )

    assert getattr(exc_info.value, "status_code", None) == 401
    assert str(exc_info.value.detail) == "Unauthorized"


@pytest.mark.parametrize(
    ("role", "user"),
    [
        ("admin", {"id": str(SUBJECT_ID), "role": "admin", "admin_level": "master"}),
        ("secretary", {"id": str(SUBJECT_ID), "role": "secretary", "posting_code": "TTSHCardio"}),
        ("resident", {"id": str(SUBJECT_ID), "role": "resident", "mcr": "M10000A"}),
        (
            "external_resident",
            {"id": str(SUBJECT_ID), "role": "external_resident", "mcr": "E10000A"},
        ),
    ],
)
def test_session_hydration_wraps_every_identity_family_without_db_mutation(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    user: dict[str, str],
) -> None:
    identity = AuthIdentity(role=role, subject_id=str(SUBJECT_ID))
    session = _active_session(subject_type="staff" if role in {"admin", "secretary"} else role)

    async def current_identity(*args, **kwargs):
        return user

    monkeypatch.setattr(auth.auth_service, "get_current_identity", current_identity)
    monkeypatch.setattr(auth, "csrf_for_session_token", lambda *args, **kwargs: "c" * 43)
    client, db = _auth_router_client(
        monkeypatch,
        identity=identity,
        app_session=session,
        session_token="opaque-session-token",
    )

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["user"] == user
    assert response.json()["csrf_token"] == "c" * 43
    assert db.commits == 0
    assert db.rollbacks == 0


def test_refresh_rotates_cookie_and_logout_revokes_then_clears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(environment="test", auth_mode="stub", _env_file=None)
    identity = AuthIdentity(role="resident", subject_id=str(SUBJECT_ID))
    original = _active_session(subject_type="resident")
    rotated_session = _active_session(subject_type="resident")
    revoke_calls: list[tuple[str | None, str | None, str]] = []
    refresh_call_order: list[str] = []

    async def rotate(*args, **kwargs):
        refresh_call_order.append("rotate")
        return CreatedSession(
            session=rotated_session,
            session_token="replacement-opaque-session",
            csrf_token="replacement-csrf-token-memory-only",
        )

    async def current_identity(*args, **kwargs):
        refresh_call_order.append("identity")
        return {"id": str(SUBJECT_ID), "role": "resident", "mcr": "M10000A"}

    async def revoke(
        *args,
        session_token: str | None,
        csrf_token: str | None,
        reason: str,
        **kwargs,
    ):
        revoke_calls.append((session_token, csrf_token, reason))
        return 1

    monkeypatch.setattr(auth, "rotate_session", rotate)
    monkeypatch.setattr(auth, "revoke_session_family_for_logout", revoke)
    monkeypatch.setattr(auth.auth_service, "get_current_identity", current_identity)
    client, db = _auth_router_client(
        monkeypatch,
        settings=settings,
        identity=identity,
        app_session=original,
        session_token="original-opaque-session",
    )

    refreshed = client.post("/api/v1/auth/session/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["csrf_token"] == "replacement-csrf-token-memory-only"
    assert "replacement-opaque-session" in refreshed.headers["set-cookie"]
    assert refresh_call_order == ["identity", "rotate"]

    logged_out = client.post(
        "/api/v1/auth/logout",
        headers={
            settings.csrf_header_name: "replacement-csrf-token-memory-only"
        },
    )
    assert logged_out.status_code == 200
    assert logged_out.json() == {
        "success": True,
        "server_logout_confirmed": True,
    }
    assert "Max-Age=0" in logged_out.headers["set-cookie"]
    assert revoke_calls == [
        (
            "replacement-opaque-session",
            "replacement-csrf-token-memory-only",
            "logout",
        )
    ]
    assert db.commits == 2


@pytest.mark.parametrize("csrf_token", (None, "malformed"))
def test_logout_with_unusable_proof_remains_idempotent_without_clearing_cookie(
    monkeypatch: pytest.MonkeyPatch,
    csrf_token: str | None,
) -> None:
    settings = Settings(environment="test", auth_mode="stub", _env_file=None)
    revoke_calls: list[tuple[str | None, str | None]] = []

    async def reject_proof(
        *args,
        session_token: str | None,
        csrf_token: str | None,
        **kwargs,
    ) -> int:
        revoke_calls.append((session_token, csrf_token))
        return 0

    monkeypatch.setattr(
        auth,
        "revoke_session_family_for_logout",
        reject_proof,
    )
    client, db = _auth_router_client(monkeypatch, settings=settings)
    client.cookies.set(
        session_cookie_name(settings),
        "malformed-or-stale-session",
    )
    headers = (
        {settings.csrf_header_name: csrf_token}
        if csrf_token is not None
        else {}
    )

    response = client.post("/api/v1/auth/logout", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "server_logout_confirmed": False,
    }
    assert "set-cookie" not in response.headers
    assert revoke_calls == [("malformed-or-stale-session", csrf_token)]
    assert db.commits == 1


def test_concurrent_refresh_failure_is_conflict_and_preserves_shared_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = AuthIdentity(role="admin", subject_id=str(SUBJECT_ID))
    original = _active_session(subject_type="staff")

    async def fail_rotation(*args, **kwargs):
        raise AppSessionInvalidError("internal rotation detail")

    async def current_identity(*args, **kwargs):
        return {
            "id": str(SUBJECT_ID),
            "role": "admin",
            "admin_level": "master",
        }

    monkeypatch.setattr(auth, "rotate_session", fail_rotation)
    monkeypatch.setattr(
        auth.auth_service,
        "get_current_identity",
        current_identity,
    )
    client, db = _auth_router_client(
        monkeypatch,
        identity=identity,
        app_session=original,
        session_token="original-opaque-session",
    )

    response = client.post("/api/v1/auth/session/refresh")

    assert response.status_code == 409
    assert response.json()["error_code"] == ErrorCode.CONFLICT.value
    assert "internal rotation detail" not in response.text
    assert "set-cookie" not in response.headers
    assert db.rollbacks == 1


class _MiddlewareDb:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def commit(self) -> None:
        return None


def _cookie_middleware_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    settings: Settings | None = None,
    resolved_session: SimpleNamespace | None = None,
    resolve_error: Exception | None = None,
    touch_result: bool = True,
    touch_error: Exception | None = None,
) -> tuple[TestClient, list[bool], list[str | None]]:
    selected_settings = settings or Settings(
        environment="test",
        auth_mode="supabase",
        auth_transport="cookie",
        database_rls_enabled=False,
        mata_session_hash_key=SESSION_KEY,
        _env_file=None,
    )
    touches: list[bool] = []
    csrf_values: list[str | None] = []

    async def resolve(_db, _settings, _token, *, touch=True, **kwargs):
        touches.append(touch)
        if resolve_error is not None:
            raise resolve_error
        return resolved_session

    async def identity_for_session(self, app_session, request):
        return AuthIdentity(role="admin", subject_id=str(SUBJECT_ID), admin_level="master")

    async def validate(_db, _session, csrf_token, _settings, **kwargs):
        csrf_values.append(csrf_token)
        return (
            "valid"
            if csrf_token == "valid-csrf-token"
            else "invalid_csrf"
        )

    async def touch(_db, _settings, _session, **kwargs):
        touches.append(True)
        if touch_error is not None:
            raise touch_error
        return touch_result

    monkeypatch.setattr("app.middleware.auth_stub.AsyncSessionLocal", lambda: _MiddlewareDb())
    monkeypatch.setattr("app.middleware.auth_stub.resolve_session", resolve)
    monkeypatch.setattr(
        "app.middleware.auth_stub.validate_session_csrf",
        validate,
    )
    monkeypatch.setattr("app.middleware.auth_stub.touch_session", touch)
    monkeypatch.setattr(AuthStubMiddleware, "_resolve_app_session_identity", identity_for_session)

    app = FastAPI()
    install_error_handlers(app)

    @app.api_route("/api/v1/protected", methods=["GET", "POST"])
    async def protected(request: Request) -> dict[str, str]:
        return {"role": request.state.identity.role}

    app.add_middleware(AuthStubMiddleware, settings=selected_settings)
    return TestClient(app), touches, csrf_values


def test_production_protected_requests_require_cookie_coordination_before_hydration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _production_settings()
    client, touches, csrf_values = _cookie_middleware_client(
        monkeypatch,
        settings=settings,
        resolved_session=_active_session(),
    )
    client.cookies.set(session_cookie_name(settings), "opaque-session-token")

    missing = client.get("/api/v1/protected")
    wrong = client.get(
        "/api/v1/protected",
        headers={AUTH_COOKIE_COORDINATION_HEADER_NAME: "wrong-version"},
    )
    assert missing.status_code == 409
    assert wrong.status_code == 409
    assert "set-cookie" not in missing.headers
    assert "set-cookie" not in wrong.headers
    assert touches == []
    assert csrf_values == []


def test_cookie_logout_bypasses_hydration_and_csrf_but_keeps_outer_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _production_settings()
    db = _RouterDb()
    resolve_calls: list[str] = []
    revoke_calls: list[tuple[str | None, str | None]] = []

    async def unexpected_resolve(*args, **kwargs):
        resolve_calls.append("resolve")
        raise AssertionError("Logout must not hydrate the presented cookie")

    async def revoke(
        *args,
        session_token: str | None,
        csrf_token: str | None,
        **kwargs,
    ) -> int:
        revoke_calls.append((session_token, csrf_token))
        return int(csrf_token == "matching-child-csrf")

    async def db_override():
        yield db

    monkeypatch.setattr("app.middleware.auth_stub.resolve_session", unexpected_resolve)
    monkeypatch.setattr(auth, "revoke_session_family_for_logout", revoke)

    app = FastAPI()
    install_error_handlers(app)
    app.dependency_overrides[auth.get_logout_db_session] = db_override
    app.dependency_overrides[auth.get_settings] = lambda: settings
    app.include_router(auth.router, prefix="/api/v1")
    app.add_middleware(AuthStubMiddleware, settings=settings)
    client = TestClient(app, base_url="https://mata.example.com")
    cookie_name = session_cookie_name(settings)
    approved_origin = {
        "Origin": "https://mata.example.com",
        **COORDINATION_HEADERS,
    }

    client.cookies.set(cookie_name, "active-child-cookie")
    stale_proof = client.post(
        "/api/v1/auth/logout",
        headers={
            **approved_origin,
            settings.csrf_header_name: "stale-parent-csrf",
        },
    )
    client.cookies.set(cookie_name, "active-child-cookie")
    matching_proof = client.post(
        "/api/v1/auth/logout",
        headers={
            **approved_origin,
            settings.csrf_header_name: "matching-child-csrf",
        },
    )
    client.cookies.set(cookie_name, "active-child-cookie")
    bearer = client.post(
        "/api/v1/auth/logout",
        headers={
            **approved_origin,
            "Authorization": "Bearer browser-token",
            settings.csrf_header_name: "matching-child-csrf",
        },
    )
    unapproved_origin = client.post(
        "/api/v1/auth/logout",
        headers={
            "Origin": "https://preview-attacker.example.com",
            "Authorization": "Bearer browser-token",
        },
    )

    assert stale_proof.status_code == 200
    assert stale_proof.json() == {
        "success": True,
        "server_logout_confirmed": False,
    }
    assert "set-cookie" not in stale_proof.headers
    assert matching_proof.status_code == 200
    assert matching_proof.json() == {
        "success": True,
        "server_logout_confirmed": True,
    }
    assert "Max-Age=0" in matching_proof.headers["set-cookie"]
    assert bearer.status_code == 401
    assert unapproved_origin.status_code == 403
    assert resolve_calls == []
    assert revoke_calls == [
        ("active-child-cookie", "stale-parent-csrf"),
        ("active-child-cookie", "matching-child-csrf"),
    ]
    assert db.commits == 2


def test_safe_get_hydrates_cookie_without_csrf_or_session_touch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, touches, csrf_values = _cookie_middleware_client(
        monkeypatch,
        resolved_session=_active_session(),
    )
    client.cookies.set("mata_session_local", "opaque-session-token")

    response = client.get("/api/v1/protected")

    assert response.status_code == 200
    assert response.json() == {"role": "admin"}
    assert touches == [False]
    assert csrf_values == []


def test_unsafe_cookie_request_requires_matching_csrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, touches, csrf_values = _cookie_middleware_client(
        monkeypatch,
        resolved_session=_active_session(),
    )
    client.cookies.set("mata_session_local", "opaque-session-token")

    missing = client.post("/api/v1/protected")
    malformed = client.post(
        "/api/v1/protected",
        headers={"X-CSRF-Token": "wrong"},
    )
    accepted = client.post(
        "/api/v1/protected",
        headers={"X-CSRF-Token": "valid-csrf-token"},
    )

    assert missing.status_code == 403
    assert malformed.status_code == 403
    assert accepted.status_code == 200
    assert touches == [False, False, False, True]
    assert csrf_values == [None, "wrong", "valid-csrf-token"]


@pytest.mark.parametrize(
    ("touch_result", "touch_error"),
    [
        (False, None),
        (True, RuntimeError("post-response touch unavailable")),
    ],
    ids=["invalidated", "store-error"],
)
def test_failed_post_response_touch_rejects_without_clearing_shared_cookie(
    monkeypatch: pytest.MonkeyPatch,
    touch_result: bool,
    touch_error: Exception | None,
) -> None:
    client, touches, csrf_values = _cookie_middleware_client(
        monkeypatch,
        resolved_session=_active_session(),
        touch_result=touch_result,
        touch_error=touch_error,
    )
    client.cookies.set("mata_session_local", "opaque-session-token")

    response = client.post(
        "/api/v1/protected",
        headers={"X-CSRF-Token": "valid-csrf-token"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == ErrorCode.UNAUTHORIZED.value
    assert "set-cookie" not in response.headers
    assert response.json() != {"role": "admin"}
    assert touches == [False, True]
    assert csrf_values == ["valid-csrf-token"]


def test_unknown_session_and_store_failure_do_not_clear_shared_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_client, _, _ = _cookie_middleware_client(monkeypatch, resolved_session=None)
    missing_client.cookies.set("mata_session_local", "unknown-session")
    unknown = missing_client.get("/api/v1/protected")

    assert unknown.status_code == 401
    assert unknown.json()["error_code"] == ErrorCode.UNAUTHORIZED.value
    assert "set-cookie" not in unknown.headers

    failing_client, _, _ = _cookie_middleware_client(
        monkeypatch,
        resolve_error=RuntimeError("postgresql://user:secret@private/session-token"),
    )
    failing_client.cookies.set("mata_session_local", "opaque-session-secret")
    unavailable = failing_client.get("/api/v1/protected")

    assert unavailable.status_code == 503
    assert "postgresql" not in unavailable.text
    assert "opaque-session-secret" not in unavailable.text
    assert "set-cookie" not in unavailable.headers


def test_cookie_mode_rejects_raw_identity_headers_and_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _ = _cookie_middleware_client(
        monkeypatch,
        resolved_session=_active_session(),
    )
    raw_headers = client.get(
        "/api/v1/protected",
        headers={"X-User-Role": "admin", "X-User-Id": str(SUBJECT_ID)},
    )
    client.cookies.set("mata_session_local", "opaque-session-token")
    bearer = client.get(
        "/api/v1/protected",
        headers={"Authorization": "Bearer browser-token"},
    )

    assert raw_headers.status_code == 401
    assert bearer.status_code == 401


def test_production_public_mutations_require_exact_origin_and_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _production_settings()
    app = FastAPI()
    configure_cors(app, settings)

    @app.post("/api/v1/auth/login")
    async def public_login() -> dict[str, bool]:
        return {"accepted": True}

    app.add_middleware(AuthStubMiddleware, settings=settings)
    client = TestClient(app, base_url="https://mata.example.com")

    approved = client.post(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://mata.example.com",
            "Sec-Fetch-Site": "same-origin",
            **COORDINATION_HEADERS,
        },
        json={"role": "resident", "mcr": "M10000A"},
    )
    missing_coordination = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://mata.example.com"},
        json={"role": "resident", "mcr": "M10000A"},
    )
    wrong_coordination = client.post(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://mata.example.com",
            AUTH_COOKIE_COORDINATION_HEADER_NAME: "wrong-version",
        },
        json={"role": "resident", "mcr": "M10000A"},
    )
    missing_origin = client.post(
        "/api/v1/auth/login",
        json={"role": "resident", "mcr": "M10000A"},
    )
    unapproved = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://preview-attacker.example.com"},
        json={"role": "resident", "mcr": "M10000A"},
    )
    direct_backend_browser = client.post(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://mata.example.com",
            "Sec-Fetch-Site": "same-site",
            **COORDINATION_HEADERS,
        },
        json={"role": "resident", "mcr": "M10000A"},
    )
    bearer = client.post(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://mata.example.com",
            "Authorization": "Bearer browser-token",
            **COORDINATION_HEADERS,
        },
        json={"role": "resident", "mcr": "M10000A"},
    )
    wrong_content_type = client.post(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://mata.example.com",
            "Content-Type": "text/plain",
        },
        content="credential-body",
    )
    preflight = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://mata.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": (
                "content-type,x-mata-session-coordination"
            ),
        },
    )
    bearer_preflight = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://mata.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert approved.status_code == 200
    assert missing_coordination.status_code == 409
    assert wrong_coordination.status_code == 409
    assert "set-cookie" not in missing_coordination.headers
    assert "set-cookie" not in wrong_coordination.headers
    assert missing_origin.status_code == 403
    assert unapproved.status_code == 403
    assert "preview-attacker" not in unapproved.text
    assert direct_backend_browser.status_code == 403
    assert bearer.status_code == 401
    assert "browser-token" not in bearer.text
    assert wrong_content_type.status_code == 415
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://mata.example.com"
    assert AUTH_COOKIE_COORDINATION_HEADER_NAME.lower() in (
        preflight.headers["access-control-allow-headers"].lower()
    )
    assert bearer_preflight.status_code == 400
    assert "authorization" not in (
        bearer_preflight.headers.get("access-control-allow-headers", "").lower()
    )
    assert "browser-token" not in bearer_preflight.text


def test_security_headers_no_store_and_trusted_host_contract() -> None:
    settings = _production_settings()
    app = FastAPI()
    configure_trusted_hosts(app, settings)

    @app.get("/identity")
    async def identity(request: Request) -> dict[str, bool | str]:
        return {
            "authenticated": True,
            "request_path": request.url.path,
        }

    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    client = TestClient(app, base_url="https://mata.example.com")

    response = client.get("/identity")
    rejected_host = client.get("/identity", headers={"Host": "unapproved.example.com"})
    poisoned_host = client.get(
        "/identity",
        headers={"Host": "mata.example.com:443/forged?path="},
    )

    assert response.status_code == 200
    assert response.headers["Strict-Transport-Security"].startswith("max-age=")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "object-src 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["CDN-Cache-Control"] == "no-store"
    assert response.headers["Vercel-CDN-Cache-Control"] == "no-store"
    assert {item.strip() for item in response.headers["Vary"].split(",")} >= {
        "Origin",
        "Cookie",
    }
    assert rejected_host.status_code == 400
    assert poisoned_host.status_code == 400
    assert poisoned_host.text == "Invalid host header"


def test_outer_security_middleware_contains_unexpected_errors_with_safe_headers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = _production_settings()
    app = FastAPI()

    @app.get("/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("private path and credential must never be returned")

    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    client = TestClient(app, base_url="https://mata.example.com")

    with caplog.at_level(logging.ERROR, logger="app.middleware.errors"):
        response = client.get("/unexpected")

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"].startswith("no-store")
    assert response.headers["X-Correlation-ID"]
    assert "credential must never be returned" not in response.text
    assert "credential must never be returned" not in caplog.text
    assert "Traceback" not in caplog.text


def test_application_middleware_order_rejects_host_before_auth_and_wraps_all_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as main_module

    settings = Settings(environment="test", _env_file=None)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    app = main_module.create_app()

    assert [middleware.cls.__name__ for middleware in app.user_middleware] == [
        "SecurityHeadersMiddleware",
        "StrictHostSyntaxMiddleware",
        "TrustedHostMiddleware",
        "CORSMiddleware",
        "RequestBodyLimitMiddleware",
        "AuthStubMiddleware",
        "UploadGuardMiddleware",
        "RateLimitMiddleware",
    ]
