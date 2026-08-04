from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from hashlib import blake2b
from typing import Any, Literal, NoReturn
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.security import log_safe_exception
from app.services import cache_invalidation
from app.services.reporting_period_status import (
    list_effectively_active_reporting_periods,
    resolve_active_reporting_period_for_date,
    resolve_reporting_period_for_date,
)
from app.services.teaching_event_locks import acquire_teaching_event_locks


logger = logging.getLogger(__name__)

ACTIVE_POSTING_STATUSES = {"active", "loa_working"}
WEEKEND_WARNING = (
    "{count} session(s) submitted on a weekend will not count toward your PTT compliance "
    "as they do not meet the weekend exception rules for your programme."
)
ADHOC_COMPLIANCE_TEACHING_NAME = "Department/Programme Teaching [1h]"
ADHOC_DURATION_HOURS = Decimal("1.00")
ExternalEventIneligibilityReason = Literal[
    "future_event",
    "posting_unavailable",
    "posting_mismatch",
    "event_scope",
    "secretary_events_not_supported",
    "already_attended",
    "overlapping_attendance",
]


def _event_row(
    row: dict[str, Any],
    *,
    reporting_period: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
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
    if reporting_period is not None:
        event["reporting_period_id"] = reporting_period["id"]
        event["reporting_period_label"] = reporting_period["label"]
    return event


def _available_event_row(
    event: dict[str, Any],
    *,
    resolved: dict[str, Any],
    reporting_period: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
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
    if reporting_period is not None:
        row["reporting_period_id"] = reporting_period["id"]
        row["reporting_period_label"] = reporting_period["label"]
    return row


def _resolve_scheduled_event_source(
    event: dict[str, Any],
    *,
    reporting_period_id: UUID | str,
    programme_code: str | None,
) -> dict[str, Any] | None:
    """Project a scheduled event from persisted source evidence only.

    Explicit pool identities retain their source programme and reporting-period
    scope.  Global identities remain programme-neutral.  A pre-Phase-F row
    with neither identity is deliberately treated as legacy: its immutable
    event ownership, posting, timing, and snapshot are used by callers, never
    its display text.
    """

    teaching_name_id = event.get("teaching_name_id")
    global_session_type_id = event.get("global_session_type_id")
    if teaching_name_id is not None and global_session_type_id is not None:
        return None

    if teaching_name_id is not None:
        source_programme_code = event.get("source_programme_code")
        source_reporting_period_id = event.get("source_reporting_period_id")
        if (
            source_programme_code is None
            or source_reporting_period_id is None
            or programme_code is None
            or str(source_reporting_period_id) != str(reporting_period_id)
            or str(source_programme_code) != str(programme_code)
        ):
            return None
        return {
            "kind": "teaching_name",
            "session_type": event.get("session_type"),
            "duration_hours": event.get("duration_hours"),
            "is_global": False,
        }

    if global_session_type_id is not None:
        return {
            "kind": "global_session_type",
            "session_type": event.get("session_type") or event["teaching_name"],
            "duration_hours": event.get("duration_hours"),
            "is_global": True,
        }

    return {
        "kind": "legacy",
        "session_type": event.get("session_type"),
        # Legacy rows retain the persisted session type solely for the existing
        # weekend-exception check.  It is not source classification and must
        # never be recovered from display text or catalogue data.
        "session_type_id": event.get("session_type_id"),
        "duration_hours": event.get("duration_hours"),
        "is_global": False,
    }


def _submission_period_row(period: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": period["id"],
        "label": period["label"],
        "start_date": period["start_date"],
        "end_date": period["end_date"],
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
    try:
        cache_invalidation.invalidate_after_resident_attendance_mutation(
            resident_id=resident_id,
            external_resident_id=external_resident_id,
            posting_codes=posting_codes,
            programme_code=programme_code,
            reporting_period_id=reporting_period_id,
            include_secretary_events=include_secretary_events,
        )
    except Exception as exc:
        log_safe_exception(
            logger,
            "resident_attendance_cache_invalidation_failed",
            exc,
            category="cache_invalidation",
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


async def list_submission_periods(
    db: AsyncSession,
    *,
    role: str = "resident",
    resident_id: UUID | None = None,
    external_resident_id: UUID | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """List operationally active periods for resident scheduled-event discovery."""

    today = today or date.today()
    if role == "external_resident":
        if external_resident_id is None:
            raise ApiError(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )
        await _external_resident(db, external_resident_id)
    else:
        if resident_id is None:
            raise ApiError(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )
        await _resident(db, resident_id)

    periods = await list_effectively_active_reporting_periods(
        db,
        status_as_of_date=today,
    )
    return {"periods": [_submission_period_row(period) for period in periods]}


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


def _fixed_adhoc_option(
    *,
    posting_code: str,
    posting_label: str,
    reporting_period_id: UUID | str,
    r_year: str | None,
) -> dict[str, Any]:
    return {
        "teaching_name": ADHOC_COMPLIANCE_TEACHING_NAME,
        "keyword": ADHOC_COMPLIANCE_TEACHING_NAME,
        "session_type": ADHOC_COMPLIANCE_TEACHING_NAME,
        "session_type_name": ADHOC_COMPLIANCE_TEACHING_NAME,
        "session_type_id": None,
        "duration_hours": ADHOC_DURATION_HOURS,
        "posting_code": posting_code,
        "posting_label": posting_label,
        "reporting_period_id": str(reporting_period_id),
        "r_year": r_year,
        "is_global": False,
    }


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
    await _resident(db, resident_id)
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
    attended_posting_options = [
        {
            "posting_code": assigned_posting_code,
            "label": posting_label,
        }
    ]
    selected_attended_posting = _select_attended_posting(
        attended_posting_options,
        requested_posting_code=attended_posting_code,
        default_posting_code=assigned_posting_code,
    )
    if selected_attended_posting is None:
        raise RuntimeError("Assigned posting option invariant was not established")
    options = [
        _fixed_adhoc_option(
            posting_code=selected_attended_posting["posting_code"],
            posting_label=selected_attended_posting["label"],
            reporting_period_id=period["id"],
            r_year=context["r_year"],
        )
    ]
    return _adhoc_options_response(
        teaching_date=teaching_date,
        available=True,
        reason=None,
        message=None,
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
    attended_posting_options = [
        {
            "posting_code": posting_code,
            "label": posting_label,
        }
    ]
    selected_attended_posting = _select_attended_posting(
        attended_posting_options,
        requested_posting_code=attended_posting_code,
        default_posting_code=posting_code,
    )
    if selected_attended_posting is None:
        raise RuntimeError("Assigned posting option invariant was not established")
    options = [
        _fixed_adhoc_option(
            posting_code=selected_attended_posting["posting_code"],
            posting_label=selected_attended_posting["label"],
            reporting_period_id=period["id"],
            r_year=None,
        )
    ]
    return _adhoc_options_response(
        teaching_date=teaching_date,
        available=True,
        reason=None,
        message=None,
        reporting_period_id=period["id"],
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
                teaching_events.id,
                teaching_events.posting_code,
                teaching_events.created_for_programme_code,
                teaching_events.teaching_name,
                teaching_events.details_of_session,
                teaching_events.event_date,
                teaching_events.start_time,
                teaching_events.end_time,
                teaching_events.duration_hours,
                teaching_events.session_type_id,
                teaching_events.teaching_name_id,
                teaching_events.global_session_type_id,
                source_scope.reporting_period_id AS source_reporting_period_id,
                source_scope.programme_code AS source_programme_code,
                session_type.name AS session_type,
                teaching_events.series_id,
                teaching_events.cme_points_awarded,
                teaching_events.smc_event_code,
                teaching_events.is_adhoc,
                teaching_events.created_by_role,
                teaching_events.created_at,
                teaching_events.updated_at
            FROM teaching_events
            LEFT JOIN LATERAL mata_rls.scheduled_event_source_scope(
                teaching_events.id
            ) AS source_scope ON true
            LEFT JOIN session_types AS session_type
              ON session_type.id = teaching_events.session_type_id
            WHERE teaching_events.id = :event_id
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
                teaching_events.id,
                teaching_events.posting_code,
                teaching_events.created_for_programme_code,
                teaching_events.teaching_name,
                teaching_events.details_of_session,
                teaching_events.event_date,
                teaching_events.start_time,
                teaching_events.end_time,
                teaching_events.duration_hours,
                teaching_events.session_type_id,
                teaching_events.teaching_name_id,
                teaching_events.global_session_type_id,
                source_scope.reporting_period_id AS source_reporting_period_id,
                source_scope.programme_code AS source_programme_code,
                session_type.name AS session_type,
                teaching_events.series_id,
                teaching_events.cme_points_awarded,
                teaching_events.smc_event_code,
                teaching_events.is_adhoc,
                teaching_events.created_by_role,
                teaching_events.created_at,
                teaching_events.updated_at
            FROM teaching_events
            LEFT JOIN LATERAL mata_rls.scheduled_event_source_scope(
                teaching_events.id
            ) AS source_scope ON true
            LEFT JOIN session_types AS session_type
              ON session_type.id = teaching_events.session_type_id
            WHERE {' AND '.join(where)}
            ORDER BY teaching_events.event_date ASC, teaching_events.start_time ASC,
                     teaching_events.teaching_name ASC
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
                teaching_events.id,
                teaching_events.posting_code,
                teaching_events.created_for_programme_code,
                teaching_events.teaching_name,
                teaching_events.details_of_session,
                teaching_events.event_date,
                teaching_events.start_time,
                teaching_events.end_time,
                teaching_events.duration_hours,
                teaching_events.session_type_id,
                teaching_events.teaching_name_id,
                teaching_events.global_session_type_id,
                source_scope.reporting_period_id AS source_reporting_period_id,
                source_scope.programme_code AS source_programme_code,
                session_type.name AS session_type,
                teaching_events.series_id,
                teaching_events.cme_points_awarded,
                teaching_events.smc_event_code,
                teaching_events.is_adhoc,
                teaching_events.created_by_role,
                teaching_events.created_at,
                teaching_events.updated_at,
                EXISTS (
                    SELECT 1
                    FROM external_attendance_records ear
                    WHERE ear.external_resident_id = :external_resident_id
                      AND ear.teaching_event_id = teaching_events.id
                      AND ear.status = 'submitted'
                ) AS already_attended
            FROM teaching_events
            LEFT JOIN LATERAL mata_rls.scheduled_event_source_scope(
                teaching_events.id
            ) AS source_scope ON true
            LEFT JOIN session_types AS session_type
              ON session_type.id = teaching_events.session_type_id
            WHERE {' AND '.join(where)}
            ORDER BY teaching_events.event_date ASC, teaching_events.start_time ASC,
                     teaching_events.teaching_name ASC
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


def _matching_external_contexts_for_date(
    contexts: list[dict[str, Any]],
    *,
    event_date: date,
) -> list[dict[str, Any]]:
    return [
        row
        for row in contexts
        if row["start_date"] <= event_date
        and (row.get("end_date") is None or event_date <= row["end_date"])
    ]


def _external_event_ineligibility_reason(
    *,
    event: dict[str, Any],
    posting_contexts: list[dict[str, Any]],
    posting_capabilities: dict[str, bool],
    reporting_period_id: UUID | str,
    today: date,
    already_attended: bool,
) -> ExternalEventIneligibilityReason | None:
    if event["event_date"] > today:
        return "future_event"
    if not posting_contexts:
        return "posting_unavailable"
    matching_contexts = _matching_external_contexts_for_date(
        posting_contexts,
        event_date=event["event_date"],
    )
    if (
        len(matching_contexts) != 1
        or matching_contexts[0]["posting_code"] != event["posting_code"]
    ):
        return "posting_mismatch"
    if bool(event.get("is_adhoc")):
        return "event_scope"
    source = _resolve_scheduled_event_source(
        event,
        reporting_period_id=reporting_period_id,
        programme_code=matching_contexts[0].get("programme_code"),
    )
    if source is None:
        return "event_scope"
    owner = event.get("created_for_programme_code")
    if owner is None:
        if not posting_capabilities.get(event["posting_code"], False):
            return "secretary_events_not_supported"
    else:
        if matching_contexts[0].get("programme_code") != owner:
            return "event_scope"
    if already_attended:
        return "already_attended"
    return None


def _external_event_ineligibility_error(
    reason: ExternalEventIneligibilityReason,
) -> ApiError:
    if reason in {"already_attended", "overlapping_attendance"}:
        return ApiError(
            status_code=409,
            detail=(
                "Attendance already submitted for this teaching event"
                if reason == "already_attended"
                else "Attendance overlaps an earlier accepted event"
            ),
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
                programme_code,
                posting_code,
                start_date,
                end_date,
                is_current
            FROM external_resident_postings
            WHERE external_resident_id = :external_resident_id
              AND start_date <= :end_date
              AND (end_date IS NULL OR end_date >= :start_date)
            ORDER BY start_date ASC, posting_code ASC, programme_code ASC NULLS LAST
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
    # Unlike a display option, the derived host posting is authorization
    # evidence.  Corrupt/legacy overlapping schedules therefore fail closed
    # instead of letting order choose an arbitrary department.
    return contexts[0] if len(contexts) == 1 else None


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
    resident: dict[str, Any] | None = None
    if role == "external_resident":
        if external_resident_id is None:
            raise ApiError(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )
        await _external_resident(db, external_resident_id)
    else:
        if resident_id is None:
            raise ApiError(
                status_code=401,
                detail="Unauthorized",
                error_code=ErrorCode.UNAUTHORIZED.value,
            )
        resident = await _resident(db, resident_id)

    active_periods = await list_effectively_active_reporting_periods(
        db,
        status_as_of_date=today,
    )
    active_period_rows = [_submission_period_row(period) for period in active_periods]

    if not active_periods:
        return {
            "events": [],
            "reason": "active_reporting_period_unavailable",
            "ad_hoc_allowed": False,
            "message": "No active submission period is currently available.",
            "posting_capabilities": [],
            "filter_options": {
                "posting_options": [],
                "teaching_name_options": [],
            },
            "active_reporting_periods": [],
        }

    if role == "external_resident":
        if external_resident_id is None:
            raise RuntimeError("External resident identity invariant was not established")
        all_contexts: list[dict[str, Any]] = []
        all_capability_codes: set[str] = set()
        supported_anywhere = False
        event_rows: dict[str, dict[str, Any]] = {}
        option_names: set[str] = set()
        posting_option_codes: set[str] = set()
        queried_ranges: list[tuple[date, date]] = []

        for period in active_periods:
            range_start, range_end = _effective_event_range(
                period_start=period["start_date"],
                period_end=period["end_date"],
                today=today,
                date_from=date_from,
                date_to=date_to,
            )
            if range_start > range_end:
                continue
            queried_ranges.append((range_start, range_end))
            contexts = await _external_posting_contexts(
                db,
                external_resident_id=external_resident_id,
                start_date=range_start,
                end_date=range_end,
            )
            all_contexts.extend(contexts)
            eligible_codes = {
                row["posting_code"]
                for row in contexts
                if row.get("posting_code")
                and _context_overlaps_range(row, start=range_start, end=range_end)
            }
            posting_option_codes.update(eligible_codes)
            all_capability_codes.update(eligible_codes)
            selected_codes = eligible_codes
            if posting_code is not None:
                selected_codes = {posting_code} if posting_code in eligible_codes else set()
            period_capabilities = await _posting_capabilities(
                db,
                posting_codes=eligible_codes,
            )
            supported_anywhere = supported_anywhere or any(period_capabilities.values())
            for external_posting_code in sorted(selected_codes):
                raw_events = await _events_for_external_posting(
                    db,
                    external_resident_id=external_resident_id,
                    posting_code=external_posting_code,
                    today=today,
                    date_from=range_start,
                    date_to=range_end,
                    teaching_name=teaching_name,
                )
                for event in raw_events:
                    resolved_period = resolve_reporting_period_for_date(
                        active_periods,
                        relevant_date=event["event_date"],
                        status_as_of_date=today,
                    )
                    if resolved_period is None or str(resolved_period["id"]) != str(period["id"]):
                        continue
                    reason = _external_event_ineligibility_reason(
                        event=event,
                        posting_contexts=contexts,
                        posting_capabilities=period_capabilities,
                        reporting_period_id=resolved_period["id"],
                        today=today,
                        already_attended=bool(event.get("already_attended")),
                    )
                    if reason is None:
                        event_rows[str(event["id"])] = _event_row(
                            event,
                            reporting_period=resolved_period,
                        )
                        option_names.add(event["teaching_name"])

        capabilities = await _posting_capabilities(
            db,
            posting_codes=all_capability_codes,
        )
        posting_capability_rows = [
            {
                "posting_code": code,
                "supports_secretary_events": capabilities.get(code, False),
            }
            for code in sorted(all_capability_codes)
        ]
        filter_options = {
            "posting_options": [
                {"posting_code": code, "label": code}
                for code in sorted(posting_option_codes)
            ],
            "teaching_name_options": [
                {"teaching_name": name, "label": name}
                for name in sorted(option_names, key=str.casefold)
            ],
        }
        if queried_ranges:
            filter_options["date_from"] = min(item[0] for item in queried_ranges).isoformat()
            filter_options["date_to"] = max(item[1] for item in queried_ranges).isoformat()
        if not all_contexts:
            return {
                "events": [],
                "reason": "posting_schedule_unavailable",
                "ad_hoc_allowed": False,
                "message": "No posting schedule is available for an active submission period.",
                "posting_capabilities": posting_capability_rows,
                "filter_options": filter_options,
                "active_reporting_periods": active_period_rows,
            }
        if not supported_anywhere and not event_rows:
            return {
                "events": [],
                "reason": "secretary_events_not_supported",
                "ad_hoc_allowed": True,
                "message": "No scheduled teaching events are supported for your postings.",
                "posting_capabilities": posting_capability_rows,
                "filter_options": filter_options,
                "active_reporting_periods": active_period_rows,
            }
        events = sorted(
            event_rows.values(),
            key=lambda row: (
                row["event_date"],
                row["start_time"],
                row["teaching_name"],
                str(row["id"]),
            ),
        )
        return {
            "events": events,
            "reason": None if events else "no_eligible_scheduled_events",
            "ad_hoc_allowed": True,
            "message": (
                None
                if events
                else "No scheduled teaching events are currently available for your postings."
            ),
            "posting_capabilities": posting_capability_rows,
            "filter_options": filter_options,
            "active_reporting_periods": active_period_rows,
        }

    if resident_id is None or resident is None:
        raise RuntimeError("Resident identity invariant was not established")
    has_posting_context = False
    eligible_posting_codes: set[str] = set()
    posting_option_codes: set[str] = set()
    option_names: set[str] = set()
    queried_ranges: list[tuple[date, date]] = []
    event_rows: dict[str, dict[str, Any]] = {}

    for period in active_periods:
        contexts, visibility_contexts = await _resident_visibility_contexts(
            db,
            resident_id=resident_id,
            resident=resident,
            reporting_period_id=period["id"],
        )
        has_posting_context = has_posting_context or bool(contexts)
        range_start, range_end = _effective_event_range(
            period_start=period["start_date"],
            period_end=period["end_date"],
            today=today,
            date_from=date_from,
            date_to=date_to,
        )
        if range_start > range_end:
            continue
        queried_ranges.append((range_start, range_end))
        period_eligible_codes = {
            row["posting_code"]
            for row in visibility_contexts
            if row.get("posting_code")
            and _context_overlaps_range(row, start=range_start, end=range_end)
        }
        eligible_posting_codes.update(period_eligible_codes)
        posting_option_codes.update(period_eligible_codes)
        selected_codes = period_eligible_codes
        if posting_code is not None:
            selected_codes = {posting_code} if posting_code in period_eligible_codes else set()

        raw_events = await _events_for_postings(
            db,
            resident_id=resident_id,
            programme_code=resident["programme_code"],
            posting_codes=selected_codes,
            today=today,
            period_start=period["start_date"],
            period_end=period["end_date"],
            date_from=range_start,
            date_to=range_end,
            teaching_name=teaching_name,
        )
        for event in raw_events:
            resolved_period = resolve_reporting_period_for_date(
                active_periods,
                relevant_date=event["event_date"],
                status_as_of_date=today,
            )
            if resolved_period is None or str(resolved_period["id"]) != str(period["id"]):
                continue
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
            resolved = _resolve_scheduled_event_source(
                event,
                reporting_period_id=resolved_period["id"],
                programme_code=resident["programme_code"],
            )
            if resolved is not None:
                event_rows[str(event["id"])] = _available_event_row(
                    event,
                    resolved=resolved,
                    reporting_period=resolved_period,
                )

        option_raw_events = await _events_for_postings(
            db,
            resident_id=resident_id,
            programme_code=resident["programme_code"],
            posting_codes=selected_codes,
            today=today,
            period_start=period["start_date"],
            period_end=period["end_date"],
            date_from=range_start,
            date_to=range_end,
            teaching_name=None,
        )
        for event in option_raw_events:
            resolved_period = resolve_reporting_period_for_date(
                active_periods,
                relevant_date=event["event_date"],
                status_as_of_date=today,
            )
            if resolved_period is None or str(resolved_period["id"]) != str(period["id"]):
                continue
            context = _matching_context_for_event(
                visibility_contexts,
                posting_code=event["posting_code"],
                event_date=event["event_date"],
            )
            if context is None:
                continue
            resolved = _resolve_scheduled_event_source(
                event,
                reporting_period_id=resolved_period["id"],
                programme_code=resident["programme_code"],
            )
            if resolved is not None:
                option_names.add(event["teaching_name"])

    if not has_posting_context:
        return {
            "events": [],
            "reason": "posting_schedule_unavailable",
            "ad_hoc_allowed": False,
            "message": (
                "Your posting schedule is not available for an active submission period. "
                "Please contact your programme coordinator after RDB upload."
            ),
            "posting_capabilities": [],
            "filter_options": {
                "posting_options": [],
                "teaching_name_options": [],
            },
            "active_reporting_periods": active_period_rows,
        }

    posting_capabilities = await _posting_capabilities(
        db,
        posting_codes=eligible_posting_codes,
    )
    capabilities = [
        {
            "posting_code": code,
            "supports_secretary_events": posting_capabilities.get(code, False),
        }
        for code in sorted(eligible_posting_codes)
    ]
    filter_options = {
        "posting_options": [
            {"posting_code": code, "label": code}
            for code in sorted(posting_option_codes)
        ],
        "teaching_name_options": [
            {"teaching_name": name, "label": name}
            for name in sorted(option_names, key=str.casefold)
        ],
    }
    if queried_ranges:
        filter_options["date_from"] = min(item[0] for item in queried_ranges).isoformat()
        filter_options["date_to"] = max(item[1] for item in queried_ranges).isoformat()

    events = sorted(
        event_rows.values(),
        key=lambda row: (
            row["event_date"],
            row["start_time"],
            row["teaching_name"],
            str(row["id"]),
        ),
    )
    if events:
        return {
            "events": events,
            "reason": None,
            "ad_hoc_allowed": True,
            "message": None,
            "posting_capabilities": capabilities,
            "filter_options": filter_options,
            "active_reporting_periods": active_period_rows,
        }

    has_secretary_support_hint = any(item["supports_secretary_events"] for item in capabilities)
    return {
        "events": [],
        "reason": "no_eligible_scheduled_events",
        "ad_hoc_allowed": True,
        "message": (
            "No scheduled teaching events are currently available for your postings. "
            "You can submit ad-hoc teaching."
            if has_secretary_support_hint
            else (
                "No scheduled teaching events are currently available for your postings. "
                "You can submit ad-hoc teaching."
            )
        ),
        "posting_capabilities": capabilities,
        "filter_options": filter_options,
        "active_reporting_periods": active_period_rows,
    }


async def _submitted_attendance_for_event(
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
              AND status = 'submitted'
            ORDER BY submitted_at DESC, id DESC
            LIMIT 1
            """
        ),
        {"resident_id": str(resident_id), "event_id": str(event_id)},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row is not None else None


async def _attendance_by_id(
    db: AsyncSession,
    *,
    resident_id: UUID,
    attendance_id: UUID | str,
) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT id, resident_id, teaching_event_id, status, posting_code, submitted_at
            FROM attendance_records
            WHERE id = :attendance_id
              AND resident_id = :resident_id
            """
        ),
        {
            "attendance_id": str(attendance_id),
            "resident_id": str(resident_id),
        },
    )
    row = result.mappings().one_or_none()
    return dict(row) if row is not None else None


async def _external_attendance_by_id(
    db: AsyncSession,
    *,
    external_resident_id: UUID,
    attendance_id: UUID | str,
) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT
                id,
                external_resident_id,
                teaching_event_id,
                status,
                posting_code,
                submitted_at
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


def _event_intervals_overlap(
    *,
    left_start: time,
    left_end: time | None,
    right_start: time,
    right_end: time | None,
) -> bool:
    if left_start == right_start:
        return True
    effective_left_end = left_end or left_start
    effective_right_end = right_end or right_start
    return left_start < effective_right_end and right_start < effective_left_end


def _native_attendance_lock_keys(
    *,
    resident_id: UUID,
    event_date: date,
) -> tuple[int, int]:
    scope = f"native-attendance:{resident_id}:{event_date.isoformat()}".encode("utf-8")
    signed = int.from_bytes(
        blake2b(scope, digest_size=8).digest(),
        byteorder="big",
        signed=True,
    )
    key1 = signed >> 32
    key2 = signed & 0xFFFFFFFF
    if key2 >= 2**31:
        key2 -= 2**32
    return key1, key2


def _external_attendance_lock_keys(
    *,
    external_resident_id: UUID,
    event_date: date,
) -> tuple[int, int]:
    scope = (
        f"external-attendance:{external_resident_id}:{event_date.isoformat()}".encode(
            "utf-8"
        )
    )
    signed = int.from_bytes(
        blake2b(scope, digest_size=8).digest(),
        byteorder="big",
        signed=True,
    )
    key1 = signed >> 32
    key2 = signed & 0xFFFFFFFF
    if key2 >= 2**31:
        key2 -= 2**32
    return key1, key2


async def _lock_teaching_events(
    db: AsyncSession,
    *,
    event_ids: Sequence[UUID | str],
) -> None:
    await acquire_teaching_event_locks(db, event_ids=event_ids)


async def _acquire_native_attendance_locks(
    db: AsyncSession,
    *,
    resident_id: UUID,
    event_dates: set[date],
) -> None:
    for event_date in sorted(event_dates):
        key1, key2 = _native_attendance_lock_keys(
            resident_id=resident_id,
            event_date=event_date,
        )
        await db.execute(
            text(
                """
                /* native_attendance_overlap_lock */
                SELECT pg_advisory_xact_lock(:key1, :key2)
                """
            ),
            {"key1": key1, "key2": key2},
        )
        await db.execute(
            text(
                """
                /* native_attendance_database_overlap_lock */
                SELECT pg_advisory_xact_lock(
                    hashtextextended(:lock_scope, 0)
                )
                """
            ),
            {
                "lock_scope": (
                    f"native-attendance:{resident_id}:"
                    f"{event_date.isoformat()}"
                )
            },
        )


async def _acquire_external_attendance_locks(
    db: AsyncSession,
    *,
    external_resident_id: UUID,
    event_dates: set[date],
) -> None:
    for event_date in sorted(event_dates):
        key1, key2 = _external_attendance_lock_keys(
            external_resident_id=external_resident_id,
            event_date=event_date,
        )
        await db.execute(
            text(
                """
                /* external_attendance_overlap_lock */
                SELECT pg_advisory_xact_lock(:key1, :key2)
                """
            ),
            {"key1": key1, "key2": key2},
        )
        await db.execute(
            text(
                """
                /* external_attendance_database_overlap_lock */
                SELECT pg_advisory_xact_lock(
                    hashtextextended(:lock_scope, 0)
                )
                """
            ),
            {
                "lock_scope": (
                    f"external-attendance:{external_resident_id}:"
                    f"{event_date.isoformat()}"
                )
            },
        )


async def _overlapping_native_attendance_exists(
    db: AsyncSession,
    *,
    resident_id: UUID,
    event: dict[str, Any],
) -> bool:
    result = await db.execute(
        text(
            """
            /* native_attendance_overlap_candidates */
            SELECT existing.start_time, existing.end_time
            FROM attendance_records AS attendance
            JOIN teaching_events AS existing
              ON existing.id = attendance.teaching_event_id
            WHERE attendance.resident_id = :resident_id
              AND attendance.status = 'submitted'
              AND (
                  CAST(:event_id AS uuid) IS NULL
                  OR existing.id <> CAST(:event_id AS uuid)
              )
              AND existing.event_date = :event_date
            """
        ),
        {
            "resident_id": str(resident_id),
            "event_id": str(event["id"]) if event.get("id") is not None else None,
            "event_date": event["event_date"],
        },
    )
    return any(
        _event_intervals_overlap(
            left_start=event["start_time"],
            left_end=event.get("end_time"),
            right_start=row["start_time"],
            right_end=row.get("end_time"),
        )
        for row in result.mappings().all()
    )


async def _overlapping_external_attendance_exists(
    db: AsyncSession,
    *,
    external_resident_id: UUID,
    event: dict[str, Any],
) -> bool:
    result = await db.execute(
        text(
            """
            /* external_attendance_overlap_candidates */
            SELECT existing.start_time, existing.end_time
            FROM external_attendance_records AS attendance
            JOIN teaching_events AS existing
              ON existing.id = attendance.teaching_event_id
            WHERE attendance.external_resident_id = :external_resident_id
              AND attendance.status = 'submitted'
              AND (
                  CAST(:event_id AS uuid) IS NULL
                  OR existing.id <> CAST(:event_id AS uuid)
              )
              AND existing.event_date = :event_date
            """
        ),
        {
            "external_resident_id": str(external_resident_id),
            "event_id": str(event["id"]) if event.get("id") is not None else None,
            "event_date": event["event_date"],
        },
    )
    return any(
        _event_intervals_overlap(
            left_start=event["start_time"],
            left_end=event.get("end_time"),
            right_start=row["start_time"],
            right_end=row.get("end_time"),
        )
        for row in result.mappings().all()
    )


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


async def _create_adhoc_attendance(
    db: AsyncSession,
    *,
    posting_code: str,
    attended_posting_code: str,
    attended_teaching_name: str,
    teaching_name: str,
    details_of_session: str | None,
    event_date: date,
    start_time: time,
    end_time: time | None,
    duration_hours: Decimal | None,
    session_type_id: UUID | str | None,
) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT event_id, attendance_id
            FROM mata_rls.create_adhoc_attendance(
                :posting_code,
                :attended_posting_code,
                :attended_teaching_name,
                :teaching_name,
                :details_of_session,
                :event_date,
                :start_time,
                :end_time,
                :duration_hours,
                :session_type_id
            )
            """
        ),
        {
            "posting_code": posting_code,
            "attended_posting_code": attended_posting_code,
            "attended_teaching_name": attended_teaching_name,
            "teaching_name": teaching_name,
            "details_of_session": details_of_session,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
            "duration_hours": duration_hours,
            "session_type_id": (
                str(session_type_id) if session_type_id is not None else None
            ),
        },
    )
    return dict(result.mappings().one())


def _database_sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return (
        getattr(original, "sqlstate", None)
        or getattr(original, "pgcode", None)
    )


def _is_unique_violation(exc: IntegrityError) -> bool:
    return _database_sqlstate(exc) == "23505"


async def _raise_duplicate_attendance_conflict(
    db: AsyncSession,
    exc: IntegrityError,
) -> NoReturn:
    if not _is_unique_violation(exc):
        raise exc
    await db.rollback()
    raise ApiError(
        status_code=409,
        detail="Attendance already submitted for this teaching event",
        error_code=ErrorCode.CONFLICT.value,
    ) from exc


async def _raise_adhoc_helper_error(
    db: AsyncSession,
    exc: DBAPIError,
) -> NoReturn:
    sqlstate = _database_sqlstate(exc)
    if sqlstate not in {"22023", "23P01", "23505", "28000"}:
        raise exc

    await db.rollback()
    if sqlstate == "23505":
        raise ApiError(
            status_code=409,
            detail="Attendance already submitted for this teaching event",
            error_code=ErrorCode.CONFLICT.value,
        ) from exc
    if sqlstate == "23P01":
        raise ApiError(
            status_code=409,
            detail="Attendance overlaps an earlier accepted event",
            error_code=ErrorCode.CONFLICT.value,
        ) from exc
    if sqlstate == "22023":
        raise ApiError(
            status_code=422,
            detail="Invalid ad-hoc teaching event",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        ) from exc
    raise ApiError(
        status_code=401,
        detail="Unauthorized",
        error_code=ErrorCode.UNAUTHORIZED.value,
    ) from exc


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
        await _lock_teaching_events(db, event_ids=event_ids)

        event_lookups: list[
            tuple[UUID, dict[str, Any] | None, ApiError | None]
        ] = []
        for event_id in event_ids:
            try:
                event = await _get_event(db, event_id)
            except ApiError as exc:
                event_lookups.append((event_id, None, exc))
            else:
                event_lookups.append((event_id, event, None))

        lock_dates: set[date] = set()
        for _, event, lookup_error in event_lookups:
            if lookup_error is not None:
                break
            if event is None:
                raise RuntimeError("Teaching event lookup returned no result or error")
            lock_dates.add(event["event_date"])
        await _acquire_external_attendance_locks(
            db,
            external_resident_id=external_resident_id,
            event_dates=lock_dates,
        )

        submission_plans: list[dict[str, Any]] = []
        seen_event_ids: set[str] = set()
        planned_events: list[dict[str, Any]] = []
        for event_id, event, lookup_error in event_lookups:
            if lookup_error is not None:
                raise lookup_error
            if event is None:
                raise RuntimeError("Teaching event lookup returned no result or error")
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
            event_key = str(event_id)
            if event_key in seen_event_ids:
                raise _external_event_ineligibility_error("already_attended")
            already_attended = await _duplicate_external_attendance_exists(
                db,
                external_resident_id=external_resident_id,
                event_id=event_id,
            )
            reason = _external_event_ineligibility_reason(
                event=event,
                posting_contexts=posting_contexts,
                posting_capabilities=posting_capabilities,
                reporting_period_id=period["id"],
                today=today,
                already_attended=already_attended,
            )
            if reason is not None:
                raise _external_event_ineligibility_error(reason)
            overlaps_accepted = await _overlapping_external_attendance_exists(
                db,
                external_resident_id=external_resident_id,
                event=event,
            )
            overlaps_planned = any(
                prior_event["event_date"] == event["event_date"]
                and _event_intervals_overlap(
                    left_start=event["start_time"],
                    left_end=event.get("end_time"),
                    right_start=prior_event["start_time"],
                    right_end=prior_event.get("end_time"),
                )
                for prior_event in planned_events
            )
            if overlaps_accepted or overlaps_planned:
                raise _external_event_ineligibility_error("overlapping_attendance")
            accepted = await _weekend_is_accepted(
                db,
                event=event,
                programme_code="",
                session_type_id=event.get("session_type_id"),
            )
            submission_plans.append(
                {
                    "event_id": event_id,
                    "event": event,
                    "period": period,
                    "accepted": accepted,
                }
            )
            seen_event_ids.add(event_key)
            planned_events.append(event)

        submitted = 0
        submitted_events: list[dict[str, Any]] = []
        weekend_warning_count = 0
        touched_postings: set[str] = set()
        touched_period_ids: set[str] = set()
        try:
            for plan in submission_plans:
                event_id = plan["event_id"]
                event = plan["event"]
                period = plan["period"]
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
                if not plan["accepted"]:
                    weekend_warning_count += 1
        except IntegrityError as exc:
            await _raise_duplicate_attendance_conflict(db, exc)

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
    await _lock_teaching_events(db, event_ids=event_ids)

    event_lookups: list[tuple[UUID, dict[str, Any] | None, ApiError | None]] = []
    for event_id in event_ids:
        try:
            event = await _get_event(db, event_id)
        except ApiError as exc:
            event_lookups.append((event_id, None, exc))
        else:
            event_lookups.append((event_id, event, None))

    lock_dates: set[date] = set()
    for _, event, lookup_error in event_lookups:
        if lookup_error is not None:
            break
        if event is None:
            raise RuntimeError("Teaching event lookup returned no result or error")
        lock_dates.add(event["event_date"])
    await _acquire_native_attendance_locks(
        db,
        resident_id=resident_id,
        event_dates=lock_dates,
    )

    submission_plans: list[dict[str, Any]] = []
    seen_event_ids: set[str] = set()
    planned_events: list[dict[str, Any]] = []
    for event_id, event, lookup_error in event_lookups:
        if lookup_error is not None:
            raise lookup_error
        if event is None:
            raise RuntimeError("Teaching event lookup returned no result or error")
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
        resolved = _resolve_scheduled_event_source(
            event,
            reporting_period_id=period["id"],
            programme_code=resident["programme_code"],
        )
        if resolved is None:
            raise ApiError(
                status_code=422,
                detail="Teaching event is not visible for this resident",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        event_key = str(event_id)
        if event_key in seen_event_ids:
            raise ApiError(
                status_code=409,
                detail="Attendance already submitted for this teaching event",
                error_code=ErrorCode.CONFLICT.value,
            )
        existing_attendance = await _submitted_attendance_for_event(
            db,
            resident_id=resident_id,
            event_id=event_id,
        )
        if existing_attendance is not None:
            raise ApiError(
                status_code=409,
                detail="Attendance already submitted for this teaching event",
                error_code=ErrorCode.CONFLICT.value,
            )
        overlaps_accepted = await _overlapping_native_attendance_exists(
            db,
            resident_id=resident_id,
            event=event,
        )
        overlaps_planned = any(
            prior_event["event_date"] == event["event_date"]
            and _event_intervals_overlap(
                left_start=event["start_time"],
                left_end=event.get("end_time"),
                right_start=prior_event["start_time"],
                right_end=prior_event.get("end_time"),
            )
            for prior_event in planned_events
        )
        if overlaps_accepted or overlaps_planned:
            raise ApiError(
                status_code=409,
                detail="Attendance overlaps an earlier accepted event",
                error_code=ErrorCode.CONFLICT.value,
            )
        submission_plans.append(
            {
                "event_id": event_id,
                "event": event,
                "period": period,
                "resolved": resolved,
            }
        )
        seen_event_ids.add(event_key)
        planned_events.append(event)

    submitted = 0
    submitted_events: list[dict[str, Any]] = []
    weekend_warning_count = 0
    touched_postings: set[str] = set()
    touched_period_ids: set[str] = set()
    try:
        for plan in submission_plans:
            event_id = plan["event_id"]
            event = plan["event"]
            period = plan["period"]
            resolved = plan["resolved"]
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
    except IntegrityError as exc:
        await _raise_duplicate_attendance_conflict(db, exc)

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
        attended_posting_options = [{"posting_code": posting_code}]
        selected_attended_posting = _select_attended_posting(
            attended_posting_options,
            requested_posting_code=attended_posting_code,
            default_posting_code=posting_code,
        )
        if selected_attended_posting is None:
            raise RuntimeError("Assigned posting option invariant was not established")
        duration_hours = ADHOC_DURATION_HOURS
        end_time = _compute_end_time(event_date, start_time, duration_hours)
        await _acquire_external_attendance_locks(
            db,
            external_resident_id=external_resident_id,
            event_dates={event_date},
        )
        if await _overlapping_external_attendance_exists(
            db,
            external_resident_id=external_resident_id,
            event={
                "id": None,
                "event_date": event_date,
                "start_time": start_time,
                "end_time": end_time,
            },
        ):
            raise _external_event_ineligibility_error("overlapping_attendance")
        try:
            created = await _create_adhoc_attendance(
                db,
                posting_code=posting_code,
                attended_posting_code=selected_attended_posting[
                    "posting_code"
                ],
                attended_teaching_name=ADHOC_COMPLIANCE_TEACHING_NAME,
                teaching_name=ADHOC_COMPLIANCE_TEACHING_NAME,
                details_of_session=details_of_session,
                event_date=event_date,
                start_time=start_time,
                end_time=end_time,
                duration_hours=duration_hours,
                session_type_id=None,
            )
        except DBAPIError as exc:
            await _raise_adhoc_helper_error(db, exc)
        event = _event_row(await _get_event(db, created["event_id"]))
        attendance_row = await _external_attendance_by_id(
            db,
            external_resident_id=external_resident_id,
            attendance_id=created["attendance_id"],
        )
        if attendance_row is None:
            raise RuntimeError("Ad-hoc attendance was not visible after creation")
        attendance = _external_attendance_row(attendance_row)
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
    attended_posting_options = [{"posting_code": context["posting_code"]}]
    selected_attended_posting = _select_attended_posting(
        attended_posting_options,
        requested_posting_code=attended_posting_code,
        default_posting_code=context["posting_code"],
    )
    if selected_attended_posting is None:
        raise RuntimeError("Assigned posting option invariant was not established")
    duration_hours = ADHOC_DURATION_HOURS
    end_time = _compute_end_time(event_date, start_time, duration_hours)
    await _acquire_native_attendance_locks(
        db,
        resident_id=resident_id,
        event_dates={event_date},
    )
    if await _overlapping_native_attendance_exists(
        db,
        resident_id=resident_id,
        event={
            "id": None,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
        },
    ):
        raise ApiError(
            status_code=409,
            detail="Attendance overlaps an earlier accepted event",
            error_code=ErrorCode.CONFLICT.value,
        )
    try:
        created = await _create_adhoc_attendance(
            db,
            posting_code=context["posting_code"],
            attended_posting_code=selected_attended_posting["posting_code"],
            attended_teaching_name=ADHOC_COMPLIANCE_TEACHING_NAME,
            teaching_name=ADHOC_COMPLIANCE_TEACHING_NAME,
            details_of_session=details_of_session,
            event_date=event_date,
            start_time=start_time,
            end_time=end_time,
            duration_hours=duration_hours,
            session_type_id=None,
        )
    except DBAPIError as exc:
        await _raise_adhoc_helper_error(db, exc)
    event = _event_row(await _get_event(db, created["event_id"]))
    attendance_row = await _attendance_by_id(
        db,
        resident_id=resident_id,
        attendance_id=created["attendance_id"],
    )
    if attendance_row is None:
        raise RuntimeError("Ad-hoc attendance was not visible after creation")
    attendance = _attendance_row(attendance_row)
    accepted = await _weekend_is_accepted(
        db,
        event=event,
        programme_code=resident["programme_code"],
        session_type_id=None,
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
    existing = await _attendance_by_id(
        db,
        resident_id=resident_id,
        attendance_id=attendance_id,
    )
    if existing is None:
        raise ApiError(
            status_code=404,
            detail="Attendance record not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )

    await _lock_teaching_events(
        db,
        event_ids=[existing["teaching_event_id"]],
    )
    event = await _get_event(db, existing["teaching_event_id"])
    await _acquire_native_attendance_locks(
        db,
        resident_id=resident_id,
        event_dates={event["event_date"]},
    )
    locked_result = await db.execute(
        text(
            """
            /* native_attendance_removal_lock */
            SELECT
                attendance.id,
                attendance.resident_id,
                attendance.teaching_event_id,
                attendance.status,
                attendance.posting_code,
                attendance.submitted_at,
                teaching_event.event_date
            FROM attendance_records AS attendance
            JOIN teaching_events AS teaching_event
              ON teaching_event.id = attendance.teaching_event_id
            WHERE attendance.id = :attendance_id
              AND attendance.resident_id = :resident_id
            FOR UPDATE OF attendance
            """
        ),
        {
            "attendance_id": str(attendance_id),
            "resident_id": str(resident_id),
        },
    )
    locked = locked_result.mappings().one_or_none()
    if locked is None:
        raise ApiError(
            status_code=404,
            detail="Attendance record not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    if locked["status"] == "removed":
        await db.commit()
        return {
            "attendance_id": locked["id"],
            "status": "removed",
            "removed_count": 0,
        }

    result = await db.execute(
        text(
            """
            UPDATE attendance_records
            SET status = 'removed',
                updated_at = now()
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
    existing = await _external_attendance_by_id(
        db,
        external_resident_id=external_resident_id,
        attendance_id=attendance_id,
    )
    if existing is None:
        raise ApiError(
            status_code=404,
            detail="Attendance record not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )

    await _lock_teaching_events(
        db,
        event_ids=[existing["teaching_event_id"]],
    )
    event = await _get_event(db, existing["teaching_event_id"])
    await _acquire_external_attendance_locks(
        db,
        external_resident_id=external_resident_id,
        event_dates={event["event_date"]},
    )
    locked_result = await db.execute(
        text(
            """
            /* external_attendance_removal_lock */
            SELECT
                attendance.id,
                attendance.external_resident_id,
                attendance.teaching_event_id,
                attendance.status,
                attendance.posting_code,
                attendance.submitted_at,
                teaching_event.event_date
            FROM external_attendance_records AS attendance
            JOIN teaching_events AS teaching_event
              ON teaching_event.id = attendance.teaching_event_id
            WHERE attendance.id = :attendance_id
              AND attendance.external_resident_id = :external_resident_id
            FOR UPDATE OF attendance
            """
        ),
        {
            "attendance_id": str(attendance_id),
            "external_resident_id": str(external_resident_id),
        },
    )
    locked = locked_result.mappings().one_or_none()
    if locked is None:
        raise ApiError(
            status_code=404,
            detail="Attendance record not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    if locked["status"] == "removed":
        await db.commit()
        return {
            "attendance_id": locked["id"],
            "status": "removed",
            "removed_count": 0,
        }

    result = await db.execute(
        text(
            """
            UPDATE external_attendance_records
            SET status = 'removed',
                updated_at = now()
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
