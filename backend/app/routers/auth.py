from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.dependencies.auth import require_authenticated
from app.errors import ApiError, ErrorCode
from app.middleware.auth_stub import AuthIdentity
from app.schemas.auth import LoginRequest, StaffActorNameRequest
from app.services import auth as auth_service


router = APIRouter(prefix="/auth", tags=["auth"])


try:
    from app.database import get_db_session
except Exception:

    async def get_db_session() -> AsyncIterator[AsyncSession | None]:
        yield None


def _parse_subject(raw_value: str | None) -> UUID:
    if not raw_value:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    try:
        return UUID(raw_value)
    except ValueError as exc:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        ) from exc


@router.post("/login")
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    return await auth_service.login(
        db,
        role=request.role,
        email=request.email,
        password=request.password,
        mcr=request.mcr,
        auth_mode=settings.auth_mode,
        settings=settings,
    )


@router.get("/me")
async def me(
    identity: AuthIdentity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    role = identity.role
    if role not in {"admin", "secretary", "resident", "external_resident"}:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    return await auth_service.get_current_identity(
        db,
        role=role,
        subject_id=_parse_subject(identity.subject_id),
    )


@router.post("/staff-actor-name")
async def update_staff_actor_name(
    request: StaffActorNameRequest,
    identity: AuthIdentity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    if identity.role not in {"admin", "secretary"}:
        raise ApiError(
            status_code=403,
            detail="Forbidden - staff role required",
            error_code=ErrorCode.FORBIDDEN.value,
        )
    return await auth_service.update_staff_actor_name(
        db,
        user_id=_parse_subject(identity.subject_id),
        role=identity.role,
        full_name=request.full_name,
    )
