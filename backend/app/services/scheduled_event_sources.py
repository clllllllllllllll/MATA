from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.services.pool_event_timing import (
    PoolEventTimingScope,
    resolve_pool_event_timing,
)
from app.services.teaching_name_pool import TeachingNamePoolActor


ScheduledEventSourceKind = Literal["teaching_name", "global_session_type"]


@dataclass(frozen=True, slots=True)
class ScheduledEventSource:
    teaching_name_id: UUID | None
    global_session_type_id: UUID | None
    teaching_name: str
    duration_hours: Decimal
    kind: ScheduledEventSourceKind
    programme_code: str | None = None
    reporting_period_id: UUID | None = None
    duration_is_mapped: bool = True

    @property
    def is_pool_backed(self) -> bool:
        return self.kind == "teaching_name"


def require_exactly_one_source(
    *,
    teaching_name_id: UUID | None,
    global_session_type_id: UUID | None,
) -> None:
    if (teaching_name_id is None) == (global_session_type_id is None):
        raise ApiError(
            status_code=422,
            detail=(
                "Exactly one of teaching_name_id or global_session_type_id is required"
            ),
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )


def require_at_most_one_source(
    *,
    teaching_name_id: UUID | None,
    global_session_type_id: UUID | None,
) -> None:
    if teaching_name_id is not None and global_session_type_id is not None:
        raise ApiError(
            status_code=422,
            detail=(
                "Only one of teaching_name_id or global_session_type_id may be supplied"
            ),
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )


def validate_scheduled_event_start_time(
    *,
    source: ScheduledEventSource,
    start_time: time,
) -> None:
    if source.is_pool_backed and start_time > time(23, 0):
        raise _validation_error(
            "Pool-backed teaching events must start no later than 23:00"
        )


def _validation_error(detail: str) -> ApiError:
    return ApiError(
        status_code=422,
        detail=detail,
        error_code=ErrorCode.VALIDATION_FAILED.value,
    )


async def _require_pool_source_visibility(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    programme_code: str,
) -> None:
    if actor.kind == "programme_pc":
        scope = {
            value.strip().upper()
            for value in actor.programme_scope
            if isinstance(value, str) and value.strip()
        }
        if programme_code.upper() in scope:
            return
        raise ApiError(
            status_code=403,
            detail="Forbidden - Teaching Name is outside programme scope",
            error_code=ErrorCode.FORBIDDEN.value,
        )

    if actor.kind != "secretary" or not actor.posting_code:
        raise ApiError(
            status_code=403,
            detail="Forbidden - scheduled event source is not available to this role",
            error_code=ErrorCode.FORBIDDEN.value,
        )

    result = await db.execute(
        text(
            """
            /* scheduled_event_sources:secretary_capability */
            SELECT 1
            FROM secretary_programme_pools
            WHERE posting_code = :posting_code
              AND programme_code = :programme_code
              AND is_active = true
              AND can_manage_teaching_names = true
            LIMIT 1
            """
        ),
        {
            "posting_code": actor.posting_code,
            "programme_code": programme_code,
        },
    )
    if result.scalar_one_or_none() is not None:
        return
    raise ApiError(
        status_code=403,
        detail="Forbidden - Secretary cannot create events from this Teaching Name pool",
        error_code=ErrorCode.FORBIDDEN.value,
    )


async def _resolve_teaching_name_source(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    teaching_name_id: UUID,
    reporting_period_id: UUID | str,
    posting_code: str,
    programme_code: str | None,
) -> ScheduledEventSource:
    result = await db.execute(
        text(
            """
            /* scheduled_event_sources:teaching_name */
            SELECT
                id,
                reporting_period_id,
                programme_code,
                display_name AS teaching_name,
                is_active
            FROM teaching_names
            WHERE id = :teaching_name_id
            """
        ),
        {"teaching_name_id": str(teaching_name_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise _validation_error("Selected Teaching Name is unavailable")

    source = dict(row)
    source_programme_code = str(source["programme_code"])
    await _require_pool_source_visibility(
        db,
        actor=actor,
        programme_code=source_programme_code,
    )
    if programme_code is not None and source_programme_code != programme_code:
        raise _validation_error(
            "Selected Teaching Name does not belong to the requested programme"
        )
    if str(source["reporting_period_id"]) != str(reporting_period_id):
        raise _validation_error(
            "Selected Teaching Name is not in the active reporting period for this event"
        )
    if not bool(source["is_active"]):
        raise _validation_error("Selected Teaching Name is inactive")

    timing = await resolve_pool_event_timing(
        db,
        scope=PoolEventTimingScope(
            teaching_name_id=source["id"],
            reporting_period_id=source["reporting_period_id"],
            programme_code=source_programme_code,
            posting_code=posting_code,
        ),
    )

    return ScheduledEventSource(
        teaching_name_id=UUID(str(source["id"])),
        global_session_type_id=None,
        teaching_name=str(source["teaching_name"]),
        duration_hours=timing.duration_hours,
        kind="teaching_name",
        programme_code=source_programme_code,
        reporting_period_id=UUID(str(source["reporting_period_id"])),
        duration_is_mapped=timing.is_mapped,
    )


async def _resolve_global_session_type_source(
    db: AsyncSession,
    *,
    global_session_type_id: UUID,
    allow_inactive: bool = False,
) -> ScheduledEventSource:
    result = await db.execute(
        text(
            """
            /* scheduled_event_sources:global_session_type */
            SELECT id, name AS teaching_name, duration_hours, is_active
            FROM global_session_types
            WHERE id = :global_session_type_id
            """
        ),
        {"global_session_type_id": str(global_session_type_id)},
    )
    row = result.mappings().one_or_none()
    if row is None or (not allow_inactive and not bool(row["is_active"])):
        raise _validation_error("Selected Global Session Type is unavailable")

    source = dict(row)
    return ScheduledEventSource(
        teaching_name_id=None,
        global_session_type_id=UUID(str(source["id"])),
        teaching_name=str(source["teaching_name"]),
        duration_hours=Decimal(str(source["duration_hours"])),
        kind="global_session_type",
    )


async def resolve_scheduled_event_source(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    reporting_period_id: UUID | str,
    teaching_name_id: UUID | None,
    global_session_type_id: UUID | None,
    posting_code: str | None = None,
    programme_code: str | None = None,
    allow_inactive_global_session_type_id: UUID | None = None,
) -> ScheduledEventSource:
    """Resolve a write-time event source without matching display text."""

    require_exactly_one_source(
        teaching_name_id=teaching_name_id,
        global_session_type_id=global_session_type_id,
    )
    if teaching_name_id is not None:
        if not posting_code:
            raise _validation_error("posting_code is required for a Teaching Name source")
        return await _resolve_teaching_name_source(
            db,
            actor=actor,
            teaching_name_id=teaching_name_id,
            reporting_period_id=reporting_period_id,
            posting_code=posting_code,
            programme_code=programme_code,
        )
    assert global_session_type_id is not None
    return await _resolve_global_session_type_source(
        db,
        global_session_type_id=global_session_type_id,
        allow_inactive=(
            allow_inactive_global_session_type_id is not None
            and str(global_session_type_id)
            == str(allow_inactive_global_session_type_id)
        ),
    )
