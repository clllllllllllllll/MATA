from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode


VALID_ATTENDANCE_STATUSES = {"submitted", "flagged", "removed"}
SECRETARY_SOURCE_VALUES = {"secretary", "secretary_event", "secretary event", "scheduled"}
ADHOC_SOURCE_VALUES = {"adhoc", "ad_hoc", "ad-hoc", "ad hoc"}


def _normalise_status(value: str | None) -> str | None:
    if value is None:
        return None
    normalised = value.strip().lower()
    if normalised not in VALID_ATTENDANCE_STATUSES:
        raise ApiError(
            status_code=422,
            detail="status must be one of submitted, flagged, removed",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    return normalised


def _normalise_source(value: str | None) -> bool | None:
    if value is None:
        return None
    normalised = value.strip().lower()
    if normalised in SECRETARY_SOURCE_VALUES:
        return False
    if normalised in ADHOC_SOURCE_VALUES:
        return True
    raise ApiError(
        status_code=422,
        detail="source must be Secretary Event or Ad-hoc",
        error_code=ErrorCode.VALIDATION_FAILED.value,
    )


def _source_label(is_adhoc: bool) -> str:
    return "Ad-hoc" if is_adhoc else "Secretary Event"


def _summary(row: dict[str, Any] | None) -> dict[str, int]:
    row = row or {}
    return {
        "total_submissions": int(row.get("total_submissions") or 0),
        "submitted_count": int(row.get("submitted_count") or 0),
        "flagged_count": int(row.get("flagged_count") or 0),
        "removed_count": int(row.get("removed_count") or 0),
        "secretary_event_count": int(row.get("secretary_event_count") or 0),
        "adhoc_count": int(row.get("adhoc_count") or 0),
    }


def _list_item(row: dict[str, Any]) -> dict[str, Any]:
    is_adhoc = bool(row.get("is_adhoc"))
    return {
        "id": row["id"],
        "resident_id": row["resident_id"],
        "resident_name": row["resident_name"],
        "mcr": row["mcr"],
        "programme_code": row.get("programme_code"),
        "attendance_posting_code": row.get("attendance_posting_code"),
        "posting_code": row["posting_code"],
        "posting_display_name": row.get("posting_display_name"),
        "teaching_event_id": row["teaching_event_id"],
        "teaching_name": row["teaching_name"],
        "event_date": row["event_date"],
        "start_time": row["start_time"],
        "end_time": row.get("end_time"),
        "duration_hours": row.get("duration_hours"),
        "source": row.get("source") or _source_label(is_adhoc),
        "is_adhoc": is_adhoc,
        "status": row["status"],
        "submitted_at": row["submitted_at"],
        "session_type_id": row.get("session_type_id"),
        "session_type_name": row.get("session_type_name"),
        "cme_points_awarded": bool(row.get("cme_points_awarded", False)),
        "smc_event_code": row.get("smc_event_code"),
        "created_by_role": row.get("created_by_role"),
    }


def _detail(row: dict[str, Any]) -> dict[str, Any]:
    item = _list_item(row)
    return {
        **item,
        "attendance_record": {
            "id": row["id"],
            "resident_id": row["resident_id"],
            "teaching_event_id": row["teaching_event_id"],
            "status": row["status"],
            "attendance_posting_code": row.get("attendance_posting_code"),
            "submitted_at": row["submitted_at"],
            "created_at": row.get("attendance_created_at"),
            "updated_at": row.get("attendance_updated_at"),
        },
        "resident": {
            "id": row["resident_id"],
            "name": row["resident_name"],
            "mcr": row["mcr"],
            "programme_code": row.get("programme_code"),
            "r_year": row.get("resident_r_year"),
            "classification": row.get("resident_classification"),
            "status": row.get("resident_status"),
            "identity_label": "NHG Resident",
        },
        "event": {
            "id": row["teaching_event_id"],
            "teaching_name": row["teaching_name"],
            "event_date": row["event_date"],
            "start_time": row["start_time"],
            "end_time": row.get("end_time"),
            "duration_hours": row.get("duration_hours"),
            "session_type_id": row.get("session_type_id"),
            "session_type_name": row.get("session_type_name"),
            "cme_points_awarded": bool(row.get("cme_points_awarded", False)),
            "smc_event_code": row.get("smc_event_code"),
            "is_adhoc": bool(row.get("is_adhoc")),
            "source": item["source"],
            "created_by_role": row.get("created_by_role"),
            "created_at": row.get("event_created_at"),
            "updated_at": row.get("event_updated_at"),
        },
        "posting": {
            "code": row["posting_code"],
            "display_name": row.get("posting_display_name"),
            "institution": row.get("posting_institution"),
            "department": row.get("posting_department"),
        },
        "notes": {
            "identity_scope": "nhg_resident_attendance_records_only",
            "session_type_authority": "display_only",
            "compliance_included": None,
        },
    }


def _require_read_scope(
    *,
    programme_scope: set[str],
    master_admin: bool,
    programme_code: str | None,
) -> None:
    if master_admin:
        return
    if not programme_scope:
        raise ApiError(
            status_code=403,
            detail="Forbidden - admin programme scope is empty",
            error_code=ErrorCode.FORBIDDEN.value,
        )
    if programme_code is not None and programme_code not in programme_scope:
        raise ApiError(
            status_code=403,
            detail="Forbidden - programme not in admin scope",
            error_code=ErrorCode.FORBIDDEN.value,
        )


def _base_where(
    *,
    programme_scope: set[str],
    master_admin: bool,
    reporting_period_id: UUID | None,
    programme_code: str | None,
    posting_code: str | None,
    resident_id: UUID | None,
    mcr: str | None,
    date_from: date | None,
    date_to: date | None,
    source: str | None,
    is_adhoc: bool | None,
    status: str | None,
    search: str | None,
    teaching_event_id: UUID | None,
    teaching_name: str | None,
    session_type_id: UUID | None,
    submitted_from: datetime | None,
    submitted_to: datetime | None,
    include_removed_by_default: bool = False,
) -> tuple[list[str], dict[str, Any]]:
    clean_programme_code = programme_code.strip() if programme_code else None
    clean_programme_code = clean_programme_code or None
    _require_read_scope(
        programme_scope=programme_scope,
        master_admin=master_admin,
        programme_code=clean_programme_code,
    )

    clean_status = _normalise_status(status)
    source_is_adhoc = _normalise_source(source)
    if source_is_adhoc is not None and is_adhoc is not None and source_is_adhoc != is_adhoc:
        raise ApiError(
            status_code=422,
            detail="source and is_adhoc filters conflict",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    effective_is_adhoc = is_adhoc if is_adhoc is not None else source_is_adhoc

    where: list[str] = []
    params: dict[str, Any] = {}

    if not master_admin:
        params["programme_scope"] = sorted(programme_scope)
        where.append("r.programme_code = ANY(:programme_scope)")
    if clean_programme_code:
        params["programme_code"] = clean_programme_code
        where.append("r.programme_code = :programme_code")
    if reporting_period_id is not None:
        params["reporting_period_id"] = str(reporting_period_id)
        where.append(
            """
            EXISTS (
                SELECT 1
                FROM reporting_periods rp
                WHERE rp.id = :reporting_period_id
                  AND te.event_date BETWEEN rp.start_date AND rp.end_date
            )
            """
        )
    if posting_code:
        params["posting_code"] = posting_code.strip()
        where.append("te.posting_code = :posting_code")
    if resident_id is not None:
        params["resident_id"] = str(resident_id)
        where.append("ar.resident_id = :resident_id")
    if mcr:
        params["mcr"] = mcr.strip()
        where.append("LOWER(r.mcr) = LOWER(:mcr)")
    if date_from is not None:
        params["date_from"] = date_from
        where.append("te.event_date >= :date_from")
    if date_to is not None:
        params["date_to"] = date_to
        where.append("te.event_date <= :date_to")
    if effective_is_adhoc is not None:
        params["is_adhoc"] = effective_is_adhoc
        where.append("te.is_adhoc = :is_adhoc")
    if clean_status:
        params["status"] = clean_status
        where.append("ar.status = :status")
    elif not include_removed_by_default:
        where.append("ar.status != 'removed'")
    if search:
        params["search_pattern"] = f"%{search.strip()}%"
        where.append(
            """
            (
                r.name ILIKE :search_pattern
                OR r.mcr ILIKE :search_pattern
                OR r.programme_code ILIKE :search_pattern
                OR te.posting_code ILIKE :search_pattern
                OR pc.display_name ILIKE :search_pattern
                OR te.teaching_name ILIKE :search_pattern
                OR te.smc_event_code ILIKE :search_pattern
            )
            """
        )
    if teaching_event_id is not None:
        params["teaching_event_id"] = str(teaching_event_id)
        where.append("ar.teaching_event_id = :teaching_event_id")
    if teaching_name:
        params["teaching_name_pattern"] = f"%{teaching_name.strip()}%"
        where.append("te.teaching_name ILIKE :teaching_name_pattern")
    if session_type_id is not None:
        params["session_type_id"] = str(session_type_id)
        where.append("te.session_type_id = :session_type_id")
    if submitted_from is not None:
        params["submitted_from"] = submitted_from
        where.append("ar.submitted_at >= :submitted_from")
    if submitted_to is not None:
        params["submitted_to"] = submitted_to
        where.append("ar.submitted_at <= :submitted_to")

    return where or ["true"], params


_SELECT_COLUMNS = """
    ar.id,
    ar.resident_id,
    r.name AS resident_name,
    r.mcr,
    r.programme_code,
    r.r_year AS resident_r_year,
    r.classification AS resident_classification,
    r.status AS resident_status,
    ar.posting_code AS attendance_posting_code,
    ar.teaching_event_id,
    te.posting_code,
    pc.display_name AS posting_display_name,
    pc.institution AS posting_institution,
    pc.department AS posting_department,
    te.teaching_name,
    te.event_date,
    te.start_time,
    te.end_time,
    te.duration_hours,
    te.session_type_id,
    st.name AS session_type_name,
    te.is_adhoc,
    CASE WHEN te.is_adhoc THEN 'Ad-hoc' ELSE 'Secretary Event' END AS source,
    ar.status,
    ar.submitted_at,
    te.cme_points_awarded,
    te.smc_event_code,
    te.created_by_role,
    ar.created_at AS attendance_created_at,
    ar.updated_at AS attendance_updated_at,
    te.created_at AS event_created_at,
    te.updated_at AS event_updated_at
"""


async def list_resident_submissions(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    reporting_period_id: UUID | None,
    programme_code: str | None,
    posting_code: str | None,
    resident_id: UUID | None,
    mcr: str | None,
    date_from: date | None,
    date_to: date | None,
    source: str | None,
    is_adhoc: bool | None,
    status: str | None,
    search: str | None,
    teaching_event_id: UUID | None,
    teaching_name: str | None,
    session_type_id: UUID | None,
    submitted_from: datetime | None,
    submitted_to: datetime | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    where, params = _base_where(
        programme_scope=programme_scope,
        master_admin=master_admin,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        posting_code=posting_code,
        resident_id=resident_id,
        mcr=mcr,
        date_from=date_from,
        date_to=date_to,
        source=source,
        is_adhoc=is_adhoc,
        status=status,
        search=search,
        teaching_event_id=teaching_event_id,
        teaching_name=teaching_name,
        session_type_id=session_type_id,
        submitted_from=submitted_from,
        submitted_to=submitted_to,
    )
    params.update({"limit": limit, "offset": offset})
    where_sql = " AND ".join(f"({clause})" for clause in where)

    result = await db.execute(
        text(
            f"""
            /* admin_resident_submissions:list */
            WITH filtered_submissions AS (
                SELECT
                    {_SELECT_COLUMNS}
                FROM attendance_records ar
                JOIN residents r ON r.id = ar.resident_id
                JOIN teaching_events te ON te.id = ar.teaching_event_id
                LEFT JOIN posting_codes pc ON pc.code = te.posting_code
                LEFT JOIN session_types st ON st.id = te.session_type_id
                WHERE {where_sql}
            )
            SELECT
                filtered_submissions.*,
                COUNT(*) OVER() AS total
            FROM filtered_submissions
            ORDER BY event_date DESC, start_time DESC, submitted_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    rows = [dict(row) for row in result.mappings().all()]

    summary_result = await db.execute(
        text(
            f"""
            /* admin_resident_submissions:summary */
            WITH filtered_submissions AS (
                SELECT
                    ar.id,
                    ar.status,
                    te.is_adhoc
                FROM attendance_records ar
                JOIN residents r ON r.id = ar.resident_id
                JOIN teaching_events te ON te.id = ar.teaching_event_id
                LEFT JOIN posting_codes pc ON pc.code = te.posting_code
                LEFT JOIN session_types st ON st.id = te.session_type_id
                WHERE {where_sql}
            )
            SELECT
                COUNT(*) AS total_submissions,
                COUNT(*) FILTER (WHERE status = 'submitted') AS submitted_count,
                COUNT(*) FILTER (WHERE status = 'flagged') AS flagged_count,
                COUNT(*) FILTER (WHERE status = 'removed') AS removed_count,
                COUNT(*) FILTER (WHERE is_adhoc = false) AS secretary_event_count,
                COUNT(*) FILTER (WHERE is_adhoc = true) AS adhoc_count
            FROM filtered_submissions
            """
        ),
        params,
    )
    summary_row = summary_result.mappings().one_or_none()
    summary = _summary(summary_row)
    total = int(rows[0].get("total") or 0) if rows else summary["total_submissions"]
    return {
        "items": [_list_item(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "summary": summary,
    }


async def get_resident_submission(
    db: AsyncSession,
    *,
    submission_id: UUID,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    where, params = _base_where(
        programme_scope=programme_scope,
        master_admin=master_admin,
        reporting_period_id=None,
        programme_code=None,
        posting_code=None,
        resident_id=None,
        mcr=None,
        date_from=None,
        date_to=None,
        source=None,
        is_adhoc=None,
        status=None,
        search=None,
        teaching_event_id=None,
        teaching_name=None,
        session_type_id=None,
        submitted_from=None,
        submitted_to=None,
        include_removed_by_default=True,
    )
    params["submission_id"] = str(submission_id)
    where.append("ar.id = :submission_id")
    where_sql = " AND ".join(f"({clause})" for clause in where)

    result = await db.execute(
        text(
            f"""
            /* admin_resident_submissions:detail */
            SELECT
                {_SELECT_COLUMNS}
            FROM attendance_records ar
            JOIN residents r ON r.id = ar.resident_id
            JOIN teaching_events te ON te.id = ar.teaching_event_id
            LEFT JOIN posting_codes pc ON pc.code = te.posting_code
            LEFT JOIN session_types st ON st.id = te.session_type_id
            WHERE {where_sql}
            """
        ),
        params,
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise ApiError(
            status_code=404,
            detail="Resident submission not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    return _detail(dict(row))
