from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.staff_actor import StaffActorContext
from app.errors import ApiError, ErrorCode
from app.security import log_safe_exception
from app.services import cache_invalidation
from app.services.audit import write_audit_log


logger = logging.getLogger(__name__)


SOURCE_SECRETARY = "secretary"
SOURCE_PROGRAMME_PC = "programme_pc"
SOURCE_ALL = "all"
_SOURCE_TYPES = {SOURCE_ALL, SOURCE_SECRETARY, SOURCE_PROGRAMME_PC}


def _source_type(created_for_programme_code: str | None) -> str:
    return (
        SOURCE_PROGRAMME_PC
        if created_for_programme_code is not None
        else SOURCE_SECRETARY
    )


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
    source_type: str,
) -> tuple[list[str], dict[str, Any]]:
    if source_type not in _SOURCE_TYPES:
        raise ApiError(
            status_code=422,
            detail="Invalid teaching event source filter",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )

    where = ["te.is_adhoc = false"]
    params: dict[str, Any] = {}

    if source_type == SOURCE_SECRETARY:
        where.append("te.created_for_programme_code IS NULL")
    elif source_type == SOURCE_PROGRAMME_PC:
        where.append("te.created_for_programme_code IS NOT NULL")

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
        where.append(f"{attendance_predicate} = :has_attendance")
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
    te.created_for_programme_code,
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
    (
        SELECT COUNT(*)
        FROM attendance_records ar
        WHERE ar.teaching_event_id = te.id
    ) AS native_attendance_count,
    (
        SELECT COUNT(*)
        FROM external_attendance_records ear
        WHERE ear.teaching_event_id = te.id
    ) AS non_nhg_attendance_count,
    te.created_at,
    te.updated_at
"""


def _list_item(row: dict[str, Any]) -> dict[str, Any]:
    attendance_count = int(row.get("attendance_count") or 0)
    external_attendance_count = int(row.get("external_attendance_count") or 0)
    native_attendance_count = int(
        row.get("native_attendance_count", attendance_count) or 0
    )
    non_nhg_attendance_count = int(
        row.get("non_nhg_attendance_count", external_attendance_count) or 0
    )
    total_attendance_count = native_attendance_count + non_nhg_attendance_count
    series_id = row.get("series_id")
    is_adhoc = bool(row.get("is_adhoc", False))
    source_type = _source_type(row.get("created_for_programme_code"))
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
        "is_adhoc": is_adhoc,
        "attendance_count": attendance_count,
        "native_attendance_count": native_attendance_count,
        "external_attendance_count": external_attendance_count,
        "non_nhg_attendance_count": non_nhg_attendance_count,
        "total_attendance_count": total_attendance_count,
        "has_attendance": (attendance_count + external_attendance_count) > 0,
        "source_type": source_type,
        "created_by_role": row.get("created_by_role"),
        "created_for_programme_code": row.get("created_for_programme_code"),
        "force_delete_allowed": not is_adhoc
        and source_type in {SOURCE_SECRETARY, SOURCE_PROGRAMME_PC},
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
    source_type: str = SOURCE_ALL,
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
        source_type=source_type,
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
    native_attendance_count = item["native_attendance_count"]
    non_nhg_attendance_count = item["non_nhg_attendance_count"]
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
            "native": native_attendance_count,
            "external": non_nhg_attendance_count,
            "total": native_attendance_count + non_nhg_attendance_count,
        },
        "notes": {
            "event_source": f"{item['source_type']}_scheduled",
            "session_type_authority": "display_only",
        },
    }


def _is_foreign_key_conflict(exc: IntegrityError) -> bool:
    original = getattr(exc, "orig", None)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return sqlstate == "23503"


def _require_master_admin_actor(actor: StaffActorContext) -> None:
    admin_level = (actor.actor_admin_level or "").strip().lower()
    if actor.actor_role != "admin" or admin_level != "master":
        raise ApiError(
            status_code=403,
            detail="Forbidden - master admin access required",
            error_code=ErrorCode.FORBIDDEN.value,
        )


async def force_delete_event(
    db: AsyncSession,
    *,
    event_id: UUID,
    reason: str,
    expected_native_attendance_count: int,
    expected_external_attendance_count: int,
    actor: StaffActorContext,
) -> dict[str, Any]:
    """Hard-delete one scheduled event occurrence and its linked attendance atomically."""

    event_snapshot: dict[str, Any] | None = None
    result_payload: dict[str, Any] | None = None
    try:
        _require_master_admin_actor(actor)
        deletion_reason = reason.strip()
        if not deletion_reason:
            raise ApiError(
                status_code=422,
                detail="Deletion reason is required",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )

        event_result = await db.execute(
            text(
                """
                /* admin_secretary_events:force_delete_lock */
                SELECT
                    te.id,
                    te.posting_code,
                    te.created_for_programme_code,
                    te.teaching_name,
                    te.details_of_session,
                    te.event_date,
                    te.start_time,
                    te.end_time,
                    te.duration_hours,
                    te.session_type_id,
                    te.series_id,
                    te.cme_points_awarded,
                    te.smc_event_code,
                    te.is_adhoc,
                    te.created_by_role,
                    te.created_at,
                    te.updated_at
                FROM teaching_events te
                WHERE te.id = :event_id
                FOR UPDATE OF te
                """
            ),
            {"event_id": str(event_id)},
        )
        locked_row = event_result.mappings().one_or_none()
        if locked_row is None:
            raise ApiError(
                status_code=404,
                detail="Teaching event not found",
                error_code=ErrorCode.NOT_FOUND.value,
            )

        event_snapshot = dict(locked_row)
        if bool(event_snapshot.get("is_adhoc")):
            raise ApiError(
                status_code=422,
                detail="Ad-hoc teaching events cannot be force deleted from this surface",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )

        source_type = _source_type(event_snapshot.get("created_for_programme_code"))
        counts_result = await db.execute(
            text(
                """
                /* admin_secretary_events:force_delete_counts */
                SELECT
                    (
                        SELECT COUNT(*)
                        FROM attendance_records ar
                        WHERE ar.teaching_event_id = :event_id
                    ) AS native_attendance_count,
                    (
                        SELECT COUNT(*)
                        FROM external_attendance_records ear
                        WHERE ear.teaching_event_id = :event_id
                    ) AS external_attendance_count
                """
            ),
            {"event_id": str(event_id)},
        )
        counts = dict(counts_result.mappings().one())
        native_attendance_count = int(counts.get("native_attendance_count") or 0)
        external_attendance_count = int(counts.get("external_attendance_count") or 0)
        if (
            native_attendance_count != expected_native_attendance_count
            or external_attendance_count != expected_external_attendance_count
        ):
            raise ApiError(
                status_code=409,
                detail=(
                    "Linked attendance changed since confirmation; "
                    "review the updated impact and retry"
                ),
                error_code=ErrorCode.CONFLICT.value,
            )

        native_delete_result = await db.execute(
            text(
                """
                /* admin_secretary_events:force_delete_native_attendance */
                DELETE FROM attendance_records
                WHERE teaching_event_id = :event_id
                RETURNING id
                """
            ),
            {"event_id": str(event_id)},
        )
        native_deleted = len(native_delete_result.mappings().all())

        external_delete_result = await db.execute(
            text(
                """
                /* admin_secretary_events:force_delete_external_attendance */
                DELETE FROM external_attendance_records
                WHERE teaching_event_id = :event_id
                RETURNING id
                """
            ),
            {"event_id": str(event_id)},
        )
        external_deleted = len(external_delete_result.mappings().all())

        if (
            native_deleted != native_attendance_count
            or external_deleted != external_attendance_count
        ):
            raise ApiError(
                status_code=409,
                detail="Teaching event attendance changed during deletion; please retry",
                error_code=ErrorCode.CONFLICT.value,
            )

        event_delete_result = await db.execute(
            text(
                """
                /* admin_secretary_events:force_delete_event */
                DELETE FROM teaching_events
                WHERE id = :event_id
                RETURNING id
                """
            ),
            {"event_id": str(event_id)},
        )
        if event_delete_result.mappings().one_or_none() is None:
            raise ApiError(
                status_code=409,
                detail="Teaching event changed during deletion; please retry",
                error_code=ErrorCode.CONFLICT.value,
            )

        deleted_at = datetime.now(timezone.utc)
        total_deleted = native_deleted + external_deleted
        result_payload = {
            "event_id": event_id,
            "deleted": True,
            "source_type": source_type,
            "native_attendance_deleted": native_deleted,
            "external_attendance_deleted": external_deleted,
            "total_attendance_deleted": total_deleted,
        }
        await write_audit_log(
            db,
            actor=actor,
            action="admin.teaching_event.force_delete",
            entity_type="teaching_event",
            entity_id=event_id,
            before=event_snapshot,
            after={
                "deleted": True,
                "native_attendance_deleted": native_deleted,
                "external_attendance_deleted": external_deleted,
                "total_attendance_deleted": total_deleted,
                "deleted_at": deleted_at,
            },
            metadata={
                "route_context": "master_admin_secretary_pc_events",
                "deletion_reason": deletion_reason,
                "event_id": str(event_id),
                "event_source_type": source_type,
                "posting_code": event_snapshot["posting_code"],
                "owner_programme_code": event_snapshot.get(
                    "created_for_programme_code"
                ),
                "event_date": event_snapshot["event_date"],
                "teaching_name": event_snapshot["teaching_name"],
                "series_id": event_snapshot.get("series_id"),
                "native_attendance_deleted": native_deleted,
                "external_attendance_deleted": external_deleted,
                "total_attendance_deleted": total_deleted,
                "deleted_at": deleted_at,
                "attendance_identifiers_included": False,
            },
        )
        await db.commit()
    except ApiError:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        if _is_foreign_key_conflict(exc):
            raise ApiError(
                status_code=409,
                detail="Teaching event attendance changed during deletion; please retry",
                error_code=ErrorCode.CONFLICT.value,
            ) from exc
        raise
    except Exception:
        await db.rollback()
        raise

    assert event_snapshot is not None
    assert result_payload is not None
    try:
        cache_invalidation.invalidate_after_admin_event_force_delete(
            event_id=event_id,
            posting_code=event_snapshot["posting_code"],
            programme_code=event_snapshot.get("created_for_programme_code"),
        )
    except Exception as exc:
        log_safe_exception(
            logger,
            "admin_teaching_event_cache_invalidation_failed",
            exc,
            category="cache_invalidation",
        )
    return result_payload
