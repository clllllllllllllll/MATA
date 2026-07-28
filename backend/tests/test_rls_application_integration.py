from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Mapping
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import database
from app.config import Settings, get_settings
from app.middleware.auth_stub import AuthStubMiddleware
from app.routers import auth, external_residents
from app.services import app_sessions
from app.services.database_context import (
    AUTH_BOUNDARY_INFO_KEY,
    RLS_ENABLED_INFO_KEY,
)


SESSION_KEY = "unit-test-session-hash-key-at-least-32-characters"
SUBJECT_ID = UUID("00000000-0000-0000-0000-000000000321")
FINGERPRINT = "a" * 64


def _session_settings() -> SimpleNamespace:
    return SimpleNamespace(
        environment="test",
        mata_session_hash_key=SESSION_KEY,
        staff_session_idle_timeout_seconds=30 * 60,
        staff_session_absolute_timeout_seconds=8 * 60 * 60,
        resident_session_idle_timeout_seconds=60 * 60,
        resident_session_absolute_timeout_seconds=12 * 60 * 60,
        session_rotation_seconds=15 * 60,
        session_touch_interval_seconds=60,
        session_cleanup_retention_seconds=7 * 24 * 60 * 60,
        session_cleanup_batch_size=500,
    )


def _rls_settings() -> Settings:
    return Settings(
        environment="test",
        auth_mode="supabase",
        auth_transport="cookie",
        database_rls_enabled=True,
        database_url=(
            "postgresql+asyncpg://mata_runtime_login:test@"
            "db.example.invalid:5432/mata"
        ),
        auth_database_url=(
            "postgresql+asyncpg://mata_auth_login:test@"
            "db.example.invalid:5432/mata"
        ),
        sync_database_url=(
            "postgresql+psycopg2://mata_migration_login:test@"
            "db.example.invalid:5432/mata"
        ),
        mata_session_hash_key=SESSION_KEY,
        _env_file=None,
    )


def _session_row(
    *,
    session_id: UUID,
    token_digest: bytes,
    subject_type: str = "resident",
    subject_id: UUID = SUBJECT_ID,
    generation: int = 3,
    session_family_id: UUID | None = None,
    auth_source: str = "mata_resident",
    csrf_token_digest: bytes,
    created_at: datetime | None = None,
    absolute_expires_at: datetime | None = None,
    rotated_from_session_id: UUID | None = None,
    **extra: Any,
) -> dict[str, Any]:
    created = created_at or datetime(2026, 7, 27, 8, 0, tzinfo=UTC)
    absolute_expiry = absolute_expires_at or created + timedelta(hours=12)
    return {
        "id": session_id,
        "token_digest": token_digest,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "subject_session_generation": generation,
        "session_family_id": session_family_id or session_id,
        "auth_source": auth_source,
        "csrf_token_digest": csrf_token_digest,
        "created_at": created,
        "last_seen_at": created,
        "idle_expires_at": min(created + timedelta(hours=1), absolute_expiry),
        "absolute_expires_at": absolute_expiry,
        "revoked_at": None,
        "revoked_reason": None,
        "rotated_from_session_id": rotated_from_session_id,
        "user_agent_hash": None,
        **extra,
    }


class _Result:
    def __init__(
        self,
        *,
        mapping: Mapping[str, Any] | None = None,
        scalar: Any = None,
    ) -> None:
        self._mapping = mapping
        self._scalar = scalar

    def mappings(self) -> _Result:
        return self

    def one_or_none(self) -> Mapping[str, Any] | None:
        return self._mapping

    def scalar_one(self) -> Any:
        return self._scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class _HelperDb:
    def __init__(self, execute_handler) -> None:
        self.info = {AUTH_BOUNDARY_INFO_KEY: True}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._execute_handler = execute_handler

    async def execute(self, statement, parameters=None) -> _Result:
        sql = str(statement)
        copied_parameters = dict(parameters or {})
        self.calls.append((sql, copied_parameters))
        return self._execute_handler(sql, copied_parameters)


def _assert_call(
    db: _HelperDb,
    helper_name: str,
) -> tuple[str, dict[str, Any]]:
    return next(call for call in db.calls if helper_name in call[0])


@pytest.mark.asyncio
async def test_helper_backed_session_lifecycle_uses_only_reviewed_functions() -> None:
    settings = _session_settings()

    def issue_handler(sql: str, parameters: dict[str, Any]) -> _Result:
        if "issue_resident_app_session" in sql:
            return _Result(
                mapping={
                    "id": parameters["session_id"],
                    "subject_type": "resident",
                    "subject_id": parameters["subject_id"],
                    "subject_session_generation": parameters[
                        "expected_generation"
                    ],
                    "session_family_id": parameters["session_id"],
                    "auth_source": "mata_resident",
                }
            )
        if "cleanup_app_sessions" in sql:
            return _Result(scalar=0)
        raise AssertionError(f"Unexpected helper call: {sql}")

    issue_db = _HelperDb(issue_handler)
    created = await app_sessions.create_session(
        issue_db,
        settings,
        "resident",
        SUBJECT_ID,
        "mata_resident",
        expected_subject_session_generation=3,
        normalized_mcr=" m12345a ",
    )

    _, issue_parameters = _assert_call(
        issue_db,
        "mata_rls.issue_resident_app_session_lifecycle",
    )
    assert issue_parameters["normalized_mcr"] == "M12345A"
    assert issue_parameters["expected_subject_type"] == "resident"
    assert created.session.id == issue_parameters["session_id"]
    assert app_sessions.parse_session_token(created.session_token) is not None
    assert (
        app_sessions.csrf_for_session_token(
            created.session_token,
            settings,
        )
        == created.csrf_token
    )
    _assert_call(issue_db, "mata_rls.cleanup_app_sessions")

    def resolve_handler(sql: str, parameters: dict[str, Any]) -> _Result:
        if "resolve_app_session_lifecycle" in sql:
            return _Result(
                mapping={
                    "id": created.session.id,
                    "subject_type": "resident",
                    "subject_id": SUBJECT_ID,
                    "subject_session_generation": 3,
                    "session_family_id": created.session.session_family_id,
                    "auth_source": "mata_resident",
                    "session_refresh_required": False,
                    "authorization_fingerprint": FINGERPRINT,
                    "app_role": "resident",
                    "admin_level": None,
                    "programme_scope": [" im ", "IM", ""],
                    "posting_code": None,
                    "current_staff_actor_name": None,
                }
            )
        if "touch_app_session_lifecycle" in sql:
            return _Result(scalar=True)
        raise AssertionError(f"Unexpected helper call: {sql}")

    resolve_db = _HelperDb(resolve_handler)
    resolved = await app_sessions.resolve_session(
        resolve_db,
        settings,
        created.session_token,
        touch=True,
    )

    assert resolved is not None
    _assert_call(resolve_db, "mata_rls.resolve_app_session_lifecycle")
    _assert_call(resolve_db, "mata_rls.touch_app_session_lifecycle")
    assert app_sessions.authorization_fingerprint_for_session(resolved) == FINGERPRINT
    assert app_sessions.identity_context_for_session(resolved) == {
        "app_role": "resident",
        "admin_level": None,
        "programme_scope": ["IM"],
        "posting_code": None,
        "current_staff_actor_name": None,
    }

    def rotate_handler(sql: str, parameters: dict[str, Any]) -> _Result:
        if "rotate_app_session" in sql:
            return _Result(
                mapping={
                    "id": parameters["new_session_id"],
                    "subject_type": "resident",
                    "subject_id": SUBJECT_ID,
                    "subject_session_generation": 3,
                    "session_family_id": created.session.session_family_id,
                    "auth_source": "mata_resident",
                    "rotated_from_session_id": created.session.id,
                }
            )
        if "cleanup_app_sessions" in sql:
            return _Result(scalar=0)
        raise AssertionError(f"Unexpected helper call: {sql}")

    rotate_db = _HelperDb(rotate_handler)
    rotated = await app_sessions.rotate_session(
        rotate_db,
        settings,
        created.session,
        session_token=created.session_token,
    )

    _, rotate_parameters = _assert_call(
        rotate_db,
        "mata_rls.rotate_app_session_lifecycle",
    )
    assert rotate_parameters["expected_parent_id"] == created.session.id
    assert rotated.session.rotated_from_session_id == created.session.id
    assert rotated.session.session_family_id == created.session.session_family_id
    assert rotated.session_token != created.session_token
    assert rotated.csrf_token != created.csrf_token
    assert created.session.revoked_reason == "rotated"
    _assert_call(rotate_db, "mata_rls.cleanup_app_sessions")

    revoke_db = _HelperDb(
        lambda sql, _parameters: (
            _Result(scalar=True)
            if "revoke_app_session" in sql
            else pytest.fail(f"Unexpected helper call: {sql}")
        )
    )
    assert await app_sessions.revoke_session(
        revoke_db,
        rotated.session,
        reason=" test_logout ",
    )
    _, revoke_parameters = _assert_call(
        revoke_db,
        "mata_rls.revoke_app_session",
    )
    assert revoke_parameters == {
        "token_digest": rotated.session.token_digest,
        "session_id": rotated.session.id,
        "reason": "test_logout",
    }
    assert rotated.session.revoked_reason == "test_logout"


@pytest.mark.asyncio
async def test_logout_family_helper_is_auth_only_and_requires_both_digests() -> None:
    settings = _session_settings()
    session_bytes = b"s" * 32
    csrf_bytes = b"c" * 32
    session_token = app_sessions._encode_raw_token(session_bytes)
    csrf_token = app_sessions._encode_raw_token(csrf_bytes)
    auth_db = _HelperDb(
        lambda sql, _parameters: (
            _Result(scalar=2)
            if "revoke_app_session_family_for_logout" in sql
            else pytest.fail(f"Unexpected helper call: {sql}")
        )
    )

    assert (
        await app_sessions.revoke_session_family_for_logout(
            auth_db,
            settings,
            session_token=session_token,
            csrf_token=csrf_token,
            reason=" logout ",
        )
        == 2
    )
    _, parameters = _assert_call(
        auth_db,
        "mata_rls.revoke_app_session_family_for_logout",
    )
    key = app_sessions._session_hash_key(settings)
    assert parameters == {
        "token_digest": app_sessions._session_digest(
            session_bytes,
            key=key,
        ),
        "csrf_token_digest": app_sessions._csrf_digest(
            csrf_bytes,
            key=key,
        ),
        "reason": "logout",
    }

    runtime_db = _HelperDb(
        lambda sql, _parameters: pytest.fail(
            f"Runtime boundary reached auth-only helper: {sql}"
        )
    )
    runtime_db.info = {RLS_ENABLED_INFO_KEY: True}
    with pytest.raises(
        app_sessions.AppSessionConfigurationError,
        match="auth database boundary",
    ):
        await app_sessions.revoke_session_family_for_logout(
            runtime_db,
            settings,
            session_token=session_token,
            csrf_token=csrf_token,
        )
    assert runtime_db.calls == []

    malformed_db = _HelperDb(
        lambda sql, _parameters: pytest.fail(
            f"Malformed logout proof reached database helper: {sql}"
        )
    )
    assert (
        await app_sessions.revoke_session_family_for_logout(
            malformed_db,
            settings,
            session_token=session_token,
            csrf_token=None,
        )
        == 0
    )
    assert malformed_db.calls == []


@pytest.mark.asyncio
async def test_helper_rejection_is_controlled_but_database_errors_propagate() -> None:
    settings = _session_settings()
    session_id = uuid4()
    family_id = uuid4()
    session_token = app_sessions._encode_raw_token(b"s" * 32)
    digest = app_sessions._session_digest(
        b"s" * 32,
        key=app_sessions._session_hash_key(settings),
    )
    parent = app_sessions._app_session_from_mapping(
        _session_row(
            session_id=session_id,
            token_digest=digest,
            session_family_id=family_id,
            csrf_token_digest=b"c" * 32,
        )
    )

    rejected_db = _HelperDb(lambda _sql, _parameters: _Result(mapping=None))
    with pytest.raises(
        app_sessions.AppSessionInvalidError,
        match="no longer active",
    ):
        await app_sessions.rotate_session(
            rejected_db,
            settings,
            parent,
            session_token=session_token,
        )

    def fail_execute(_sql: str, _parameters: dict[str, Any]) -> _Result:
        raise RuntimeError("database connection failed")

    failing_db = _HelperDb(fail_execute)
    with pytest.raises(RuntimeError, match="database connection failed"):
        await app_sessions.resolve_session(
            failing_db,
            settings,
            session_token,
        )


class _MiddlewareDb:
    def __init__(self) -> None:
        self.commits = 0

    async def __aenter__(self) -> _MiddlewareDb:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        return False

    async def commit(self) -> None:
        self.commits += 1


def _rls_resolved_session() -> Any:
    return app_sessions._app_session_from_mapping(
        _session_row(
            session_id=uuid4(),
            token_digest=b"t" * 32,
            csrf_token_digest=b"c" * 32,
            authorization_fingerprint=FINGERPRINT,
            app_role="resident",
            admin_level=None,
            programme_scope=["IM"],
            posting_code=None,
            current_staff_actor_name=None,
        )
    )


def _middleware_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    resolved_session: Any | None = None,
    resolve_error: Exception | None = None,
) -> TestClient:
    settings = _rls_settings()

    async def resolve(_db, _settings, _token, **_kwargs):
        if resolve_error is not None:
            raise resolve_error
        return resolved_session

    monkeypatch.setattr(
        "app.middleware.auth_stub.AsyncSessionLocal",
        lambda: _MiddlewareDb(),
    )
    monkeypatch.setattr("app.middleware.auth_stub.resolve_session", resolve)

    app = FastAPI()

    @app.get("/api/v1/protected")
    async def protected(request: Request) -> dict[str, Any]:
        identity = request.state.identity
        return {
            "role": identity.role,
            "subject_id": identity.subject_id,
            "programme_code": identity.programme_code,
            "authorization_fingerprint": (
                request.state.authorization_fingerprint
            ),
        }

    app.add_middleware(AuthStubMiddleware, settings=settings)
    return TestClient(app)


def test_cookie_middleware_uses_database_identity_and_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _middleware_client(
        monkeypatch,
        resolved_session=_rls_resolved_session(),
    )
    client.cookies.set("mata_session_local", "opaque-session-token")

    response = client.get("/api/v1/protected")

    assert response.status_code == 200
    assert response.json() == {
        "role": "resident",
        "subject_id": str(SUBJECT_ID),
        "programme_code": "IM",
        "authorization_fingerprint": FINGERPRINT,
    }


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        (
            app_sessions.AppSessionInvalidError(
                "database rejected the session binding"
            ),
            401,
        ),
        (RuntimeError("database connection unavailable"), 503),
    ],
)
def test_cookie_middleware_keeps_invalid_and_unexpected_failures_distinct(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_status: int,
) -> None:
    client = _middleware_client(monkeypatch, resolve_error=failure)
    client.cookies.set("mata_session_local", "opaque-session-token")

    response = client.get("/api/v1/protected")

    assert response.status_code == expected_status
    assert "database rejected" not in response.text
    assert "database connection" not in response.text
    assert "set-cookie" not in response.headers


def _route(router, path: str, method: str) -> APIRoute:
    return next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


def _dependency_calls(route: APIRoute) -> set[Any]:
    calls: set[Any] = set()
    pending = list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        calls.add(dependency.call)
        pending.extend(dependency.dependencies)
    return calls


def test_public_auth_and_registration_routes_use_only_auth_boundary_dependency() -> None:
    public_routes = [
        _route(auth.router, "/auth/login", "POST"),
        _route(
            external_residents.router,
            "/external-residents/registration-options",
            "GET",
        ),
        _route(
            external_residents.router,
            "/external-residents/register",
            "POST",
        ),
    ]

    for route in public_routes:
        dependency_calls = _dependency_calls(route)
        assert database.get_auth_db_session in dependency_calls
        assert database.get_db_session not in dependency_calls


class _AuthBoundaryFactory:
    def __init__(self) -> None:
        self.sessions: list[_MiddlewareDb] = []

    def __call__(self) -> _MiddlewareDb:
        session = _MiddlewareDb()
        self.sessions.append(session)
        return session


def test_no_cookie_logout_uses_auth_boundary_and_remains_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _rls_settings()
    auth_boundary_factory = _AuthBoundaryFactory()
    monkeypatch.setattr(database, "AuthSessionLocal", auth_boundary_factory)

    app = FastAPI()
    app.include_router(auth.router, prefix=settings.api_prefix)
    app.dependency_overrides[get_settings] = lambda: settings
    app.add_middleware(AuthStubMiddleware, settings=settings)

    response = TestClient(app).post("/api/v1/auth/logout")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "server_logout_confirmed": False,
    }
    assert len(auth_boundary_factory.sessions) == 1
    assert auth_boundary_factory.sessions[0].commits == 0
    assert "set-cookie" not in response.headers
