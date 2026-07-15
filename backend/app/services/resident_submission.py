from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.services import cache_invalidation
from app.services.reporting_period_status import resolve_active_reporting_period_for_date


ACTIVE_POSTING_STATUSES = {"active", "loa_working"}
WEEKEND_WARNING = (
    "{count} session(s) submitted on a weekend will not count toward your PTT compliance "
    "as they do not meet the weekend exception rules for your programme."
)
ADHOC_COMPLIANCE_TEACHING_NAME = "Department/Programme Teaching [1h]"
ExternalEventIneligibilityReason = Literal[
    "future_event",
    "posting_unavailable",
    "posting_mismatch",
    "event_scope",
    "secretary_events_not_supported",
    "already_attended",
]


def _event_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "posting_code": row["posting_code"],
        "teaching_name": row["teaching_name"],
        "details_of_session": row.get("details_of_session"),
        "event_date": row["event_date"],
        "start_time": row["start_time"],
        "end_time": row.get("end_time"),
        "duration_hours": row.get("duration_hours"),
        "session_type_id": row.get("session_type_id"),
        "series_id": row.get("series_id"),
        "cme_points_awarded": row.get("cme_points_awarded", False),
        "smc_event_code": row.get("smc_event_code"),
        "is_adhoc": row.get("is_adhoc", False),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _available_event_row(
    event: dict[str, Any],
    *,
    resolved: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": event["id"],
        "teaching_name": event["teaching_name"],
        "event_date": event["event_date"],
        "start_time": event["start_time"],
        "end_time": event.get("end_time"),
        "posting_code": event["posting_code"],
        "session_type": resolved.get("session_type"),
        "session_type_name": resolved.get("session_type"),
        "duration_hours": event.get("duration_hours") or resolved.get("duration_hours"),
        "details_of_session": event.get("details_of_session"),
        "is_global": bool(resolved.get("is_global")),
        "is_adhoc": bool(event.get("is_adhoc", False)),
        "already_submitted": False,
    }


def _attendance_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "resident_id": row["resident_id"],
        "teaching_event_id": row["teaching_event_id"],
        "status": row["status"],
        "posting_code": row.get("posting_code"),
        "submitted_at": row.get("submitted_at"),
    }


def _external_attendance_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "external_resident_id": row["external_resident_id"],
        "teaching_event_id": row["teaching_event_id"],
        "status": row["status"],
        "posting_code": row.get("posting_code"),
        "submitted_at": row.get("submitted_at"),
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


def invalidate_resident_caches(
    *,
    resident_id: UUID | str | None = None,
    external_resident_id: UUID | str | None = None,
    posting_codes: set[str],
    programme_code: str | None = None,
    reporting_period_id: UUID | str | None = None,
    include_secretary_events: bool = False,
) -> None:
    cache_invalidation.invalidate_after_resident_attendance_mutation(
        resident_id=resident_id,
        external_resident_id=external_resident_id,
        posting_codes=posting_codes,
        programme_code=programme_code,
        reporting_period_id=reporting_period_id,
        include_secretary_events=include_secretary_events,
    )


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


async def _active_reporting_period(
    db: AsyncSession,
    *,
    relevant_date: date,
    status_as_of_date: date | None = None,
) -> dict[str, Any] | None:
    return await resolve_active_reporting_period_for_date(
        db,
        relevant_date=relevant_date,
        status_as_of_date=status_as_of_date,
    )


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


async def _posting_contexts_for_period(
    db: AsyncSession,
    *,
    resident_id: UUID,
    reporting_period_id: UUID | str,
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
              AND status IN ('active', 'loa_working')
            ORDER BY start_date DESC
            """
        ),
        {
            "resident_id": str(resident_id),
            "reporting_period_id": str(reporting_period_id),
        },
    )
    return [dict(row) for row in result.mappings().all()]


async def _resident_visibility_contexts(
    db: AsyncSession,
    *,
    resident_id: UUID,
    resident: dict[str, Any],
    reporting_period_id: UUID | str,
    on_date: date | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    contexts = (
        await _posting_contexts(
            db,
            resident_id=resident_id,
            reporting_period_id=reporting_period_id,
            on_date=on_date,
        )
        if on_date is not None
        else await _posting_contexts_for_period(
            db,
            resident_id=resident_id,
            reporting_period_id=reporting_period_id,
        )
    )
    native_posting_code = await _native_teaching_posting_code(
        db,
        programme_code=resident["programme_code"],
    )
    return contexts, [
        *contexts,
        *_native_visibility_contexts(
            contexts,
            native_posting_code=native_posting_code,
        ),
    ]


async def _native_teaching_posting_code(
    db: AsyncSession,
    *,
    programme_code: str,
) -> str | None:
    result = await db.execute(
        text(
            """
            SELECT native_teaching_posting_code
            FROM programmes
            WHERE code = :programme_code
            """
        ),
        {"programme_code": programme_code},
    )
    row = result.mappings().one_or_none()
    if row is None:
        return None
    return row.get("native_teaching_posting_code")


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


async def _resolve_teaching_target(
    db: AsyncSession,
    *,
    posting_code: str,
    programme_code: str,
    r_year: str,
    reporting_period_id: UUID | str,
    session_type: str,
) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT
                st.name AS keyword,
                tt.session_type_id,
                st.name AS session_type,
                st.duration_hours,
                tt.is_tracked,
                false AS is_global
            FROM teaching_targets tt
            JOIN session_types st ON st.id = tt.session_type_id
            WHERE tt.posting_code = :posting_code
              AND tt.programme_code = :programme_code
              AND tt.reporting_period_id = :reporting_period_id
              AND tt.r_year IN (:r_year, 'ALL')
              AND st.name = :session_type
            ORDER BY
                CASE WHEN tt.r_year = :r_year THEN 0 ELSE 1 END,
                st.duration_hours DESC,
                st.name ASC
            LIMIT 1
            """
        ),
        {
            "posting_code": posting_code,
            "programme_code": programme_code,
            "reporting_period_id": str(reporting_period_id),
            "r_year": r_year,
            "session_type": session_type,
        },
    )
    row = result.mappings().one_or_none()
    return dict(row) if row is not None else None


async def _posting_display_label(db: AsyncSession, posting_code: str) -> str:
    result = await db.execute(
        text(
            """
            SELECT display_name
            FROM posting_codes
            WHERE code = :posting_code
            """
        ),
        {"posting_code": posting_code},
    )
    row = result.mappings().one_or_none()
    if row is None:
        return posting_code
    return row.get("display_name") or posting_code


async def _teaching_options_for_context(
    db: AsyncSession,
    *,
    posting_code: str,
    programme_code: str,
    r_year: str,
    reporting_period_id: UUID | str,
) -> list[dict[str, Any]]:
    global_result = await db.execute(
        text(
            """
            SELECT
                name AS teaching_name,
                name AS keyword,
                NULL AS session_type_id,
                name AS session_type,
                name AS session_type_name,
                duration_hours,
                false AS is_tracked,
                true AS is_global
            FROM global_session_types
            WHERE is_active = true
            ORDER BY name ASC
            """
        )
    )
    catalogue_result = await db.execute(
        text(
            """
            SELECT
                tnc.keyword AS teaching_name,
                tnc.keyword AS keyword,
                tnc.session_type_id,
                st.name AS session_type,
                st.name AS session_type_name,
                tnc.duration_hours,
                tnc.is_tracked,
                false AS is_global
            FROM teaching_name_catalogue tnc
            JOIN session_types st ON st.id = tnc.session_type_id
            WHERE tnc.posting_code = :posting_code
              AND tnc.programme_code = :programme_code
              AND tnc.reporting_period_id = :reporting_period_id
              AND tnc.r_year IN (:r_year, 'ALL')
            ORDER BY tnc.keyword ASC, tnc.duration_hours DESC, st.name ASC
            """
        ),
        {
            "posting_code": posting_code,
            "programme_code": programme_code,
            "reporting_period_id": str(reporting_period_id),
            "r_year": r_year,
        },
    )
    rows = [dict(row) for row in global_result.mappings().all()]
    rows.extend(dict(row) for row in catalogue_result.mappings().all())
    rows.sort(key=lambda row: str(row["teaching_name"]).casefold())
    return rows


async def _teaching_options_for_posting(
    db: AsyncSession,
    *,
    posting_code: str,
    reporting_period_id: UUID | str,
) -> list[dict[str, Any]]:
    global_result = await db.execute(
        text(
            """
            SELECT
                name AS teaching_name,
                name AS keyword,
                NULL AS session_type_id,
                name AS session_type,
                name AS session_type_name,
                duration_hours,
                false AS is_tracked,
                true AS is_global
            FROM global_session_types
            WHERE is_active = true
            ORDER BY name ASC
            """
        )
    )
    catalogue_result = await db.execute(
        text(
            """
            SELECT DISTINCT ON (tnc.keyword)
                tnc.keyword AS teaching_name,
                tnc.keyword AS keyword,
                tnc.session_type_id,
                st.name AS session_type,
                st.name AS session_type_name,
                tnc.duration_hours,
                tnc.is_tracked,
                false AS is_global
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
    rows = [dict(row) for row in global_result.mappings().all()]
    rows.extend(dict(row) for row in catalogue_result.mappings().all())
    rows.sort(key=lambda row: str(row["teaching_name"]).casefold())
    return rows


async def _attended_posting_options_for_resident(
    db: AsyncSession,
    *,
    programme_code: str,
    r_year: str,
    reporting_period_id: UUID | str,
) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT DISTINCT
                pc.code AS posting_code,
                COALESCE(pc.display_name, pc.code) AS label,
                tnc.programme_code,
                p.name AS programme_name
            FROM teaching_name_catalogue tnc
            JOIN posting_codes pc ON pc.code = tnc.posting_code
            LEFT JOIN programmes p ON p.code = tnc.programme_code
            WHERE tnc.programme_code = :programme_code
              AND tnc.reporting_period_id = :reporting_period_id
              AND tnc.r_year IN (:r_year, 'ALL')
            ORDER BY label ASC, pc.code ASC
            """
        ),
        {
            "programme_code": programme_code,
            "reporting_period_id": str(reporting_period_id),
            "r_year": r_year,
        },
    )
    return [dict(row) for row in result.mappings().all()]


async def _attended_posting_options_for_external(
    db: AsyncSession,
    *,
    reporting_period_id: UUID | str,
) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT DISTINCT
                pc.code AS posting_code,
                COALESCE(pc.display_name, pc.code) AS label,
                tnc.programme_code,
                p.name AS programme_name
            FROM teaching_name_catalogue tnc
            JOIN posting_codes pc ON pc.code = tnc.posting_code
            LEFT JOIN programmes p ON p.code = tnc.programme_code
            WHERE tnc.reporting_period_id = :reporting_period_id
            ORDER BY label ASC, pc.code ASC, tnc.programme_code ASC
            """
        ),
        {"reporting_period_id": str(reporting_period_id)},
    )
    return [dict(row) for row in result.mappings().all()]


def _select_attended_posting(
    options: list[dict[str, Any]],
    *,
    requested_posting_code: str | None,
    default_posting_code: str,
) -> dict[str, Any] | None:
    if requested_posting_code:
        selected = next(
            (row for row in options if row["posting_code"] == requested_posting_code),
            None,
        )
        if selected is None:
            raise ApiError(
                status_code=422,
                detail="attended_posting_code must be selected from attended posting options",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        return selected
    return next(
        (row for row in options if row["posting_code"] == default_posting_code),
        options[0] if options else None,
    )


def _adhoc_options_response(
    *,
    teaching_date: date,
    available: bool,
    reason: str | None,
    message: str | None,
    reporting_period_id: UUID | str | None = None,
    posting_code: str | None = None,
    posting_label: str | None = None,
    r_year: str | None = None,
    attended_posting_options: list[dict[str, Any]] | None = None,
    selected_attended_posting: dict[str, Any] | None = None,
    options: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "date": teaching_date,
        "teaching_date": teaching_date,
        "available": available,
        "reason": reason,
        "message": message,
        "reporting_period_id": str(reporting_period_id) if reporting_period_id else None,
        "posting_code": posting_code,
        "posting_label": posting_label,
        "r_year": r_year,
        "attended_posting_options": attended_posting_options or [],
        "selected_attended_posting_code": (
            selected_attended_posting.get("posting_code")
            if selected_attended_posting
            else None
        ),
        "selected_attended_posting_label": (
            selected_attended_posting.get("label")
            if selected_attended_posting
            else None
        ),
        "options": options or [],
    }


async def list_adhoc_teaching_options(
    db: AsyncSession,
    *,
    resident_id: UUID,
    teaching_date: date,
    attended_posting_code: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    resident = await _resident(db, resident_id)
    period = await _active_reporting_period(
        db,
        relevant_date=teaching_date,
        status_as_of_date=today,
    )
    if period is None:
        return _adhoc_options_response(
            teaching_date=teaching_date,
            available=False,
            reason="active_reporting_period_unavailable",
            message="No active reporting period is available yet.",
        )
    await _ensure_not_public_holiday(db, teaching_date)
    contexts = await _posting_contexts(
        db,
        resident_id=resident_id,
        reporting_period_id=period["id"],
        on_date=teaching_date,
    )
    if not contexts:
        return _adhoc_options_response(
            teaching_date=teaching_date,
            available=False,
            reason="posting_unavailable",
            message="No active resident posting is available for the selected teaching date.",
            reporting_period_id=period["id"],
        )
    if len(contexts) > 1:
        return _adhoc_options_response(
            teaching_date=teaching_date,
            available=False,
            reason="posting_disambiguation_required",
            message="Multiple resident postings match the selected teaching date.",
            reporting_period_id=period["id"],
        )

    context = contexts[0]
    assigned_posting_code = context["posting_code"]
    posting_label = await _posting_display_label(db, assigned_posting_code)
    attended_posting_options = await _attended_posting_options_for_resident(
        db,
        programme_code=resident["programme_code"],
        r_year=context["r_year"],
        reporting_period_id=period["id"],
    )
    selected_attended_posting = _select_attended_posting(
        attended_posting_options,
        requested_posting_code=attended_posting_code,
        default_posting_code=assigned_posting_code,
    )
    if selected_attended_posting is None:
        return _adhoc_options_response(
            teaching_date=teaching_date,
            available=False,
            reason="attended_posting_unavailable",
            message="No attended department/programme options are available for this date.",
            reporting_period_id=period["id"],
            posting_code=assigned_posting_code,
            posting_label=posting_label,
            r_year=context["r_year"],
            attended_posting_options=attended_posting_options,
        )
    raw_options = await _teaching_options_for_context(
        db,
        posting_code=selected_attended_posting["posting_code"],
        programme_code=resident["programme_code"],
        r_year=context["r_year"],
        reporting_period_id=period["id"],
    )
    options = [
        {
            "teaching_name": row["teaching_name"],
            "keyword": row["keyword"],
            "session_type": row.get("session_type"),
            "session_type_name": row.get("session_type_name") or row.get("session_type"),
            "session_type_id": row.get("session_type_id"),
            "duration_hours": row.get("duration_hours"),
            "posting_code": selected_attended_posting["posting_code"],
            "posting_label": selected_attended_posting["label"],
            "reporting_period_id": str(period["id"]),
            "r_year": context["r_year"],
            "is_tracked": bool(row.get("is_tracked")),
            "is_global": bool(row.get("is_global")),
        }
        for row in raw_options
    ]
    return _adhoc_options_response(
        teaching_date=teaching_date,
        available=bool(options),
        reason=None if options else "no_catalogue_options",
        message=None if options else "No teaching options are available for this posting and date.",
        reporting_period_id=period["id"],
        posting_code=assigned_posting_code,
        posting_label=posting_label,
        r_year=context["r_year"],
        attended_posting_options=attended_posting_options,
        selected_attended_posting=selected_attended_posting,
        options=options,
    )


async def list_external_adhoc_teaching_options(
    db: AsyncSession,
    *,
    external_resident_id: UUID,
    teaching_date: date,
    attended_posting_code: str | None = None,
) -> dict[str, Any]:
    await _external_resident(db, external_resident_id)
    period = await _active_reporting_period(db, relevant_date=teaching_date)
    if period is None:
        return _adhoc_options_response(
            teaching_date=teaching_date,
            available=False,
            reason="active_reporting_period_unavailable",
            message="No active reporting period is available for this teaching date.",
        )
    await _ensure_not_public_holiday(db, teaching_date)
    posting_context = await _external_posting_context_for_date(
        db,
        external_resident_id=external_resident_id,
        on_date=teaching_date,
    )
    if posting_context is None:
        return _adhoc_options_response(
            teaching_date=teaching_date,
            available=False,
            reason="posting_unavailable",
            message="No Non-NHG posting schedule row is available for the selected teaching date.",
        )

    posting_code = posting_context["posting_code"]
    posting_label = await _posting_display_label(db, posting_code)
    attended_posting_options = await _attended_posting_options_for_external(
        db,
        reporting_period_id=period["id"],
    )
    selected_attended_posting = _select_attended_posting(
        attended_posting_options,
        requested_posting_code=attended_posting_code,
        default_posting_code=posting_code,
    )
    if selected_attended_posting is None:
        return _adhoc_options_response(
            teaching_date=teaching_date,
            available=False,
            reason="attended_posting_unavailable",
            message="No attended department/programme options are available for this date.",
            posting_code=posting_code,
            posting_label=posting_label,
            attended_posting_options=attended_posting_options,
        )
    raw_options = await _teaching_options_for_posting(
        db,
        posting_code=selected_attended_posting["posting_code"],
        reporting_period_id=period["id"],
    )
    options = [
        {
            "teaching_name": row["teaching_name"],
            "keyword": row["keyword"],
            "session_type": row.get("session_type"),
            "session_type_name": row.get("session_type_name") or row.get("session_type"),
            "session_type_id": row.get("session_type_id"),
            "duration_hours": row.get("duration_hours"),
            "posting_code": selected_attended_posting["posting_code"],
            "posting_label": selected_attended_posting["label"],
            "reporting_period_id": str(period["id"]),
            "r_year": None,
            "is_tracked": bool(row.get("is_tracked")),
            "is_global": bool(row.get("is_global")),
        }
        for row in raw_options
    ]
    return _adhoc_options_response(
        teaching_date=teaching_date,
        available=bool(options),
        reason=None if options else "no_catalogue_options",
        message=None if options else "No teaching options are available for this posting and date.",
        posting_code=posting_code,
        posting_label=posting_label,
        attended_posting_options=attended_posting_options,
        selected_attended_posting=selected_attended_posting,
        options=options,
    )


async def _get_event(db: AsyncSession, event_id: UUID) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT
                id,
                posting_code,
                created_for_programme_code,
                teaching_name,
                details_of_session,
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


async def _posting_capabilities(
    db: AsyncSession,
    *,
    posting_codes: set[str],
) -> dict[str, bool]:
    if not posting_codes:
        return {}
    result = await db.execute(
        text(
            """
            SELECT code, supports_secretary_events
            FROM posting_codes
            WHERE code = ANY(:posting_codes)
            """
        ),
        {"posting_codes": sorted(posting_codes)},
    )
    return {
        str(row["code"]): bool(row["supports_secretary_events"])
        for row in result.mappings().all()
    }


async def _events_for_postings(
    db: AsyncSession,
    *,
    resident_id: UUID,
    programme_code: str,
    posting_codes: set[str],
    today: date,
    period_start: date,
    period_end: date,
    date_from: date | None,
    date_to: date | None,
    teaching_name: str | None = None,
) -> list[dict[str, Any]]:
    if not posting_codes:
        return []
    params: dict[str, Any] = {
        "resident_id": str(resident_id),
        "posting_codes": sorted(posting_codes),
        "programme_code": programme_code,
        "today": today,
        "period_start": period_start,
        "period_end": period_end,
    }
    where = [
        "posting_code = ANY(:posting_codes)",
        "event_date <= :today",
        "event_date >= :period_start",
        "event_date <= :period_end",
        "(created_by_role IN ('secretary', 'programme_pc') OR created_by_role IS NULL)",
        "(created_for_programme_code IS NULL OR created_for_programme_code = :programme_code)",
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
    if teaching_name:
        params["teaching_name"] = teaching_name.strip()
        where.append("teaching_name = :teaching_name")

    result = await db.execute(
        text(
            f"""
            SELECT
                id,
                posting_code,
                created_for_programme_code,
                teaching_name,
                details_of_session,
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
    teaching_name: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "external_resident_id": str(external_resident_id),
        "posting_code": posting_code,
        "today": today,
    }
    where = [
        "posting_code = :posting_code",
        "event_date <= :today",
    ]
    if date_from is not None:
        params["date_from"] = date_from
        where.append("event_date >= :date_from")
    if date_to is not None:
        params["date_to"] = date_to
        where.append("event_date <= :date_to")
    if teaching_name:
        params["teaching_name"] = teaching_name.strip()
        where.append("teaching_name = :teaching_name")

    result = await db.execute(
        text(
            f"""
            SELECT
                id,
                posting_code,
                created_for_programme_code,
                teaching_name,
                details_of_session,
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
                updated_at,
                EXISTS (
                    SELECT 1
                    FROM external_attendance_records ear
                    WHERE ear.external_resident_id = :external_resident_id
                      AND ear.teaching_event_id = teaching_events.id
                      AND ear.status = 'submitted'
                ) AS already_attended
            FROM teaching_events
            WHERE {' AND '.join(where)}
            ORDER BY event_date ASC, start_time ASC, teaching_name ASC
            """
        ),
        params,
    )
    return [dict(row) for row in result.mappings().all()]


def _matching_context_for_event(
    contexts: list[dict[str, Any]],
    *,
    posting_code: str,
    event_date: date,
) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in contexts
            if row["posting_code"] == posting_code
            and row["start_date"] <= event_date
            and (row.get("end_date") is None or event_date <= row["end_date"])
        ),
        None,
    )


def _external_event_ineligibility_reason(
    *,
    event: dict[str, Any],
    posting_contexts: list[dict[str, Any]],
    posting_capabilities: dict[str, bool],
    today: date,
    already_attended: bool,
) -> ExternalEventIneligibilityReason | None:
    if event["event_date"] > today:
        return "future_event"
    if not posting_contexts:
        return "posting_unavailable"
    if _matching_context_for_event(
        posting_contexts,
        posting_code=event["posting_code"],
        event_date=event["event_date"],
    ) is None:
        return "posting_mismatch"
    if (
        event.get("created_by_role") != "secretary"
        or event.get("created_for_programme_code") is not None
    ):
        return "event_scope"
    if not posting_capabilities.get(event["posting_code"], False):
        return "secretary_events_not_supported"
    if already_attended:
        return "already_attended"
    return None


def _external_event_ineligibility_error(
    reason: ExternalEventIneligibilityReason,
) -> ApiError:
    if reason == "already_attended":
        return ApiError(
            status_code=409,
            detail="Attendance already submitted for this teaching event",
            error_code=ErrorCode.CONFLICT.value,
        )
    detail_by_reason = {
        "future_event": "Future teaching events cannot be submitted",
        "posting_unavailable": "No Non-NHG Resident posting is available for the teaching date",
        "posting_mismatch": "Teaching event is outside the resident posting scope",
        "event_scope": "Teaching event is outside the Non-NHG Resident scope",
        "secretary_events_not_supported": (
            "Secretary-created events are not supported for this posting"
        ),
    }
    return ApiError(
        status_code=422,
        detail=detail_by_reason[reason],
        error_code=ErrorCode.VALIDATION_FAILED.value,
    )


async def _external_posting_contexts(
    db: AsyncSession,
    *,
    external_resident_id: UUID,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT
                external_resident_id,
                posting_code,
                start_date,
                end_date,
                is_current
            FROM external_resident_postings
            WHERE external_resident_id = :external_resident_id
              AND start_date <= :end_date
              AND (end_date IS NULL OR end_date >= :start_date)
            ORDER BY start_date ASC, posting_code ASC
            """
        ),
        {
            "external_resident_id": str(external_resident_id),
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    return [dict(row) for row in result.mappings().all()]


async def _external_posting_context_for_date(
    db: AsyncSession,
    *,
    external_resident_id: UUID,
    on_date: date,
) -> dict[str, Any] | None:
    contexts = await _external_posting_contexts(
        db,
        external_resident_id=external_resident_id,
        start_date=on_date,
        end_date=on_date,
    )
    return contexts[0] if contexts else None


def _normalise_optional_filter(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _effective_event_range(
    *,
    period_start: date,
    period_end: date,
    today: date,
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date]:
    start = max(date_from or period_start, period_start)
    end = min(date_to or today, today, period_end)
    return start, end


def _context_overlaps_range(context: dict[str, Any], *, start: date, end: date) -> bool:
    context_end = context.get("end_date") or date.max
    return context["start_date"] <= end and context_end >= start


def _native_visibility_contexts(
    contexts: list[dict[str, Any]],
    *,
    native_posting_code: str | None,
) -> list[dict[str, Any]]:
    if not native_posting_code:
        return []
    return [
        {
            **context,
            "posting_code": native_posting_code,
        }
        for context in contexts
        if context.get("posting_code")
    ]


def _posting_filter_options(
    contexts: list[dict[str, Any]],
    *,
    start: date,
    end: date,
) -> list[dict[str, str]]:
    posting_codes = {
        row["posting_code"]
        for row in contexts
        if row.get("posting_code") and _context_overlaps_range(row, start=start, end=end)
    }
    return [
        {"posting_code": posting_code, "label": posting_code}
        for posting_code in sorted(posting_codes)
    ]


async def list_available_events(
    db: AsyncSession,
    *,
    role: str = "resident",
    resident_id: UUID | None = None,
    external_resident_id: UUID | None = None,
    today: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    teaching_name: str | None = None,
    posting_code: str | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    teaching_name = _normalise_optional_filter(teaching_name)
    posting_code = _normalise_optional_filter(posting_code)
    if role == "external_resident":
        if external_resident_id is None:
            raise ApiError(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )
        await _external_resident(db, external_resident_id)
        period = await _active_reporting_period(
            db,
            relevant_date=date_to or today,
            status_as_of_date=today,
        )
        if period is None:
            return {
                "events": [],
                "reason": "active_reporting_period_unavailable",
            }
        range_start, range_end = _effective_event_range(
            period_start=period["start_date"],
            period_end=period["end_date"],
            today=today,
            date_from=date_from,
            date_to=date_to,
        )
        if range_start > range_end:
            return {"events": []}
        contexts = await _external_posting_contexts(
            db,
            external_resident_id=external_resident_id,
            start_date=range_start,
            end_date=range_end,
        )
        if not contexts:
            return {"events": [], "reason": "posting_schedule_unavailable"}

        eligible_posting_codes = {
            row["posting_code"]
            for row in contexts
            if row.get("posting_code")
            and _context_overlaps_range(row, start=range_start, end=range_end)
        }
        if posting_code is not None:
            eligible_posting_codes = (
                {posting_code} if posting_code in eligible_posting_codes else set()
            )
        posting_capabilities = await _posting_capabilities(
            db,
            posting_codes=eligible_posting_codes,
        )
        supported_posting_codes = {
            code for code, supports in posting_capabilities.items() if supports
        }
        if not supported_posting_codes:
            return {"events": [], "reason": "secretary_events_not_supported"}
        raw_events: list[dict[str, Any]] = []
        for external_posting_code in sorted(supported_posting_codes):
            raw_events.extend(
                await _events_for_external_posting(
                    db,
                    external_resident_id=external_resident_id,
                    posting_code=external_posting_code,
                    today=today,
                    date_from=range_start,
                    date_to=range_end,
                    teaching_name=teaching_name,
                )
            )
        deduped_events: dict[str, dict[str, Any]] = {}
        for event in raw_events:
            reason = _external_event_ineligibility_reason(
                event=event,
                posting_contexts=contexts,
                posting_capabilities=posting_capabilities,
                today=today,
                already_attended=bool(event.get("already_attended")),
            )
            if reason is None:
                deduped_events[str(event["id"])] = event
        events = sorted(
            deduped_events.values(),
            key=lambda row: (row["event_date"], row["start_time"], row["teaching_name"]),
        )
        return {"events": [_event_row(row) for row in events]}

    if resident_id is None:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
    resident = await _resident(db, resident_id)
    period = await _active_reporting_period(
        db,
        relevant_date=today,
        status_as_of_date=today,
    )
    if period is None:
        return {
            "events": [],
            "reason": "active_reporting_period_unavailable",
            "ad_hoc_allowed": False,
            "message": "No active reporting period is available yet.",
            "posting_capabilities": [],
        }

    contexts, visibility_contexts = await _resident_visibility_contexts(
        db,
        resident_id=resident_id,
        resident=resident,
        reporting_period_id=period["id"],
    )
    if not contexts:
        return {
            "events": [],
            "reason": "posting_schedule_unavailable",
            "ad_hoc_allowed": False,
            "message": (
                "Your posting schedule is not available yet. "
                "Please contact your programme coordinator after RDB upload."
            ),
            "posting_capabilities": [],
        }

    range_start, range_end = _effective_event_range(
        period_start=period["start_date"],
        period_end=period["end_date"],
        today=today,
        date_from=date_from,
        date_to=date_to,
    )

    eligible_posting_codes = {
        row["posting_code"]
        for row in visibility_contexts
        if row.get("posting_code") and _context_overlaps_range(row, start=range_start, end=range_end)
    }
    posting_codes = set(eligible_posting_codes)
    if posting_code is not None:
        posting_codes = {posting_code} if posting_code in eligible_posting_codes else set()
    posting_capabilities = await _posting_capabilities(db, posting_codes=eligible_posting_codes)
    raw_events = await _events_for_postings(
        db,
        resident_id=resident_id,
        programme_code=resident["programme_code"],
        posting_codes=posting_codes,
        today=today,
        period_start=period["start_date"],
        period_end=period["end_date"],
        date_from=date_from,
        date_to=date_to,
        teaching_name=teaching_name,
    )

    events: list[dict[str, Any]] = []
    for event in raw_events:
        owner = event.get("created_for_programme_code")
        if owner is not None and owner != resident["programme_code"]:
            continue
        context = _matching_context_for_event(
            visibility_contexts,
            posting_code=event["posting_code"],
            event_date=event["event_date"],
        )
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
            event_row = _available_event_row(event, resolved=resolved)
            if all(existing["id"] != event_row["id"] for existing in events):
                events.append(event_row)

    option_raw_events = await _events_for_postings(
        db,
        resident_id=resident_id,
        programme_code=resident["programme_code"],
        posting_codes=posting_codes or eligible_posting_codes,
        today=today,
        period_start=period["start_date"],
        period_end=period["end_date"],
        date_from=date_from,
        date_to=date_to,
        teaching_name=None,
    )
    option_names: set[str] = set()
    for event in option_raw_events:
        context = _matching_context_for_event(
            visibility_contexts,
            posting_code=event["posting_code"],
            event_date=event["event_date"],
        )
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
            option_names.add(event["teaching_name"])
    filter_options = {
        "date_from": range_start.isoformat(),
        "date_to": range_end.isoformat(),
        "posting_options": _posting_filter_options(
            visibility_contexts,
            start=range_start,
            end=range_end,
        ),
        "teaching_name_options": [
            {"teaching_name": name, "label": name}
            for name in sorted(option_names, key=str.casefold)
        ],
    }

    capabilities = [
        {
            "posting_code": posting_code,
            "supports_secretary_events": posting_capabilities.get(posting_code, False),
        }
        for posting_code in sorted(eligible_posting_codes)
    ]
    if events:
        return {
            "events": events,
            "reason": None,
            "ad_hoc_allowed": True,
            "message": None,
            "posting_capabilities": capabilities,
            "filter_options": filter_options,
        }

    has_secretary_support_hint = any(item["supports_secretary_events"] for item in capabilities)
    return {
        "events": [],
        "reason": "no_eligible_scheduled_events",
        "ad_hoc_allowed": True,
        "message": (
            "No scheduled teaching events available. You can submit ad-hoc teaching."
            if has_secretary_support_hint
            else (
                "No eligible scheduled teaching events are currently available for your posting. "
                "You can submit ad-hoc teaching."
            )
        ),
        "posting_capabilities": capabilities,
        "filter_options": filter_options,
    }


async def _attendance_for_event(
    db: AsyncSession,
    *,
    resident_id: UUID,
    event_id: UUID | str,
) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT id, resident_id, teaching_event_id, status, posting_code, submitted_at
            FROM attendance_records
            WHERE resident_id = :resident_id
              AND teaching_event_id = :event_id
            LIMIT 1
            """
        ),
        {"resident_id": str(resident_id), "event_id": str(event_id)},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row is not None else None


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
            RETURNING id, resident_id, teaching_event_id, status, posting_code, submitted_at
            """
        ),
        {
            "resident_id": str(resident_id),
            "event_id": str(event_id),
            "posting_code": posting_code,
        },
    )
    return _attendance_row(dict(result.mappings().one()))


async def _restore_removed_attendance(
    db: AsyncSession,
    *,
    attendance_id: UUID | str,
    resident_id: UUID,
    posting_code: str,
) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            UPDATE attendance_records
            SET status = 'submitted',
                submitted_at = now(),
                posting_code = :posting_code
            WHERE id = :attendance_id
              AND resident_id = :resident_id
              AND status = 'removed'
            RETURNING id, resident_id, teaching_event_id, status, posting_code, submitted_at
            """
        ),
        {
            "attendance_id": str(attendance_id),
            "resident_id": str(resident_id),
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
    reporting_period_id: UUID | str,
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
              AND tnc.reporting_period_id = :reporting_period_id
            ORDER BY tnc.duration_hours DESC, st.name ASC
            """
        ),
        {
            "posting_code": posting_code,
            "teaching_name": teaching_name,
            "reporting_period_id": str(reporting_period_id),
        },
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
        await _external_resident(db, external_resident_id)
        submitted = 0
        submitted_events: list[dict[str, Any]] = []
        weekend_warning_count = 0
        touched_postings: set[str] = set()
        touched_period_ids: set[str] = set()
        for event_id in event_ids:
            event = await _get_event(db, event_id)
            period = await _active_reporting_period(
                db,
                relevant_date=event["event_date"],
                status_as_of_date=today,
            )
            if period is None:
                raise ApiError(
                    status_code=422,
                    detail="No active reporting period is available for the teaching event date",
                    error_code=ErrorCode.VALIDATION_FAILED.value,
                )
            posting_contexts = await _external_posting_contexts(
                db,
                external_resident_id=external_resident_id,
                start_date=event["event_date"],
                end_date=event["event_date"],
            )
            posting_capabilities = await _posting_capabilities(
                db,
                posting_codes={
                    context["posting_code"]
                    for context in posting_contexts
                    if context.get("posting_code")
                },
            )
            already_attended = await _duplicate_external_attendance_exists(
                db,
                external_resident_id=external_resident_id,
                event_id=event_id,
            )
            reason = _external_event_ineligibility_reason(
                event=event,
                posting_contexts=posting_contexts,
                posting_capabilities=posting_capabilities,
                today=today,
                already_attended=already_attended,
            )
            if reason is not None:
                raise _external_event_ineligibility_error(reason)
            await _insert_external_attendance(
                db,
                external_resident_id=external_resident_id,
                event_id=event_id,
                posting_code=event["posting_code"],
            )
            submitted += 1
            submitted_events.append(_event_row(event))
            touched_postings.add(event["posting_code"])
            touched_period_ids.add(str(period["id"]))
            accepted = await _weekend_is_accepted(
                db,
                event=event,
                programme_code="",
                session_type_id=event.get("session_type_id"),
            )
            if not accepted:
                weekend_warning_count += 1

        await db.commit()
        for reporting_period_id in touched_period_ids:
            invalidate_resident_caches(
                external_resident_id=external_resident_id,
                posting_codes=touched_postings,
                reporting_period_id=reporting_period_id,
            )
        return {
            "submitted": submitted,
            "submitted_events": submitted_events,
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

    submitted = 0
    submitted_events: list[dict[str, Any]] = []
    weekend_warning_count = 0
    touched_postings: set[str] = set()
    touched_period_ids: set[str] = set()
    for event_id in event_ids:
        event = await _get_event(db, event_id)
        if event["event_date"] > today:
            raise ApiError(
                status_code=422,
                detail="Future teaching events cannot be submitted",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        period = await _active_reporting_period(
            db,
            relevant_date=event["event_date"],
            status_as_of_date=today,
        )
        if period is None:
            raise ApiError(
                status_code=422,
                detail="No active reporting period is available for the teaching event date",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        if event.get("created_by_role") not in {"secretary", "programme_pc", None}:
            raise ApiError(
                status_code=422,
                detail="Only scheduled teaching events can be submitted from this endpoint",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        owner = event.get("created_for_programme_code")
        if owner is not None and owner != resident["programme_code"]:
            raise ApiError(
                status_code=422,
                detail="Teaching event is outside the resident programme scope",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        _, visibility_contexts = await _resident_visibility_contexts(
            db,
            resident_id=resident_id,
            resident=resident,
            reporting_period_id=period["id"],
            on_date=event["event_date"],
        )
        context = _matching_context_for_event(
            visibility_contexts,
            posting_code=event["posting_code"],
            event_date=event["event_date"],
        )
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
        existing_attendance = await _attendance_for_event(
            db,
            resident_id=resident_id,
            event_id=event_id,
        )
        if existing_attendance and existing_attendance["status"] == "submitted":
            raise ApiError(
                status_code=409,
                detail="Attendance already submitted for this teaching event",
                error_code=ErrorCode.CONFLICT.value,
            )
        if existing_attendance and existing_attendance["status"] == "removed":
            await _restore_removed_attendance(
                db,
                attendance_id=existing_attendance["id"],
                resident_id=resident_id,
                posting_code=event["posting_code"],
            )
        elif existing_attendance:
            raise ApiError(
                status_code=409,
                detail="Attendance already exists for this teaching event",
                error_code=ErrorCode.CONFLICT.value,
            )
        else:
            await _insert_attendance(
                db,
                resident_id=resident_id,
                event_id=event_id,
                posting_code=event["posting_code"],
            )
        submitted += 1
        submitted_events.append(_available_event_row(event, resolved=resolved))
        touched_postings.add(event["posting_code"])
        touched_period_ids.add(str(period["id"]))
        accepted = await _weekend_is_accepted(
            db,
            event=event,
            programme_code=resident["programme_code"],
            session_type_id=resolved.get("session_type_id"),
        )
        if not accepted:
            weekend_warning_count += 1

    await db.commit()
    for reporting_period_id in touched_period_ids:
        invalidate_resident_caches(
            resident_id=resident_id,
            posting_codes=touched_postings,
            programme_code=resident["programme_code"],
            reporting_period_id=reporting_period_id,
        )
    return {
        "submitted": submitted,
        "submitted_events": submitted_events,
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
    attended_posting_code: str | None = None,
    details_of_session: str | None = None,
) -> dict[str, Any]:
    if role == "external_resident":
        if external_resident_id is None:
            raise ApiError(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )
        await _external_resident(db, external_resident_id)
        period = await _active_reporting_period(db, relevant_date=event_date)
        if period is None:
            raise ApiError(
                status_code=422,
                detail="No active reporting period is available",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        await _ensure_not_public_holiday(db, event_date)
        posting_context = await _external_posting_context_for_date(
            db,
            external_resident_id=external_resident_id,
            on_date=event_date,
        )
        if posting_context is None:
            raise ApiError(
                status_code=422,
                detail="No Non-NHG Resident posting is available for the submitted teaching date",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        posting_code = posting_context["posting_code"]
        attended_posting_options = await _attended_posting_options_for_external(
            db,
            reporting_period_id=period["id"],
        )
        selected_attended_posting = _select_attended_posting(
            attended_posting_options,
            requested_posting_code=attended_posting_code,
            default_posting_code=posting_code,
        )
        if selected_attended_posting is None:
            raise ApiError(
                status_code=422,
                detail="No attended department/programme options are available for this teaching date",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        resolved = await _resolve_teaching_name_for_posting(
            db,
            posting_code=selected_attended_posting["posting_code"],
            teaching_name=teaching_name,
            reporting_period_id=period["id"],
        )
        if resolved is None:
            raise ApiError(
                status_code=422,
                detail="teaching_name must be selected from catalogue-backed ad-hoc teaching options",
                error_code=ErrorCode.VALIDATION_FAILED.value,
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
                    details_of_session,
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
                    :details_of_session,
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
                    details_of_session,
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
                "details_of_session": details_of_session,
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
            include_secretary_events=True,
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
    period = await _active_reporting_period(db, relevant_date=event_date)
    if period is None:
        raise ApiError(
            status_code=422,
            detail="No active reporting period is available",
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
        raise ApiError(
            status_code=422,
            detail="Posting disambiguation is required for this teaching date",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    context = contexts[0]
    attended_posting_options = await _attended_posting_options_for_resident(
        db,
        programme_code=resident["programme_code"],
        r_year=context["r_year"],
        reporting_period_id=period["id"],
    )
    selected_attended_posting = _select_attended_posting(
        attended_posting_options,
        requested_posting_code=attended_posting_code,
        default_posting_code=context["posting_code"],
    )
    if selected_attended_posting is None:
        raise ApiError(
            status_code=422,
            detail="No attended department/programme options are available for this teaching date",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    selected = await _resolve_teaching_name(
        db,
        posting_code=selected_attended_posting["posting_code"],
        programme_code=resident["programme_code"],
        r_year=context["r_year"],
        reporting_period_id=period["id"],
        teaching_name=teaching_name,
    )
    if selected is None:
        raise ApiError(
            status_code=422,
            detail="teaching_name must be selected from catalogue-backed ad-hoc teaching options",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    if selected.get("is_global") or not bool(selected.get("is_tracked")):
        raise ApiError(
            status_code=422,
            detail="teaching_name must be selected from tracked catalogue-backed ad-hoc teaching options",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    resolved = await _resolve_teaching_target(
        db,
        posting_code=context["posting_code"],
        programme_code=resident["programme_code"],
        r_year=context["r_year"],
        reporting_period_id=period["id"],
        session_type=ADHOC_COMPLIANCE_TEACHING_NAME,
    )
    if resolved is None or resolved.get("is_global") or not bool(resolved.get("is_tracked")):
        raise ApiError(
            status_code=422,
            detail=(
                f"{ADHOC_COMPLIANCE_TEACHING_NAME} is unavailable for countable "
                "ad-hoc teaching on this resident posting"
            ),
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
                details_of_session,
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
                :details_of_session,
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
                details_of_session,
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
            "teaching_name": ADHOC_COMPLIANCE_TEACHING_NAME,
            "details_of_session": details_of_session,
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
    invalidate_resident_caches(
        resident_id=resident_id,
        posting_codes={event["posting_code"]},
        programme_code=resident["programme_code"],
        reporting_period_id=period["id"],
        include_secretary_events=True,
    )
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
) -> dict[str, Any]:
    existing_result = await db.execute(
        text(
            """
            SELECT id, resident_id, teaching_event_id, status, posting_code, submitted_at
            FROM attendance_records
            WHERE id = :attendance_id
              AND resident_id = :resident_id
            """
        ),
        {"attendance_id": str(attendance_id), "resident_id": str(resident_id)},
    )
    existing = existing_result.mappings().one_or_none()
    if existing is None:
        raise ApiError(
            status_code=404,
            detail="Attendance record not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    if existing["status"] == "removed":
        return {
            "attendance_id": existing["id"],
            "status": "removed",
            "removed_count": 0,
        }

    result = await db.execute(
        text(
            """
            UPDATE attendance_records
            SET status = 'removed'
            WHERE id = :attendance_id
              AND resident_id = :resident_id
              AND status = 'submitted'
            RETURNING id, resident_id, teaching_event_id, status, posting_code, submitted_at
            """
        ),
        {"attendance_id": str(attendance_id), "resident_id": str(resident_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise ApiError(
            status_code=409,
            detail="Attendance record cannot be removed from its current status",
            error_code=ErrorCode.CONFLICT.value,
        )
    await db.commit()
    invalidate_resident_caches(
        resident_id=resident_id,
        posting_codes={row["posting_code"]} if row.get("posting_code") else set(),
    )
    return {
        "attendance_id": row["id"],
        "status": row["status"],
        "removed_count": 1,
    }


async def remove_external_attendance(
    db: AsyncSession,
    *,
    external_resident_id: UUID,
    attendance_id: UUID,
) -> dict[str, Any]:
    existing_result = await db.execute(
        text(
            """
            SELECT id, external_resident_id, teaching_event_id, status, posting_code, submitted_at
            FROM external_attendance_records
            WHERE id = :attendance_id
              AND external_resident_id = :external_resident_id
            """
        ),
        {
            "attendance_id": str(attendance_id),
            "external_resident_id": str(external_resident_id),
        },
    )
    existing = existing_result.mappings().one_or_none()
    if existing is None:
        raise ApiError(
            status_code=404,
            detail="Attendance record not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    if existing["status"] == "removed":
        return {
            "attendance_id": existing["id"],
            "status": "removed",
            "removed_count": 0,
        }

    result = await db.execute(
        text(
            """
            UPDATE external_attendance_records
            SET status = 'removed'
            WHERE id = :attendance_id
              AND external_resident_id = :external_resident_id
              AND status = 'submitted'
            RETURNING id, external_resident_id, teaching_event_id, status, posting_code, submitted_at
            """
        ),
        {
            "attendance_id": str(attendance_id),
            "external_resident_id": str(external_resident_id),
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise ApiError(
            status_code=409,
            detail="Attendance record cannot be removed from its current status",
            error_code=ErrorCode.CONFLICT.value,
        )
    await db.commit()
    invalidate_resident_caches(
        external_resident_id=external_resident_id,
        posting_codes={row["posting_code"]} if row.get("posting_code") else set(),
        include_secretary_events=True,
    )
    return {
        "attendance_id": row["id"],
        "status": row["status"],
        "removed_count": 1,
    }


async def list_attendance_records(
    db: AsyncSession,
    *,
    role: str = "resident",
    resident_id: UUID | None = None,
    external_resident_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    posting_code: str | None = None,
    teaching_name: str | None = None,
    source: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    include_removed: bool = True,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    where: list[str] = []
    source = _normalise_optional_filter(source)
    status = _normalise_optional_filter(status)
    posting_code = _normalise_optional_filter(posting_code)
    teaching_name = _normalise_optional_filter(teaching_name)
    if status and status not in {"submitted", "removed"}:
        raise ApiError(
            status_code=422,
            detail="status must be submitted or removed",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    if source and source not in {"scheduled", "adhoc"}:
        raise ApiError(
            status_code=422,
            detail="source must be scheduled or adhoc",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
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
    if status:
        params["status"] = status
        where.append("attendance.status = :status")
    elif include_removed:
        where.append("attendance.status IN ('submitted', 'removed')")
    else:
        where.append("attendance.status != 'removed'")
    if date_from is not None:
        params["date_from"] = date_from
        where.append("events.event_date >= :date_from")
    if date_to is not None:
        params["date_to"] = date_to
        where.append("events.event_date <= :date_to")
    if posting_code:
        params["posting_code"] = posting_code
        where.append("events.posting_code = :posting_code")
    if teaching_name:
        params["teaching_name"] = teaching_name
        where.append("events.teaching_name = :teaching_name")
    if source:
        params["is_adhoc"] = source == "adhoc"
        where.append("events.is_adhoc = :is_adhoc")
    params["limit"] = max(1, min(limit, 500))
    params["offset"] = max(0, offset)

    result = await db.execute(
        text(
            f"""
            SELECT
                attendance.id AS attendance_id,
                attendance.teaching_event_id,
                events.teaching_name,
                events.details_of_session,
                events.is_adhoc,
                CASE WHEN events.is_adhoc THEN 'adhoc' ELSE 'scheduled' END AS source,
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
            ORDER BY events.event_date DESC, events.start_time DESC, attendance.submitted_at DESC, attendance.id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    rows = [dict(row) for row in result.mappings().all()]
    return {
        "attendance": rows,
        "limit": params["limit"],
        "offset": params["offset"],
        "count": len(rows),
    }


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
    return await list_attendance_records(
        db,
        role=role,
        resident_id=resident_id,
        external_resident_id=external_resident_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
        include_removed=False,
    )


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
                "Non-NHG Resident attendance is stored for future export to the home "
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
    period = await _active_reporting_period(db, relevant_date=date.today())
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
