from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import Settings, get_settings
from app.database import AsyncSessionLocal
from app.errors import ErrorCode, build_error_response
from app.models import ExternalResident, Resident, User


@dataclass
class AuthIdentity:
    role: str
    subject_id: str
    programme_scope: list[str] | None = None
    programme_code: str | None = None
    posting_code: str | None = None
    admin_level: str | None = None
    mcr: str | None = None
    home_cluster: str | None = None


class AuthStubMiddleware(BaseHTTPMiddleware):
    OPEN_PATHS = {
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
    }

    def __init__(self, app: Starlette, settings: Settings | None = None) -> None:
        super().__init__(app)
        self._settings = settings or get_settings()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if (
            request.method == "OPTIONS"
            or path in self.OPEN_PATHS
            or path.endswith("/auth/login")
            or path.endswith("/external-residents/register")
        ):
            return await call_next(request)

        if not self._stub_header_auth_allowed():
            return self._unauthorized_response()

        role = (request.headers.get("X-User-Role") or "").strip().lower()
        raw_subject = (request.headers.get("X-User-Id") or "").strip()

        if not role or not raw_subject:
            return self._unauthorized_response()

        try:
            subject_id = UUID(raw_subject)
        except ValueError:
            return self._unauthorized_response()

        if role in {"admin", "secretary"}:
            identity_or_error = await self._resolve_user_identity(request, role, subject_id)
        elif role == "resident":
            identity_or_error = await self._resolve_resident_identity(request, subject_id)
        elif role == "external_resident":
            identity_or_error = await self._resolve_external_resident_identity(subject_id)
        else:
            return self._unauthorized_response()

        if isinstance(identity_or_error, Response):
            return identity_or_error

        request.state.identity = identity_or_error
        return await call_next(request)

    async def _resolve_user_identity(
        self,
        request: Request,
        role: str,
        subject_id: UUID,
    ) -> AuthIdentity | Response:
        async with AsyncSessionLocal() as session:
            user = await session.scalar(
                select(User).where(User.id == subject_id, User.is_active.is_(True)),
            )

        if user is None or user.role != role:
            return build_error_response(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )

        if role == "admin":
            requested_programmes = self._parse_programme_header(
                request.headers.get("X-User-Programme"),
            )
            allowed_programmes = user.programme_scope or []
            admin_level = self._resolve_admin_level(
                persisted_admin_level=getattr(user, "admin_level", None),
            )
            if requested_programmes:
                if not allowed_programmes or not set(requested_programmes).issubset(
                    set(allowed_programmes),
                ):
                    return build_error_response(
                        status_code=403,
                        detail="Forbidden",
                        error_code=ErrorCode.FORBIDDEN.value,
                    )
            return AuthIdentity(
                role=role,
                subject_id=str(user.id),
                programme_scope=allowed_programmes,
                programme_code=",".join(requested_programmes) if requested_programmes else None,
                admin_level=admin_level,
            )

        # secretary role
        requested_site = (request.headers.get("X-User-Site") or "").strip()
        if not requested_site or requested_site != user.posting_code:
            return build_error_response(
                status_code=403,
                detail="Forbidden",
                error_code=ErrorCode.FORBIDDEN.value,
            )
        return AuthIdentity(
            role=role,
            subject_id=str(user.id),
            posting_code=user.posting_code,
        )

    async def _resolve_resident_identity(
        self,
        request: Request,
        subject_id: UUID,
    ) -> AuthIdentity | Response:
        async with AsyncSessionLocal() as session:
            resident = await session.scalar(select(Resident).where(Resident.id == subject_id))

        if resident is None or resident.status == "inactive":
            return build_error_response(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )

        requested_programme = (request.headers.get("X-User-Programme") or "").strip()
        if requested_programme and requested_programme != (resident.programme_code or ""):
            return build_error_response(
                status_code=403,
                detail="Forbidden",
                error_code=ErrorCode.FORBIDDEN.value,
            )

        return AuthIdentity(
            role="resident",
            subject_id=str(resident.id),
            programme_code=resident.programme_code,
            mcr=resident.mcr,
        )

    async def _resolve_external_resident_identity(
        self,
        subject_id: UUID,
    ) -> AuthIdentity | Response:
        async with AsyncSessionLocal() as session:
            resident = await session.scalar(
                select(ExternalResident).where(ExternalResident.id == subject_id),
            )

        if resident is None or resident.status == "inactive":
            return build_error_response(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )

        return AuthIdentity(
            role="external_resident",
            subject_id=str(resident.id),
            mcr=resident.mcr,
            home_cluster=resident.home_cluster,
        )

    @staticmethod
    def _unauthorized_response() -> Response:
        return build_error_response(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )

    @staticmethod
    def _parse_programme_header(raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        return [token.strip() for token in raw_value.split(",") if token.strip()]

    def _resolve_admin_level(
        self,
        *,
        persisted_admin_level: str | None,
    ) -> str:
        persisted = self._normalise_admin_level(persisted_admin_level) or "programme"
        if persisted == "master":
            return "master"

        return persisted

    def _stub_header_auth_allowed(self) -> bool:
        return (
            self._settings.environment != "production"
            and self._settings.auth_mode in {"stub", "demo"}
        )

    @staticmethod
    def _normalise_admin_level(raw_value: str | None) -> str | None:
        if not raw_value:
            return None
        value = raw_value.strip().lower()
        if value == "master_admin":
            return "master"
        if value in {"programme", "master"}:
            return value
        return None
