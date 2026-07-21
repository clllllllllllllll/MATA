from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.services.current_posting import (
    NATIVE_CURRENT_POSTING_JOIN_SQL,
    current_reporting_period_params,
)


VALID_ATTENDANCE_STATUSES = {"submitted", "flagged", "removed"}
SOURCE_LABELS = {
    "department_secretary": "Department Secretary",
    "programme_pc": "Programme PC",
    "adhoc": "Ad-hoc",
}

# One authoritative projection is reused for response values and source filtering.
# Programme ownership is authoritative for scheduled rows even when legacy
# created_by_role metadata is absent or inconsistent.
EVENT_SOURCE_SQL = """
CASE
    WHEN te.is_adhoc = true THEN 'Ad-hoc'
    WHEN te.created_for_programme_code IS NOT NULL THEN 'Programme PC'
    ELSE 'Department Secretary'
END
"""


def ensure_read_access(
    *,
    programme_scope: set[str],
    master_admin: bool,
    programme_code: str | None = None,
) -> set[str]:
    scope = {value.strip() for value in programme_scope if value.strip()}
    if master_admin:
        return scope
    if not scope:
        raise ApiError(
            status_code=403,
            detail="Forbidden - admin programme scope is empty",
            error_code=ErrorCode.FORBIDDEN.value,
        )
    if programme_code is not None and programme_code not in scope:
        raise ApiError(
            status_code=403,
            detail="Forbidden - programme not in admin scope",
            error_code=ErrorCode.FORBIDDEN.value,
        )
    return scope


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _validate_date_range(date_from: date | None, date_to: date | None) -> None:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ApiError(
            status_code=422,
            detail="date_from must be on or before date_to",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )


def _normalise_source(value: str | None) -> str | None:
    cleaned = _clean_optional(value)
    if cleaned is None:
        return None
    normalised = cleaned.lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "department_secretary": "department_secretary",
        "secretary": "department_secretary",
        "secretary_event": "department_secretary",
        "programme_pc": "programme_pc",
        "pc": "programme_pc",
        "adhoc": "adhoc",
        "ad_hoc": "adhoc",
    }
    source = aliases.get(normalised)
    if source is None:
        raise ApiError(
            status_code=422,
            detail="source must be one of department_secretary, programme_pc, adhoc",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    return source


def _normalise_status(value: str | None) -> str | None:
    cleaned = _clean_optional(value)
    if cleaned is None:
        return None
    status = cleaned.lower()
    if status not in VALID_ATTENDANCE_STATUSES:
        raise ApiError(
            status_code=422,
            detail="status must be one of submitted, flagged, removed",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    return status


def _page(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(int(limit), 200)), max(0, int(offset))


def _scope_where(
    *,
    programme_scope: set[str],
    master_admin: bool,
    params: dict[str, Any],
) -> list[str]:
    if master_admin:
        return []
    params["programme_scope"] = sorted(programme_scope)
    return ["r.programme_code = ANY(:programme_scope)"]


async def list_residents(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    programme_code: str | None,
    search: str | None,
    posting_code: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    programme_code = _clean_optional(programme_code)
    scope = ensure_read_access(
        programme_scope=programme_scope,
        master_admin=master_admin,
        programme_code=programme_code,
    )
    search = _clean_optional(search)
    posting_code = _clean_optional(posting_code)
    limit, offset = _page(limit, offset)
    period_params = await current_reporting_period_params(db)

    params: dict[str, Any] = dict(period_params)
    where = _scope_where(
        programme_scope=scope,
        master_admin=master_admin,
        params=params,
    )
    if programme_code is not None:
        params["programme_code"] = programme_code
        where.append("r.programme_code = :programme_code")
    if search is not None:
        params["search_pattern"] = f"%{search}%"
        where.append("(r.name ILIKE :search_pattern OR r.mcr ILIKE :search_pattern)")
    if posting_code is not None:
        params["posting_code"] = posting_code
        where.append("current_posting.posting_code = :posting_code")
    where_sql = " AND ".join(f"({clause})" for clause in where) or "true"

    count_result = await db.execute(
        text(
            f"""
            /* admin_resident_attendance:overview_count */
            SELECT COUNT(*) AS total
            FROM residents r
            {NATIVE_CURRENT_POSTING_JOIN_SQL}
            WHERE {where_sql}
            """
        ),
        params,
    )
    count_row = count_result.mappings().one_or_none() or {}
    total = int(count_row.get("total") or 0)

    list_params = {**params, "limit": limit, "offset": offset}
    result = await db.execute(
        text(
            f"""
            /* admin_resident_attendance:overview */
            SELECT
                r.id AS resident_id,
                r.name,
                r.mcr,
                r.programme_code,
                r.r_year,
                current_posting.posting_code AS current_posting_code,
                COALESCE(pc.display_name, current_posting.posting_code) AS current_posting_label,
                COALESCE(attendance_totals.attendance_count, 0) AS attendance_count
            FROM residents r
            {NATIVE_CURRENT_POSTING_JOIN_SQL}
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS attendance_count
                FROM attendance_records ar
                WHERE ar.resident_id = r.id
            ) attendance_totals ON true
            WHERE {where_sql}
            ORDER BY LOWER(r.name) ASC, r.mcr ASC, r.id ASC
            LIMIT :limit OFFSET :offset
            """
        ),
        list_params,
    )
    return {
        "items": [dict(row) for row in result.mappings().all()],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def _resident_summary(
    db: AsyncSession,
    *,
    resident_id: UUID,
    programme_scope: set[str],
    master_admin: bool,
) -> tuple[dict[str, Any], set[str]]:
    scope = ensure_read_access(
        programme_scope=programme_scope,
        master_admin=master_admin,
    )
    period_params = await current_reporting_period_params(db)
    params: dict[str, Any] = {
        **period_params,
        "resident_id": str(resident_id),
    }
    where = ["r.id = :resident_id"]
    where.extend(
        _scope_where(
            programme_scope=scope,
            master_admin=master_admin,
            params=params,
        )
    )
    result = await db.execute(
        text(
            f"""
            /* admin_resident_attendance:resident */
            SELECT
                r.id AS resident_id,
                r.name,
                r.mcr,
                r.programme_code,
                r.r_year,
                current_posting.posting_code AS current_posting_code,
                COALESCE(pc.display_name, current_posting.posting_code) AS current_posting_label
            FROM residents r
            {NATIVE_CURRENT_POSTING_JOIN_SQL}
            WHERE {' AND '.join(f'({clause})' for clause in where)}
            """
        ),
        params,
    )
    row = result.mappings().one_or_none()
    if row is None:
        # Deliberately make an out-of-scope UUID indistinguishable from a missing UUID.
        raise ApiError(
            status_code=404,
            detail="Resident not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    return dict(row), scope


async def get_resident_attendance(
    db: AsyncSession,
    *,
    resident_id: UUID,
    programme_scope: set[str],
    master_admin: bool,
    reporting_period_id: UUID | None,
    posting_code: str | None,
    date_from: date | None,
    date_to: date | None,
    source: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    _validate_date_range(date_from, date_to)
    source = _normalise_source(source)
    status = _normalise_status(status)
    posting_code = _clean_optional(posting_code)
    limit, offset = _page(limit, offset)
    resident, scope = await _resident_summary(
        db,
        resident_id=resident_id,
        programme_scope=programme_scope,
        master_admin=master_admin,
    )

    params: dict[str, Any] = {"resident_id": str(resident_id)}
    where = ["ar.resident_id = :resident_id"]
    where.extend(
        _scope_where(
            programme_scope=scope,
            master_admin=master_admin,
            params=params,
        )
    )
    if reporting_period_id is not None:
        params["reporting_period_id"] = str(reporting_period_id)
        where.append(
            """
            EXISTS (
                SELECT 1
                FROM reporting_periods reporting_period
                WHERE reporting_period.id = :reporting_period_id
                  AND te.event_date >= reporting_period.start_date
                  AND te.event_date <= reporting_period.end_date
            )
            """
        )
    if posting_code is not None:
        params["posting_code"] = posting_code
        where.append("te.posting_code = :posting_code")
    if date_from is not None:
        params["date_from"] = date_from
        where.append("te.event_date >= :date_from")
    if date_to is not None:
        params["date_to"] = date_to
        where.append("te.event_date <= :date_to")
    if source is not None:
        params["source_label"] = SOURCE_LABELS[source]
        where.append(f"({EVENT_SOURCE_SQL}) = :source_label")
    if status is not None:
        params["status"] = status
        where.append("ar.status = :status")
    where_sql = " AND ".join(f"({clause})" for clause in where)
    from_sql = """
        FROM attendance_records ar
        JOIN residents r ON r.id = ar.resident_id
        JOIN teaching_events te ON te.id = ar.teaching_event_id
        LEFT JOIN posting_codes event_posting ON event_posting.code = te.posting_code
    """

    count_result = await db.execute(
        text(
            f"""
            /* admin_resident_attendance:history_count */
            SELECT COUNT(*) AS total
            {from_sql}
            WHERE {where_sql}
            """
        ),
        params,
    )
    count_row = count_result.mappings().one_or_none() or {}
    total = int(count_row.get("total") or 0)

    list_params = {**params, "limit": limit, "offset": offset}
    result = await db.execute(
        text(
            f"""
            /* admin_resident_attendance:history */
            SELECT
                ar.id AS attendance_id,
                ar.teaching_event_id,
                te.teaching_name,
                te.details_of_session,
                te.event_date,
                te.start_time,
                te.end_time,
                te.posting_code,
                COALESCE(event_posting.display_name, te.posting_code) AS posting_label,
                {EVENT_SOURCE_SQL} AS source,
                ar.status,
                ar.submitted_at
            {from_sql}
            WHERE {where_sql}
            ORDER BY te.event_date DESC, te.start_time DESC, ar.id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        list_params,
    )
    return {
        "resident": resident,
        "items": [dict(row) for row in result.mappings().all()],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
