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


async def _resolve_secretary_programme_pool(
    db: AsyncSession,
    posting_code: str,
) -> list[str]:
    result = await db.execute(
        text(
            """
            SELECT programme_code
            FROM secretary_programme_pools
            WHERE posting_code = :posting_code
              AND is_active = true
            ORDER BY programme_code ASC
            """
        ),
        {"posting_code": posting_code},
    )
    return [str(row["programme_code"]) for row in result.mappings().all()]


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


async def _catalogue_rows_for_secretary_posting(
    db: AsyncSession,
    *,
    posting_code: str,
    reporting_period_id: UUID | str,
    teaching_name: str | None = None,
) -> list[dict[str, Any]]:
    programme_codes = await _resolve_secretary_programme_pool(db, posting_code)
    if programme_codes:
        if teaching_name is None:
            result = await db.execute(
                text(
                    """
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
                    WHERE tnc.programme_code = ANY(:programme_codes)
                      AND tnc.reporting_period_id = :reporting_period_id
                    ORDER BY tnc.keyword ASC, tnc.duration_hours DESC, st.name ASC
                    """
                ),
                {
                    "programme_codes": programme_codes,
                    "reporting_period_id": str(reporting_period_id),
                },
            )
        else:
            result = await db.execute(
                text(
                    """
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
                    WHERE tnc.programme_code = ANY(:programme_codes)
                      AND tnc.reporting_period_id = :reporting_period_id
                      AND tnc.keyword = :teaching_name
                    ORDER BY tnc.keyword ASC, tnc.duration_hours DESC, st.name ASC
                    """
                ),
                {
                    "programme_codes": programme_codes,
                    "reporting_period_id": str(reporting_period_id),
                    "teaching_name": teaching_name,
                },
            )
        return [dict(row) for row in result.mappings().all()]

    if teaching_name is None:
        result = await db.execute(
            text(
                """
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
                WHERE tnc.posting_code = :posting_code
                  AND tnc.reporting_period_id = :reporting_period_id
                ORDER BY tnc.keyword ASC, tnc.duration_hours DESC, st.name ASC
                """
            ),
            {
                "posting_code": posting_code,
                "reporting_period_id": str(reporting_period_id),
            },
        )
    else:
        result = await db.execute(
            text(
                """
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
                WHERE tnc.posting_code = :posting_code
                  AND tnc.reporting_period_id = :reporting_period_id
                  AND tnc.keyword = :teaching_name
                ORDER BY tnc.keyword ASC, tnc.duration_hours DESC, st.name ASC
                """
            ),
            {
                "posting_code": posting_code,
                "reporting_period_id": str(reporting_period_id),
                "teaching_name": teaching_name,
            },
        )
    return [dict(row) for row in result.mappings().all()]


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


async def resolve_teaching_name(
    db: AsyncSession,
    *,
    posting_code: str,
    teaching_name: str,
    reporting_period_id: UUID | str,
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

    rows = await _catalogue_rows_for_secretary_posting(
        db,
        posting_code=posting_code,
        reporting_period_id=reporting_period_id,
        teaching_name=teaching_name,
    )
    if not rows:
        raise ApiError(
            status_code=422,
            detail="teaching_name is not available for this secretary posting",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    return rows[0]


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
    posting_code: str,
    teaching_name: str,
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
    resolved = await resolve_teaching_name(
        db,
        posting_code=posting_code,
        teaching_name=teaching_name,
        reporting_period_id=period["id"],
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
    return event


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


async def update_teaching_event(
    db: AsyncSession,
    *,
    posting_code: str,
    event_id: UUID,
    teaching_name: str,
    event_date: date,
    start_time: time,
    cme_points_awarded: bool,
    smc_event_code: str | None,
) -> dict[str, Any]:
    source = await _get_event_for_posting(
        db,
        event_id=event_id,
        posting_code=posting_code,
    )
    if source.get("created_by_role") not in {"secretary", "programme_pc", None} or source.get("is_adhoc"):
        raise ApiError(
            status_code=409,
            detail="Teaching event cannot be edited because it is not a scheduled teaching event",
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
    resolved = await resolve_teaching_name(
        db,
        posting_code=posting_code,
        teaching_name=teaching_name,
        reporting_period_id=period["id"],
    )
    duration_hours = resolved["duration_hours"]
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
            "teaching_name": teaching_name,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
            "duration_hours": duration_hours,
            "session_type_id": resolved.get("session_type_id"),
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
    await db.commit()
    invalidate_secretary_event_caches(posting_code)
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
                  AND ar.status = 'submitted'
            )
            OR EXISTS (
                SELECT 1
                FROM external_attendance_records ear
                WHERE ear.teaching_event_id = ANY(:event_ids)
                  AND ear.status = 'submitted'
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
    source = await _get_event_for_posting(db, event_id=event_id, posting_code=posting_code)
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
    await db.commit()
    invalidate_secretary_event_caches(posting_code)
    return {"deleted_count": 1}


async def teaching_name_options(
    db: AsyncSession,
    *,
    posting_code: str,
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
    catalogue_rows = await _catalogue_rows_for_secretary_posting(
        db,
        posting_code=posting_code,
        reporting_period_id=period["id"],
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

    options_by_keyword: dict[str, dict[str, Any]] = {}

    for row in catalogue_rows:
        keyword = str(row.get("keyword") or "").strip()
        if not keyword:
            continue
        posting_code_value = row.get("posting_code")
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

        if posting_code_value and posting_code_value not in aggregate["posting_codes"]:
            aggregate["posting_codes"].append(posting_code_value)
        aggregate["_session_type_ids"].add(str(row.get("session_type_id")))
        if row.get("session_type") is not None:
            aggregate["_session_types"].add(str(row.get("session_type")))
        if row.get("duration_hours") is not None:
            aggregate["_durations"].add(str(row.get("duration_hours")))
        aggregate["_tracked_values"].add(bool(row.get("is_tracked")))

    options: list[dict[str, Any]] = []
    for keyword in sorted(options_by_keyword.keys()):
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

    for row in global_result.mappings().all():
        keyword = str(row.get("keyword") or "").strip()
        if not keyword:
            continue
        if keyword in options_by_keyword:
            continue
        options.append(
            {
                "keyword": keyword,
                "session_type_id": row.get("session_type_id"),
                "session_type": row.get("session_type"),
                "duration_hours": row.get("duration_hours"),
                "is_tracked": row.get("is_tracked"),
                "is_global": True,
                "posting_codes": [],
            }
        )

    return sorted(options, key=lambda row: (_natural_sort_key(row["keyword"]), row["is_global"]))


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
