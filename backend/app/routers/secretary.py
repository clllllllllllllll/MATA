from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, AsyncIterator, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session, get_exclusive_db_session
from app.dependencies.auth import require_secretary
from app.dependencies.staff_actor import StaffActorContext, require_staff_actor
from app.errors import ApiError, ErrorCode
from app.middleware.auth_stub import AuthIdentity
from app.security import log_safe_exception
from app.schemas.secretary import (
    SecretaryTeachingEventCreateRequest,
    SecretaryTeachingEventUpdateRequest,
    SecretaryTeachingEventDuplicateRequest,
    SecretaryTeachingEventSeriesCreateRequest,
)
from app.schemas.teaching_names import (
    TeachingNameCreateRequest,
    TeachingNameDeleteRequest,
    TeachingNameDeleteResponse,
    TeachingNameListResponse,
    TeachingNameMutationResponse,
    TeachingNameProgrammeListResponse,
    TeachingNameRevisionRequest,
    TeachingNameUpdateRequest,
)
from app.services.audit import write_audit_log
from app.services import secretary_events, teaching_name_pool
from app.services.teaching_event_locks import acquire_teaching_event_locks


router = APIRouter(prefix="/secretary", tags=["secretary"])
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SecretaryContext:
    user_id: UUID
    posting_code: str


def _teaching_name_pool_actor(
    secretary_context: SecretaryContext,
    staff_actor: StaffActorContext,
) -> teaching_name_pool.TeachingNamePoolActor:
    return teaching_name_pool.TeachingNamePoolActor(
        kind="secretary",
        user_id=secretary_context.user_id,
        staff_actor=staff_actor,
        posting_code=secretary_context.posting_code,
    )


_SECRETARY_AUDIT_ACTIONS = {
    ("teaching_event", "create"): "secretary.teaching_event.create",
    ("teaching_event", "duplicate"): "secretary.teaching_event.duplicate",
    ("teaching_event", "update"): "secretary.teaching_event.update",
    ("teaching_event", "delete"): "secretary.teaching_event.delete",
    ("teaching_event_series", "create"): "secretary.teaching_event_series.create",
    ("teaching_event_series", "delete_single"): "secretary.teaching_event_series.delete_single",
    ("teaching_event_series", "delete_following"): "secretary.teaching_event_series.delete_following",
    ("teaching_event_series", "delete_all"): "secretary.teaching_event_series.delete_all",
}

_EVENT_SNAPSHOT_SQL = """
    /* audit_snapshot:secretary_event */
    SELECT
        id,
        posting_code,
        teaching_name,
        event_date,
        start_time,
        end_time,
        duration_hours,
        session_type_id,
        teaching_name_id,
        global_session_type_id,
        series_id,
        cme_points_awarded,
        smc_event_code,
        is_adhoc,
        created_by_role,
        created_at,
        updated_at
    FROM teaching_events
    WHERE id = :event_id
      AND posting_code = :posting_code
"""

_SERIES_SNAPSHOT_SQL = """
    /* audit_snapshot:secretary_series */
    SELECT
        id,
        posting_code,
        recurrence_pattern,
        recurrence_interval,
        days_of_week,
        end_type,
        end_date,
        end_after_count,
        created_at,
        updated_at
    FROM event_series
    WHERE id = :series_id
      AND posting_code = :posting_code
    FOR UPDATE
"""

_SERIES_EVENTS_SNAPSHOT_SQL = """
    /* audit_snapshot:secretary_series_events */
    SELECT
        id,
        posting_code,
        teaching_name,
        event_date,
        start_time,
        end_time,
        duration_hours,
        session_type_id,
        teaching_name_id,
        global_session_type_id,
        series_id,
        cme_points_awarded,
        smc_event_code,
        is_adhoc,
        created_by_role,
        created_at,
        updated_at
    FROM teaching_events
    WHERE series_id = :series_id
      AND posting_code = :posting_code
    ORDER BY id ASC
    FOR UPDATE
"""


def _compact_snapshot(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


async def _read_event_audit_snapshot(
    db: AsyncSession,
    *,
    posting_code: str,
    event_id: UUID,
    lock: Literal["share", "update"] | None = None,
) -> dict[str, Any] | None:
    if lock is not None:
        await acquire_teaching_event_locks(db, event_ids=[event_id])
    lock_clause = {
        "share": "FOR SHARE",
        "update": "FOR UPDATE",
        None: "",
    }[lock]
    result = await db.execute(
        text(f"{_EVENT_SNAPSHOT_SQL}\n{lock_clause}"),
        {"event_id": str(event_id), "posting_code": posting_code},
    )
    return _compact_snapshot(result.mappings().one_or_none())


async def _read_series_audit_snapshot(
    db: AsyncSession,
    *,
    posting_code: str,
    series_id: UUID,
    scope: str | None = None,
    event_id: UUID | None = None,
) -> dict[str, Any]:
    event_ids = (
        await db.scalars(
            text(
                """
                SELECT id
                FROM teaching_events
                WHERE series_id = :series_id
                  AND posting_code = :posting_code
                """
            ),
            {
                "series_id": str(series_id),
                "posting_code": posting_code,
            },
        )
    ).all()
    await acquire_teaching_event_locks(db, event_ids=event_ids)
    series_result = await db.execute(
        text(_SERIES_SNAPSHOT_SQL),
        {"series_id": str(series_id), "posting_code": posting_code},
    )
    series = _compact_snapshot(series_result.mappings().one_or_none())
    events_result = await db.execute(
        text(_SERIES_EVENTS_SNAPSHOT_SQL),
        {"series_id": str(series_id), "posting_code": posting_code},
    )
    events = [dict(row) for row in events_result.mappings().all()]
    events.sort(key=lambda row: (row["event_date"], row["start_time"], str(row["id"])))
    if scope == "single":
        events = [row for row in events if str(row["id"]) == str(event_id)]
    elif scope == "following":
        anchor = next((row for row in events if str(row["id"]) == str(event_id)), None)
        events = [] if anchor is None else [
            row for row in events if row["event_date"] >= anchor["event_date"]
        ]
    return {
        "series": series,
        "events": events,
        "event_ids": [str(row["id"]) for row in events],
        "event_count": len(events),
        "scope": scope,
        "anchor_event_id": str(event_id) if event_id else None,
    }


def _event_audit_metadata(
    *,
    posting_code: str,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = after or before or {}
    metadata: dict[str, Any] = {
        "route_context": "secretary_teaching_event_crud",
        "mutation": action,
        "posting_code": posting_code,
        "cache_invalidation_target": f"secretary_events|posting_code={posting_code}",
    }
    if snapshot.get("event_date") is not None:
        metadata["event_date"] = snapshot["event_date"]
    if snapshot.get("teaching_name") is not None:
        metadata["teaching_name"] = snapshot["teaching_name"]
    if snapshot.get("teaching_name_id") is not None:
        metadata["teaching_name_id"] = str(snapshot["teaching_name_id"])
    if snapshot.get("global_session_type_id") is not None:
        metadata["global_session_type_id"] = str(snapshot["global_session_type_id"])
    if snapshot.get("series_id") is not None:
        metadata["series_id"] = str(snapshot["series_id"])
    return metadata


def _series_create_audit_payload(result: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    event_ids = [str(row["id"]) for row in result.get("events", [])]
    series = dict(result.get("series") or {})
    after = {
        "series": series,
        "created_count": result.get("created_count", len(event_ids)),
        "created_event_ids": event_ids,
        "warnings": result.get("warnings", []),
    }
    metadata = {
        "route_context": "secretary_teaching_event_series_crud",
        "mutation": "create",
        "posting_code": series.get("posting_code"),
        "series_id": str(series["id"]) if series.get("id") else None,
        "created_count": after["created_count"],
        "created_event_ids": event_ids,
        "cache_invalidation_target": f"secretary_events|posting_code={series.get('posting_code')}",
    }
    return after, metadata


def _series_delete_audit_metadata(
    *,
    posting_code: str,
    series_id: UUID,
    scope: str,
    event_id: UUID | None,
    before: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    event_ids = [str(value) for value in before.get("event_ids", [])]
    return {
        "route_context": "secretary_teaching_event_series_crud",
        "mutation": f"delete_{scope}",
        "posting_code": posting_code,
        "series_id": str(series_id),
        "scope": scope,
        "anchor_event_id": str(event_id) if event_id else None,
        "deleted_event_ids": event_ids,
        "deleted_count": result.get("deleted_count", len(event_ids)),
        "cache_invalidation_target": f"secretary_events|posting_code={posting_code}",
    }


async def _write_secretary_event_audit(
    db: AsyncSession,
    *,
    actor: StaffActorContext,
    mutation: Literal["create", "duplicate", "update", "delete"],
    event_id: UUID | str | None,
    posting_code: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    await write_audit_log(
        db,
        actor=actor,
        action=_SECRETARY_AUDIT_ACTIONS[("teaching_event", mutation)],
        entity_type="teaching_event",
        entity_id=event_id,
        before=before,
        after=after,
        metadata=_event_audit_metadata(
            posting_code=posting_code,
            action=mutation,
            before=before,
            after=after,
        ),
    )


async def _write_secretary_series_audit(
    db: AsyncSession,
    *,
    actor: StaffActorContext,
    mutation: Literal["create", "delete_single", "delete_following", "delete_all"],
    series_id: UUID | str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    metadata: dict[str, Any],
) -> None:
    await write_audit_log(
        db,
        actor=actor,
        action=_SECRETARY_AUDIT_ACTIONS[("teaching_event_series", mutation)],
        entity_type="teaching_event_series",
        entity_id=series_id,
        before=before,
        after=after,
        metadata=metadata,
    )


@asynccontextmanager
async def _secretary_event_mutation(
    db: AsyncSession,
    *,
    posting_code: str,
) -> AsyncIterator[None]:
    try:
        yield
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    try:
        secretary_events.invalidate_secretary_event_caches(posting_code)
    except Exception as exc:
        log_safe_exception(
            logger,
            "secretary_event_cache_invalidation_failed",
            exc,
            category="cache_invalidation",
        )


async def require_secretary_context(
    identity: AuthIdentity = Depends(require_secretary),
) -> SecretaryContext:
    try:
        user_id = UUID(identity.subject_id)
    except ValueError as exc:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        ) from exc

    return SecretaryContext(user_id=user_id, posting_code=identity.posting_code or "")


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
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    async with _secretary_event_mutation(
        db,
        posting_code=secretary_context.posting_code,
    ):
        event = await secretary_events.create_teaching_event(
            db,
            source_actor=_teaching_name_pool_actor(secretary_context, staff_actor),
            posting_code=secretary_context.posting_code,
            teaching_name_id=request.teaching_name_id,
            global_session_type_id=request.global_session_type_id,
            event_date=request.event_date,
            start_time=request.start_time,
            cme_points_awarded=request.cme_points_awarded,
            smc_event_code=request.smc_event_code,
        )
        await _write_secretary_event_audit(
            db,
            actor=staff_actor,
            mutation="create",
            event_id=event["id"],
            posting_code=secretary_context.posting_code,
            before=None,
            after=_compact_snapshot(event),
        )
    return event


@router.post("/teaching-events/duplicate")
async def duplicate_teaching_event(
    request: SecretaryTeachingEventDuplicateRequest,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    async with _secretary_event_mutation(
        db,
        posting_code=secretary_context.posting_code,
    ):
        before = await _read_event_audit_snapshot(
            db,
            posting_code=secretary_context.posting_code,
            event_id=request.source_event_id,
            lock="share",
        )
        event = await secretary_events.duplicate_teaching_event(
            db,
            source_actor=_teaching_name_pool_actor(secretary_context, staff_actor),
            posting_code=secretary_context.posting_code,
            source_event_id=request.source_event_id,
            event_date=request.event_date,
            start_time=request.start_time,
            teaching_name_id=request.teaching_name_id,
            global_session_type_id=request.global_session_type_id,
        )
        await _write_secretary_event_audit(
            db,
            actor=staff_actor,
            mutation="duplicate",
            event_id=event["id"],
            posting_code=secretary_context.posting_code,
            before=before,
            after=_compact_snapshot(event),
        )
    return event


@router.put("/teaching-events/{event_id}")
async def update_teaching_event(
    event_id: UUID,
    request: SecretaryTeachingEventUpdateRequest,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    async with _secretary_event_mutation(
        db,
        posting_code=secretary_context.posting_code,
    ):
        before = await _read_event_audit_snapshot(
            db,
            posting_code=secretary_context.posting_code,
            event_id=event_id,
            lock="update",
        )
        event = await secretary_events.update_teaching_event(
            db,
            source_actor=_teaching_name_pool_actor(secretary_context, staff_actor),
            posting_code=secretary_context.posting_code,
            event_id=event_id,
            teaching_name_id=request.teaching_name_id,
            global_session_type_id=request.global_session_type_id,
            event_date=request.event_date,
            start_time=request.start_time,
            cme_points_awarded=request.cme_points_awarded,
            smc_event_code=request.smc_event_code,
        )
        await _write_secretary_event_audit(
            db,
            actor=staff_actor,
            mutation="update",
            event_id=event_id,
            posting_code=secretary_context.posting_code,
            before=before,
            after=_compact_snapshot(event),
        )
    return event


@router.delete("/teaching-events/{event_id}")
async def delete_teaching_event(
    event_id: UUID,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    async with _secretary_event_mutation(
        db,
        posting_code=secretary_context.posting_code,
    ):
        before = await _read_event_audit_snapshot(
            db,
            posting_code=secretary_context.posting_code,
            event_id=event_id,
            lock="update",
        )
        result = await secretary_events.delete_teaching_event(
            db,
            posting_code=secretary_context.posting_code,
            event_id=event_id,
        )
        await _write_secretary_event_audit(
            db,
            actor=staff_actor,
            mutation="delete",
            event_id=event_id,
            posting_code=secretary_context.posting_code,
            before=before,
            after=None,
        )
    return result


@router.post("/teaching-events/series")
async def create_event_series(
    request: SecretaryTeachingEventSeriesCreateRequest,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    async with _secretary_event_mutation(
        db,
        posting_code=secretary_context.posting_code,
    ):
        result = await secretary_events.create_event_series(
            db,
            source_actor=_teaching_name_pool_actor(secretary_context, staff_actor),
            posting_code=secretary_context.posting_code,
            teaching_name_id=request.teaching_name_id,
            global_session_type_id=request.global_session_type_id,
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
        after, metadata = _series_create_audit_payload(result)
        await _write_secretary_series_audit(
            db,
            actor=staff_actor,
            mutation="create",
            series_id=(result.get("series") or {}).get("id"),
            before=None,
            after=after,
            metadata=metadata,
        )
    return result


@router.delete("/teaching-events/series/{series_id}")
async def delete_event_series(
    series_id: UUID,
    scope: Annotated[str, Query()],
    event_id: UUID | None = None,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    async with _secretary_event_mutation(
        db,
        posting_code=secretary_context.posting_code,
    ):
        before = await _read_series_audit_snapshot(
            db,
            posting_code=secretary_context.posting_code,
            series_id=series_id,
            scope=scope,
            event_id=event_id,
        )
        result = await secretary_events.delete_event_series(
            db,
            posting_code=secretary_context.posting_code,
            series_id=series_id,
            scope=scope,
            event_id=event_id,
        )
        await _write_secretary_series_audit(
            db,
            actor=staff_actor,
            mutation=f"delete_{scope}",  # type: ignore[arg-type]
            series_id=series_id,
            before=before,
            after=None,
            metadata=_series_delete_audit_metadata(
                posting_code=secretary_context.posting_code,
                series_id=series_id,
                scope=scope,
                event_id=event_id,
                before=before,
                result=result,
            ),
        )
    return result


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


@router.get("/reporting-periods")
async def reporting_periods(
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    db: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    del secretary_context
    return await secretary_events.list_reporting_periods(db)


@router.get(
    "/teaching-name-programmes",
    response_model=TeachingNameProgrammeListResponse,
)
async def list_teaching_name_programmes(
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    db: AsyncSession = Depends(get_db_session),
) -> TeachingNameProgrammeListResponse:
    payload = await teaching_name_pool.list_secretary_programmes(
        db,
        posting_code=secretary_context.posting_code,
    )
    return TeachingNameProgrammeListResponse.model_validate({"items": payload})


@router.get("/teaching-names", response_model=TeachingNameListResponse)
async def list_teaching_names(
    reporting_period_id: UUID = Query(...),
    programme_code: str = Query(..., min_length=1, max_length=20),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession = Depends(get_db_session),
) -> TeachingNameListResponse:
    payload = await teaching_name_pool.list_teaching_names(
        db,
        actor=_teaching_name_pool_actor(secretary_context, staff_actor),
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        is_active=is_active,
        search=search,
        limit=limit,
        offset=offset,
    )
    return TeachingNameListResponse.model_validate(payload)


@router.post("/teaching-names", response_model=TeachingNameMutationResponse)
async def create_teaching_name(
    request: TeachingNameCreateRequest,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession = Depends(get_exclusive_db_session),
) -> TeachingNameMutationResponse:
    payload = await teaching_name_pool.create_teaching_name(
        db,
        actor=_teaching_name_pool_actor(secretary_context, staff_actor),
        **request.model_dump(mode="python"),
    )
    return TeachingNameMutationResponse.model_validate(payload)


@router.patch(
    "/teaching-names/{teaching_name_id}",
    response_model=TeachingNameMutationResponse,
)
async def update_teaching_name(
    teaching_name_id: UUID,
    request: TeachingNameUpdateRequest,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession = Depends(get_exclusive_db_session),
) -> TeachingNameMutationResponse:
    payload = await teaching_name_pool.update_teaching_name(
        db,
        actor=_teaching_name_pool_actor(secretary_context, staff_actor),
        teaching_name_id=teaching_name_id,
        **request.model_dump(mode="python"),
    )
    return TeachingNameMutationResponse.model_validate(payload)


@router.post(
    "/teaching-names/{teaching_name_id}/deactivate",
    response_model=TeachingNameMutationResponse,
)
async def deactivate_teaching_name(
    teaching_name_id: UUID,
    request: TeachingNameRevisionRequest,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession = Depends(get_exclusive_db_session),
) -> TeachingNameMutationResponse:
    payload = await teaching_name_pool.deactivate_teaching_name(
        db,
        actor=_teaching_name_pool_actor(secretary_context, staff_actor),
        teaching_name_id=teaching_name_id,
        expected_revision=request.expected_revision,
    )
    return TeachingNameMutationResponse.model_validate(payload)


@router.post(
    "/teaching-names/{teaching_name_id}/reactivate",
    response_model=TeachingNameMutationResponse,
)
async def reactivate_teaching_name(
    teaching_name_id: UUID,
    request: TeachingNameRevisionRequest,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession = Depends(get_exclusive_db_session),
) -> TeachingNameMutationResponse:
    payload = await teaching_name_pool.reactivate_teaching_name(
        db,
        actor=_teaching_name_pool_actor(secretary_context, staff_actor),
        teaching_name_id=teaching_name_id,
        expected_revision=request.expected_revision,
    )
    return TeachingNameMutationResponse.model_validate(payload)


@router.delete(
    "/teaching-names/{teaching_name_id}",
    response_model=TeachingNameDeleteResponse,
)
async def delete_teaching_name(
    teaching_name_id: UUID,
    request: TeachingNameDeleteRequest,
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    staff_actor: StaffActorContext = Depends(require_staff_actor),
    db: AsyncSession = Depends(get_exclusive_db_session),
) -> TeachingNameDeleteResponse:
    payload = await teaching_name_pool.delete_teaching_name(
        db,
        actor=_teaching_name_pool_actor(secretary_context, staff_actor),
        teaching_name_id=teaching_name_id,
        **request.model_dump(mode="python"),
    )
    return TeachingNameDeleteResponse.model_validate(payload)


@router.get("/teaching-name-options")
async def teaching_name_options(
    reporting_period_id: UUID | None = Query(default=None),
    event_date: date | None = Query(default=None),
    programme_code: str | None = Query(default=None, min_length=1, max_length=20),
    secretary_context: SecretaryContext = Depends(require_secretary_context),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    options = await secretary_events.teaching_name_options(
        db,
        posting_code=secretary_context.posting_code,
        reporting_period_id=reporting_period_id,
        relevant_date=event_date,
        programme_code=programme_code,
    )
    return {"options": options}
