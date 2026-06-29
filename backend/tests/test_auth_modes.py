from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.middleware.auth_stub import AuthStubMiddleware
from app.services import auth as auth_service
from tests.resident_fakes import FakeResidentSession


def _protected_client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.add_middleware(AuthStubMiddleware, settings=settings)

    @app.get("/api/v1/protected")
    async def protected() -> dict[str, bool]:
        return {"ok": True}

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


def test_demo_mode_rejects_mock_identity_headers_when_not_explicitly_allowed() -> None:
    client = _protected_client(
        Settings(auth_mode="demo", allow_demo_role_switcher=False),
    )

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


@pytest.mark.asyncio
async def test_supabase_mode_login_does_not_issue_stub_token() -> None:
    fake_db = FakeResidentSession()

    with pytest.raises(Exception) as exc_info:
        await auth_service.login(
            fake_db,
            role="resident",
            email=None,
            password=None,
            mcr="M12345A",
            auth_mode="supabase",
            allow_demo_role_switcher=False,
        )

    assert getattr(exc_info.value, "status_code", None) == 401
