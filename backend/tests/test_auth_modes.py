from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.dependencies.staff_actor import StaffActorContext, require_staff_actor
from app.middleware import install_error_handlers
from app.middleware.auth_stub import AuthStubMiddleware
from app.services.session_transport import (
    AUTH_COOKIE_COORDINATION_HEADER_NAME,
    AUTH_COOKIE_COORDINATION_PROTOCOL,
)
from app.middleware.rate_limit import RateLimitMiddleware
from app.routers.admin import AdminContext, require_admin_context
from app.services import auth as auth_service
from tests.resident_fakes import FakeResidentSession


def _protected_client(settings: Settings) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(AuthStubMiddleware, settings=settings)

    @app.get("/api/v1/protected")
    async def protected() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def _dependency_client(settings: Settings) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.dependency_overrides[get_settings] = lambda: settings

    @app.get("/admin-context")
    async def admin_context(
        context: AdminContext = Depends(require_admin_context),
    ) -> dict[str, object]:
        return {
            "user_id": str(context.user_id),
            "programme_scope": sorted(context.programme_scope),
            "is_master_admin": context.is_master_admin,
        }

    @app.get("/staff-actor")
    async def staff_actor(
        actor: StaffActorContext = Depends(require_staff_actor),
    ) -> dict[str, object]:
        return {
            "actor_role": actor.actor_role,
            "actor_site": actor.actor_site,
            "actor_programme": actor.actor_programme,
        }

    return TestClient(app)


def _rate_limit_key_client(settings: Settings) -> TestClient:
    app = FastAPI()
    middleware = RateLimitMiddleware(app, settings=settings)

    @app.get("/bucket-key")
    async def bucket_key(request: Request) -> dict[str, str]:
        return {"key": middleware._build_bucket_key(request, "test")}

    return TestClient(app)


def test_supabase_mode_rejects_mock_identity_headers() -> None:
    client = _protected_client(Settings(auth_mode="supabase"))

    response = client.get(
        "/api/v1/protected",
        headers={
            "X-User-Role": "resident",
            "X-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-User-Programme": "GRM",
        },
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_production_rejects_raw_identity_headers() -> None:
    client = _protected_client(
        Settings(
            environment="production",
            auth_mode="supabase",
            auth_transport="cookie",
            supabase_url="https://mata-test.supabase.co",
            supabase_publishable_key="sb_publishable_test_key",
            database_url="postgresql+asyncpg://runtime@db.example.invalid:5432/mata",
            auth_database_url="postgresql+asyncpg://auth@db.example.invalid:5432/mata",
            sync_database_url="postgresql+psycopg2://migration@db.example.invalid:5432/mata",
            database_rls_enabled=True,
            mata_session_hash_key="test-session-key-that-is-at-least-32-characters",
            rate_limit_store="postgres",
            rate_limit_hash_secret="test-rate-limit-key-that-is-at-least-32-characters",
            cors_origins=["https://mata.example.com"],
            allowed_hosts=["mata.example.com"],
        ),
    )

    response = client.get(
        "/api/v1/protected",
        headers={
            "X-User-Role": "admin",
            "X-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-User-Programme": "DR,GERI",
            "X-Admin-Level": "master",
            AUTH_COOKIE_COORDINATION_HEADER_NAME: (
                AUTH_COOKIE_COORDINATION_PROTOCOL
            ),
        },
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_demo_mode_login_allows_local_stub_identity_without_role_switcher_flag() -> None:
    fake_db = FakeResidentSession()

    response = await auth_service.login(
        fake_db,
        role="resident",
        email=None,
        password=None,
        mcr="M12345A",
        auth_mode="demo",
    )

    assert response["user"]["role"] == "resident"
    assert response["access_token"].startswith("stub.resident.")


def test_supabase_mode_admin_context_rejects_raw_identity_headers() -> None:
    client = _dependency_client(Settings(auth_mode="supabase"))

    response = client.get(
        "/admin-context",
        headers={
            "X-User-Role": "admin",
            "X-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-User-Programme": "DR,GERI",
            "X-Admin-Level": "master",
        },
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_supabase_mode_staff_actor_rejects_raw_identity_headers() -> None:
    client = _dependency_client(Settings(auth_mode="supabase"))

    response = client.get(
        "/staff-actor",
        headers={
            "X-User-Role": "secretary",
            "X-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-User-Site": "TTSHGerMed",
        },
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_stub_mode_staff_dependencies_accept_local_stub_headers() -> None:
    client = _dependency_client(Settings(auth_mode="stub"))

    admin_response = client.get(
        "/admin-context",
        headers={
            "X-User-Role": "admin",
            "X-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-User-Programme": "DR,GERI",
        },
    )
    staff_response = client.get(
        "/staff-actor",
        headers={
            "X-User-Role": "secretary",
            "X-User-Id": "00000000-0000-0000-0000-000000000002",
            "X-User-Site": "TTSHGerMed",
        },
    )

    assert admin_response.status_code == 200
    assert admin_response.json()["programme_scope"] == ["DR", "GERI"]
    assert staff_response.status_code == 200
    assert staff_response.json()["actor_site"] == "TTSHGerMed"


def test_supabase_rate_limit_bucket_ignores_raw_identity_headers() -> None:
    client = _rate_limit_key_client(Settings(auth_mode="supabase"))

    response = client.get(
        "/bucket-key",
        headers={
            "X-User-Role": "admin",
            "X-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-User-Programme": "DR,GERI",
            "X-User-Site": "TTSHGerMed",
        },
    )

    assert response.status_code == 200
    key = response.json()["key"]
    assert "role=anonymous" in key
    assert "user=unknown" in key
    assert "programme=" in key
    assert "DR" not in key
    assert "TTSHGerMed" not in key


@pytest.mark.asyncio
async def test_supabase_mode_login_does_not_issue_stub_token() -> None:
    fake_db = FakeResidentSession()

    response = await auth_service.login(
        fake_db,
        role="resident",
        email=None,
        password=None,
        mcr="M12345A",
        auth_mode="supabase",
    )

    assert response["user"]["role"] == "resident"
    assert response["access_token"]
    assert not response["access_token"].startswith("stub.")
