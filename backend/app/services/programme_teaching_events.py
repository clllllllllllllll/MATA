from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.staff_actor import StaffActorContext
from app.errors import ApiError, ErrorCode
from app.security import log_safe_exception
from app.services.reporting_period_status import (
    resolve_active_reporting_period_for_date,
    resolve_explicit_reporting_period,
)
from app.services import cache_invalidation
from app.services import scheduled_event_sources
from app.services.audit import write_audit_log
from app.services.pool_event_timing import (
    PoolEventTiming,
    list_pool_event_timings,
    pool_event_timing_payload,
    staff_pool_event_session_type_label,
    with_staff_pool_event_timings,
)
from app.services.teaching_event_locks import acquire_teaching_event_locks
from app.services.teaching_name_pool import TeachingNamePoolActor


logger = logging.getLogger(__name__)

MANAGEABLE_CREATED_BY_ROLES = {"secretary", "programme_pc", None}


def _invalidate_event_caches(posting_code: str) -> None:
    try:
        cache_invalidation.invalidate_after_secretary_event_mutation(
            posting_code=posting_code,
        )
    except Exception as exc:
        log_safe_exception(
            logger,
            "programme_teaching_event_cache_invalidation_failed",
            exc,
            category="cache_invalidation",
        )


def _event_row(row: dict[str, Any]) -> dict[str, Any]:
    attendance_count = int(row.get("attendance_count") or 0)
    external_attendance_count = int(row.get("external_attendance_count") or 0)
    return {
        "id": row["id"],
        "posting_code": row["posting_code"],
        "created_for_programme_code": row.get("created_for_programme_code"),
        "teaching_name": row["teaching_name"],
        "event_date": row["event_date"],
        "start_time": row["start_time"],
        "end_time": row.get("end_time"),
        "duration_hours": row.get("duration_hours"),
        "duration_varies": bool(row.get("duration_varies", False)),
        "has_pending_mappings": bool(row.get("has_pending_mappings", False)),
        "r_year_durations": row.get("r_year_durations", []),
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
        "attendance_count": attendance_count,
        "external_attendance_count": external_attendance_count,
        "has_attendance": bool(
            row.get("has_attendance", attendance_count + external_attendance_count > 0)
        ),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _with_resolved_source_timing(
    event: dict[str, Any],
    source: scheduled_event_sources.ScheduledEventSource,
) -> dict[str, Any]:
    if source.is_pool_backed:
        timing = PoolEventTiming(
            duration_hours=source.duration_hours,
            is_mapped=source.duration_is_mapped,
            duration_varies=source.duration_varies,
            r_year_timings=source.r_year_timings,
        )
        event.update(pool_event_timing_payload(timing))
        event["session_type"] = staff_pool_event_session_type_label(timing)
    else:
        event["session_type"] = source.teaching_name
    return event


def _compute_end_time(event_date: date, start_time: time, duration_hours: Decimal) -> time:
    minutes = int(duration_hours * Decimal("60"))
    starts_at = datetime.combine(event_date, start_time)
    return (starts_at + timedelta(minutes=minutes)).time()


def _scope_values(programme_scope: set[str] | list[str] | tuple[str, ...]) -> list[str]:
    return sorted({str(value).strip() for value in programme_scope if str(value).strip()})


def _natural_sort_key(value: str) -> tuple[str | int, ...]:
    import re

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


async def _public_holiday_name(db: AsyncSession, event_date: date) -> str | None:
    result = await db.execute(
        text(
            """
            /* programme_teaching_events:public_holiday */
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


async def teaching_name_options(
    db: AsyncSession,
    *,
    programme_code: str,
    reporting_period_id: UUID | str | None = None,
    relevant_date: date | None = None,
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
    pool_result = await db.execute(
        text(
            """
            /* programme_teaching_events:options_teaching_names */
            SELECT
                tn.id AS teaching_name_id,
                CAST(NULL AS uuid) AS global_session_type_id,
                tn.display_name AS keyword,
                tn.display_name AS teaching_name,
                tn.programme_code,
                CAST(NULL AS numeric) AS duration_hours,
                false AS is_global,
                ARRAY(
                    SELECT DISTINCT mapping.posting_code
                    FROM teaching_name_mappings AS mapping
                    JOIN secretary_programme_pools AS spp
                      ON spp.posting_code = mapping.posting_code
                     AND spp.programme_code = mapping.programme_code
                     AND spp.is_active = true
                    WHERE mapping.teaching_name_id = tn.id
                      AND mapping.reporting_period_id = tn.reporting_period_id
                      AND mapping.programme_code = :programme_code
                    ORDER BY mapping.posting_code
                ) AS posting_codes
            FROM teaching_names tn
            JOIN teaching_name_programme_scopes AS scope
              ON scope.teaching_name_id = tn.id
             AND scope.reporting_period_id = tn.reporting_period_id
             AND scope.programme_code = :programme_code
            WHERE tn.reporting_period_id = :reporting_period_id
              AND tn.is_active = true
            ORDER BY tn.display_name ASC, tn.id ASC
            """
        ),
        {
            "programme_code": programme_code,
            "reporting_period_id": str(period["id"]),
        },
    )
    global_result = await db.execute(
        text(
            """
            /* programme_teaching_events:options_global */
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
            ORDER BY name ASC
            """
        )
    )
    global_posting_result = await db.execute(
        text(
            """
            /* programme_teaching_events:global_posting_options */
            SELECT DISTINCT posting_code
            FROM secretary_programme_pools
            WHERE programme_code = :programme_code
              AND is_active = true
              AND posting_code IS NOT NULL
            ORDER BY posting_code ASC
            """
        ),
        {
            "programme_code": programme_code,
            "reporting_period_id": str(period["id"]),
        },
    )
    global_posting_codes = [
        str(row["posting_code"])
        for row in global_posting_result.mappings().all()
        if row.get("posting_code")
    ]

    options = [dict(row) for row in pool_result.mappings().all()]
    timings = await list_pool_event_timings(
        db,
        teaching_name_ids=[row["teaching_name_id"] for row in options],
        reporting_period_id=period["id"],
        programme_code=programme_code,
    )
    for option in options:
        posting_durations = []
        for posting_code in option["posting_codes"]:
            timing = timings[(str(option["teaching_name_id"]), posting_code)]
            posting_durations.append(
                {
                    "posting_code": posting_code,
                    "duration_hours": timing.duration_hours,
                    "is_mapped": timing.is_mapped,
                    "duration_varies": timing.duration_varies,
                    "has_pending_mappings": timing.has_pending_mappings,
                    "r_year_durations": [
                        {
                            "r_year": r_year_timing.r_year,
                            "programme_code": r_year_timing.programme_code,
                            "duration_hours": r_year_timing.duration_hours,
                            "is_mapped": r_year_timing.is_mapped,
                            "session_type_id": r_year_timing.session_type_id,
                            "session_type_name": r_year_timing.session_type_name,
                        }
                        for r_year_timing in timing.r_year_timings
                    ],
                }
            )
        option["posting_durations"] = posting_durations
    for row in global_result.mappings().all():
        option = dict(row)
        option["posting_codes"] = global_posting_codes
        option["posting_durations"] = []
        options.append(option)
    return sorted(
        options,
        key=lambda row: (
            _natural_sort_key(str(row["keyword"])),
            bool(row["is_global"]),
            str(row.get("programme_code") or ""),
        ),
    )


async def _posting_available_for_programme(
    db: AsyncSession,
    *,
    programme_code: str,
    posting_code: str,
    reporting_period_id: UUID | str,
) -> bool:
    result = await db.execute(
        text(
            """
            /* programme_teaching_events:posting_available */
            SELECT EXISTS (
                SELECT 1
                FROM secretary_programme_pools spp
                WHERE spp.posting_code = :posting_code
                  AND spp.programme_code = :programme_code
                  AND spp.is_active = true
            ) AS is_available
            """
        ),
        {
            "programme_code": programme_code,
            "posting_code": posting_code,
            "reporting_period_id": str(reporting_period_id),
        },
    )
    return bool(result.scalar_one_or_none())


async def _ensure_pool_source_mapping_scope(
    db: AsyncSession,
    *,
    source: scheduled_event_sources.ScheduledEventSource,
    posting_code: str,
) -> None:
    """Require the PC's pool event posting to be an existing mapping scope."""

    if not source.is_pool_backed:
        return
    if (
        source.teaching_name_id is None
        or source.reporting_period_id is None
        or source.mapping_programme_code is None
    ):
        raise RuntimeError("Pool-backed scheduled event source is missing its scope")

    result = await db.execute(
        text(
            """
            /* programme_teaching_events:pool_mapping_scope */
            SELECT EXISTS (
                SELECT 1
                FROM teaching_name_mappings AS mapping
                WHERE mapping.teaching_name_id = :teaching_name_id
                  AND mapping.reporting_period_id = :reporting_period_id
                  AND mapping.programme_code = :programme_code
                  AND mapping.posting_code = :posting_code
            ) AS has_mapping_scope
            """
        ),
        {
            "teaching_name_id": str(source.teaching_name_id),
            "reporting_period_id": str(source.reporting_period_id),
            "programme_code": source.mapping_programme_code,
            "posting_code": posting_code,
        },
    )
    if bool(result.scalar_one_or_none()):
        return
    raise ApiError(
        status_code=422,
        detail="Selected Teaching Name has no configured mapping scope for this posting",
        error_code=ErrorCode.VALIDATION_FAILED.value,
    )


async def list_teaching_events(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    programme_code: str | None = None,
    reporting_period_id: UUID | str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    posting_code: str | None = None,
) -> list[dict[str, Any]]:
    if reporting_period_id is not None:
        period = await resolve_explicit_reporting_period(
            db,
            reporting_period_id=reporting_period_id,
            require_effectively_active=True,
            relevant_date=date_from or date_to,
        )
        if period is not None and date_from is not None and not (
            period["start_date"] <= date_from <= period["end_date"]
        ):
            raise ApiError(
                status_code=422,
                detail="The selected reporting period does not contain the relevant date",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        if period is not None and date_to is not None and not (
            period["start_date"] <= date_to <= period["end_date"]
        ):
            raise ApiError(
                status_code=422,
                detail="The selected reporting period does not contain the relevant date",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
    else:
        period = await resolve_active_reporting_period_for_date(
            db,
            relevant_date=date.today(),
        )
    if period is None:
        return []

    scope = _scope_values(programme_scope)
    params: dict[str, Any] = {
        "programme_scope": scope,
        "reporting_period_id": str(period["id"]),
        "reporting_period_start": period["start_date"],
        "reporting_period_end": period["end_date"],
    }
    where = [
        "te.is_adhoc = false",
        "(te.created_by_role IN ('secretary', 'programme_pc') OR te.created_by_role IS NULL)",
        "te.event_date BETWEEN :reporting_period_start AND :reporting_period_end",
        """
        (
            (
                te.source_programme_code IS NOT NULL
                AND te.source_reporting_period_id = :reporting_period_id
                AND te.global_session_type_id IS NULL
                AND (
                    te.created_for_programme_code = ANY(:programme_scope)
                    OR (
                        te.created_for_programme_code IS NULL
                        AND EXISTS (
                            SELECT 1
                            FROM teaching_name_programme_scopes AS scope
                            WHERE scope.teaching_name_id = te.teaching_name_id
                              AND scope.reporting_period_id = te.source_reporting_period_id
                              AND scope.programme_code = ANY(:programme_scope)
                        )
                    )
                )
            )
            OR (
                te.global_session_type_id IS NOT NULL
                AND te.teaching_name_id IS NULL
                AND te.source_programme_code IS NULL
                AND te.source_reporting_period_id IS NULL
                AND (
                    (
                        te.created_for_programme_code IS NOT NULL
                        AND te.created_for_programme_code = ANY(:programme_scope)
                    )
                    OR (
                        te.created_for_programme_code IS NULL
                        AND EXISTS (
                            SELECT 1
                            FROM secretary_programme_pools spp
                            WHERE spp.posting_code = te.posting_code
                              AND spp.programme_code = ANY(:programme_scope)
                              AND spp.is_active = true
                        )
                    )
                )
            )
            OR (
                te.teaching_name_id IS NULL
                AND te.global_session_type_id IS NULL
                AND te.source_programme_code IS NULL
                AND te.source_reporting_period_id IS NULL
                AND te.created_for_programme_code IS NOT NULL
                AND te.created_for_programme_code = ANY(:programme_scope)
            )
            OR (
                te.teaching_name_id IS NULL
                AND te.global_session_type_id IS NULL
                AND te.source_programme_code IS NULL
                AND te.source_reporting_period_id IS NULL
                AND te.created_for_programme_code IS NULL
                AND EXISTS (
                    SELECT 1
                    FROM secretary_programme_pools spp
                    WHERE spp.posting_code = te.posting_code
                      AND spp.programme_code = ANY(:programme_scope)
                      AND spp.is_active = true
                )
            )
        )
        """,
    ]
    if programme_code is not None:
        params["programme_code"] = programme_code
        where.append(
            """
            (
                te.source_programme_code IS NOT NULL
                AND te.source_reporting_period_id = :reporting_period_id
                AND te.global_session_type_id IS NULL
                AND (
                    te.created_for_programme_code = :programme_code
                    OR (
                        te.created_for_programme_code IS NULL
                        AND EXISTS (
                            SELECT 1
                            FROM teaching_name_programme_scopes AS scope
                            WHERE scope.teaching_name_id = te.teaching_name_id
                              AND scope.reporting_period_id = te.source_reporting_period_id
                              AND scope.programme_code = :programme_code
                        )
                    )
                )
            )
            OR (
                te.global_session_type_id IS NOT NULL
                AND te.teaching_name_id IS NULL
                AND te.source_programme_code IS NULL
                AND te.source_reporting_period_id IS NULL
                AND (
                    te.created_for_programme_code = :programme_code
                    OR (
                        te.created_for_programme_code IS NULL
                        AND EXISTS (
                            SELECT 1
                            FROM secretary_programme_pools spp
                            WHERE spp.posting_code = te.posting_code
                              AND spp.programme_code = :programme_code
                              AND spp.is_active = true
                        )
                    )
                )
            )
            OR (
                te.teaching_name_id IS NULL
                AND te.global_session_type_id IS NULL
                AND te.source_programme_code IS NULL
                AND te.source_reporting_period_id IS NULL
                AND te.created_for_programme_code = :programme_code
            )
            OR (
                te.teaching_name_id IS NULL
                AND te.global_session_type_id IS NULL
                AND te.source_programme_code IS NULL
                AND te.source_reporting_period_id IS NULL
                AND te.created_for_programme_code IS NULL
                AND EXISTS (
                    SELECT 1
                    FROM secretary_programme_pools spp
                    WHERE spp.posting_code = te.posting_code
                      AND spp.programme_code = :programme_code
                      AND spp.is_active = true
                )
            )
            """
        )
    if date_from is not None:
        params["date_from"] = date_from
        where.append("te.event_date >= :date_from")
    if date_to is not None:
        params["date_to"] = date_to
        where.append("te.event_date <= :date_to")
    if posting_code is not None:
        params["posting_code"] = posting_code
        where.append("te.posting_code = :posting_code")

    result = await db.execute(
        text(
            f"""
            /* programme_teaching_events:list */
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
                COALESCE(native_attendance.attendance_count, 0) AS attendance_count,
                COALESCE(external_attendance.external_attendance_count, 0) AS external_attendance_count,
                (
                    COALESCE(native_attendance.attendance_count, 0)
                    + COALESCE(external_attendance.external_attendance_count, 0)
                ) > 0 AS has_attendance,
                te.created_at,
                te.updated_at
            FROM teaching_events te
            LEFT JOIN session_types st ON st.id = te.session_type_id
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS attendance_count
                FROM attendance_records ar
                WHERE ar.teaching_event_id = te.id
                  AND ar.status = 'submitted'
            ) native_attendance ON true
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS external_attendance_count
                FROM external_attendance_records ear
                WHERE ear.teaching_event_id = te.id
                  AND ear.status = 'submitted'
            ) external_attendance ON true
            WHERE {' AND '.join(where)}
            ORDER BY te.event_date ASC, te.start_time ASC, te.teaching_name ASC
            """
        ),
        params,
    )
    rows = await with_staff_pool_event_timings(
        db,
        rows=[dict(row) for row in result.mappings().all()],
        programme_code=programme_code,
    )
    return [_event_row(row) for row in rows]


async def _get_event(
    db: AsyncSession,
    event_id: UUID,
    *,
    for_update: bool = False,
) -> dict[str, Any]:
    if for_update:
        await acquire_teaching_event_locks(db, event_ids=[event_id])
    lock_clause = "FOR UPDATE OF te" if for_update else ""
    result = await db.execute(
        text(
            f"""
            /* programme_teaching_events:get_event */
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
                te.created_at,
                te.updated_at
            FROM teaching_events te
            LEFT JOIN session_types st ON st.id = te.session_type_id
            WHERE te.id = :event_id
            {lock_clause}
            """
        ),
        {"event_id": str(event_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise ApiError(
            status_code=404,
            detail="Teaching event not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    return dict(row)


async def _event_matches_programme(
    db: AsyncSession,
    *,
    event: dict[str, Any],
    programme_code: str,
    reporting_period_id: UUID | str,
) -> bool:
    owner = event.get("created_for_programme_code")
    source_programme = event.get("source_programme_code")
    source_period = event.get("source_reporting_period_id")
    if (source_programme is None) != (source_period is None):
        return False
    if source_programme is not None:
        if (
            event.get("global_session_type_id") is not None
            or str(source_period) != str(reporting_period_id)
        ):
            return False
        if owner is not None and owner != programme_code:
            return False
        result = await db.execute(
            text(
                """
                /* programme_teaching_events:event_programme_pool_match */
                SELECT 1
                FROM teaching_name_programme_scopes AS scope
                WHERE scope.teaching_name_id = :teaching_name_id
                  AND scope.reporting_period_id = :reporting_period_id
                  AND scope.programme_code = :programme_code
                LIMIT 1
                """
            ),
            {
                "teaching_name_id": str(event["teaching_name_id"]),
                "reporting_period_id": str(reporting_period_id),
                "programme_code": programme_code,
            },
        )
        return result.scalar_one_or_none() is not None
    if event.get("teaching_name_id") is not None:
        return False
    if event.get("global_session_type_id") is not None:
        if owner is not None:
            return owner == programme_code
        result = await db.execute(
            text(
                """
                /* programme_teaching_events:event_programme_global_match */
                SELECT 1
                FROM secretary_programme_pools
                WHERE posting_code = :posting_code
                  AND programme_code = :programme_code
                  AND is_active = true
                LIMIT 1
                """
            ),
            {
                "posting_code": event["posting_code"],
                "programme_code": programme_code,
            },
        )
        return result.scalar_one_or_none() is not None

    if owner is not None:
        return owner == programme_code
    result = await db.execute(
        text(
            """
            /* programme_teaching_events:event_programme_match */
            SELECT EXISTS (
                SELECT 1
                FROM secretary_programme_pools spp
                WHERE spp.posting_code = :posting_code
                  AND spp.programme_code = :programme_code
                  AND spp.is_active = true
            ) AS is_match
            """
        ),
        {
            "posting_code": event["posting_code"],
            "programme_code": programme_code,
        },
    )
    return bool(result.scalar_one_or_none())


async def _ensure_event_manageable_for_programme(
    db: AsyncSession,
    *,
    event: dict[str, Any],
    programme_code: str,
) -> None:
    if event.get("is_adhoc") or event.get("created_by_role") not in MANAGEABLE_CREATED_BY_ROLES:
        raise ApiError(
            status_code=409,
            detail="Teaching event cannot be managed from the programme PC schedule",
            error_code=ErrorCode.CONFLICT.value,
        )
    period = await resolve_active_reporting_period_for_date(
        db,
        relevant_date=event["event_date"],
    )
    if period is None:
        raise ApiError(
            status_code=422,
            detail="No active reporting period is available for the teaching event date",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    if not await _event_matches_programme(
        db,
        event=event,
        programme_code=programme_code,
        reporting_period_id=period["id"],
    ):
        raise ApiError(
            status_code=403,
            detail="Forbidden - teaching event is outside programme scope",
            error_code=ErrorCode.FORBIDDEN.value,
        )


async def _has_attendance(db: AsyncSession, *, event_id: UUID) -> bool:
    result = await db.execute(
        text(
            """
            /* programme_teaching_events:attendance_guard */
            SELECT 1
            WHERE EXISTS (
                SELECT 1
                FROM attendance_records ar
                WHERE ar.teaching_event_id = :event_id
            )
            OR EXISTS (
                SELECT 1
                FROM external_attendance_records ear
                WHERE ear.teaching_event_id = :event_id
            )
            """
        ),
        {"event_id": str(event_id)},
    )
    return result.scalar_one_or_none() is not None


async def _insert_event(
    db: AsyncSession,
    *,
    source_actor: TeachingNamePoolActor,
    programme_code: str,
    posting_code: str,
    teaching_name_id: UUID | None,
    global_session_type_id: UUID | None,
    event_date: date,
    start_time: time,
    cme_points_awarded: bool,
    smc_event_code: str | None,
    created_by_role: str = "programme_pc",
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
        programme_code=programme_code,
        reporting_period_id=period["id"],
        teaching_name_id=teaching_name_id,
        global_session_type_id=global_session_type_id,
        posting_code=posting_code,
    )
    await _ensure_pool_source_mapping_scope(
        db,
        source=source,
        posting_code=posting_code,
    )
    if source.kind == "global_session_type" and not await _posting_available_for_programme(
        db,
        programme_code=programme_code,
        posting_code=posting_code,
        reporting_period_id=period["id"],
    ):
        raise ApiError(
            status_code=422,
            detail=(
                "No posting is configured for this global teaching name and programme. "
                "Contact an administrator."
            ),
            error_code=ErrorCode.VALIDATION_FAILED.value,
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
            /* programme_teaching_events:insert */
            INSERT INTO teaching_events (
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
                cme_points_awarded,
                smc_event_code,
                is_adhoc,
                created_by_role
            )
            VALUES (
                :posting_code,
                :programme_code,
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
                :cme_points_awarded,
                :smc_event_code,
                false,
                :created_by_role
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
            "programme_code": programme_code,
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
            "cme_points_awarded": cme_points_awarded,
            "smc_event_code": smc_event_code,
            "created_by_role": created_by_role,
        },
    )
    event = _with_resolved_source_timing(dict(result.mappings().one()), source)
    return _event_row(event)


async def _write_programme_event_audit(
    db: AsyncSession,
    *,
    actor: StaffActorContext,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    source_event_id: UUID | None = None,
) -> None:
    event = after or before
    if event is None:
        raise RuntimeError("Programme teaching event audit snapshot is required")
    metadata: dict[str, Any] = {
        "route_context": "programme_teaching_event_crud",
        "posting_code": event["posting_code"],
        "programme_code": event.get("created_for_programme_code"),
        "cache_invalidation_target": (
            f"secretary_events|posting_code={event['posting_code']}"
        ),
    }
    if event.get("teaching_name_id") is not None:
        metadata["teaching_name_id"] = str(event["teaching_name_id"])
    if event.get("global_session_type_id") is not None:
        metadata["global_session_type_id"] = str(event["global_session_type_id"])
    if source_event_id is not None:
        metadata["source_event_id"] = str(source_event_id)
    await write_audit_log(
        db,
        actor=actor,
        action=action,
        entity_type="teaching_event",
        entity_id=event["id"],
        before=before,
        after=after,
        metadata=metadata,
    )


async def create_teaching_event(
    db: AsyncSession,
    *,
    source_actor: TeachingNamePoolActor,
    audit_actor: StaffActorContext,
    programme_code: str,
    posting_code: str,
    teaching_name_id: UUID | None,
    global_session_type_id: UUID | None,
    event_date: date,
    start_time: time,
    cme_points_awarded: bool,
    smc_event_code: str | None,
) -> dict[str, Any]:
    try:
        await _ensure_not_public_holiday(db, event_date)
        event = await _insert_event(
            db,
            source_actor=source_actor,
            programme_code=programme_code,
            posting_code=posting_code,
            teaching_name_id=teaching_name_id,
            global_session_type_id=global_session_type_id,
            event_date=event_date,
            start_time=start_time,
            cme_points_awarded=cme_points_awarded,
            smc_event_code=smc_event_code,
        )
        await _write_programme_event_audit(
            db,
            actor=audit_actor,
            action="programme_pc.teaching_event.create",
            before=None,
            after=event,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    _invalidate_event_caches(posting_code)
    return event


async def update_teaching_event(
    db: AsyncSession,
    *,
    source_actor: TeachingNamePoolActor,
    audit_actor: StaffActorContext,
    event_id: UUID,
    programme_code: str,
    posting_code: str,
    teaching_name_id: UUID | None,
    global_session_type_id: UUID | None,
    event_date: date,
    start_time: time,
    cme_points_awarded: bool,
    smc_event_code: str | None,
) -> dict[str, Any]:
    source = await _get_event(db, event_id, for_update=True)
    await _ensure_event_manageable_for_programme(
        db,
        event=source,
        programme_code=programme_code,
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
    if await _has_attendance(db, event_id=event_id):
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
        programme_code=programme_code,
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
    await _ensure_pool_source_mapping_scope(
        db,
        source=source_identity,
        posting_code=posting_code,
    )
    if source_identity.kind == "global_session_type" and not await _posting_available_for_programme(
        db,
        programme_code=programme_code,
        posting_code=posting_code,
        reporting_period_id=period["id"],
    ):
        raise ApiError(
            status_code=422,
            detail=(
                "No posting is configured for this global teaching name and programme. "
                "Contact an administrator."
            ),
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    scheduled_event_sources.validate_scheduled_event_start_time(
        source=source_identity,
        start_time=start_time,
    )
    duration_hours = source_identity.duration_hours
    end_time = _compute_end_time(event_date, start_time, duration_hours)
    try:
        result = await db.execute(
            text(
                """
            /* programme_teaching_events:update */
            UPDATE teaching_events
            SET
                posting_code = :posting_code,
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
            "event_id": str(event_id),
            "posting_code": posting_code,
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
            },
        )
        event = result.mappings().one_or_none()
        if event is None:
            raise ApiError(
                status_code=409,
                detail="Teaching event could not be updated",
                error_code=ErrorCode.CONFLICT.value,
            )
        event_payload = _event_row(
            _with_resolved_source_timing(dict(event), source_identity)
        )
        await _write_programme_event_audit(
            db,
            actor=audit_actor,
            action="programme_pc.teaching_event.update",
            before=source,
            after=event_payload,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    _invalidate_event_caches(source["posting_code"])
    if posting_code != source["posting_code"]:
        _invalidate_event_caches(posting_code)
    return event_payload


async def duplicate_teaching_event(
    db: AsyncSession,
    *,
    source_actor: TeachingNamePoolActor,
    audit_actor: StaffActorContext,
    event_id: UUID,
    programme_code: str,
    event_date: date,
    start_time: time | None,
    posting_code: str | None,
    teaching_name_id: UUID | None,
    global_session_type_id: UUID | None,
    cme_points_awarded: bool | None,
    smc_event_code: str | None,
) -> dict[str, Any]:
    source = await _get_event(db, event_id, for_update=True)
    await _ensure_event_manageable_for_programme(
        db,
        event=source,
        programme_code=programme_code,
    )
    if (
        source.get("teaching_name_id") is None
        and source.get("global_session_type_id") is None
        and teaching_name_id is None
        and global_session_type_id is None
    ):
        raise ApiError(
            status_code=409,
            detail="Legacy teaching events require an explicit source to be duplicated",
            error_code=ErrorCode.CONFLICT.value,
        )
    await _ensure_not_public_holiday(db, event_date)
    scheduled_event_sources.require_at_most_one_source(
        teaching_name_id=teaching_name_id,
        global_session_type_id=global_session_type_id,
    )
    new_teaching_name_id = teaching_name_id
    new_global_session_type_id = global_session_type_id
    if new_teaching_name_id is None and new_global_session_type_id is None:
        new_teaching_name_id = source.get("teaching_name_id")
        new_global_session_type_id = source.get("global_session_type_id")
    new_posting_code = posting_code or source["posting_code"]
    try:
        event = await _insert_event(
            db,
            source_actor=source_actor,
            programme_code=programme_code,
            posting_code=new_posting_code,
            teaching_name_id=new_teaching_name_id,
            global_session_type_id=new_global_session_type_id,
            event_date=event_date,
            start_time=start_time or source["start_time"],
            cme_points_awarded=(
                cme_points_awarded
                if cme_points_awarded is not None
                else bool(source.get("cme_points_awarded", False))
            ),
            smc_event_code=(
                smc_event_code
                if smc_event_code is not None
                else source.get("smc_event_code")
            ),
            created_by_role="programme_pc",
        )
        await _write_programme_event_audit(
            db,
            actor=audit_actor,
            action="programme_pc.teaching_event.duplicate",
            before=None,
            after=event,
            source_event_id=event_id,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    _invalidate_event_caches(new_posting_code)
    return event


async def delete_teaching_event(
    db: AsyncSession,
    *,
    event_id: UUID,
    programme_code: str,
) -> dict[str, int]:
    source = await _get_event(db, event_id, for_update=True)
    await _ensure_event_manageable_for_programme(
        db,
        event=source,
        programme_code=programme_code,
    )
    if await _has_attendance(db, event_id=event_id):
        raise ApiError(
            status_code=409,
            detail="Teaching event cannot be deleted because attendance exists",
            error_code=ErrorCode.CONFLICT.value,
        )

    await db.execute(
        text(
            """
            /* programme_teaching_events:delete */
            DELETE FROM teaching_events
            WHERE id = :event_id
              AND is_adhoc = false
            """
        ),
        {"event_id": str(event_id)},
    )
    await db.commit()
    _invalidate_event_caches(source["posting_code"])
    return {"deleted_count": 1}
