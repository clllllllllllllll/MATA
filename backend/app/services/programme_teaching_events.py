from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.security import log_safe_exception
from app.services.reporting_period_status import (
    resolve_active_reporting_period_for_date,
    resolve_explicit_reporting_period,
)
from app.services import cache_invalidation
from app.services.teaching_event_locks import acquire_teaching_event_locks


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
        "session_type_id": row.get("session_type_id"),
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


def _normalise_option_row(row: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    keyword = str(row.get("keyword") or "").strip()
    if not keyword:
        return None
    posting_codes = row.get("posting_codes")
    if isinstance(posting_codes, list):
        codes = [str(code) for code in posting_codes if str(code).strip()]
    else:
        posting_code = row.get("posting_code")
        codes = [str(posting_code)] if posting_code else []
    return keyword, {
        "keyword": keyword,
        "session_type_id": row.get("session_type_id"),
        "session_type": row.get("session_type"),
        "duration_hours": row.get("duration_hours"),
        "is_tracked": row.get("is_tracked"),
        "is_global": bool(row.get("is_global")),
        "posting_codes": codes,
    }


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
    catalogue_result = await db.execute(
        text(
            """
            /* programme_teaching_events:options_catalogue */
            SELECT
                tnc.keyword,
                tnc.session_type_id,
                st.name AS session_type,
                tnc.duration_hours,
                tnc.is_tracked,
                false AS is_global,
                tnc.posting_code
            FROM teaching_name_catalogue tnc
            JOIN session_types st ON st.id = tnc.session_type_id
            WHERE tnc.programme_code = :programme_code
              AND tnc.reporting_period_id = :reporting_period_id
            ORDER BY tnc.keyword ASC, tnc.posting_code ASC, tnc.duration_hours DESC
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
                name AS keyword,
                NULL AS session_type_id,
                name AS session_type,
                duration_hours,
                false AS is_tracked,
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
            FROM (
                SELECT spp.posting_code
                FROM secretary_programme_pools spp
                WHERE spp.programme_code = :programme_code
                  AND spp.is_active = true
                UNION
                SELECT tnc.posting_code
                FROM teaching_name_catalogue tnc
                WHERE tnc.programme_code = :programme_code
                  AND tnc.reporting_period_id = :reporting_period_id
            ) safe_postings
            WHERE posting_code IS NOT NULL
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

    options_by_keyword: dict[str, dict[str, Any]] = {}
    for raw_row in catalogue_result.mappings().all():
        parsed = _normalise_option_row(dict(raw_row))
        if parsed is None:
            continue
        keyword, row = parsed
        aggregate = options_by_keyword.setdefault(
            keyword,
            {
                "keyword": keyword,
                "session_type_id": row.get("session_type_id"),
                "session_type": row.get("session_type"),
                "duration_hours": row.get("duration_hours"),
                "is_tracked": row.get("is_tracked"),
                "is_global": False,
                "posting_codes": [],
                "_session_type_ids": set(),
                "_session_types": set(),
                "_durations": set(),
                "_tracked_values": set(),
            },
        )
        for posting_code in row["posting_codes"]:
            if posting_code not in aggregate["posting_codes"]:
                aggregate["posting_codes"].append(posting_code)
        aggregate["_session_type_ids"].add(str(row.get("session_type_id")))
        if row.get("session_type") is not None:
            aggregate["_session_types"].add(str(row.get("session_type")))
        if row.get("duration_hours") is not None:
            aggregate["_durations"].add(str(row.get("duration_hours")))
        aggregate["_tracked_values"].add(bool(row.get("is_tracked")))

    options: list[dict[str, Any]] = []
    for keyword in sorted(options_by_keyword):
        aggregate = options_by_keyword[keyword]
        session_type_ids = {
            value for value in aggregate.pop("_session_type_ids") if value and value != "None"
        }
        session_types = aggregate.pop("_session_types")
        durations = aggregate.pop("_durations")
        tracked_values = aggregate.pop("_tracked_values")
        if len(session_type_ids) != 1 or len(session_types) != 1:
            aggregate["session_type_id"] = None
            aggregate["session_type"] = None
        if len(durations) != 1:
            aggregate["duration_hours"] = None
        if len(tracked_values) != 1:
            aggregate["is_tracked"] = None
        aggregate["posting_codes"] = sorted(aggregate["posting_codes"])
        options.append(aggregate)

    for raw_row in global_result.mappings().all():
        parsed = _normalise_option_row(dict(raw_row))
        if parsed is None:
            continue
        keyword, row = parsed
        if keyword in options_by_keyword:
            continue
        row["posting_codes"] = global_posting_codes
        options.append(row)

    return sorted(options, key=lambda row: (_natural_sort_key(row["keyword"]), row["is_global"]))


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
            SELECT
                (
                    EXISTS (
                        SELECT 1
                        FROM secretary_programme_pools spp
                        WHERE spp.posting_code = :posting_code
                          AND spp.programme_code = :programme_code
                          AND spp.is_active = true
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM teaching_name_catalogue tnc
                        WHERE tnc.posting_code = :posting_code
                          AND tnc.programme_code = :programme_code
                          AND tnc.reporting_period_id = :reporting_period_id
                    )
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


async def resolve_teaching_name(
    db: AsyncSession,
    *,
    programme_code: str,
    posting_code: str,
    teaching_name: str,
    reporting_period_id: UUID | str,
) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            /* programme_teaching_events:resolve_name */
            SELECT *
            FROM (
                SELECT
                    name AS keyword,
                    NULL AS session_type_id,
                    name AS session_type,
                    duration_hours,
                    false AS is_tracked,
                    true AS is_global,
                    0 AS source_priority
                FROM global_session_types
                WHERE is_active = true
                  AND name = :teaching_name
                UNION ALL
                SELECT
                    tnc.keyword,
                    tnc.session_type_id,
                    st.name AS session_type,
                    tnc.duration_hours,
                    tnc.is_tracked,
                    false AS is_global,
                    1 AS source_priority
                FROM teaching_name_catalogue tnc
                JOIN session_types st ON st.id = tnc.session_type_id
                WHERE tnc.programme_code = :programme_code
                  AND tnc.posting_code = :posting_code
                  AND tnc.keyword = :teaching_name
                  AND tnc.reporting_period_id = :reporting_period_id
            ) resolved
            ORDER BY source_priority ASC, duration_hours DESC, session_type ASC
            LIMIT 1
            """
        ),
        {
            "programme_code": programme_code,
            "posting_code": posting_code,
            "teaching_name": teaching_name,
            "reporting_period_id": str(reporting_period_id),
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise ApiError(
            status_code=422,
            detail="teaching_name is not available for this programme and posting",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    resolved = dict(row)
    if resolved.get("is_global") and not await _posting_available_for_programme(
        db,
        programme_code=programme_code,
        posting_code=posting_code,
        reporting_period_id=reporting_period_id,
    ):
        raise ApiError(
            status_code=422,
            detail=(
                "No posting is configured for this global teaching name and programme. "
                "Contact an administrator."
            ),
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    return resolved


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
            te.created_for_programme_code = ANY(:programme_scope)
            OR (
                te.created_for_programme_code IS NULL
                AND (
                    EXISTS (
                        SELECT 1
                        FROM secretary_programme_pools spp
                        WHERE spp.posting_code = te.posting_code
                          AND spp.programme_code = ANY(:programme_scope)
                          AND spp.is_active = true
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM teaching_name_catalogue tnc
                        WHERE tnc.posting_code = te.posting_code
                          AND tnc.programme_code = ANY(:programme_scope)
                          AND tnc.keyword = te.teaching_name
                          AND tnc.reporting_period_id = :reporting_period_id
                    )
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
                te.created_for_programme_code = :programme_code
                OR (
                    te.created_for_programme_code IS NULL
                    AND (
                        EXISTS (
                            SELECT 1
                            FROM secretary_programme_pools spp
                            WHERE spp.posting_code = te.posting_code
                              AND spp.programme_code = :programme_code
                              AND spp.is_active = true
                        )
                        OR EXISTS (
                            SELECT 1
                            FROM teaching_name_catalogue tnc
                        WHERE tnc.posting_code = te.posting_code
                          AND tnc.programme_code = :programme_code
                          AND tnc.keyword = te.teaching_name
                          AND tnc.reporting_period_id = :reporting_period_id
                        )
                    )
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
    return [_event_row(dict(row)) for row in result.mappings().all()]


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
    if event.get("created_for_programme_code") is not None:
        return event.get("created_for_programme_code") == programme_code

    result = await db.execute(
        text(
            """
            /* programme_teaching_events:event_programme_match */
            SELECT
                (
                    EXISTS (
                        SELECT 1
                        FROM secretary_programme_pools spp
                        WHERE spp.posting_code = :posting_code
                          AND spp.programme_code = :programme_code
                          AND spp.is_active = true
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM teaching_name_catalogue tnc
                        WHERE tnc.posting_code = :posting_code
                          AND tnc.programme_code = :programme_code
                          AND tnc.keyword = :teaching_name
                          AND tnc.reporting_period_id = :reporting_period_id
                    )
                ) AS is_match
            """
        ),
        {
            "posting_code": event["posting_code"],
            "programme_code": programme_code,
            "teaching_name": event["teaching_name"],
            "reporting_period_id": str(reporting_period_id),
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
    programme_code: str,
    posting_code: str,
    teaching_name: str,
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
    resolved = await resolve_teaching_name(
        db,
        programme_code=programme_code,
        posting_code=posting_code,
        teaching_name=teaching_name,
        reporting_period_id=period["id"],
    )
    duration_hours = resolved["duration_hours"]
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
            "teaching_name": teaching_name,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
            "duration_hours": duration_hours,
            "session_type_id": resolved.get("session_type_id"),
            "cme_points_awarded": cme_points_awarded,
            "smc_event_code": smc_event_code,
            "created_by_role": created_by_role,
        },
    )
    return _event_row(dict(result.mappings().one()))


async def create_teaching_event(
    db: AsyncSession,
    *,
    programme_code: str,
    posting_code: str,
    teaching_name: str,
    event_date: date,
    start_time: time,
    cme_points_awarded: bool,
    smc_event_code: str | None,
) -> dict[str, Any]:
    await _ensure_not_public_holiday(db, event_date)
    event = await _insert_event(
        db,
        programme_code=programme_code,
        posting_code=posting_code,
        teaching_name=teaching_name,
        event_date=event_date,
        start_time=start_time,
        cme_points_awarded=cme_points_awarded,
        smc_event_code=smc_event_code,
    )
    await db.commit()
    _invalidate_event_caches(posting_code)
    return event


async def update_teaching_event(
    db: AsyncSession,
    *,
    event_id: UUID,
    programme_code: str,
    posting_code: str,
    teaching_name: str,
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
    resolved = await resolve_teaching_name(
        db,
        programme_code=programme_code,
        posting_code=posting_code,
        teaching_name=teaching_name,
        reporting_period_id=period["id"],
    )
    duration_hours = resolved["duration_hours"]
    end_time = _compute_end_time(event_date, start_time, duration_hours)
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
            "teaching_name": teaching_name,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
            "duration_hours": duration_hours,
            "session_type_id": resolved.get("session_type_id"),
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
    await db.commit()
    _invalidate_event_caches(source["posting_code"])
    if posting_code != source["posting_code"]:
        _invalidate_event_caches(posting_code)
    return _event_row(dict(event))


async def duplicate_teaching_event(
    db: AsyncSession,
    *,
    event_id: UUID,
    programme_code: str,
    event_date: date,
    start_time: time | None,
    posting_code: str | None,
    teaching_name: str | None,
    cme_points_awarded: bool | None,
    smc_event_code: str | None,
) -> dict[str, Any]:
    source = await _get_event(db, event_id, for_update=True)
    await _ensure_event_manageable_for_programme(
        db,
        event=source,
        programme_code=programme_code,
    )
    await _ensure_not_public_holiday(db, event_date)
    new_posting_code = posting_code or source["posting_code"]
    new_teaching_name = teaching_name or source["teaching_name"]
    event = await _insert_event(
        db,
        programme_code=programme_code,
        posting_code=new_posting_code,
        teaching_name=new_teaching_name,
        event_date=event_date,
        start_time=start_time or source["start_time"],
        cme_points_awarded=(
            cme_points_awarded
            if cme_points_awarded is not None
            else bool(source.get("cme_points_awarded", False))
        ),
        smc_event_code=smc_event_code if smc_event_code is not None else source.get("smc_event_code"),
        created_by_role="programme_pc",
    )
    await db.commit()
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
