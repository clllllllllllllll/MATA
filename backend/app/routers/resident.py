from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.schemas.resident import ResidentAdhocTeachingRequest, ResidentAttendanceSubmitRequest
from app.services import resident_submission


router = APIRouter(prefix="/resident", tags=["resident"])


try:
    from app.database import get_db_session
except Exception:

    async def get_db_session() -> AsyncIterator[AsyncSession | None]:
        yield None


@dataclass(slots=True)
class ResidentContext:
    resident_id: UUID
    programme_code: str | None
    mcr: str | None


async def require_resident_context(
    x_user_role: Annotated[str | None, Header(alias="X-User-Role")] = None,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_user_programme: Annotated[str | None, Header(alias="X-User-Programme")] = None,
    x_user_mcr: Annotated[str | None, Header(alias="X-User-MCR")] = None,
) -> ResidentContext:
    if x_user_role != "resident":
        raise ApiError(
            status_code=403,
            detail="Forbidden - resident role required",
            error_code=ErrorCode.FORBIDDEN.value,
        )
    if not x_user_id:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    try:
        resident_id = UUID(x_user_id)
    except ValueError as exc:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        ) from exc
    return ResidentContext(
        resident_id=resident_id,
        programme_code=(x_user_programme or "").strip() or None,
        mcr=(x_user_mcr or "").strip() or None,
    )


@router.get("/events")
async def list_events(
    date_from: date | None = None,
    date_to: date | None = None,
    resident_context: ResidentContext = Depends(require_resident_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await resident_submission.list_available_events(
        db,
        resident_id=resident_context.resident_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.post("/attendance")
async def submit_attendance(
    request: ResidentAttendanceSubmitRequest,
    resident_context: ResidentContext = Depends(require_resident_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await resident_submission.submit_attendance(
        db,
        resident_id=resident_context.resident_id,
        event_ids=request.event_ids,
    )


@router.delete("/attendance/{attendance_id}")
async def delete_attendance(
    attendance_id: UUID,
    resident_context: ResidentContext = Depends(require_resident_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await resident_submission.remove_attendance(
        db,
        resident_id=resident_context.resident_id,
        attendance_id=attendance_id,
    )


@router.post("/adhoc-teaching")
async def submit_adhoc_teaching(
    request: ResidentAdhocTeachingRequest,
    resident_context: ResidentContext = Depends(require_resident_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await resident_submission.submit_adhoc_teaching(
        db,
        resident_id=resident_context.resident_id,
        event_date=request.date,
        start_time=request.start_time,
        teaching_name=request.teaching_name,
    )


@router.get("/dashboard")
async def dashboard(
    resident_context: ResidentContext = Depends(require_resident_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await resident_submission.dashboard_placeholder(
        db,
        resident_id=resident_context.resident_id,
    )
