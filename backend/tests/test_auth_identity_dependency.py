from __future__ import annotations

from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.dependencies.auth import (
    ensure_programme_in_scope,
    require_external_resident,
    require_master_admin,
    require_programme_pc,
)
from app.middleware.auth_stub import AuthIdentity
from app.middleware.errors import install_error_handlers
from app.models import User
from app.routers.admin import AdminContext, require_admin_context


def _identity_client(identity: AuthIdentity | None) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.middleware("http")
    async def inject_identity(request, call_next):
        if identity is not None:
            request.state.identity = identity
        return await call_next(request)

    @app.get("/master")
    async def master(current: AuthIdentity = Depends(require_master_admin)) -> dict:
        return {"subject_id": current.subject_id, "admin_level": current.admin_level}

    @app.get("/programme/{programme_code}")
    async def programme(
        programme_code: str,
        current: AuthIdentity = Depends(require_programme_pc),
    ) -> dict:
        ensure_programme_in_scope(current, programme_code)
        return {"programme_scope": current.programme_scope}

    @app.get("/external")
    async def external(
        current: AuthIdentity = Depends(require_external_resident),
    ) -> dict:
        return {"subject_id": current.subject_id, "home_cluster": current.home_cluster}

    @app.get("/admin-context")
    async def admin_context(
        current: AdminContext = Depends(require_admin_context),
    ) -> dict:
        return {
            "user_id": str(current.user_id),
            "programme_scope": sorted(current.programme_scope),
            "is_master_admin": current.is_master_admin,
        }

    return TestClient(app)


def _admin_identity(
    *,
    admin_level: str | None,
    programme_scope: list[str] | None,
) -> AuthIdentity:
    return AuthIdentity(
        role="admin",
        subject_id=str(uuid4()),
        admin_level=admin_level,
        programme_scope=programme_scope,
    )


def test_user_model_has_explicit_non_nullable_admin_level() -> None:
    column = User.__table__.c.admin_level

    assert column.nullable is False
    assert str(column.server_default.arg) == "'programme'"
    assert any(
        constraint.name == "ck_users_admin_level"
        for constraint in User.__table__.constraints
    )


def test_master_admin_requires_explicit_admin_level_marker() -> None:
    master = _identity_client(
        _admin_identity(admin_level="master", programme_scope=[]),
    )
    programme_admin = _identity_client(
        _admin_identity(admin_level="programme", programme_scope=[]),
    )
    missing_marker = _identity_client(
        _admin_identity(admin_level=None, programme_scope=[]),
    )

    assert master.get("/master").status_code == 200
    assert programme_admin.get("/master").status_code == 403
    assert missing_marker.get("/master").status_code == 403


def test_programme_pc_null_or_empty_scope_grants_no_programme_access() -> None:
    empty_scope = _identity_client(
        _admin_identity(admin_level="programme", programme_scope=[]),
    )
    null_scope = _identity_client(
        _admin_identity(admin_level="programme", programme_scope=None),
    )
    scoped = _identity_client(
        _admin_identity(admin_level="programme", programme_scope=["GRM"]),
    )

    assert empty_scope.get("/programme/GRM").status_code == 403
    assert null_scope.get("/programme/GRM").status_code == 403
    assert scoped.get("/programme/GRM").status_code == 200
    assert scoped.get("/programme/DR").status_code == 403


def test_programme_pc_scope_and_lookup_are_case_canonicalized() -> None:
    client = _identity_client(
        _admin_identity(
            admin_level="programme",
            programme_scope=[" dr ", "DR", "geri", ""],
        )
    )

    first = client.get("/programme/dr")
    second = client.get("/programme/GERI")

    assert first.status_code == 200
    assert first.json()["programme_scope"] == ["DR", "GERI"]
    assert second.status_code == 200


def test_programme_pc_dependency_rejects_master_admin() -> None:
    client = _identity_client(_admin_identity(admin_level="master", programme_scope=[]))

    response = client.get("/programme/GRM")

    assert response.status_code == 403


def test_external_resident_dependency_uses_external_identity_only() -> None:
    external = _identity_client(
        AuthIdentity(
            role="external_resident",
            subject_id=str(uuid4()),
            home_cluster="NUH",
        ),
    )
    native = _identity_client(
        AuthIdentity(role="resident", subject_id=str(uuid4()), programme_code="GRM"),
    )

    assert external.get("/external").status_code == 200
    assert external.get("/external").json()["home_cluster"] == "NUH"
    assert native.get("/external").status_code == 403


def test_admin_context_uses_verified_identity_admin_level_without_header() -> None:
    subject_id = str(uuid4())
    client = _identity_client(
        AuthIdentity(
            role="admin",
            subject_id=subject_id,
            admin_level="master",
            programme_scope=[],
        ),
    )

    response = client.get("/admin-context")

    assert response.status_code == 200
    assert response.json() == {
        "user_id": subject_id,
        "programme_scope": [],
        "is_master_admin": True,
    }
