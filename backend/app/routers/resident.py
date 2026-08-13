from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.dependencies.auth import require_resident_or_external
from app.errors import ApiError, ErrorCode
from app.middleware.auth_stub import AuthIdentity
from app.schemas.resident import ResidentAdhocTeachingRequest, ResidentAttendanceSubmitRequest
from app.services import resident_submission


router = APIRouter(prefix="/resident", tags=["resident"])


@dataclass(slots=True)
class ResidentContext:
    role: str
    subject_id: UUID
    programme_code: str | None


async def require_resident_context(
    identity: AuthIdentity = Depends(require_resident_or_external),
) -> ResidentContext:
    try:
        resident_id = UUID(identity.subject_id)
    except ValueError as exc:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        ) from exc
    return ResidentContext(
        role=identity.role,
        subject_id=resident_id,
        programme_code=identity.programme_code,
    )


@router.get("/events")
async def list_events(
    date_from: date | None = None,
    date_to: date | None = None,
    teaching_name: str | None = None,
    posting_code: str | None = None,
    resident_context: ResidentContext = Depends(require_resident_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    if resident_context.role == "external_resident":
        return await resident_submission.list_available_events(
            db,
            role="external_resident",
            external_resident_id=resident_context.subject_id,
            date_from=date_from,
            date_to=date_to,
            teaching_name=teaching_name,
            posting_code=posting_code,
        )
    return await resident_submission.list_available_events(
        db,
        role="resident",
        resident_id=resident_context.subject_id,
        date_from=date_from,
        date_to=date_to,
        teaching_name=teaching_name,
        posting_code=posting_code,
    )


@router.get("/submission-periods")
async def list_submission_periods(
    resident_context: ResidentContext = Depends(require_resident_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    if resident_context.role == "external_resident":
        return await resident_submission.list_submission_periods(
            db,
            role="external_resident",
            external_resident_id=resident_context.subject_id,
        )
    return await resident_submission.list_submission_periods(
        db,
        role="resident",
        resident_id=resident_context.subject_id,
    )


@router.post("/attendance")
async def submit_attendance(
    request: ResidentAttendanceSubmitRequest,
    resident_context: ResidentContext = Depends(require_resident_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    if resident_context.role == "external_resident":
        return await resident_submission.submit_attendance(
            db,
            role="external_resident",
            external_resident_id=resident_context.subject_id,
            event_ids=request.event_ids,
        )
    return await resident_submission.submit_attendance(
        db,
        role="resident",
        resident_id=resident_context.subject_id,
        event_ids=request.event_ids,
    )


@router.get("/attendance")
async def list_attendance(
    date_from: date | None = None,
    date_to: date | None = None,
    posting_code: str | None = None,
    teaching_name: str | None = None,
    source: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    resident_context: ResidentContext = Depends(require_resident_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    if resident_context.role == "external_resident":
        return await resident_submission.list_attendance_records(
            db,
            role="external_resident",
            external_resident_id=resident_context.subject_id,
            date_from=date_from,
            date_to=date_to,
            posting_code=posting_code,
            teaching_name=teaching_name,
            source=source,
            status=status,
            limit=limit,
            offset=offset,
        )
    return await resident_submission.list_attendance_records(
        db,
        role="resident",
        resident_id=resident_context.subject_id,
        date_from=date_from,
        date_to=date_to,
        posting_code=posting_code,
        teaching_name=teaching_name,
        source=source,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.delete("/attendance/{attendance_id}")
async def delete_attendance(
    attendance_id: UUID,
    resident_context: ResidentContext = Depends(require_resident_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    if resident_context.role == "external_resident":
        return await resident_submission.remove_external_attendance(
            db,
            external_resident_id=resident_context.subject_id,
            attendance_id=attendance_id,
        )
    return await resident_submission.remove_attendance(
        db,
        resident_id=resident_context.subject_id,
        attendance_id=attendance_id,
    )


@router.get("/adhoc-teaching-options")
async def adhoc_teaching_options(
    teaching_date: Annotated[date, Query(alias="date")],
    attended_posting_code: str | None = None,
    attended_department_posting_code: str | None = None,
    resident_context: ResidentContext = Depends(require_resident_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    selected_attended_posting_code = attended_posting_code or attended_department_posting_code
    if (
        attended_posting_code is not None
        and attended_department_posting_code is not None
        and attended_posting_code != attended_department_posting_code
    ):
        raise ApiError(
            status_code=422,
            detail="attended_posting_code and attended_department_posting_code must match when both are provided",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    if resident_context.role == "external_resident":
        return await resident_submission.list_external_adhoc_teaching_options(
            db,
            external_resident_id=resident_context.subject_id,
            teaching_date=teaching_date,
            attended_posting_code=selected_attended_posting_code,
        )
    return await resident_submission.list_adhoc_teaching_options(
        db,
        resident_id=resident_context.subject_id,
        teaching_date=teaching_date,
        attended_posting_code=selected_attended_posting_code,
    )


@router.get("/adhoc-teaching/options")
async def adhoc_teaching_options_alias(
    teaching_date: Annotated[date | None, Query(alias="teaching_date")] = None,
    date_alias: Annotated[date | None, Query(alias="date")] = None,
    attended_posting_code: str | None = None,
    attended_department_posting_code: str | None = None,
    resident_context: ResidentContext = Depends(require_resident_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    resolved_date = teaching_date or date_alias
    if resolved_date is None:
        raise ApiError(
            status_code=422,
            detail="teaching_date or date is required",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    if teaching_date is not None and date_alias is not None and teaching_date != date_alias:
        raise ApiError(
            status_code=422,
            detail="teaching_date and date must match when both are provided",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    return await adhoc_teaching_options(
        teaching_date=resolved_date,
        attended_posting_code=attended_posting_code,
        attended_department_posting_code=attended_department_posting_code,
        resident_context=resident_context,
        db=db,
    )


@router.post("/adhoc-teaching")
async def submit_adhoc_teaching(
    request: ResidentAdhocTeachingRequest,
    resident_context: ResidentContext = Depends(require_resident_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    if resident_context.role == "external_resident":
        return await resident_submission.submit_adhoc_teaching(
            db,
            role="external_resident",
            external_resident_id=resident_context.subject_id,
            event_date=request.teaching_date,
            start_time=request.start_time,
            attended_posting_code=request.attended_posting_code,
            details_of_session=request.details_of_session,
        )
    return await resident_submission.submit_adhoc_teaching(
        db,
        role="resident",
        resident_id=resident_context.subject_id,
        event_date=request.teaching_date,
        start_time=request.start_time,
        attended_posting_code=request.attended_posting_code,
        details_of_session=request.details_of_session,
    )


@router.get("/attendance-history")
async def attendance_history(
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    resident_context: ResidentContext = Depends(require_resident_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    if resident_context.role == "external_resident":
        return await resident_submission.list_attendance_history(
            db,
            role="external_resident",
            external_resident_id=resident_context.subject_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )
    return await resident_submission.list_attendance_history(
        db,
        role="resident",
        resident_id=resident_context.subject_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
    )


@router.get("/dashboard")
async def dashboard(
    resident_context: ResidentContext = Depends(require_resident_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    if resident_context.role == "external_resident":
        return await resident_submission.dashboard_placeholder(
            db,
            role="external_resident",
            external_resident_id=resident_context.subject_id,
        )
    return await resident_submission.dashboard_placeholder(
        db,
        role="resident",
        resident_id=resident_context.subject_id,
    )
