from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode


DEFAULT_POOL_EVENT_DURATION_HOURS = Decimal("1.00")


@dataclass(frozen=True, slots=True)
class PoolEventTiming:
    duration_hours: Decimal
    is_mapped: bool


@dataclass(frozen=True, slots=True)
class PoolEventTimingScope:
    teaching_name_id: UUID | str
    reporting_period_id: UUID | str
    programme_code: str
    posting_code: str


def _conflicting_duration_error(*, posting_code: str) -> ApiError:
    return ApiError(
        status_code=409,
        detail=(
            "Teaching Name mappings for this posting have conflicting durations. "
            "Align the Programme PC mappings before scheduling teaching."
        ),
        error_code=ErrorCode.CONFLICT.value,
        metadata={"posting_code": posting_code},
    )


async def resolve_pool_event_timing(
    db: AsyncSession,
    *,
    scope: PoolEventTimingScope,
) -> PoolEventTiming:
    """Resolve one effective duration across the scope's mapped R-year rows."""

    result = await db.execute(
        text(
            """
            /* pool_event_timing:resolve */
            SELECT DISTINCT session_type.duration_hours
            FROM teaching_name_mappings AS mapping
            JOIN teaching_targets AS target
              ON target.id = mapping.teaching_target_id
            JOIN session_types AS session_type
              ON session_type.id = target.session_type_id
            WHERE mapping.teaching_name_id = :teaching_name_id
              AND mapping.reporting_period_id = :reporting_period_id
              AND mapping.programme_code = :programme_code
              AND mapping.posting_code = :posting_code
              AND mapping.teaching_target_id IS NOT NULL
            ORDER BY session_type.duration_hours ASC
            """
        ),
        {
            "teaching_name_id": str(scope.teaching_name_id),
            "reporting_period_id": str(scope.reporting_period_id),
            "programme_code": scope.programme_code,
            "posting_code": scope.posting_code,
        },
    )
    durations = {
        Decimal(str(row["duration_hours"]))
        for row in result.mappings().all()
        if row.get("duration_hours") is not None
    }
    if len(durations) > 1:
        raise _conflicting_duration_error(posting_code=scope.posting_code)
    if not durations:
        return PoolEventTiming(
            duration_hours=DEFAULT_POOL_EVENT_DURATION_HOURS,
            is_mapped=False,
        )
    return PoolEventTiming(duration_hours=durations.pop(), is_mapped=True)


async def list_pool_event_timings(
    db: AsyncSession,
    *,
    teaching_name_ids: Sequence[UUID | str],
    reporting_period_id: UUID | str,
    programme_code: str,
    posting_code: str | None = None,
) -> dict[tuple[str, str], PoolEventTiming]:
    """Resolve all persisted name/posting scopes in one bounded query."""

    if not teaching_name_ids:
        return {}
    result = await db.execute(
        text(
            """
            /* pool_event_timing:list */
            SELECT
                mapping.teaching_name_id,
                mapping.posting_code,
                session_type.duration_hours
            FROM teaching_name_mappings AS mapping
            LEFT JOIN teaching_targets AS target
              ON target.id = mapping.teaching_target_id
            LEFT JOIN session_types AS session_type
              ON session_type.id = target.session_type_id
            WHERE mapping.teaching_name_id = ANY(CAST(:teaching_name_ids AS uuid[]))
              AND mapping.reporting_period_id = :reporting_period_id
              AND mapping.programme_code = :programme_code
              AND (
                  CAST(:posting_code AS text) IS NULL
                  OR mapping.posting_code = CAST(:posting_code AS text)
              )
            ORDER BY mapping.teaching_name_id ASC, mapping.posting_code ASC
            """
        ),
        {
            "teaching_name_ids": [str(value) for value in teaching_name_ids],
            "reporting_period_id": str(reporting_period_id),
            "programme_code": programme_code,
            "posting_code": posting_code,
        },
    )
    durations_by_scope: defaultdict[tuple[str, str], set[Decimal]] = defaultdict(set)
    for row in result.mappings().all():
        key = (str(row["teaching_name_id"]), str(row["posting_code"]))
        durations_by_scope[key]
        if row.get("duration_hours") is not None:
            durations_by_scope[key].add(Decimal(str(row["duration_hours"])))

    timings: dict[tuple[str, str], PoolEventTiming] = {}
    for key, durations in durations_by_scope.items():
        if len(durations) > 1:
            raise _conflicting_duration_error(posting_code=key[1])
        timings[key] = (
            PoolEventTiming(duration_hours=durations.pop(), is_mapped=True)
            if durations
            else PoolEventTiming(
                duration_hours=DEFAULT_POOL_EVENT_DURATION_HOURS,
                is_mapped=False,
            )
        )
    return timings


async def sync_pool_event_timings(
    db: AsyncSession,
    *,
    scopes: Iterable[PoolEventTimingScope],
) -> int:
    """Recalculate stored pool-event timing for unique exact source scopes."""

    unique_scopes = sorted(
        {
            (
                str(scope.teaching_name_id),
                str(scope.reporting_period_id),
                scope.programme_code,
                scope.posting_code,
            )
            for scope in scopes
        }
    )
    updated_count = 0
    for teaching_name_id, reporting_period_id, programme_code, posting_code in unique_scopes:
        scope = PoolEventTimingScope(
            teaching_name_id=teaching_name_id,
            reporting_period_id=reporting_period_id,
            programme_code=programme_code,
            posting_code=posting_code,
        )
        timing = await resolve_pool_event_timing(db, scope=scope)
        duration_seconds = int(timing.duration_hours * Decimal("3600"))
        result = await db.execute(
            text(
                """
                /* pool_event_timing:sync */
                UPDATE teaching_events
                SET duration_hours = :duration_hours,
                    end_time = (
                        start_time + make_interval(secs => :duration_seconds)
                    )::time,
                    updated_at = now()
                WHERE teaching_name_id = :teaching_name_id
                  AND source_reporting_period_id = :reporting_period_id
                  AND source_programme_code = :programme_code
                  AND posting_code = :posting_code
                  AND global_session_type_id IS NULL
                  AND is_adhoc = false
                  AND (
                      duration_hours IS DISTINCT FROM :duration_hours
                      OR end_time IS DISTINCT FROM (
                          start_time + make_interval(secs => :duration_seconds)
                      )::time
                  )
                """
            ),
            {
                "teaching_name_id": teaching_name_id,
                "reporting_period_id": reporting_period_id,
                "programme_code": programme_code,
                "posting_code": posting_code,
                "duration_hours": timing.duration_hours,
                "duration_seconds": duration_seconds,
            },
        )
        updated_count += max(int(result.rowcount or 0), 0)
    return updated_count


async def sync_programme_period_pool_event_timings(
    db: AsyncSession,
    *,
    reporting_period_id: UUID | str,
    programme_code: str,
) -> int:
    """Synchronize every persisted Teaching Name/posting scope after a TTF upload."""

    result = await db.execute(
        text(
            """
            /* pool_event_timing:list_programme_period_scopes */
            SELECT DISTINCT teaching_name_id, posting_code
            FROM teaching_name_mappings
            WHERE reporting_period_id = :reporting_period_id
              AND programme_code = :programme_code
            ORDER BY teaching_name_id ASC, posting_code ASC
            """
        ),
        {
            "reporting_period_id": str(reporting_period_id),
            "programme_code": programme_code,
        },
    )
    return await sync_pool_event_timings(
        db,
        scopes=(
            PoolEventTimingScope(
                teaching_name_id=row["teaching_name_id"],
                reporting_period_id=reporting_period_id,
                programme_code=programme_code,
                posting_code=str(row["posting_code"]),
            )
            for row in result.mappings().all()
        ),
    )
