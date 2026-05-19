from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.schemas.auth import LoginRequest
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
) -> dict:
    return await auth_service.login(
        db,
        role=request.role,
        email=request.email,
        password=request.password,
        mcr=request.mcr,
    )


@router.get("/me")
async def me(
    x_user_role: Annotated[str | None, Header(alias="X-User-Role")] = None,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    role = (x_user_role or "").strip().lower()
    if role not in {"admin", "secretary", "resident"}:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    return await auth_service.get_current_identity(
        db,
        role=role,
        subject_id=_parse_subject(x_user_id),
    )
