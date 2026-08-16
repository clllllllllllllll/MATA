from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database_context import RLS_ENABLED_INFO_KEY


_EMPTY_COUNTS = {
    "mapped_target_count": 0,
    "affected_event_count": 0,
    "affected_attendance_count": 0,
}


async def stable_target_mapping_impact_counts(
    db: AsyncSession,
    *,
    target_ids: Iterable[UUID | str],
    include_events: bool = True,
) -> dict[str, int]:
    """Count stable Teaching Name impacts for target rows.

    Legacy text-only events are excluded. A pool event has no R-year field, so
    any changed exact R-year mapping can change that stable name/posting event's
    staff envelope and is counted without display-text inference.
    """
    normalized_target_ids = sorted({str(target_id) for target_id in target_ids})
    if not normalized_target_ids:
        return dict(_EMPTY_COUNTS)

    rls_enabled = bool(
        getattr(db, "info", {}).get(RLS_ENABLED_INFO_KEY, False)
    )
    if rls_enabled:
        impact_result = await db.execute(
            text(
                """
                SELECT
                    mapped_target_count,
                    affected_event_count,
                    affected_attendance_count
                FROM mata_rls.teaching_target_mapping_impacts(
                    CAST(:target_ids AS uuid[])
                )
                """
            ),
            {"target_ids": normalized_target_ids},
        )
        impact_row: dict[str, Any] | None = impact_result.mappings().one_or_none()
        if impact_row is None:
            return dict(_EMPTY_COUNTS)
        counts = {
            "mapped_target_count": int(impact_row["mapped_target_count"] or 0),
            "affected_event_count": int(impact_row["affected_event_count"] or 0),
            "affected_attendance_count": int(
                impact_row["affected_attendance_count"] or 0
            ),
        }
        if not include_events:
            counts["affected_event_count"] = 0
            counts["affected_attendance_count"] = 0
        return counts

    mapped_result = await db.execute(
        text(
            """
            /* teaching_target_impacts:mapped_count */
            SELECT COUNT(*)
            FROM teaching_name_mappings
            WHERE teaching_target_id = ANY(CAST(:target_ids AS uuid[]))
            """
        ),
        {"target_ids": normalized_target_ids},
    )
    counts = {
        **_EMPTY_COUNTS,
        "mapped_target_count": int(mapped_result.scalar() or 0),
    }
    if not include_events:
        return counts

    impact_result = await db.execute(
        text(
            """
            /* teaching_target_impacts:stable_events */
            WITH affected_mappings AS (
                SELECT
                    mapping.id,
                    mapping.teaching_name_id,
                    mapping.reporting_period_id,
                    mapping.programme_code AS mapping_programme_code,
                    mapping.posting_code,
                    name.programme_code AS source_programme_code
                FROM teaching_name_mappings AS mapping
                JOIN teaching_names AS name
                  ON name.id = mapping.teaching_name_id
                WHERE mapping.teaching_target_id = ANY(CAST(:target_ids AS uuid[]))
            ), safe_events AS (
                SELECT DISTINCT event.id
                FROM affected_mappings AS mapping
                JOIN teaching_events AS event
                  ON event.teaching_name_id = mapping.teaching_name_id
                 AND event.source_reporting_period_id = mapping.reporting_period_id
                 AND event.source_programme_code = mapping.source_programme_code
                 AND event.posting_code = mapping.posting_code
                 AND event.global_session_type_id IS NULL
                 AND event.is_adhoc = false
                 AND (
                     event.created_for_programme_code IS NULL
                     OR event.created_for_programme_code
                        = mapping.mapping_programme_code
                 )
            )
            SELECT
                COUNT(DISTINCT event.id) AS affected_event_count,
                COUNT(DISTINCT attendance.id) AS native_attendance_count,
                COUNT(DISTINCT external_attendance.id) AS external_attendance_count
            FROM safe_events
            LEFT JOIN teaching_events AS event ON event.id = safe_events.id
            LEFT JOIN attendance_records AS attendance
              ON attendance.teaching_event_id = event.id
             AND attendance.status = 'submitted'
            LEFT JOIN external_attendance_records AS external_attendance
              ON external_attendance.teaching_event_id = event.id
             AND external_attendance.status = 'submitted'
            """
        ),
        {"target_ids": normalized_target_ids},
    )
    impact_row: dict[str, Any] | None = impact_result.mappings().one_or_none()
    if impact_row is None:
        return counts
    counts["affected_event_count"] = int(impact_row["affected_event_count"] or 0)
    counts["affected_attendance_count"] = int(
        impact_row["native_attendance_count"] or 0
    ) + int(impact_row["external_attendance_count"] or 0)
    return counts
