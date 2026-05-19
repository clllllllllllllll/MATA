from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.services.cache import cache


ACTIVE_POSTING_STATUSES = {"active", "loa_working"}
WEEKEND_WARNING = (
    "{count} session(s) submitted on a weekend will not count toward your PTT compliance "
    "as they do not meet the weekend exception rules for your programme."
)


def _event_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "posting_code": row["posting_code"],
        "teaching_name": row["teaching_name"],
        "event_date": row["event_date"],
        "start_time": row["start_time"],
        "end_time": row.get("end_time"),
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


def _attendance_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "resident_id": row["resident_id"],
        "teaching_event_id": row["teaching_event_id"],
        "status": row["status"],
        "posting_code": row.get("posting_code"),
    }


def _external_attendance_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "external_resident_id": row["external_resident_id"],
        "teaching_event_id": row["teaching_event_id"],
        "status": row["status"],
        "posting_code": row.get("posting_code"),
    }


def _compute_end_time(event_date: date, start_time: time, duration_hours: Decimal) -> time:
    minutes = int(duration_hours * Decimal("60"))
    return (datetime.combine(event_date, start_time) + timedelta(minutes=minutes)).time()


def _is_weekend(value: date) -> tuple[bool, str]:
    if value.weekday() == 5:
        return True, "sat"
    if value.weekday() == 6:
        return True, "sun"
    return False, ""


def _cache_posting_prefix(posting_code: str) -> str:
    return f"resident_events|posting_code={posting_code}"


def invalidate_resident_caches(
    *,
    resident_id: UUID | str | None = None,
    external_resident_id: UUID | str | None = None,
    posting_codes: set[str],
) -> None:
    if resident_id is not None:
        cache.invalidate_prefix(f"resident_events|resident_id={resident_id}")
        cache.invalidate_prefix(f"resident_dashboard|resident_id={resident_id}")
    if external_resident_id is not None:
        cache.invalidate_prefix(f"resident_events|external_resident_id={external_resident_id}")
        cache.invalidate_prefix(
            f"resident_dashboard|external_resident_id={external_resident_id}"
        )
    for posting_code in posting_codes:
        cache.invalidate_prefix(_cache_posting_prefix(posting_code))


async def _resident(db: AsyncSession, resident_id: UUID) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT id, name, mcr, programme_code, status
            FROM residents
            WHERE id = :resident_id
            """
        ),
        {"resident_id": str(resident_id)},
    )
    row = result.mappings().one_or_none()
    if row is None or row.get("status") == "inactive":
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    return dict(row)


async def _external_resident(
    db: AsyncSession,
    external_resident_id: UUID,
) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT id, name, mcr, home_cluster, current_nhg_posting_code, status
            FROM external_residents
            WHERE id = :external_resident_id
            """
        ),
        {"external_resident_id": str(external_resident_id)},
    )
    row = result.mappings().one_or_none()
    if row is None or row.get("status") == "inactive":
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    return dict(row)


async def _open_reporting_period(db: AsyncSession) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT id, label, start_date, end_date, status
            FROM reporting_periods
            WHERE status = 'open'
            ORDER BY start_date DESC
            LIMIT 1
            """
        )
    )
    row = result.mappings().one_or_none()
    return dict(row) if row is not None else None


async def _posting_contexts(
    db: AsyncSession,
    *,
    resident_id: UUID,
    reporting_period_id: UUID | str,
    on_date: date,
) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT
                resident_id,
                reporting_period_id,
                posting_code,
                r_year,
                start_date,
                end_date,
                status
            FROM resident_postings
            WHERE resident_id = :resident_id
              AND reporting_period_id = :reporting_period_id
              AND start_date <= :on_date
              AND end_date >= :on_date
              AND status IN ('active', 'loa_working')
            ORDER BY start_date DESC
            """
        ),
        {
            "resident_id": str(resident_id),
            "reporting_period_id": str(reporting_period_id),
            "on_date": on_date,
        },
    )
    return [dict(row) for row in result.mappings().all()]


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
        detail="Ad-hoc teaching cannot be submitted on public holidays",
        error_code=ErrorCode.VALIDATION_FAILED.value,
        metadata={"holiday_date": event_date.isoformat(), "holiday_name": holiday_name},
    )


async def _resolve_teaching_name(
    db: AsyncSession,
    *,
    posting_code: str,
    programme_code: str,
    r_year: str,
    reporting_period_id: UUID | str,
    teaching_name: str,
) -> dict[str, Any] | None:
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
              AND name = :teaching_name
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
              AND tnc.programme_code = :programme_code
              AND tnc.reporting_period_id = :reporting_period_id
              AND tnc.r_year IN (:r_year, 'ALL')
              AND tnc.keyword = :teaching_name
            ORDER BY
                CASE WHEN tnc.r_year = :r_year THEN 0 ELSE 1 END,
                tnc.duration_hours DESC,
                st.name ASC
            """
        ),
        {
            "posting_code": posting_code,
            "programme_code": programme_code,
            "reporting_period_id": str(reporting_period_id),
            "r_year": r_year,
            "teaching_name": teaching_name,
        },
    )
    row = result.mappings().one_or_none()
    return dict(row) if row is not None else None


async def _get_event(db: AsyncSession, event_id: UUID) -> dict[str, Any]:
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
            WHERE id = :event_id
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


async def _posting_supports_secretary_events(
    db: AsyncSession,
    posting_code: str,
) -> bool:
    result = await db.execute(
        text(
            """
            SELECT supports_secretary_events
            FROM posting_codes
            WHERE code = :posting_code
            """
        ),
        {"posting_code": posting_code},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise ApiError(
            status_code=422,
            detail="current_nhg_posting_code is not valid",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    return bool(row["supports_secretary_events"])


async def _events_for_postings(
    db: AsyncSession,
    *,
    resident_id: UUID,
    posting_codes: set[str],
    today: date,
    date_from: date | None,
    date_to: date | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "resident_id": str(resident_id),
        "posting_codes": sorted(posting_codes),
        "today": today,
    }
    where = [
        "posting_code = ANY(:posting_codes)",
        "event_date <= :today",
        """NOT EXISTS (
              SELECT 1
              FROM attendance_records ar
              WHERE ar.resident_id = :resident_id
                AND ar.teaching_event_id = teaching_events.id
                AND ar.status = 'submitted'
          )""",
    ]
    if date_from is not None:
        params["date_from"] = date_from
        where.append("event_date >= :date_from")
    if date_to is not None:
        params["date_to"] = date_to
        where.append("event_date <= :date_to")

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
    return [dict(row) for row in result.mappings().all()]


async def _events_for_external_posting(
    db: AsyncSession,
    *,
    external_resident_id: UUID,
    posting_code: str,
    today: date,
    date_from: date | None,
    date_to: date | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "external_resident_id": str(external_resident_id),
        "posting_code": posting_code,
        "today": today,
    }
    where = [
        "posting_code = :posting_code",
        "event_date <= :today",
        "created_by_role = 'secretary'",
        """NOT EXISTS (
              SELECT 1
              FROM external_attendance_records ear
              WHERE ear.external_resident_id = :external_resident_id
                AND ear.teaching_event_id = teaching_events.id
                AND ear.status = 'submitted'
          )""",
    ]
    if date_from is not None:
        params["date_from"] = date_from
        where.append("event_date >= :date_from")
    if date_to is not None:
        params["date_to"] = date_to
        where.append("event_date <= :date_to")

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
    return [dict(row) for row in result.mappings().all()]


def _matching_context(
    contexts: list[dict[str, Any]],
    *,
    posting_code: str,
) -> dict[str, Any] | None:
    return next((row for row in contexts if row["posting_code"] == posting_code), None)


async def list_available_events(
    db: AsyncSession,
    *,
    role: str = "resident",
    resident_id: UUID | None = None,
    external_resident_id: UUID | None = None,
    today: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    if role == "external_resident":
        if external_resident_id is None:
            raise ApiError(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )
        resident = await _external_resident(db, external_resident_id)
        posting_code = resident["current_nhg_posting_code"]
        supports_secretary_events = await _posting_supports_secretary_events(db, posting_code)
        if not supports_secretary_events:
            return {"events": [], "reason": "secretary_events_not_supported"}
        events = await _events_for_external_posting(
            db,
            external_resident_id=external_resident_id,
            posting_code=posting_code,
            today=today,
            date_from=date_from,
            date_to=date_to,
        )
        return {"events": [_event_row(row) for row in events]}

    if resident_id is None:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    resident = await _resident(db, resident_id)
    period = await _open_reporting_period(db)
    if period is None:
        return {"events": [], "reason": "reporting_period_unavailable"}

    contexts = await _posting_contexts(
        db,
        resident_id=resident_id,
        reporting_period_id=period["id"],
        on_date=today,
    )
    if not contexts:
        return {"events": [], "reason": "posting_schedule_unavailable"}

    posting_codes = {row["posting_code"] for row in contexts if row.get("posting_code")}
    raw_events = await _events_for_postings(
        db,
        resident_id=resident_id,
        posting_codes=posting_codes,
        today=today,
        date_from=date_from,
        date_to=date_to,
    )

    events: list[dict[str, Any]] = []
    for event in raw_events:
        context = _matching_context(contexts, posting_code=event["posting_code"])
        if context is None:
            continue
        resolved = await _resolve_teaching_name(
            db,
            posting_code=event["posting_code"],
            programme_code=resident["programme_code"],
            r_year=context["r_year"],
            reporting_period_id=period["id"],
            teaching_name=event["teaching_name"],
        )
        if resolved is not None:
            events.append(_event_row(event))
    return {"events": events}


async def _duplicate_attendance_exists(
    db: AsyncSession,
    *,
    resident_id: UUID,
    event_id: UUID | str,
) -> bool:
    result = await db.execute(
        text(
            """
            SELECT 1
            FROM attendance_records
            WHERE resident_id = :resident_id
              AND teaching_event_id = :event_id
              AND status = 'submitted'
            LIMIT 1
            """
        ),
        {"resident_id": str(resident_id), "event_id": str(event_id)},
    )
    return result.scalar_one_or_none() is not None


async def _insert_attendance(
    db: AsyncSession,
    *,
    resident_id: UUID,
    event_id: UUID | str,
    posting_code: str,
) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            INSERT INTO attendance_records (
                resident_id,
                teaching_event_id,
                status,
                posting_code
            )
            VALUES (
                :resident_id,
                :event_id,
                'submitted',
                :posting_code
            )
            RETURNING id, resident_id, teaching_event_id, status, posting_code
            """
        ),
        {
            "resident_id": str(resident_id),
            "event_id": str(event_id),
            "posting_code": posting_code,
        },
    )
    return _attendance_row(dict(result.mappings().one()))


async def _duplicate_external_attendance_exists(
    db: AsyncSession,
    *,
    external_resident_id: UUID,
    event_id: UUID | str,
) -> bool:
    result = await db.execute(
        text(
            """
            SELECT 1
            FROM external_attendance_records
            WHERE external_resident_id = :external_resident_id
              AND teaching_event_id = :event_id
              AND status = 'submitted'
            LIMIT 1
            """
        ),
        {
            "external_resident_id": str(external_resident_id),
            "event_id": str(event_id),
        },
    )
    return result.scalar_one_or_none() is not None


async def _insert_external_attendance(
    db: AsyncSession,
    *,
    external_resident_id: UUID,
    event_id: UUID | str,
    posting_code: str,
) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            INSERT INTO external_attendance_records (
                external_resident_id,
                teaching_event_id,
                status,
                posting_code
            )
            VALUES (
                :external_resident_id,
                :event_id,
                'submitted',
                :posting_code
            )
            RETURNING id, external_resident_id, teaching_event_id, status, posting_code
            """
        ),
        {
            "external_resident_id": str(external_resident_id),
            "event_id": str(event_id),
            "posting_code": posting_code,
        },
    )
    return _external_attendance_row(dict(result.mappings().one()))


async def _resolve_teaching_name_for_posting(
    db: AsyncSession,
    *,
    posting_code: str,
    teaching_name: str,
) -> dict[str, Any] | None:
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
              AND name = :teaching_name
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
    return dict(row) if row is not None else None


async def _weekend_is_accepted(
    db: AsyncSession,
    *,
    event: dict[str, Any],
    programme_code: str,
    session_type_id: UUID | str | None,
) -> bool:
    is_weekend, day_type = _is_weekend(event["event_date"])
    if not is_weekend:
        return True

    result = await db.execute(
        text(
            """
            SELECT
                programme_code,
                posting_code,
                day_type,
                start_time_min,
                end_time_max,
                session_type_id,
                session_name_pattern,
                mutates_to_session_type_id,
                adjusted_duration_hours
            FROM weekend_exceptions
            WHERE (programme_code IS NULL OR programme_code = :programme_code)
              AND (posting_code IS NULL OR posting_code = :posting_code)
              AND day_type IN (:day_type, 'both')
            """
        ),
        {
            "programme_code": programme_code,
            "posting_code": event["posting_code"],
            "day_type": day_type,
        },
    )
    rows = [dict(row) for row in result.mappings().all()]
    for row in rows:
        if row.get("start_time_min") and event["start_time"] < row["start_time_min"]:
            continue
        if row.get("end_time_max") and event.get("end_time") and event["end_time"] > row["end_time_max"]:
            continue
        if row.get("session_type_id") and str(row["session_type_id"]) != str(session_type_id):
            continue
        if row.get("session_name_pattern") and row["session_name_pattern"] not in event["teaching_name"]:
            continue
        return True
    return False


async def submit_attendance(
    db: AsyncSession,
    *,
    role: str = "resident",
    resident_id: UUID | None = None,
    external_resident_id: UUID | None = None,
    event_ids: list[UUID],
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    if role == "external_resident":
        if external_resident_id is None:
            raise ApiError(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )
        resident = await _external_resident(db, external_resident_id)
        posting_code = resident["current_nhg_posting_code"]
        submitted = 0
        weekend_warning_count = 0
        touched_postings: set[str] = set()
        for event_id in event_ids:
            event = await _get_event(db, event_id)
            if event["event_date"] > today:
                raise ApiError(
                    status_code=422,
                    detail="Future teaching events cannot be submitted",
                    error_code=ErrorCode.VALIDATION_FAILED.value,
                )
            if event["posting_code"] != posting_code:
                raise ApiError(
                    status_code=422,
                    detail="Teaching event is outside the resident posting scope",
                    error_code=ErrorCode.VALIDATION_FAILED.value,
                )
            supports_secretary_events = await _posting_supports_secretary_events(
                db,
                posting_code,
            )
            if event.get("created_by_role") == "secretary" and not supports_secretary_events:
                raise ApiError(
                    status_code=422,
                    detail="Secretary-created events are not supported for this posting",
                    error_code=ErrorCode.VALIDATION_FAILED.value,
                )
            if await _duplicate_external_attendance_exists(
                db,
                external_resident_id=external_resident_id,
                event_id=event_id,
            ):
                raise ApiError(
                    status_code=409,
                    detail="Attendance already submitted for this teaching event",
                    error_code=ErrorCode.CONFLICT.value,
                )
            await _insert_external_attendance(
                db,
                external_resident_id=external_resident_id,
                event_id=event_id,
                posting_code=event["posting_code"],
            )
            submitted += 1
            touched_postings.add(event["posting_code"])
            accepted = await _weekend_is_accepted(
                db,
                event=event,
                programme_code="",
                session_type_id=event.get("session_type_id"),
            )
            if not accepted:
                weekend_warning_count += 1

        await db.commit()
        invalidate_resident_caches(
            external_resident_id=external_resident_id,
            posting_codes=touched_postings,
        )
        return {
            "submitted": submitted,
            "errors": [],
            "compliance_warning": (
                WEEKEND_WARNING.format(count=weekend_warning_count)
                if weekend_warning_count
                else None
            ),
        }

    if resident_id is None:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    resident = await _resident(db, resident_id)
    period = await _open_reporting_period(db)
    if period is None:
        raise ApiError(
            status_code=422,
            detail="No open reporting period is available",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )

    submitted = 0
    weekend_warning_count = 0
    touched_postings: set[str] = set()
    for event_id in event_ids:
        event = await _get_event(db, event_id)
        if event["event_date"] > today:
            raise ApiError(
                status_code=422,
                detail="Future teaching events cannot be submitted",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        contexts = await _posting_contexts(
            db,
            resident_id=resident_id,
            reporting_period_id=period["id"],
            on_date=event["event_date"],
        )
        context = _matching_context(contexts, posting_code=event["posting_code"])
        if context is None:
            raise ApiError(
                status_code=422,
                detail="Teaching event is outside the resident posting schedule",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        resolved = await _resolve_teaching_name(
            db,
            posting_code=event["posting_code"],
            programme_code=resident["programme_code"],
            r_year=context["r_year"],
            reporting_period_id=period["id"],
            teaching_name=event["teaching_name"],
        )
        if resolved is None:
            raise ApiError(
                status_code=422,
                detail="Teaching event is not visible for this resident",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        if await _duplicate_attendance_exists(db, resident_id=resident_id, event_id=event_id):
            raise ApiError(
                status_code=409,
                detail="Attendance already submitted for this teaching event",
                error_code=ErrorCode.CONFLICT.value,
            )

        await _insert_attendance(
            db,
            resident_id=resident_id,
            event_id=event_id,
            posting_code=event["posting_code"],
        )
        submitted += 1
        touched_postings.add(event["posting_code"])
        accepted = await _weekend_is_accepted(
            db,
            event=event,
            programme_code=resident["programme_code"],
            session_type_id=resolved.get("session_type_id"),
        )
        if not accepted:
            weekend_warning_count += 1

    await db.commit()
    invalidate_resident_caches(resident_id=resident_id, posting_codes=touched_postings)
    return {
        "submitted": submitted,
        "errors": [],
        "compliance_warning": (
            WEEKEND_WARNING.format(count=weekend_warning_count)
            if weekend_warning_count
            else None
        ),
    }


async def submit_adhoc_teaching(
    db: AsyncSession,
    *,
    role: str = "resident",
    resident_id: UUID | None = None,
    external_resident_id: UUID | None = None,
    event_date: date,
    start_time: time,
    teaching_name: str,
) -> dict[str, Any]:
    if role == "external_resident":
        if external_resident_id is None:
            raise ApiError(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )
        resident = await _external_resident(db, external_resident_id)
        await _ensure_not_public_holiday(db, event_date)
        posting_code = resident["current_nhg_posting_code"]
        resolved = await _resolve_teaching_name_for_posting(
            db,
            posting_code=posting_code,
            teaching_name=teaching_name,
        )
        duration_hours = resolved["duration_hours"] if resolved is not None else None
        end_time = (
            _compute_end_time(event_date, start_time, duration_hours)
            if duration_hours is not None
            else None
        )
        event_result = await db.execute(
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
                    true,
                    'external_resident'
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
                "session_type_id": resolved.get("session_type_id") if resolved else None,
            },
        )
        event = _event_row(dict(event_result.mappings().one()))
        attendance = await _insert_external_attendance(
            db,
            external_resident_id=external_resident_id,
            event_id=event["id"],
            posting_code=event["posting_code"],
        )
        accepted = await _weekend_is_accepted(
            db,
            event=event,
            programme_code="",
            session_type_id=event.get("session_type_id"),
        )
        await db.commit()
        invalidate_resident_caches(
            external_resident_id=external_resident_id,
            posting_codes={event["posting_code"]},
        )
        return {
            "event": event,
            "attendance": attendance,
            "compliance_warning": None if accepted else WEEKEND_WARNING.format(count=1),
        }

    if resident_id is None:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    resident = await _resident(db, resident_id)
    period = await _open_reporting_period(db)
    if period is None:
        raise ApiError(
            status_code=422,
            detail="No open reporting period is available",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    await _ensure_not_public_holiday(db, event_date)
    contexts = await _posting_contexts(
        db,
        resident_id=resident_id,
        reporting_period_id=period["id"],
        on_date=event_date,
    )
    if not contexts:
        raise ApiError(
            status_code=422,
            detail="No active resident posting is available for the submitted teaching date",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    if len(contexts) > 1:
        # TODO: Add request-level posting disambiguation once the API contract defines it.
        raise ApiError(
            status_code=422,
            detail="Posting disambiguation is required for this teaching date",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    context = contexts[0]
    resolved = await _resolve_teaching_name(
        db,
        posting_code=context["posting_code"],
        programme_code=resident["programme_code"],
        r_year=context["r_year"],
        reporting_period_id=period["id"],
        teaching_name=teaching_name,
    )
    if resolved is None:
        raise ApiError(
            status_code=422,
            detail="teaching_name is not available for this resident posting",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )

    duration_hours = resolved["duration_hours"]
    end_time = _compute_end_time(event_date, start_time, duration_hours)
    event_result = await db.execute(
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
                true,
                'resident'
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
            "posting_code": context["posting_code"],
            "teaching_name": teaching_name,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
            "duration_hours": duration_hours,
            "session_type_id": resolved.get("session_type_id"),
        },
    )
    event = _event_row(dict(event_result.mappings().one()))
    attendance = await _insert_attendance(
        db,
        resident_id=resident_id,
        event_id=event["id"],
        posting_code=event["posting_code"],
    )
    accepted = await _weekend_is_accepted(
        db,
        event=event,
        programme_code=resident["programme_code"],
        session_type_id=resolved.get("session_type_id"),
    )
    await db.commit()
    invalidate_resident_caches(resident_id=resident_id, posting_codes={event["posting_code"]})
    return {
        "event": event,
        "attendance": attendance,
        "compliance_warning": None if accepted else WEEKEND_WARNING.format(count=1),
    }


async def remove_attendance(
    db: AsyncSession,
    *,
    resident_id: UUID,
    attendance_id: UUID,
) -> dict[str, int]:
    result = await db.execute(
        text(
            """
            UPDATE attendance_records
            SET status = 'removed'
            WHERE id = :attendance_id
              AND resident_id = :resident_id
              AND status = 'submitted'
            """
        ),
        {"attendance_id": str(attendance_id), "resident_id": str(resident_id)},
    )
    if result.rowcount != 1:
        raise ApiError(
            status_code=404,
            detail="Attendance record not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    await db.commit()
    invalidate_resident_caches(resident_id=resident_id, posting_codes=set())
    return {"removed_count": 1}


async def list_attendance_history(
    db: AsyncSession,
    *,
    role: str = "resident",
    resident_id: UUID | None = None,
    external_resident_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    where = ["attendance.status != 'removed'"]
    if role == "external_resident":
        if external_resident_id is None:
            raise ApiError(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )
        await _external_resident(db, external_resident_id)
        table_name = "external_attendance_records"
        id_column = "external_resident_id"
        params["subject_id"] = str(external_resident_id)
    else:
        if resident_id is None:
            raise ApiError(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )
        await _resident(db, resident_id)
        table_name = "attendance_records"
        id_column = "resident_id"
        params["subject_id"] = str(resident_id)
    where.append(f"attendance.{id_column} = :subject_id")
    if date_from is not None:
        params["date_from"] = date_from
        where.append("events.event_date >= :date_from")
    if date_to is not None:
        params["date_to"] = date_to
        where.append("events.event_date <= :date_to")
    if status:
        params["status"] = status.strip().lower()
        where.append("attendance.status = :status")

    result = await db.execute(
        text(
            f"""
            SELECT
                attendance.id AS attendance_id,
                attendance.teaching_event_id,
                events.teaching_name,
                events.event_date,
                events.start_time,
                events.end_time,
                events.duration_hours,
                events.posting_code,
                attendance.status,
                attendance.submitted_at
            FROM {table_name} attendance
            JOIN teaching_events events
              ON events.id = attendance.teaching_event_id
            WHERE {' AND '.join(where)}
            ORDER BY events.event_date DESC, attendance.submitted_at DESC
            """
        ),
        params,
    )
    rows = [dict(row) for row in result.mappings().all()]
    return {"attendance": rows}


async def dashboard_placeholder(
    db: AsyncSession,
    *,
    role: str = "resident",
    resident_id: UUID | None = None,
    external_resident_id: UUID | None = None,
) -> dict[str, Any]:
    if role == "external_resident":
        if external_resident_id is None:
            raise ApiError(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )
        await _external_resident(db, external_resident_id)
        return {
            "compliance_status": "not_applicable",
            "reason": "external_resident_excluded_from_nhg_compliance",
            "message": (
                "External resident attendance is stored for future export to the home "
                "cluster PC. NHG compliance and clawback do not apply."
            ),
        }

    if resident_id is None:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    resident = await _resident(db, resident_id)
    period = await _open_reporting_period(db)
    return {
        "resident": {
            "id": resident["id"],
            "name": resident["name"],
            "mcr": resident["mcr"],
            "programme_code": resident.get("programme_code"),
        },
        "reporting_period": (
            {
                "id": period["id"],
                "label": period["label"],
            }
            if period is not None
            else None
        ),
        "compliance_status": "pending_phase_6",
        "message": (
            "Compliance dashboard will be available after the Phase 6 compliance "
            "engine is implemented."
        ),
    }
