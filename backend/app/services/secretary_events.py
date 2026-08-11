from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.services.reporting_period_status import (
    resolve_active_reporting_period_for_date,
    resolve_explicit_reporting_period,
)
from app.services import cache_invalidation
from app.services import scheduled_event_sources
from app.services.pool_event_timing import (
    DEFAULT_POOL_EVENT_DURATION_HOURS,
    list_pool_event_timings,
)
from app.services.teaching_event_locks import acquire_teaching_event_locks
from app.services.teaching_name_pool import TeachingNamePoolActor


DAY_INDEX = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def invalidate_secretary_event_caches(posting_code: str) -> None:
    cache_invalidation.invalidate_after_secretary_event_mutation(posting_code=posting_code)


def _event_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "posting_code": row["posting_code"],
        "created_for_programme_code": row.get("created_for_programme_code"),
        "teaching_name": row["teaching_name"],
        "event_date": row["event_date"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "duration_hours": row.get("duration_hours"),
        "session_type_id": row.get("session_type_id"),
        "teaching_name_id": row.get("teaching_name_id"),
        "global_session_type_id": row.get("global_session_type_id"),
        "source_programme_code": row.get("source_programme_code"),
        "source_reporting_period_id": row.get("source_reporting_period_id"),
        "session_type": row.get("session_type"),
        "series_id": row.get("series_id"),
        "cme_points_awarded": row.get("cme_points_awarded", False),
        "smc_event_code": row.get("smc_event_code"),
        "is_adhoc": row.get("is_adhoc", False),
        "created_by_role": row.get("created_by_role"),
        "has_attendance": row.get("has_attendance", False),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _compute_end_time(event_date: date, start_time: time, duration_hours: Decimal) -> time:
    minutes = int(duration_hours * Decimal("60"))
    starts_at = datetime.combine(event_date, start_time)
    return (starts_at + timedelta(minutes=minutes)).time()


async def _public_holiday_name(db: AsyncSession, event_date: date) -> str | None:
    result = await db.execute(
        text(
            """
            SELECT name
            FROM public_holidays
            WHERE holiday_date = :event_date
            """
        ),
        {"event_date": event_date},
    )
    row = result.mappings().one_or_none()
    if row is None:
        return None
    return row.get("name") or "Public holiday"


async def _programme_owned_event_in_secretary_scope(
    db: AsyncSession,
    *,
    posting_code: str,
    created_for_programme_code: str | None,
) -> bool:
    if created_for_programme_code is None:
        return True

    result = await db.execute(
        text(
            """
            SELECT programme_code
            FROM secretary_programme_pools
            WHERE posting_code = :posting_code
              AND programme_code = :programme_code
              AND is_active = true
            LIMIT 1
            """
        ),
        {
            "posting_code": posting_code,
            "programme_code": created_for_programme_code,
        },
    )
    return result.mappings().one_or_none() is not None


async def _pool_source_in_secretary_scope(
    db: AsyncSession,
    *,
    event: dict[str, Any],
) -> bool:
    source_programme = event.get("source_programme_code")
    source_period = event.get("source_reporting_period_id")
    if (source_programme is None) != (source_period is None):
        return False
    if source_programme is None:
        return event.get("teaching_name_id") is None
    if event.get("global_session_type_id") is not None:
        return False
    owner = event.get("created_for_programme_code")
    if owner is not None and owner != source_programme:
        return False
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
            "posting_code": event["posting_code"],
            "programme_code": source_programme,
        },
    )
    return result.scalar_one_or_none() is not None


def _natural_sort_key(value: str) -> tuple[str | int, ...]:
    chunks = re.split(r"(\d+)", value.strip())
    key: list[str | int] = []
    for chunk in chunks:
        if not chunk:
            continue
        if chunk.isdigit():
            key.append(int(chunk))
        else:
            key.append(chunk.casefold())
    return tuple(key)


async def _ensure_not_public_holiday(db: AsyncSession, event_date: date) -> None:
    holiday_name = await _public_holiday_name(db, event_date)
    if holiday_name is None:
        return
    raise ApiError(
        status_code=422,
        detail="Teaching events cannot be created on public holidays",
        error_code=ErrorCode.VALIDATION_FAILED.value,
        metadata={"holiday_date": event_date.isoformat(), "holiday_name": holiday_name},
    )


async def list_teaching_events(
    db: AsyncSession,
    *,
    posting_code: str,
    date_from: date | None,
    date_to: date | None,
    session_type_id: UUID | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"posting_code": posting_code}
    where = [
        "posting_code = :posting_code",
        "(created_by_role IN ('secretary', 'programme_pc') OR created_by_role IS NULL)",
        """
        (
            te.created_for_programme_code IS NULL
            OR EXISTS (
                SELECT 1
                FROM secretary_programme_pools spp
                WHERE spp.posting_code = :posting_code
                  AND spp.programme_code = te.created_for_programme_code
                  AND spp.is_active = true
            )
        )
        """,
        "is_adhoc = false",
    ]
    if date_from is not None:
        params["date_from"] = date_from
        where.append("event_date >= :date_from")
    if date_to is not None:
        params["date_to"] = date_to
        where.append("event_date <= :date_to")
    if session_type_id is not None:
        params["session_type_id"] = str(session_type_id)
        where.append("session_type_id = :session_type_id")

    result = await db.execute(
        text(
            f"""
            SELECT
                te.id,
                te.posting_code,
                te.created_for_programme_code,
                te.teaching_name,
                te.event_date,
                te.start_time,
                te.end_time,
                te.duration_hours,
                te.session_type_id,
                te.teaching_name_id,
                te.global_session_type_id,
                te.source_programme_code,
                te.source_reporting_period_id,
                st.name AS session_type,
                te.series_id,
                te.cme_points_awarded,
                te.smc_event_code,
                te.is_adhoc,
                te.created_by_role,
                EXISTS (
                    SELECT 1
                    FROM attendance_records ar
                    WHERE ar.teaching_event_id = te.id
                    LIMIT 1
                ) OR EXISTS (
                    SELECT 1
                    FROM external_attendance_records ear
                    WHERE ear.teaching_event_id = te.id
                    LIMIT 1
                ) AS has_attendance,
                te.created_at,
                te.updated_at
            FROM teaching_events te
            LEFT JOIN session_types st ON st.id = te.session_type_id
            WHERE {' AND '.join(where)}
            ORDER BY te.event_date ASC, te.start_time ASC, te.teaching_name ASC
            """
        ),
        params,
    )
    return [_event_row(dict(row)) for row in result.mappings().all()]


async def _insert_event(
    db: AsyncSession,
    *,
    source_actor: TeachingNamePoolActor,
    posting_code: str,
    teaching_name_id: UUID | None,
    global_session_type_id: UUID | None,
    event_date: date,
    start_time: time,
    cme_points_awarded: bool,
    smc_event_code: str | None,
    series_id: UUID | str | None = None,
) -> dict[str, Any]:
    period = await resolve_active_reporting_period_for_date(
        db,
        relevant_date=event_date,
    )
    if period is None:
        raise ApiError(
            status_code=422,
            detail="No active reporting period is available for the teaching event date",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    source = await scheduled_event_sources.resolve_scheduled_event_source(
        db,
        actor=source_actor,
        reporting_period_id=period["id"],
        teaching_name_id=teaching_name_id,
        global_session_type_id=global_session_type_id,
        posting_code=posting_code,
    )
    scheduled_event_sources.validate_scheduled_event_start_time(
        source=source,
        start_time=start_time,
    )
    duration_hours = source.duration_hours
    end_time = _compute_end_time(event_date, start_time, duration_hours)
    result = await db.execute(
        text(
            """
            /* secretary_events:insert */
            INSERT INTO teaching_events (
                posting_code,
                teaching_name,
                event_date,
                start_time,
                end_time,
                duration_hours,
                session_type_id,
                teaching_name_id,
                global_session_type_id,
                source_programme_code,
                source_reporting_period_id,
                series_id,
                cme_points_awarded,
                smc_event_code,
                is_adhoc,
                created_by_role
            )
            VALUES (
                :posting_code,
                :teaching_name,
                :event_date,
                :start_time,
                :end_time,
                :duration_hours,
                :session_type_id,
                :teaching_name_id,
                :global_session_type_id,
                :source_programme_code,
                :source_reporting_period_id,
                :series_id,
                :cme_points_awarded,
                :smc_event_code,
                false,
                'secretary'
            )
            RETURNING
                id,
                posting_code,
                created_for_programme_code,
                teaching_name,
                event_date,
                start_time,
                end_time,
                duration_hours,
                session_type_id,
                teaching_name_id,
                global_session_type_id,
                source_programme_code,
                source_reporting_period_id,
                series_id,
                cme_points_awarded,
                smc_event_code,
                is_adhoc,
                created_by_role,
                created_at,
                updated_at
            """
        ),
        {
            "posting_code": posting_code,
            "teaching_name": source.teaching_name,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
            "duration_hours": duration_hours,
            "session_type_id": None,
            "teaching_name_id": str(source.teaching_name_id)
            if source.teaching_name_id is not None
            else None,
            "global_session_type_id": str(source.global_session_type_id)
            if source.global_session_type_id is not None
            else None,
            "source_programme_code": source.programme_code,
            "source_reporting_period_id": (
                str(source.reporting_period_id)
                if source.reporting_period_id is not None
                else None
            ),
            "series_id": series_id,
            "cme_points_awarded": cme_points_awarded,
            "smc_event_code": smc_event_code,
        },
    )
    return _event_row(dict(result.mappings().one()))


async def create_teaching_event(
    db: AsyncSession,
    *,
    source_actor: TeachingNamePoolActor,
    posting_code: str,
    teaching_name_id: UUID | None,
    global_session_type_id: UUID | None,
    event_date: date,
    start_time: time,
    cme_points_awarded: bool,
    smc_event_code: str | None,
) -> dict[str, Any]:
    await _ensure_not_public_holiday(db, event_date)
    event = await _insert_event(
        db,
        source_actor=source_actor,
        posting_code=posting_code,
        teaching_name_id=teaching_name_id,
        global_session_type_id=global_session_type_id,
        event_date=event_date,
        start_time=start_time,
        cme_points_awarded=cme_points_awarded,
        smc_event_code=smc_event_code,
    )
    return event


async def _get_event_for_posting(
    db: AsyncSession,
    *,
    event_id: UUID,
    posting_code: str,
    source: bool = False,
    for_update: bool = False,
) -> dict[str, Any]:
    id_param = "source_event_id" if source else "event_id"
    if for_update:
        await acquire_teaching_event_locks(db, event_ids=[event_id])
    lock_clause = "FOR UPDATE" if for_update else ""
    result = await db.execute(
        text(
            f"""
            /* secretary_events:get_event_for_posting */
            SELECT
                id,
                posting_code,
                created_for_programme_code,
                teaching_name,
                event_date,
                start_time,
                end_time,
                duration_hours,
                session_type_id,
                teaching_name_id,
                global_session_type_id,
                source_programme_code,
                source_reporting_period_id,
                series_id,
                cme_points_awarded,
                smc_event_code,
                is_adhoc,
                created_by_role,
                created_at,
                updated_at
            FROM teaching_events
            WHERE id = :{id_param}
              AND posting_code = :posting_code
            {lock_clause}
            """
        ),
        {id_param: str(event_id), "posting_code": posting_code},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise ApiError(
            status_code=404,
            detail="Teaching event not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    event = dict(row)
    if not await _programme_owned_event_in_secretary_scope(
        db,
        posting_code=posting_code,
        created_for_programme_code=event.get("created_for_programme_code"),
    ):
        raise ApiError(
            status_code=404,
            detail="Teaching event not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    if not await _pool_source_in_secretary_scope(db, event=event):
        raise ApiError(
            status_code=404,
            detail="Teaching event not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    return event


async def duplicate_teaching_event(
    db: AsyncSession,
    *,
    source_actor: TeachingNamePoolActor,
    posting_code: str,
    source_event_id: UUID,
    event_date: date,
    start_time: time | None,
    teaching_name_id: UUID | None,
    global_session_type_id: UUID | None,
) -> dict[str, Any]:
    source = await _get_event_for_posting(
        db,
        event_id=source_event_id,
        posting_code=posting_code,
        source=True,
        for_update=True,
    )
    if (
        source.get("teaching_name_id") is None
        and source.get("global_session_type_id") is None
        and source.get("source_programme_code") is None
        and source.get("source_reporting_period_id") is None
        and teaching_name_id is None
        and global_session_type_id is None
    ):
        raise ApiError(
            status_code=409,
            detail="Legacy teaching events require an explicit source to be duplicated",
            error_code=ErrorCode.CONFLICT.value,
        )
    scheduled_event_sources.require_at_most_one_source(
        teaching_name_id=teaching_name_id,
        global_session_type_id=global_session_type_id,
    )
    new_teaching_name_id = teaching_name_id
    new_global_session_type_id = global_session_type_id
    if new_teaching_name_id is None and new_global_session_type_id is None:
        new_teaching_name_id = source.get("teaching_name_id")
        new_global_session_type_id = source.get("global_session_type_id")
    new_start_time = start_time or source["start_time"]
    await _ensure_not_public_holiday(db, event_date)
    event = await _insert_event(
        db,
        source_actor=source_actor,
        posting_code=posting_code,
        teaching_name_id=new_teaching_name_id,
        global_session_type_id=new_global_session_type_id,
        event_date=event_date,
        start_time=new_start_time,
        cme_points_awarded=source.get("cme_points_awarded", False),
        smc_event_code=source.get("smc_event_code"),
    )
    return event


async def update_teaching_event(
    db: AsyncSession,
    *,
    source_actor: TeachingNamePoolActor,
    posting_code: str,
    event_id: UUID,
    teaching_name_id: UUID | None,
    global_session_type_id: UUID | None,
    event_date: date,
    start_time: time,
    cme_points_awarded: bool,
    smc_event_code: str | None,
) -> dict[str, Any]:
    source = await _get_event_for_posting(
        db,
        event_id=event_id,
        posting_code=posting_code,
        for_update=True,
    )
    if source.get("created_by_role") not in {"secretary", "programme_pc", None} or source.get("is_adhoc"):
        raise ApiError(
            status_code=409,
            detail="Teaching event cannot be edited because it is not a scheduled teaching event",
            error_code=ErrorCode.CONFLICT.value,
        )
    if (
        source.get("teaching_name_id") is None
        and source.get("global_session_type_id") is None
        and source.get("source_programme_code") is None
        and source.get("source_reporting_period_id") is None
    ):
        raise ApiError(
            status_code=409,
            detail="Legacy teaching events cannot be updated through source-identity routes",
            error_code=ErrorCode.CONFLICT.value,
        )
    if await _has_attendance(db, event_ids=[str(event_id)]):
        raise ApiError(
            status_code=409,
            detail="Teaching event cannot be edited because attendance exists",
            error_code=ErrorCode.CONFLICT.value,
        )

    await _ensure_not_public_holiday(db, event_date)
    period = await resolve_active_reporting_period_for_date(
        db,
        relevant_date=event_date,
    )
    if period is None:
        raise ApiError(
            status_code=422,
            detail="No active reporting period is available for the teaching event date",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    source_identity = await scheduled_event_sources.resolve_scheduled_event_source(
        db,
        actor=source_actor,
        reporting_period_id=period["id"],
        teaching_name_id=teaching_name_id,
        global_session_type_id=global_session_type_id,
        posting_code=posting_code,
        allow_inactive_global_session_type_id=source.get("global_session_type_id"),
    )
    if source.get("source_programme_code") is not None and (
        not source_identity.is_pool_backed
        or source_identity.programme_code != source.get("source_programme_code")
        or str(source_identity.reporting_period_id)
        != str(source.get("source_reporting_period_id"))
    ):
        raise ApiError(
            status_code=409,
            detail="Teaching event source programme and reporting period are immutable",
            error_code=ErrorCode.CONFLICT.value,
        )
    if source.get("global_session_type_id") is not None and source_identity.is_pool_backed:
        raise ApiError(
            status_code=409,
            detail="Teaching event source family is immutable",
            error_code=ErrorCode.CONFLICT.value,
        )
    scheduled_event_sources.validate_scheduled_event_start_time(
        source=source_identity,
        start_time=start_time,
    )
    duration_hours = source_identity.duration_hours
    end_time = _compute_end_time(event_date, start_time, duration_hours)
    result = await db.execute(
        text(
            """
            UPDATE teaching_events
            SET
                teaching_name = :teaching_name,
                event_date = :event_date,
                start_time = :start_time,
                end_time = :end_time,
                duration_hours = :duration_hours,
                session_type_id = :session_type_id,
                teaching_name_id = :teaching_name_id,
                global_session_type_id = :global_session_type_id,
                cme_points_awarded = :cme_points_awarded,
                smc_event_code = :smc_event_code,
                updated_at = now()
            WHERE id = :event_id
              AND posting_code = :posting_code
              AND (created_by_role IN ('secretary', 'programme_pc') OR created_by_role IS NULL)
              AND is_adhoc = false
            RETURNING
                id,
                posting_code,
                created_for_programme_code,
                teaching_name,
                event_date,
                start_time,
                end_time,
                duration_hours,
                session_type_id,
                teaching_name_id,
                global_session_type_id,
                source_programme_code,
                source_reporting_period_id,
                series_id,
                cme_points_awarded,
                smc_event_code,
                is_adhoc,
                created_by_role,
                created_at,
                updated_at
            """
        ),
        {
            "teaching_name": source_identity.teaching_name,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
            "duration_hours": duration_hours,
            "session_type_id": None,
            "teaching_name_id": str(source_identity.teaching_name_id)
            if source_identity.teaching_name_id is not None
            else None,
            "global_session_type_id": str(source_identity.global_session_type_id)
            if source_identity.global_session_type_id is not None
            else None,
            "cme_points_awarded": cme_points_awarded,
            "smc_event_code": smc_event_code,
            "event_id": str(event_id),
            "posting_code": posting_code,
        },
    )
    event = result.mappings().one_or_none()
    if event is None:
        raise ApiError(
            status_code=409,
            detail="Teaching event could not be updated",
            error_code=ErrorCode.CONFLICT.value,
        )
    return _event_row(dict(event))


async def _has_attendance(
    db: AsyncSession,
    *,
    event_ids: list[str],
) -> bool:
    if not event_ids:
        return False
    result = await db.execute(
        text(
            """
            SELECT 1
            WHERE EXISTS (
                SELECT 1
                FROM attendance_records ar
                WHERE ar.teaching_event_id = ANY(:event_ids)
            )
            OR EXISTS (
                SELECT 1
                FROM external_attendance_records ear
                WHERE ear.teaching_event_id = ANY(:event_ids)
            )
            """
        ),
        {"event_ids": event_ids},
    )
    return result.scalar_one_or_none() is not None


async def delete_teaching_event(
    db: AsyncSession,
    *,
    posting_code: str,
    event_id: UUID,
) -> dict[str, int]:
    source = await _get_event_for_posting(
        db,
        event_id=event_id,
        posting_code=posting_code,
        for_update=True,
    )
    if source.get("created_by_role") not in {"secretary", "programme_pc", None} or source.get("is_adhoc"):
        raise ApiError(
            status_code=409,
            detail="Teaching event cannot be deleted because it is not a scheduled teaching event",
            error_code=ErrorCode.CONFLICT.value,
        )
    event_ids = [str(event_id)]
    if await _has_attendance(db, event_ids=event_ids):
        raise ApiError(
            status_code=409,
            detail="Teaching event cannot be deleted because attendance exists",
            error_code=ErrorCode.CONFLICT.value,
        )

    await db.execute(
        text(
            """
            DELETE FROM teaching_events
            WHERE id = ANY(:event_ids)
              AND posting_code = :posting_code
            """
        ),
        {"event_ids": event_ids, "posting_code": posting_code},
    )
    return {"deleted_count": 1}


async def teaching_name_options(
    db: AsyncSession,
    *,
    posting_code: str,
    reporting_period_id: UUID | str | None = None,
    relevant_date: date | None = None,
    programme_code: str | None = None,
) -> list[dict[str, Any]]:
    period = (
        await resolve_explicit_reporting_period(
            db,
            reporting_period_id=reporting_period_id,
            require_effectively_active=True,
            relevant_date=relevant_date,
        )
        if reporting_period_id is not None
        else await resolve_active_reporting_period_for_date(
            db,
            relevant_date=relevant_date or date.today(),
        )
    )
    if period is None:
        return []
    pool_params: dict[str, Any] = {
        "posting_code": posting_code,
        "reporting_period_id": str(period["id"]),
        "programme_code": programme_code,
    }

    pool_result = await db.execute(
        text(
            """
            /* secretary_events:options_teaching_names */
            SELECT
                tn.id AS teaching_name_id,
                CAST(NULL AS uuid) AS global_session_type_id,
                tn.display_name AS keyword,
                tn.display_name AS teaching_name,
                tn.programme_code,
                CAST(NULL AS numeric) AS duration_hours,
                false AS is_global
            FROM teaching_names tn
            WHERE tn.reporting_period_id = :reporting_period_id
              AND tn.is_active = true
              AND (
                  CAST(:programme_code AS text) IS NULL
                  OR tn.programme_code = CAST(:programme_code AS text)
              )
              AND EXISTS (
                  SELECT 1
                  FROM secretary_programme_pools spp
                  WHERE spp.posting_code = :posting_code
                    AND spp.programme_code = tn.programme_code
                    AND spp.is_active = true
                    AND spp.can_manage_teaching_names = true
              )
            ORDER BY tn.display_name ASC, tn.programme_code ASC, tn.id ASC
            """
        ),
        pool_params,
    )
    global_result = await db.execute(
        text(
            """
            /* secretary_events:options_global */
            SELECT
                CAST(NULL AS uuid) AS teaching_name_id,
                id AS global_session_type_id,
                name AS keyword,
                name AS teaching_name,
                NULL AS programme_code,
                duration_hours,
                true AS is_global
            FROM global_session_types
            WHERE is_active = true
            ORDER BY name ASC, id ASC
            """
        )
    )
    options = [dict(row) for row in pool_result.mappings().all()]
    for option_programme_code in sorted(
        {str(row["programme_code"]) for row in options}
    ):
        programme_options = [
            row for row in options
            if str(row["programme_code"]) == option_programme_code
        ]
        timings = await list_pool_event_timings(
            db,
            teaching_name_ids=[row["teaching_name_id"] for row in programme_options],
            reporting_period_id=period["id"],
            programme_code=option_programme_code,
            posting_code=posting_code,
        )
        for row in programme_options:
            timing = timings.get((str(row["teaching_name_id"]), posting_code))
            row["duration_hours"] = (
                timing.duration_hours
                if timing is not None
                else DEFAULT_POOL_EVENT_DURATION_HOURS
            )
            row["duration_is_mapped"] = bool(timing and timing.is_mapped)
    for row in global_result.mappings().all():
        option = dict(row)
        option["duration_is_mapped"] = True
        options.append(option)
    return sorted(
        options,
        key=lambda row: (
            _natural_sort_key(str(row["keyword"])),
            bool(row["is_global"]),
            str(row.get("programme_code") or ""),
        ),
    )


async def list_reporting_periods(db: AsyncSession) -> list[dict[str, Any]]:
    """Return reporting-period choices for the authenticated secretary workflow."""
    result = await db.execute(
        text(
            """
            /* secretary_events:list_reporting_periods */
            SELECT
                id,
                label,
                start_date,
                end_date,
                status,
                activate_on,
                deactivate_on,
                created_at,
                updated_at
            FROM reporting_periods
            ORDER BY start_date DESC, label ASC
            """
        )
    )
    return [dict(row) for row in result.mappings().all()]


async def current_residents(
    db: AsyncSession,
    *,
    posting_code: str,
    today: date | None = None,
) -> list[dict[str, Any]]:
    today = today or date.today()
    period = await resolve_active_reporting_period_for_date(
        db,
        relevant_date=today,
        status_as_of_date=today,
    )
    if period is None:
        return []
    result = await db.execute(
        text(
            """
            SELECT
                r.id,
                r.name,
                r.mcr,
                r.programme_code,
                rp.r_year,
                rp.posting_code,
                rp.start_date,
                rp.end_date,
                rp.status
            FROM resident_postings rp
            JOIN residents r ON r.id = rp.resident_id
            WHERE rp.posting_code = :posting_code
              AND rp.reporting_period_id = :reporting_period_id
              AND rp.start_date <= :today
              AND rp.end_date >= :today
              AND rp.status IN ('active', 'loa_working')
              AND r.status != 'inactive'
            ORDER BY r.name ASC, r.mcr ASC
            """
        ),
        {
            "posting_code": posting_code,
            "reporting_period_id": str(period["id"]),
            "today": today,
        },
    )
    return [dict(row) for row in result.mappings().all()]


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def _series_occurrences(
    *,
    start_date: date,
    recurrence_pattern: str,
    recurrence_interval: int,
    days_of_week: list[str] | None,
    end_type: str,
    end_date: date | None,
    end_after_count: int | None,
) -> list[date]:
    occurrences: list[date] = []
    if end_type == "by_count":
        target_count = end_after_count or 0
    else:
        target_count = 1000

    candidate = start_date
    monthly_step = 0
    while len(occurrences) < target_count:
        if end_type == "by_date" and end_date is not None and candidate > end_date:
            break

        include = False
        if recurrence_pattern == "daily":
            include = (candidate - start_date).days % recurrence_interval == 0
            candidate += timedelta(days=1)
        elif recurrence_pattern == "weekly":
            wanted_days = {DAY_INDEX[day] for day in (days_of_week or [])}
            delta_days = (candidate - start_date).days
            include = (
                candidate.weekday() in wanted_days
                and (delta_days // 7) % recurrence_interval == 0
            )
            candidate += timedelta(days=1)
        else:
            candidate = _add_months(start_date, monthly_step * recurrence_interval)
            monthly_step += 1
            include = True

        if include:
            occurrences.append(candidate - timedelta(days=1) if recurrence_pattern != "monthly" else candidate)

        if len(occurrences) >= 1000:
            break
    return occurrences


async def create_event_series(
    db: AsyncSession,
    *,
    source_actor: TeachingNamePoolActor,
    posting_code: str,
    teaching_name_id: UUID | None,
    global_session_type_id: UUID | None,
    start_date: date,
    start_time: time,
    cme_points_awarded: bool,
    smc_event_code: str | None,
    recurrence_pattern: str,
    recurrence_interval: int,
    days_of_week: list[str] | None,
    end_type: str,
    end_date: date | None,
    end_after_count: int | None,
) -> dict[str, Any]:
    series_result = await db.execute(
        text(
            """
            INSERT INTO event_series (
                posting_code,
                recurrence_pattern,
                recurrence_interval,
                days_of_week,
                end_type,
                end_date,
                end_after_count
            )
            VALUES (
                :posting_code,
                :recurrence_pattern,
                :recurrence_interval,
                :days_of_week,
                :end_type,
                :end_date,
                :end_after_count
            )
            RETURNING
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
            """
        ),
        {
            "posting_code": posting_code,
            "recurrence_pattern": recurrence_pattern,
            "recurrence_interval": recurrence_interval,
            "days_of_week": days_of_week,
            "end_type": end_type,
            "end_date": end_date,
            "end_after_count": end_after_count,
        },
    )
    series = dict(series_result.mappings().one())
    created_events: list[dict[str, Any]] = []
    warnings: list[str] = []

    for occurrence_date in _series_occurrences(
        start_date=start_date,
        recurrence_pattern=recurrence_pattern,
        recurrence_interval=recurrence_interval,
        days_of_week=days_of_week,
        end_type=end_type,
        end_date=end_date,
        end_after_count=end_after_count,
    ):
        holiday_name = await _public_holiday_name(db, occurrence_date)
        if holiday_name is not None:
            warnings.append(
                f"Skipped public holiday occurrence on {occurrence_date.isoformat()} ({holiday_name})"
            )
            continue
        created_events.append(
            await _insert_event(
                db,
                source_actor=source_actor,
                posting_code=posting_code,
                teaching_name_id=teaching_name_id,
                global_session_type_id=global_session_type_id,
                event_date=occurrence_date,
                start_time=start_time,
                cme_points_awarded=cme_points_awarded,
                smc_event_code=smc_event_code,
                series_id=series["id"],
            )
        )

    return {
        "series": series,
        "events": created_events,
        "created_count": len(created_events),
        "warnings": warnings,
    }


async def _series_events_for_scope(
    db: AsyncSession,
    *,
    posting_code: str,
    series_id: UUID,
    scope: str,
    event_id: UUID | None,
) -> list[dict[str, Any]]:
    if scope in {"single", "following"} and event_id is None:
        raise ApiError(
            status_code=422,
            detail="event_id is required for this series deletion scope",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )

    candidate_event_ids = (
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
    await acquire_teaching_event_locks(
        db,
        event_ids=candidate_event_ids,
    )
    result = await db.execute(
        text(
            """
            SELECT
                id,
                posting_code,
                created_for_programme_code,
                teaching_name,
                event_date,
                start_time,
                end_time,
                duration_hours,
                session_type_id,
                teaching_name_id,
                global_session_type_id,
                source_programme_code,
                source_reporting_period_id,
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
        ),
        {
            "series_id": str(series_id),
            "posting_code": posting_code,
            "scope": scope,
            "event_id": str(event_id) if event_id else None,
        },
    )
    rows = [dict(row) for row in result.mappings().all()]
    if scope == "single":
        rows = [row for row in rows if str(row["id"]) == str(event_id)]
    elif scope == "following":
        anchor = next((row for row in rows if str(row["id"]) == str(event_id)), None)
        rows = [] if anchor is None else [
            row for row in rows if row["event_date"] >= anchor["event_date"]
        ]

    if not rows:
        raise ApiError(
            status_code=404,
            detail="Event series occurrences not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    return rows


async def delete_event_series(
    db: AsyncSession,
    *,
    posting_code: str,
    series_id: UUID,
    scope: str,
    event_id: UUID | None,
) -> dict[str, int]:
    if scope not in {"single", "following", "all"}:
        raise ApiError(
            status_code=422,
            detail="scope must be one of: single, following, all",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )

    rows = await _series_events_for_scope(
        db,
        posting_code=posting_code,
        series_id=series_id,
        scope=scope,
        event_id=event_id,
    )
    event_ids = [str(row["id"]) for row in rows]
    if await _has_attendance(db, event_ids=event_ids):
        raise ApiError(
            status_code=409,
            detail="Event series occurrences cannot be deleted because attendance exists",
            error_code=ErrorCode.CONFLICT.value,
        )

    await db.execute(
        text(
            """
            DELETE FROM teaching_events
            WHERE id = ANY(:event_ids)
              AND posting_code = :posting_code
            """
        ),
        {"event_ids": event_ids, "posting_code": posting_code},
    )
    if scope == "all":
        await db.execute(
            text(
                """
                DELETE FROM event_series
                WHERE id = :series_id
                  AND posting_code = :posting_code
                """
            ),
            {"series_id": str(series_id), "posting_code": posting_code},
        )
    return {"deleted_count": len(event_ids)}


async def cme_dashboard(
    db: AsyncSession,
    *,
    posting_code: str,
) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT
                COUNT(*) AS total_events,
                COUNT(*) FILTER (WHERE cme_points_awarded = true) AS cme_events,
                COUNT(*) FILTER (WHERE smc_event_code IS NOT NULL) AS with_smc_code
            FROM teaching_events
            WHERE posting_code = :posting_code
              AND created_by_role = 'secretary'
              AND is_adhoc = false
            GROUP BY posting_code
            """
        ),
        {"posting_code": posting_code},
    )
    row = result.mappings().one_or_none()
    return {
        "posting_code": posting_code,
        "total_events": 0 if row is None else row["total_events"],
        "cme_events": 0 if row is None else row["cme_events"],
        "with_smc_code": 0 if row is None else row["with_smc_code"],
    }
