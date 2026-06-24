from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode


def _base_where(
    *,
    reporting_period_id: UUID | None,
    posting_code: str | None,
    date_from: date | None,
    date_to: date | None,
    teaching_name: str | None,
    search: str | None,
    has_attendance: bool | None,
    session_type_id: UUID | None,
    series_id: UUID | None,
) -> tuple[list[str], dict[str, Any]]:
    where = [
        "te.is_adhoc = false",
        "(te.created_by_role = 'secretary' OR te.created_by_role IS NULL)",
    ]
    params: dict[str, Any] = {}

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
        params["posting_code"] = posting_code
        where.append("te.posting_code = :posting_code")
    if date_from is not None:
        params["date_from"] = date_from
        where.append("te.event_date >= :date_from")
    if date_to is not None:
        params["date_to"] = date_to
        where.append("te.event_date <= :date_to")
    if teaching_name:
        params["teaching_name_pattern"] = f"%{teaching_name.strip()}%"
        where.append("te.teaching_name ILIKE :teaching_name_pattern")
    if search:
        params["search_pattern"] = f"%{search.strip()}%"
        where.append(
            """
            (
                te.teaching_name ILIKE :search_pattern
                OR te.posting_code ILIKE :search_pattern
                OR pc.display_name ILIKE :search_pattern
                OR te.smc_event_code ILIKE :search_pattern
            )
            """
        )
    if has_attendance is not None:
        params["has_attendance"] = has_attendance
        attendance_predicate = """
            (
                EXISTS (
                    SELECT 1
                    FROM attendance_records ar
                    WHERE ar.teaching_event_id = te.id
                      AND ar.status = 'submitted'
                )
                OR EXISTS (
                    SELECT 1
                    FROM external_attendance_records ear
                    WHERE ear.teaching_event_id = te.id
                      AND ear.status = 'submitted'
                )
            )
        """
        if has_attendance:
            where.append(attendance_predicate)
        else:
            where.append(f"NOT {attendance_predicate}")
    if session_type_id is not None:
        params["session_type_id"] = str(session_type_id)
        where.append("te.session_type_id = :session_type_id")
    if series_id is not None:
        params["series_id"] = str(series_id)
        where.append("te.series_id = :series_id")

    return where, params


_EVENT_SELECT_COLUMNS = """
    te.id,
    te.posting_code,
    pc.display_name AS posting_display_name,
    pc.institution AS posting_institution,
    pc.department AS posting_department,
    te.teaching_name,
    te.event_date,
    te.start_time,
    te.end_time,
    te.duration_hours,
    te.cme_points_awarded,
    te.smc_event_code,
    te.session_type_id,
    st.name AS session_type_name,
    te.series_id,
    te.is_adhoc,
    te.created_by_role,
    (
        SELECT COUNT(*)
        FROM attendance_records ar
        WHERE ar.teaching_event_id = te.id
          AND ar.status = 'submitted'
    ) AS attendance_count,
    (
        SELECT COUNT(*)
        FROM external_attendance_records ear
        WHERE ear.teaching_event_id = te.id
          AND ear.status = 'submitted'
    ) AS external_attendance_count,
    te.created_at,
    te.updated_at
"""


def _list_item(row: dict[str, Any]) -> dict[str, Any]:
    attendance_count = int(row.get("attendance_count") or 0)
    external_attendance_count = int(row.get("external_attendance_count") or 0)
    series_id = row.get("series_id")
    return {
        "id": row["id"],
        "teaching_name": row["teaching_name"],
        "posting_code": row["posting_code"],
        "posting_display_name": row.get("posting_display_name"),
        "event_date": row["event_date"],
        "start_time": row["start_time"],
        "end_time": row.get("end_time"),
        "duration_hours": row.get("duration_hours"),
        "cme_points_awarded": row.get("cme_points_awarded", False),
        "smc_event_code": row.get("smc_event_code"),
        "session_type_id": row.get("session_type_id"),
        "session_type_name": row.get("session_type_name"),
        "series_id": series_id,
        "is_recurring": series_id is not None,
        "attendance_count": attendance_count,
        "external_attendance_count": external_attendance_count,
        "has_attendance": (attendance_count + external_attendance_count) > 0,
        "created_by_role": row.get("created_by_role"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _summary(row: dict[str, Any] | None) -> dict[str, int]:
    if row is None:
        row = {}
    return {
        "total_events": int(row.get("total_events") or 0),
        "with_attendance": int(row.get("with_attendance") or 0),
        "without_attendance": int(row.get("without_attendance") or 0),
        "total_attendance_count": int(row.get("total_attendance_count") or 0),
        "total_external_attendance_count": int(
            row.get("total_external_attendance_count") or 0
        ),
    }


async def list_secretary_events(
    db: AsyncSession,
    *,
    reporting_period_id: UUID | None,
    posting_code: str | None,
    date_from: date | None,
    date_to: date | None,
    teaching_name: str | None,
    search: str | None,
    has_attendance: bool | None,
    limit: int,
    offset: int,
    session_type_id: UUID | None = None,
    series_id: UUID | None = None,
) -> dict[str, Any]:
    where, params = _base_where(
        reporting_period_id=reporting_period_id,
        posting_code=posting_code,
        date_from=date_from,
        date_to=date_to,
        teaching_name=teaching_name,
        search=search,
        has_attendance=has_attendance,
        session_type_id=session_type_id,
        series_id=series_id,
    )
    params.update({"limit": limit, "offset": offset})
    where_sql = " AND ".join(f"({clause})" for clause in where)

    result = await db.execute(
        text(
            f"""
            /* admin_secretary_events:list */
            WITH filtered_events AS (
                SELECT
                    {_EVENT_SELECT_COLUMNS}
                FROM teaching_events te
                LEFT JOIN posting_codes pc ON pc.code = te.posting_code
                LEFT JOIN session_types st ON st.id = te.session_type_id
                WHERE {where_sql}
            )
            SELECT
                filtered_events.*,
                COUNT(*) OVER() AS total
            FROM filtered_events
            ORDER BY event_date ASC, start_time ASC, teaching_name ASC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    rows = [dict(row) for row in result.mappings().all()]

    summary_result = await db.execute(
        text(
            f"""
            /* admin_secretary_events:summary */
            WITH filtered_events AS (
                SELECT
                    te.id,
                    (
                        SELECT COUNT(*)
                        FROM attendance_records ar
                        WHERE ar.teaching_event_id = te.id
                          AND ar.status = 'submitted'
                    ) AS attendance_count,
                    (
                        SELECT COUNT(*)
                        FROM external_attendance_records ear
                        WHERE ear.teaching_event_id = te.id
                          AND ear.status = 'submitted'
                    ) AS external_attendance_count
                FROM teaching_events te
                LEFT JOIN posting_codes pc ON pc.code = te.posting_code
                LEFT JOIN session_types st ON st.id = te.session_type_id
                WHERE {where_sql}
            )
            SELECT
                COUNT(*) AS total_events,
                COUNT(*) FILTER (
                    WHERE attendance_count > 0 OR external_attendance_count > 0
                ) AS with_attendance,
                COUNT(*) FILTER (
                    WHERE attendance_count = 0 AND external_attendance_count = 0
                ) AS without_attendance,
                COALESCE(SUM(attendance_count), 0) AS total_attendance_count,
                COALESCE(SUM(external_attendance_count), 0) AS total_external_attendance_count
            FROM filtered_events
            """
        ),
        params,
    )
    summary_row = summary_result.mappings().one_or_none()
    total = int(rows[0].get("total") or 0) if rows else _summary(summary_row)["total_events"]

    return {
        "items": [_list_item(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "summary": _summary(summary_row),
    }


async def get_secretary_event(
    db: AsyncSession,
    *,
    event_id: UUID,
) -> dict[str, Any]:
    result = await db.execute(
        text(
            f"""
            /* admin_secretary_events:detail */
            SELECT
                {_EVENT_SELECT_COLUMNS},
                es.recurrence_pattern,
                es.recurrence_interval,
                es.days_of_week,
                es.end_type AS series_end_type,
                es.end_date AS series_end_date,
                es.end_after_count AS series_end_after_count
            FROM teaching_events te
            LEFT JOIN posting_codes pc ON pc.code = te.posting_code
            LEFT JOIN session_types st ON st.id = te.session_type_id
            LEFT JOIN event_series es ON es.id = te.series_id
            WHERE te.id = :event_id
              AND te.is_adhoc = false
              AND (te.created_by_role = 'secretary' OR te.created_by_role IS NULL)
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

    data = dict(row)
    item = _list_item(data)
    attendance_count = item["attendance_count"]
    external_attendance_count = item["external_attendance_count"]
    recurrence = None
    if item["series_id"] is not None:
        recurrence = {
            "series_id": item["series_id"],
            "recurrence_pattern": data.get("recurrence_pattern"),
            "recurrence_interval": data.get("recurrence_interval"),
            "days_of_week": data.get("days_of_week") or [],
            "end_type": data.get("series_end_type"),
            "end_date": data.get("series_end_date"),
            "end_after_count": data.get("series_end_after_count"),
        }

    return {
        **item,
        "posting": {
            "code": data["posting_code"],
            "display_name": data.get("posting_display_name"),
            "institution": data.get("posting_institution"),
            "department": data.get("posting_department"),
        },
        "recurrence": recurrence,
        "attendance_counts": {
            "native": attendance_count,
            "external": external_attendance_count,
            "total": attendance_count + external_attendance_count,
        },
        "notes": {
            "event_source": "secretary_scheduled_legacy"
            if item["created_by_role"] is None
            else "secretary_scheduled",
            "session_type_authority": "display_only",
        },
    }

