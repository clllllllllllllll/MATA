from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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
    """Count only unambiguous, stable Teaching Name impacts for target rows.

    Legacy text-only teaching events are intentionally excluded.  An event has
    no reporting-year field, so same-name/posting/session mappings across years
    are also excluded rather than attributed by guesswork.
    """
    normalized_target_ids = sorted({str(target_id) for target_id in target_ids})
    if not normalized_target_ids:
        return dict(_EMPTY_COUNTS)

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
                    mapping.posting_code,
                    target.session_type_id
                FROM teaching_name_mappings AS mapping
                JOIN teaching_targets AS target
                  ON target.id = mapping.teaching_target_id
                WHERE mapping.teaching_target_id = ANY(CAST(:target_ids AS uuid[]))
            ), safe_events AS (
                SELECT DISTINCT event.id
                FROM affected_mappings AS mapping
                JOIN teaching_events AS event
                  ON event.teaching_name_id = mapping.teaching_name_id
                 AND event.posting_code = mapping.posting_code
                 AND event.session_type_id = mapping.session_type_id
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM teaching_name_mappings AS competing_mapping
                    JOIN teaching_targets AS competing_target
                      ON competing_target.id = competing_mapping.teaching_target_id
                    WHERE competing_mapping.teaching_name_id = mapping.teaching_name_id
                      AND competing_mapping.posting_code = mapping.posting_code
                      AND competing_target.session_type_id = mapping.session_type_id
                      AND competing_mapping.id <> mapping.id
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
