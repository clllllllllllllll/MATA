from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from io import BytesIO
from typing import Any
from uuid import UUID

from openpyxl import Workbook
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.services.upload_validation import sanitize_spreadsheet_cell


VALID_EXTERNAL_ATTENDANCE_STATUSES = {"submitted", "flagged", "removed"}
EXPORT_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _normalise_optional(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _normalise_status(value: str | None) -> str | None:
    normalised = _normalise_optional(value)
    if normalised is None:
        return None
    normalised = normalised.lower()
    if normalised not in VALID_EXTERNAL_ATTENDANCE_STATUSES:
        raise ApiError(
            status_code=422,
            detail="status must be one of submitted, flagged, removed",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    return normalised


def _summary(row: dict[str, Any] | None) -> dict[str, int]:
    row = row or {}
    return {
        "total_records": int(row.get("total_records") or 0),
        "submitted_count": int(row.get("submitted_count") or 0),
        "flagged_count": int(row.get("flagged_count") or 0),
        "removed_count": int(row.get("removed_count") or 0),
        "adhoc_count": int(row.get("adhoc_count") or 0),
    }


def _item(row: dict[str, Any]) -> dict[str, Any]:
    is_adhoc = bool(row.get("is_adhoc"))
    return {
        "id": row["id"],
        "external_resident_id": row["external_resident_id"],
        "resident_name": row["external_resident_name"],
        "mcr": row["mcr"],
        "home_cluster": row["home_cluster"],
        "current_nhg_posting_code": row.get("current_nhg_posting_code"),
        "attendance_posting_code": row.get("attendance_posting_code"),
        "posting_code": row["posting_code"],
        "posting_display_name": row.get("posting_display_name"),
        "teaching_event_id": row["teaching_event_id"],
        "teaching_name": row["teaching_name"],
        "details_of_session": row.get("details_of_session"),
        "event_date": row["event_date"],
        "start_time": row["start_time"],
        "end_time": row.get("end_time"),
        "duration_hours": row.get("duration_hours"),
        "source": row.get("source") or ("Ad-hoc" if is_adhoc else "Secretary Event"),
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
    item = _item(row)
    return {
        **item,
        "attendance_record": {
            "id": row["id"],
            "external_resident_id": row["external_resident_id"],
            "teaching_event_id": row["teaching_event_id"],
            "status": row["status"],
            "attendance_posting_code": row.get("attendance_posting_code"),
            "submitted_at": row["submitted_at"],
            "created_at": row.get("attendance_created_at"),
            "updated_at": row.get("attendance_updated_at"),
        },
        "external_resident": {
            "id": row["external_resident_id"],
            "name": row["external_resident_name"],
            "mcr": row["mcr"],
            "home_cluster": row["home_cluster"],
            "current_nhg_posting_code": row.get("current_nhg_posting_code"),
            "status": row.get("external_resident_status"),
            "identity_label": "Non-NHG Resident",
        },
        "event": {
            "id": row["teaching_event_id"],
            "teaching_name": row["teaching_name"],
            "details_of_session": row.get("details_of_session"),
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
            "identity_scope": "non_nhg_external_attendance_records_only",
            "compliance_included": False,
            "export_only": True,
        },
    }


def _base_where(
    *,
    programme_scope: set[str],
    master_admin: bool,
    programme_code: str | None,
    home_cluster: str | None,
    posting_code: str | None,
    mcr: str | None,
    status: str | None,
    date_from: date | None,
    date_to: date | None,
    attendance_id: UUID | None = None,
) -> tuple[list[str], dict[str, Any]]:
    clean_programme_code = _normalise_optional(programme_code)
    clean_home_cluster = _normalise_optional(home_cluster)
    clean_posting_code = _normalise_optional(posting_code)
    clean_mcr = _normalise_optional(mcr)
    clean_status = _normalise_status(status)

    if not master_admin:
        if not programme_scope:
            raise ApiError(
                status_code=403,
                detail="Forbidden - admin programme scope is empty",
                error_code=ErrorCode.FORBIDDEN.value,
            )
        if clean_programme_code is not None and clean_programme_code not in programme_scope:
            raise ApiError(
                status_code=403,
                detail="Forbidden - programme not in admin scope",
                error_code=ErrorCode.FORBIDDEN.value,
            )

    where: list[str] = []
    params: dict[str, Any] = {}
    if not master_admin:
        params["programme_scope"] = sorted(programme_scope)
        where.append(
            """
            EXISTS (
                SELECT 1
                FROM teaching_name_catalogue tnc_scope
                WHERE tnc_scope.posting_code = te.posting_code
                  AND tnc_scope.programme_code = ANY(:programme_scope)
            )
            """
        )
    if clean_programme_code is not None:
        params["programme_code"] = clean_programme_code
        where.append(
            """
            EXISTS (
                SELECT 1
                FROM teaching_name_catalogue tnc_programme
                WHERE tnc_programme.posting_code = te.posting_code
                  AND tnc_programme.programme_code = :programme_code
            )
            """
        )
    if attendance_id is not None:
        params["attendance_id"] = str(attendance_id)
        where.append("ear.id = :attendance_id")
    if clean_home_cluster:
        params["home_cluster"] = clean_home_cluster
        where.append("er.home_cluster = :home_cluster")
    if clean_posting_code:
        params["posting_code"] = clean_posting_code
        where.append("te.posting_code = :posting_code")
    if clean_mcr:
        params["mcr"] = clean_mcr
        where.append("LOWER(er.mcr) = LOWER(:mcr)")
    if clean_status:
        params["status"] = clean_status
        where.append("ear.status = :status")
    else:
        where.append("ear.status != 'removed'")
    if date_from is not None:
        params["date_from"] = date_from
        where.append("te.event_date >= :date_from")
    if date_to is not None:
        params["date_to"] = date_to
        where.append("te.event_date <= :date_to")
    return where or ["true"], params


_SELECT_COLUMNS = """
    ear.id,
    ear.external_resident_id,
    er.name AS external_resident_name,
    er.mcr,
    er.home_cluster,
    er.current_nhg_posting_code,
    er.status AS external_resident_status,
    ear.posting_code AS attendance_posting_code,
    ear.teaching_event_id,
    te.posting_code,
    pc.display_name AS posting_display_name,
    pc.institution AS posting_institution,
    pc.department AS posting_department,
    te.teaching_name,
    te.details_of_session,
    te.event_date,
    te.start_time,
    te.end_time,
    te.duration_hours,
    te.session_type_id,
    st.name AS session_type_name,
    te.is_adhoc,
    CASE WHEN te.is_adhoc THEN 'Ad-hoc' ELSE 'Secretary Event' END AS source,
    ear.status,
    ear.submitted_at,
    te.cme_points_awarded,
    te.smc_event_code,
    te.created_by_role,
    ear.created_at AS attendance_created_at,
    ear.updated_at AS attendance_updated_at,
    te.created_at AS event_created_at,
    te.updated_at AS event_updated_at
"""


async def list_external_attendance(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    programme_code: str | None,
    home_cluster: str | None,
    posting_code: str | None,
    mcr: str | None,
    status: str | None,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    where, params = _base_where(
        programme_scope=programme_scope,
        master_admin=master_admin,
        programme_code=programme_code,
        home_cluster=home_cluster,
        posting_code=posting_code,
        mcr=mcr,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    params.update({"limit": limit, "offset": offset})
    where_sql = " AND ".join(f"({clause})" for clause in where)

    result = await db.execute(
        text(
            f"""
            /* admin_external_attendance:list */
            WITH filtered_external_attendance AS (
                SELECT
                    {_SELECT_COLUMNS}
                FROM external_attendance_records ear
                JOIN external_residents er ON er.id = ear.external_resident_id
                JOIN teaching_events te ON te.id = ear.teaching_event_id
                LEFT JOIN posting_codes pc ON pc.code = te.posting_code
                LEFT JOIN session_types st ON st.id = te.session_type_id
                WHERE {where_sql}
            )
            SELECT
                filtered_external_attendance.*,
                COUNT(*) OVER() AS total
            FROM filtered_external_attendance
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
            /* admin_external_attendance:summary */
            WITH filtered_external_attendance AS (
                SELECT
                    ear.id,
                    ear.status,
                    te.is_adhoc
                FROM external_attendance_records ear
                JOIN external_residents er ON er.id = ear.external_resident_id
                JOIN teaching_events te ON te.id = ear.teaching_event_id
                LEFT JOIN posting_codes pc ON pc.code = te.posting_code
                LEFT JOIN session_types st ON st.id = te.session_type_id
                WHERE {where_sql}
            )
            SELECT
                COUNT(*) AS total_records,
                COUNT(*) FILTER (WHERE status = 'submitted') AS submitted_count,
                COUNT(*) FILTER (WHERE status = 'flagged') AS flagged_count,
                COUNT(*) FILTER (WHERE status = 'removed') AS removed_count,
                COUNT(*) FILTER (WHERE is_adhoc = true) AS adhoc_count
            FROM filtered_external_attendance
            """
        ),
        params,
    )
    summary = _summary(dict(summary_result.mappings().one_or_none() or {}))
    return {
        "items": [_item(row) for row in rows],
        "total": summary["total_records"],
        "limit": limit,
        "offset": offset,
        "summary": summary,
    }


async def get_external_attendance(
    db: AsyncSession,
    *,
    attendance_id: UUID,
    programme_scope: set[str],
    master_admin: bool,
) -> dict[str, Any]:
    where, params = _base_where(
        programme_scope=programme_scope,
        master_admin=master_admin,
        programme_code=None,
        home_cluster=None,
        posting_code=None,
        mcr=None,
        status=None,
        date_from=None,
        date_to=None,
        attendance_id=attendance_id,
    )
    where_sql = " AND ".join(f"({clause})" for clause in where)
    result = await db.execute(
        text(
            f"""
            /* admin_external_attendance:get */
            SELECT
                {_SELECT_COLUMNS}
            FROM external_attendance_records ear
            JOIN external_residents er ON er.id = ear.external_resident_id
            JOIN teaching_events te ON te.id = ear.teaching_event_id
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
            detail="External attendance record not found",
            error_code=ErrorCode.NOT_FOUND.value,
        )
    return _detail(dict(row))


def _export_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str):
        return sanitize_spreadsheet_cell(value)
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    if isinstance(value, time) and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _xlsx_bytes(rows: list[dict[str, Any]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Non-NHG Attendance"
    columns = [
        ("Home Cluster", "home_cluster"),
        ("Resident Name", "external_resident_name"),
        ("MCR", "mcr"),
        ("Current NHG Posting", "current_nhg_posting_code"),
        ("Event Posting", "posting_code"),
        ("Posting Name", "posting_display_name"),
        ("Teaching Name", "teaching_name"),
        ("Details of Session", "details_of_session"),
        ("Event Date", "event_date"),
        ("Start Time", "start_time"),
        ("End Time", "end_time"),
        ("Duration Hours", "duration_hours"),
        ("Source", "source"),
        ("Status", "status"),
        ("Submitted At", "submitted_at"),
    ]
    sheet.append([header for header, _key in columns])
    for row in rows:
        sheet.append([_export_value(row.get(key)) for _header, key in columns])
    for column_cells in sheet.columns:
        header_value = str(column_cells[0].value or "")
        sheet.column_dimensions[column_cells[0].column_letter].width = min(
            max(len(header_value) + 2, 14),
            28,
        )
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def export_external_attendance_xlsx(
    db: AsyncSession,
    *,
    programme_scope: set[str],
    master_admin: bool,
    programme_code: str | None,
    home_cluster: str | None,
    posting_code: str | None,
    mcr: str | None,
    status: str | None,
    date_from: date | None,
    date_to: date | None,
) -> dict[str, Any]:
    where, params = _base_where(
        programme_scope=programme_scope,
        master_admin=master_admin,
        programme_code=programme_code,
        home_cluster=home_cluster,
        posting_code=posting_code,
        mcr=mcr,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    where_sql = " AND ".join(f"({clause})" for clause in where)
    result = await db.execute(
        text(
            f"""
            /* admin_external_attendance:export */
            SELECT
                {_SELECT_COLUMNS}
            FROM external_attendance_records ear
            JOIN external_residents er ON er.id = ear.external_resident_id
            JOIN teaching_events te ON te.id = ear.teaching_event_id
            LEFT JOIN posting_codes pc ON pc.code = te.posting_code
            LEFT JOIN session_types st ON st.id = te.session_type_id
            WHERE {where_sql}
            ORDER BY te.event_date DESC, te.start_time DESC, ear.submitted_at DESC
            """
        ),
        params,
    )
    rows = [dict(row) for row in result.mappings().all()]
    return {
        "filename": "non-nhg-attendance.xlsx",
        "content": _xlsx_bytes(rows),
        "media_type": EXPORT_MEDIA_TYPE,
    }
