from __future__ import annotations

from starlette.datastructures import Headers
from fastapi import FastAPI

from app.middleware.auth_stub import AuthIdentity


def _parse_scope(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [token.strip() for token in raw_value.split(",") if token.strip()]


def identity_from_stub_headers(headers: Headers) -> AuthIdentity | None:
    role = (headers.get("X-User-Role") or "").strip().lower()
    subject_id = (headers.get("X-User-Id") or "").strip()
    if not role or not subject_id:
        return None

    if role == "admin":
        programme_scope = _parse_scope(headers.get("X-User-Programme"))
        admin_level = (headers.get("X-Admin-Level") or "").strip().lower() or "programme"
        if admin_level == "master_admin":
            admin_level = "master"
        return AuthIdentity(
            role="admin",
            subject_id=subject_id,
            programme_scope=programme_scope,
            programme_code=",".join(programme_scope) or None,
            admin_level=admin_level,
        )
    if role == "secretary":
        return AuthIdentity(
            role="secretary",
            subject_id=subject_id,
            posting_code=(headers.get("X-User-Site") or "").strip() or None,
        )
    if role == "resident":
        return AuthIdentity(
            role="resident",
            subject_id=subject_id,
            programme_code=(headers.get("X-User-Programme") or "").strip() or None,
        )
    if role == "external_resident":
        return AuthIdentity(
            role="external_resident",
            subject_id=subject_id,
        )
    return None


def install_stub_header_identity_middleware(
    app: FastAPI,
    *,
    default_identity: AuthIdentity | None = None,
) -> None:
    @app.middleware("http")
    async def inject_identity(request, call_next):  # noqa: ANN001
        identity = default_identity or identity_from_stub_headers(request.headers)
        if identity is not None:
            request.state.identity = identity
        return await call_next(request)
