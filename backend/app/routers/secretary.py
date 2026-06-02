from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.schemas.secretary import (
    SecretaryTeachingEventCreateRequest,
    SecretaryTeachingEventUpdateRequest,
    SecretaryTeachingEventDuplicateRequest,
    SecretaryTeachingEventSeriesCreateRequest,
)
from app.services import secretary_events


router = APIRouter(prefix="/secretary", tags=["secretary"])


try:
    from app.database import get_db_session
except Exception:

    async def get_db_session() -> AsyncIterator[AsyncSession | None]:
        yield None


@dataclass(slots=True)
class SecretaryContext:
    user_id: UUID
    posting_code: str


async def require_secretary_context(
    x_user_role: Annotated[str | None, Header(alias="X-User-Role")] = None,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_user_site: Annotated[str | None, Header(alias="X-User-Site")] = None,
) -> SecretaryContext:
    if x_user_role != "secretary":
        raise ApiError(
            status_code=403,
            detail="Forbidden - secretary role required",
            error_code=ErrorCode.FORBIDDEN.value,
        )
    if not x_user_id:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    if not x_user_site or not x_user_site.strip():
        raise ApiError(
            status_code=403,
            detail="Forbidden - secretary posting scope is required",
            error_code=ErrorCode.FORBIDDEN.value,
        )

    try:
        user_id = UUID(x_user_id)
    except ValueError as exc:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        ) from exc

    return SecretaryContext(user_id=user_id, posting_code=x_user_site.strip())


@router.get("/teaching-events")
async def list_teaching_events(
    date_from: date | None = None,
    date_to: date | None = None,
    session_type_id: UUID | None = None,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    events = await secretary_events.list_teaching_events(
        db,
        posting_code=secretary_context.posting_code,
        date_from=date_from,
        date_to=date_to,
        session_type_id=session_type_id,
    )
    return {"events": events}


@router.post("/teaching-events")
async def create_teaching_event(
    request: SecretaryTeachingEventCreateRequest,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await secretary_events.create_teaching_event(
        db,
        posting_code=secretary_context.posting_code,
        teaching_name=request.teaching_name,
        event_date=request.event_date,
        start_time=request.start_time,
        cme_points_awarded=request.cme_points_awarded,
        smc_event_code=request.smc_event_code,
    )


@router.post("/teaching-events/duplicate")
async def duplicate_teaching_event(
    request: SecretaryTeachingEventDuplicateRequest,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await secretary_events.duplicate_teaching_event(
        db,
        posting_code=secretary_context.posting_code,
        source_event_id=request.source_event_id,
        event_date=request.event_date,
        start_time=request.start_time,
        teaching_name=request.teaching_name,
    )


@router.put("/teaching-events/{event_id}")
async def update_teaching_event(
    event_id: UUID,
    request: SecretaryTeachingEventUpdateRequest,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await secretary_events.update_teaching_event(
        db,
        posting_code=secretary_context.posting_code,
        event_id=event_id,
        teaching_name=request.teaching_name,
        event_date=request.event_date,
        start_time=request.start_time,
        cme_points_awarded=request.cme_points_awarded,
        smc_event_code=request.smc_event_code,
    )


@router.delete("/teaching-events/{event_id}")
async def delete_teaching_event(
    event_id: UUID,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await secretary_events.delete_teaching_event(
        db,
        posting_code=secretary_context.posting_code,
        event_id=event_id,
    )


@router.post("/teaching-events/series")
async def create_event_series(
    request: SecretaryTeachingEventSeriesCreateRequest,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await secretary_events.create_event_series(
        db,
        posting_code=secretary_context.posting_code,
        teaching_name=request.teaching_name,
        start_date=request.start_date,
        start_time=request.start_time,
        cme_points_awarded=request.cme_points_awarded,
        smc_event_code=request.smc_event_code,
        recurrence_pattern=request.recurrence_pattern,
        recurrence_interval=request.recurrence_interval,
        days_of_week=request.days_of_week,
        end_type=request.end_type,
        end_date=request.end_date,
        end_after_count=request.end_after_count,
    )


@router.delete("/teaching-events/series/{series_id}")
async def delete_event_series(
    series_id: UUID,
    scope: Annotated[str, Query()],
    event_id: UUID | None = None,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await secretary_events.delete_event_series(
        db,
        posting_code=secretary_context.posting_code,
        series_id=series_id,
        scope=scope,
        event_id=event_id,
    )


@router.get("/cme-dashboard")
async def cme_dashboard(
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await secretary_events.cme_dashboard(
        db,
        posting_code=secretary_context.posting_code,
    )


@router.get("/residents")
async def current_residents(
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    residents = await secretary_events.current_residents(
        db,
        posting_code=secretary_context.posting_code,
    )
    return {"residents": residents}


@router.get("/teaching-name-options")
async def teaching_name_options(
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    options = await secretary_events.teaching_name_options(
        db,
        posting_code=secretary_context.posting_code,
    )
    return {"options": options}
