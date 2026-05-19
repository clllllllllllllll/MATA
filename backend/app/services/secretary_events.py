from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.services.cache import cache


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
    cache.invalidate_prefix(f"secretary_events|posting_code={posting_code}")
    cache.invalidate_prefix(f"resident_events|posting_code={posting_code}")


def _event_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "posting_code": row["posting_code"],
        "teaching_name": row["teaching_name"],
        "event_date": row["event_date"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "duration_hours": row.get("duration_hours"),
        "session_type_id": row.get("session_type_id"),
        "series_id": row.get("series_id"),
        "cme_points_awarded": row.get("cme_points_awarded", False),
        "smc_event_code": row.get("smc_event_code"),
        "is_adhoc": row.get("is_adhoc", False),
        "created_by_role": row.get("created_by_role"),
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


async def resolve_teaching_name(
    db: AsyncSession,
    *,
    posting_code: str,
    teaching_name: str,
) -> dict[str, Any]:
    global_result = await db.execute(
        text(
            """
            SELECT
                name AS keyword,
                NULL AS session_type_id,
                name AS session_type,
                duration_hours,
                false AS is_tracked,
                true AS is_global
            FROM global_session_types
            WHERE is_active = true AND name = :teaching_name
            ORDER BY name ASC
            """
        ),
        {"teaching_name": teaching_name},
    )
    global_row = global_result.mappings().one_or_none()
    if global_row is not None:
        return dict(global_row)

    result = await db.execute(
        text(
            """
            SELECT
                tnc.keyword,
                tnc.session_type_id,
                st.name AS session_type,
                tnc.duration_hours,
                tnc.is_tracked,
                false AS is_global
            FROM teaching_name_catalogue tnc
            JOIN session_types st ON st.id = tnc.session_type_id
            WHERE tnc.posting_code = :posting_code
              AND tnc.keyword = :teaching_name
            ORDER BY tnc.duration_hours DESC, st.name ASC
            """
        ),
        {"posting_code": posting_code, "teaching_name": teaching_name},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise ApiError(
            status_code=422,
            detail="teaching_name is not available for this secretary posting",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    return dict(row)


async def list_teaching_events(
    db: AsyncSession,
    *,
    posting_code: str,
    date_from: date | None,
    date_to: date | None,
    session_type_id: UUID | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"posting_code": posting_code}
    where = ["posting_code = :posting_code"]
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
                id,
                posting_code,
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
            FROM teaching_events
            WHERE {' AND '.join(where)}
            ORDER BY event_date ASC, start_time ASC, teaching_name ASC
            """
        ),
        params,
    )
    return [_event_row(dict(row)) for row in result.mappings().all()]


async def _insert_event(
    db: AsyncSession,
    *,
    posting_code: str,
    teaching_name: str,
    event_date: date,
    start_time: time,
    cme_points_awarded: bool,
    smc_event_code: str | None,
    series_id: UUID | str | None = None,
) -> dict[str, Any]:
    resolved = await resolve_teaching_name(
        db,
        posting_code=posting_code,
        teaching_name=teaching_name,
    )
    duration_hours = resolved["duration_hours"]
    end_time = _compute_end_time(event_date, start_time, duration_hours)
    result = await db.execute(
        text(
            """
            INSERT INTO teaching_events (
                posting_code,
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
                :series_id,
                :cme_points_awarded,
                :smc_event_code,
                false,
                'secretary'
            )
            RETURNING
                id,
                posting_code,
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
            "posting_code": posting_code,
            "teaching_name": teaching_name,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
            "duration_hours": duration_hours,
            "session_type_id": resolved.get("session_type_id"),
            "series_id": series_id,
            "cme_points_awarded": cme_points_awarded,
            "smc_event_code": smc_event_code,
        },
    )
    return _event_row(dict(result.mappings().one()))


async def create_teaching_event(
    db: AsyncSession,
    *,
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
        posting_code=posting_code,
        teaching_name=teaching_name,
        event_date=event_date,
        start_time=start_time,
        cme_points_awarded=cme_points_awarded,
        smc_event_code=smc_event_code,
    )
    await db.commit()
    invalidate_secretary_event_caches(posting_code)
    return event


async def _get_event_for_posting(
    db: AsyncSession,
    *,
    event_id: UUID,
    posting_code: str,
    source: bool = False,
) -> dict[str, Any]:
    id_param = "source_event_id" if source else "event_id"
    result = await db.execute(
        text(
            f"""
            SELECT
                id,
                posting_code,
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
            FROM teaching_events
            WHERE id = :{id_param}
              AND posting_code = :posting_code
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
    return dict(row)


async def duplicate_teaching_event(
    db: AsyncSession,
    *,
    posting_code: str,
    source_event_id: UUID,
    event_date: date,
    start_time: time | None,
    teaching_name: str | None,
) -> dict[str, Any]:
    source = await _get_event_for_posting(
        db,
        event_id=source_event_id,
        posting_code=posting_code,
        source=True,
    )
    new_teaching_name = teaching_name or source["teaching_name"]
    new_start_time = start_time or source["start_time"]
    await _ensure_not_public_holiday(db, event_date)
    event = await _insert_event(
        db,
        posting_code=posting_code,
        teaching_name=new_teaching_name,
        event_date=event_date,
        start_time=new_start_time,
        cme_points_awarded=source.get("cme_points_awarded", False),
        smc_event_code=source.get("smc_event_code"),
    )
    await db.commit()
    invalidate_secretary_event_caches(posting_code)
    return event


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
            FROM attendance_records
            WHERE teaching_event_id = ANY(:event_ids)
            LIMIT 1
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
    await _get_event_for_posting(db, event_id=event_id, posting_code=posting_code)
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
    await db.commit()
    invalidate_secretary_event_caches(posting_code)
    return {"deleted_count": 1}


async def teaching_name_options(
    db: AsyncSession,
    *,
    posting_code: str,
) -> list[dict[str, Any]]:
    catalogue_result = await db.execute(
        text(
            """
            SELECT DISTINCT
                tnc.keyword,
                tnc.session_type_id,
                st.name AS session_type,
                tnc.duration_hours,
                tnc.is_tracked,
                false AS is_global
            FROM teaching_name_catalogue tnc
            JOIN session_types st ON st.id = tnc.session_type_id
            WHERE tnc.posting_code = :posting_code
            ORDER BY tnc.keyword ASC, tnc.duration_hours DESC
            """
        ),
        {"posting_code": posting_code},
    )
    global_result = await db.execute(
        text(
            """
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

    options = [dict(row) for row in catalogue_result.mappings().all()]
    options.extend(dict(row) for row in global_result.mappings().all())
    return sorted(options, key=lambda row: (row["keyword"], row["is_global"]))


async def current_residents(
    db: AsyncSession,
    *,
    posting_code: str,
    today: date | None = None,
) -> list[dict[str, Any]]:
    today = today or date.today()
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
              AND rp.start_date <= :today
              AND rp.end_date >= :today
              AND rp.status IN ('active', 'loa_working')
              AND r.status != 'inactive'
            ORDER BY r.name ASC, r.mcr ASC
            """
        ),
        {"posting_code": posting_code, "today": today},
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
    posting_code: str,
    teaching_name: str,
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
    await resolve_teaching_name(db, posting_code=posting_code, teaching_name=teaching_name)
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
                posting_code=posting_code,
                teaching_name=teaching_name,
                event_date=occurrence_date,
                start_time=start_time,
                cme_points_awarded=cme_points_awarded,
                smc_event_code=smc_event_code,
                series_id=series["id"],
            )
        )

    await db.commit()
    invalidate_secretary_event_caches(posting_code)
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

    result = await db.execute(
        text(
            """
            SELECT
                id,
                posting_code,
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
            FROM teaching_events
            WHERE series_id = :series_id
              AND posting_code = :posting_code
            ORDER BY event_date ASC, start_time ASC
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
    await db.commit()
    invalidate_secretary_event_caches(posting_code)
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
