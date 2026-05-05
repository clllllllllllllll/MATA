from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from app.database import AsyncSessionLocal
from app.models import Resident, User


@dataclass
class AuthIdentity:
    role: str
    subject_id: str
    programme_scope: list[str] | None = None
    programme_code: str | None = None
    posting_code: str | None = None
    mcr: str | None = None


class AuthStubMiddleware(BaseHTTPMiddleware):
    OPEN_PATHS = {
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
    }

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or path in self.OPEN_PATHS:
            return await call_next(request)

        role = (request.headers.get("X-User-Role") or "").strip().lower()
        raw_subject = (request.headers.get("X-User-Id") or "").strip()

        if not role or not raw_subject:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        try:
            subject_id = UUID(raw_subject)
        except ValueError:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        if role in {"admin", "secretary"}:
            identity_or_error = await self._resolve_user_identity(request, role, subject_id)
        elif role == "resident":
            identity_or_error = await self._resolve_resident_identity(request, subject_id)
        else:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        if isinstance(identity_or_error, JSONResponse):
            return identity_or_error

        request.state.identity = identity_or_error
        return await call_next(request)

    async def _resolve_user_identity(
        self,
        request: Request,
        role: str,
        subject_id: UUID,
    ) -> AuthIdentity | JSONResponse:
        async with AsyncSessionLocal() as session:
            user = await session.scalar(
                select(User).where(User.id == subject_id, User.is_active.is_(True)),
            )

        if user is None or user.role != role:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        if role == "admin":
            requested_programmes = self._parse_programme_header(
                request.headers.get("X-User-Programme"),
            )
            allowed_programmes = user.programme_scope or []
            if requested_programmes:
                if not allowed_programmes or not set(requested_programmes).issubset(
                    set(allowed_programmes),
                ):
                    return JSONResponse(status_code=403, content={"detail": "Forbidden"})
            return AuthIdentity(
                role=role,
                subject_id=str(user.id),
                programme_scope=allowed_programmes,
                programme_code=",".join(requested_programmes) if requested_programmes else None,
            )

        # secretary role
        requested_site = (request.headers.get("X-User-Site") or "").strip()
        if not requested_site or requested_site != user.posting_code:
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})
        return AuthIdentity(
            role=role,
            subject_id=str(user.id),
            posting_code=user.posting_code,
        )

    async def _resolve_resident_identity(
        self,
        request: Request,
        subject_id: UUID,
    ) -> AuthIdentity | JSONResponse:
        async with AsyncSessionLocal() as session:
            resident = await session.scalar(select(Resident).where(Resident.id == subject_id))

        if resident is None or resident.status == "inactive":
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        requested_programme = (request.headers.get("X-User-Programme") or "").strip()
        if requested_programme and requested_programme != (resident.programme_code or ""):
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})

        return AuthIdentity(
            role="resident",
            subject_id=str(resident.id),
            programme_code=resident.programme_code,
            mcr=resident.mcr,
        )

    @staticmethod
    def _parse_programme_header(raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        return [token.strip() for token in raw_value.split(",") if token.strip()]
