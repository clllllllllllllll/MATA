from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.services.database_context import RLS_ENABLED_INFO_KEY


DEFAULT_POOL_EVENT_DURATION_HOURS = Decimal("1.00")


@dataclass(frozen=True, slots=True)
class PoolEventRYearTiming:
    r_year: str
    duration_hours: Decimal
    is_mapped: bool
    programme_code: str | None = None
    teaching_target_id: UUID | None = None
    session_type_id: UUID | None = None
    session_type_name: str | None = None


@dataclass(frozen=True, slots=True)
class PoolEventTiming:
    """Staff-facing timing envelope for one Teaching Name/posting scope."""

    duration_hours: Decimal
    is_mapped: bool
    duration_varies: bool = False
    r_year_timings: tuple[PoolEventRYearTiming, ...] = ()

    @property
    def has_pending_mappings(self) -> bool:
        return any(not timing.is_mapped for timing in self.r_year_timings)


@dataclass(frozen=True, slots=True)
class PoolEventTimingScope:
    teaching_name_id: UUID | str
    reporting_period_id: UUID | str
    programme_code: str
    posting_code: str


def pool_event_timing_payload(timing: PoolEventTiming) -> dict[str, object]:
    return {
        "duration_varies": timing.duration_varies,
        "has_pending_mappings": timing.has_pending_mappings,
        "r_year_durations": [
            {
                "r_year": row.r_year,
                "programme_code": row.programme_code,
                "duration_hours": row.duration_hours,
                "is_mapped": row.is_mapped,
                "session_type_id": row.session_type_id,
                "session_type_name": row.session_type_name,
            }
            for row in timing.r_year_timings
        ],
    }


def staff_pool_event_session_type_label(timing: PoolEventTiming) -> str:
    """Return the staff-facing session-type label for one mapping envelope."""

    if not timing.r_year_timings or all(
        not row.is_mapped for row in timing.r_year_timings
    ):
        return "Pending mapping"
    mapped_names = {
        row.session_type_name
        for row in timing.r_year_timings
        if row.is_mapped and row.session_type_name
    }
    if timing.has_pending_mappings or len(mapped_names) != 1:
        return "Varies by R-year"
    return next(iter(mapped_names))


def _missing_r_year_mapping_error(*, posting_code: str, r_year: str) -> ApiError:
    return ApiError(
        status_code=409,
        detail=(
            "Teaching Name mapping is unavailable for the resident's event-date "
            "R-year. Ask the Programme PC to reconcile the mapping before retrying."
        ),
        error_code=ErrorCode.CONFLICT.value,
        metadata={"posting_code": posting_code, "r_year": r_year},
    )


def _timing_envelope(
    rows: Iterable[PoolEventRYearTiming],
) -> PoolEventTiming:
    r_year_timings = tuple(
        sorted(rows, key=lambda timing: (timing.programme_code or "", timing.r_year))
    )
    if not r_year_timings:
        return PoolEventTiming(
            duration_hours=DEFAULT_POOL_EVENT_DURATION_HOURS,
            is_mapped=False,
        )
    effective_durations = {timing.duration_hours for timing in r_year_timings}
    return PoolEventTiming(
        duration_hours=max(effective_durations),
        is_mapped=all(timing.is_mapped for timing in r_year_timings),
        duration_varies=len(effective_durations) > 1,
        r_year_timings=r_year_timings,
    )


async def resolve_pool_event_timing(
    db: AsyncSession,
    *,
    scope: PoolEventTimingScope,
) -> PoolEventTiming:
    """Resolve the staff envelope across the scope's R-year mapping rows."""

    rls_enabled = bool(
        getattr(db, "info", {}).get(RLS_ENABLED_INFO_KEY, False)
    )
    result = await db.execute(
        text(
            """
            SELECT
                r_year,
                teaching_target_id,
                session_type_id,
                session_type_name,
                duration_hours
            FROM mata_rls.resolve_staff_pool_event_timings(
                CAST(:teaching_name_ids AS uuid[]),
                CAST(:reporting_period_id AS uuid),
                CAST(:programme_code AS text),
                CAST(:posting_code AS text)
            )
            """
            if rls_enabled
            else """
            /* pool_event_timing:resolve */
            SELECT
                mapping.r_year,
                mapping.teaching_target_id,
                target.session_type_id,
                session_type.name AS session_type_name,
                session_type.duration_hours
            FROM teaching_name_mappings AS mapping
            LEFT JOIN teaching_targets AS target
              ON target.id = mapping.teaching_target_id
            LEFT JOIN session_types AS session_type
              ON session_type.id = target.session_type_id
            WHERE mapping.teaching_name_id = :teaching_name_id
              AND mapping.reporting_period_id = :reporting_period_id
              AND mapping.programme_code = :programme_code
              AND mapping.posting_code = :posting_code
            ORDER BY mapping.r_year ASC
            """
        ),
        {
            "teaching_name_id": str(scope.teaching_name_id),
            "teaching_name_ids": [str(scope.teaching_name_id)],
            "reporting_period_id": str(scope.reporting_period_id),
            "programme_code": scope.programme_code,
            "posting_code": scope.posting_code,
        },
    )
    return _timing_envelope(
        PoolEventRYearTiming(
            r_year=str(row["r_year"]),
            programme_code=scope.programme_code,
            duration_hours=(
                Decimal(str(row["duration_hours"]))
                if row.get("duration_hours") is not None
                else DEFAULT_POOL_EVENT_DURATION_HOURS
            ),
            is_mapped=row.get("teaching_target_id") is not None,
            teaching_target_id=(
                UUID(str(row["teaching_target_id"]))
                if row.get("teaching_target_id") is not None
                else None
            ),
            session_type_id=(
                UUID(str(row["session_type_id"]))
                if row.get("session_type_id") is not None
                else None
            ),
            session_type_name=row.get("session_type_name"),
        )
        for row in result.mappings().all()
    )


async def resolve_pool_event_r_year_timing(
    db: AsyncSession,
    *,
    scope: PoolEventTimingScope,
    r_year: str,
) -> PoolEventRYearTiming:
    """Resolve native-resident timing from one exact event-date R-year mapping."""

    result = await db.execute(
        text(
            """
            /* pool_event_timing:resolve_r_year */
            SELECT
                mapping.r_year,
                mapping.teaching_target_id,
                target.session_type_id,
                session_type.name AS session_type_name,
                session_type.duration_hours
            FROM teaching_name_mappings AS mapping
            LEFT JOIN teaching_targets AS target
              ON target.id = mapping.teaching_target_id
            LEFT JOIN session_types AS session_type
              ON session_type.id = target.session_type_id
            WHERE mapping.teaching_name_id = :teaching_name_id
              AND mapping.reporting_period_id = :reporting_period_id
              AND mapping.programme_code = :programme_code
              AND mapping.posting_code = :posting_code
              AND mapping.r_year = :r_year
            """
        ),
        {
            "teaching_name_id": str(scope.teaching_name_id),
            "reporting_period_id": str(scope.reporting_period_id),
            "programme_code": scope.programme_code,
            "posting_code": scope.posting_code,
            "r_year": r_year,
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise _missing_r_year_mapping_error(
            posting_code=scope.posting_code,
            r_year=r_year,
        )
    return PoolEventRYearTiming(
        r_year=str(row["r_year"]),
        programme_code=scope.programme_code,
        duration_hours=(
            Decimal(str(row["duration_hours"]))
            if row.get("duration_hours") is not None
            else DEFAULT_POOL_EVENT_DURATION_HOURS
        ),
        is_mapped=row.get("teaching_target_id") is not None,
        teaching_target_id=(
            UUID(str(row["teaching_target_id"]))
            if row.get("teaching_target_id") is not None
            else None
        ),
        session_type_id=(
            UUID(str(row["session_type_id"]))
            if row.get("session_type_id") is not None
            else None
        ),
        session_type_name=row.get("session_type_name"),
    )


async def list_pool_event_timings(
    db: AsyncSession,
    *,
    teaching_name_ids: Sequence[UUID | str],
    reporting_period_id: UUID | str,
    programme_code: str | None,
    posting_code: str | None = None,
) -> dict[tuple[str, str], PoolEventTiming]:
    """Resolve all persisted name/posting scopes in one bounded query."""

    if not teaching_name_ids:
        return {}
    rls_enabled = bool(
        getattr(db, "info", {}).get(RLS_ENABLED_INFO_KEY, False)
    )
    result = await db.execute(
        text(
            """
            SELECT *
            FROM mata_rls.resolve_staff_pool_event_timings(
                CAST(:teaching_name_ids AS uuid[]),
                CAST(:reporting_period_id AS uuid),
                CAST(:programme_code AS text),
                CAST(:posting_code AS text)
            )
            """
            if rls_enabled
            else """
            /* pool_event_timing:list */
            SELECT
                mapping.teaching_name_id,
                mapping.programme_code,
                mapping.posting_code,
                mapping.r_year,
                mapping.teaching_target_id,
                target.session_type_id,
                session_type.name AS session_type_name,
                session_type.duration_hours
            FROM teaching_name_mappings AS mapping
            LEFT JOIN teaching_targets AS target
              ON target.id = mapping.teaching_target_id
            LEFT JOIN session_types AS session_type
              ON session_type.id = target.session_type_id
            WHERE mapping.teaching_name_id = ANY(CAST(:teaching_name_ids AS uuid[]))
              AND mapping.reporting_period_id = :reporting_period_id
              AND (
                  CAST(:programme_code AS text) IS NULL
                  OR mapping.programme_code = CAST(:programme_code AS text)
              )
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
    timings_by_scope: defaultdict[
        tuple[str, str], list[PoolEventRYearTiming]
    ] = defaultdict(list)
    for row in result.mappings().all():
        key = (str(row["teaching_name_id"]), str(row["posting_code"]))
        timings_by_scope[key].append(
            PoolEventRYearTiming(
                r_year=str(row["r_year"]),
                programme_code=(
                    str(row["programme_code"])
                    if row.get("programme_code") is not None
                    else programme_code
                ),
                duration_hours=(
                    Decimal(str(row["duration_hours"]))
                    if row.get("duration_hours") is not None
                    else DEFAULT_POOL_EVENT_DURATION_HOURS
                ),
                is_mapped=row.get("teaching_target_id") is not None,
                teaching_target_id=(
                    UUID(str(row["teaching_target_id"]))
                    if row.get("teaching_target_id") is not None
                    else None
                ),
                session_type_id=(
                    UUID(str(row["session_type_id"]))
                    if row.get("session_type_id") is not None
                    else None
                ),
                session_type_name=row.get("session_type_name"),
            )
        )

    return {
        key: _timing_envelope(r_year_timings)
        for key, r_year_timings in timings_by_scope.items()
    }


async def with_staff_pool_event_timings(
    db: AsyncSession,
    *,
    rows: Sequence[dict[str, Any]],
    programme_code: str | None = None,
) -> list[dict[str, Any]]:
    """Attach staff timing metadata with one query per period/programme scope."""

    enriched_rows = [dict(row) for row in rows]
    teaching_names_by_scope: defaultdict[
        tuple[str, str | None, str], set[str]
    ] = defaultdict(set)
    for row in enriched_rows:
        teaching_name_id = row.get("teaching_name_id")
        reporting_period_id = row.get("source_reporting_period_id")
        timing_programme_code = (
            programme_code
            if programme_code is not None
            else row.get("created_for_programme_code")
        )
        posting_code = row.get("posting_code")
        if (
            teaching_name_id is None
            or reporting_period_id is None
            or posting_code is None
        ):
            continue
        teaching_names_by_scope[
            (
                str(reporting_period_id),
                (
                    str(timing_programme_code)
                    if timing_programme_code is not None
                    else None
                ),
                str(posting_code),
            )
        ].add(str(teaching_name_id))

    timings_by_full_scope: dict[
        tuple[str, str | None, str, str], PoolEventTiming
    ] = {}
    for (
        reporting_period_id,
        programme_code,
        posting_code,
    ), teaching_name_ids in sorted(
        teaching_names_by_scope.items(),
        key=lambda item: (item[0][0], item[0][1] or "", item[0][2]),
    ):
        timings = await list_pool_event_timings(
            db,
            teaching_name_ids=sorted(teaching_name_ids),
            reporting_period_id=reporting_period_id,
            programme_code=programme_code,
            posting_code=posting_code,
        )
        timings_by_full_scope.update(
            {
                (
                    reporting_period_id,
                    programme_code,
                    teaching_name_id,
                    posting_code,
                ): timing
                for (teaching_name_id, posting_code), timing in timings.items()
            }
        )

    for row in enriched_rows:
        timing_programme_code = (
            programme_code
            if programme_code is not None
            else row.get("created_for_programme_code")
        )
        timing = timings_by_full_scope.get(
            (
                str(row.get("source_reporting_period_id")),
                (
                    str(timing_programme_code)
                    if timing_programme_code is not None
                    else None
                ),
                str(row.get("teaching_name_id")),
                str(row.get("posting_code")),
            )
        )
        if timing is not None:
            row.update(pool_event_timing_payload(timing))
            row["session_type"] = staff_pool_event_session_type_label(timing)
    return enriched_rows


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
        pc_result = await db.execute(
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
                  AND posting_code = :posting_code
                  AND created_for_programme_code = :programme_code
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
        updated_count += max(int(pc_result.rowcount or 0), 0)

        if bool(getattr(db, "info", {}).get(RLS_ENABLED_INFO_KEY, False)):
            secretary_result = await db.execute(
                text(
                    """
                    SELECT mata_rls.sync_secretary_pool_event_timing(
                        CAST(:teaching_name_id AS uuid),
                        CAST(:reporting_period_id AS uuid),
                        CAST(:programme_code AS text),
                        CAST(:posting_code AS text)
                    )
                    """
                ),
                {
                    "teaching_name_id": teaching_name_id,
                    "reporting_period_id": reporting_period_id,
                    "programme_code": programme_code,
                    "posting_code": posting_code,
                },
            )
            updated_count += max(int(secretary_result.scalar_one() or 0), 0)
            continue

        secretary_timing = await list_pool_event_timings(
            db,
            teaching_name_ids=[teaching_name_id],
            reporting_period_id=reporting_period_id,
            programme_code=None,
            posting_code=posting_code,
        )
        aggregate = secretary_timing.get((teaching_name_id, posting_code))
        if aggregate is None:
            aggregate = PoolEventTiming(
                duration_hours=DEFAULT_POOL_EVENT_DURATION_HOURS,
                is_mapped=False,
            )
        aggregate_seconds = int(aggregate.duration_hours * Decimal("3600"))
        secretary_result = await db.execute(
            text(
                """
                /* pool_event_timing:sync_secretary_envelope */
                UPDATE teaching_events
                SET duration_hours = :duration_hours,
                    end_time = (
                        start_time + make_interval(secs => :duration_seconds)
                    )::time,
                    updated_at = now()
                WHERE teaching_name_id = :teaching_name_id
                  AND source_reporting_period_id = :reporting_period_id
                  AND posting_code = :posting_code
                  AND created_for_programme_code IS NULL
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
                "posting_code": posting_code,
                "duration_hours": aggregate.duration_hours,
                "duration_seconds": aggregate_seconds,
            },
        )
        updated_count += max(int(secretary_result.rowcount or 0), 0)
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
