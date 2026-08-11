from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode
from app.schemas.data_revalidation import (
    DataRevalidationAction,
    DataRevalidationChangedEntity,
    DataRevalidationContext,
    DataRevalidationScope,
    DataRevalidationTriggerSource,
)
from app.security import log_safe_exception
from app.services import cache_invalidation, data_revalidation_service
from app.services.audit import write_audit_log
from app.services.pool_event_timing import (
    PoolEventTimingScope,
    sync_pool_event_timings,
)
from app.services.teaching_name_pool import (
    TeachingNamePoolActor,
    _normalised_scope,
    normalise_teaching_name,
)
from app.services.ttf_scope_lock import acquire_ttf_scope_lock


logger = logging.getLogger(__name__)


_MAPPING_COLUMNS = """
    mapping.id,
    mapping.teaching_name_id,
    name.display_name AS teaching_name,
    name.is_active AS teaching_name_is_active,
    name.revision AS teaching_name_revision,
    mapping.reporting_period_id,
    mapping.programme_code,
    mapping.posting_code,
    mapping.r_year,
    mapping.teaching_target_id,
    mapping.revision,
    mapping.created_at,
    mapping.updated_at,
    target.id AS target_id,
    target.session_type_id AS target_session_type_id,
    session_type.name AS target_session_type_name,
    session_type.duration_hours AS target_duration_hours,
    target.monthly_target AS target_monthly_target,
    target.is_tracked AS target_is_tracked,
    target.is_reallocatable AS target_is_reallocatable,
    target.tag AS target_tag
"""

_TARGET_COLUMNS = """
    target.id,
    target.session_type_id,
    session_type.name AS session_type_name,
    session_type.duration_hours,
    target.monthly_target,
    target.is_tracked,
    target.is_reallocatable,
    target.tag
"""


def _raise_forbidden(detail: str) -> None:
    raise ApiError(
        status_code=403,
        detail=detail,
        error_code=ErrorCode.FORBIDDEN.value,
    )


def _raise_not_found() -> None:
    raise ApiError(
        status_code=404,
        detail="Teaching Name mapping not found",
        error_code=ErrorCode.NOT_FOUND.value,
    )


def _raise_conflict(detail: str, *, metadata: dict[str, Any] | None = None) -> None:
    raise ApiError(
        status_code=409,
        detail=detail,
        error_code=ErrorCode.CONFLICT.value,
        metadata=metadata,
    )


def _raise_validation(detail: str) -> None:
    raise ApiError(
        status_code=422,
        detail=detail,
        error_code=ErrorCode.VALIDATION_FAILED.value,
    )


def _require_mapping_mutation_actor(actor: TeachingNamePoolActor) -> None:
    if actor.kind == "master_admin":
        _raise_forbidden("Forbidden - Master Admin mapping access is read-only")
    if actor.kind != "programme_pc":
        _raise_forbidden("Forbidden - Programme PC mapping access is required")
    if not _normalised_scope(actor.programme_scope):
        _raise_forbidden("Forbidden - Programme PC scope is required")


def _require_mapping_read_actor(actor: TeachingNamePoolActor) -> None:
    if actor.kind == "master_admin":
        return
    _require_mapping_mutation_actor(actor)


def _require_actor_scope(
    actor: TeachingNamePoolActor,
    *,
    programme_code: str,
    id_lookup: bool = False,
) -> None:
    if actor.kind == "master_admin":
        return
    if programme_code in _normalised_scope(actor.programme_scope):
        return
    if id_lookup:
        _raise_not_found()
    _raise_forbidden("Forbidden - programme not in admin scope")


async def _acquire_scope_lock(
    db: AsyncSession,
    *,
    reporting_period_id: UUID | str,
    programme_code: str,
) -> None:
    if not await acquire_ttf_scope_lock(
        db,
        reporting_period_id=UUID(str(reporting_period_id)),
        programme_code=programme_code,
    ):
        _raise_conflict(
            "A Teaching Name mapping change for this reporting period and programme is already in progress"
        )


def _target_summary(row: dict[str, Any], *, prefix: str = "") -> dict[str, Any] | None:
    target_id = row.get(f"{prefix}id")
    if target_id is None:
        return None
    return {
        "id": target_id,
        "session_type_id": row[f"{prefix}session_type_id"],
        "session_type_name": row[f"{prefix}session_type_name"],
        "duration_hours": row[f"{prefix}duration_hours"],
        "monthly_target": row[f"{prefix}monthly_target"],
        "is_tracked": bool(row[f"{prefix}is_tracked"]),
        "is_reallocatable": bool(row[f"{prefix}is_reallocatable"]),
        "tag": row.get(f"{prefix}tag"),
    }


def _mapping_response(row: dict[str, Any], *, options: list[dict[str, Any]]) -> dict[str, Any]:
    target = _target_summary(
        {
            "id": row.get("target_id"),
            "session_type_id": row.get("target_session_type_id"),
            "session_type_name": row.get("target_session_type_name"),
            "duration_hours": row.get("target_duration_hours"),
            "monthly_target": row.get("target_monthly_target"),
            "is_tracked": row.get("target_is_tracked"),
            "is_reallocatable": row.get("target_is_reallocatable"),
            "tag": row.get("target_tag"),
        }
    )
    return {
        "id": row["id"],
        "teaching_name_id": row["teaching_name_id"],
        "teaching_name": row["teaching_name"],
        "teaching_name_is_active": bool(row["teaching_name_is_active"]),
        "teaching_name_revision": int(row["teaching_name_revision"]),
        "reporting_period_id": row["reporting_period_id"],
        "programme_code": row["programme_code"],
        "posting_code": row["posting_code"],
        "r_year": row["r_year"],
        "teaching_target_id": row.get("teaching_target_id"),
        "state": "mapped" if row.get("teaching_target_id") is not None else "pending",
        "revision": int(row["revision"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "target": target,
        "available_target_options": options,
    }


async def _target_options(
    db: AsyncSession,
    *,
    reporting_period_id: UUID | str,
    programme_code: str,
    posting_code: str,
    r_year: str,
) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            f"""
            SELECT
                {_TARGET_COLUMNS},
                target.reporting_period_id,
                target.programme_code,
                target.posting_code,
                target.r_year
            FROM teaching_targets AS target
            JOIN session_types AS session_type
              ON session_type.id = target.session_type_id
            WHERE target.reporting_period_id = :reporting_period_id
              AND target.programme_code = :programme_code
              AND target.posting_code = :posting_code
              AND target.r_year = :r_year
            ORDER BY session_type.name ASC, target.id ASC
            """
        ),
        {
            "reporting_period_id": str(reporting_period_id),
            "programme_code": programme_code,
            "posting_code": posting_code,
            "r_year": r_year,
        },
    )
    return [_target_summary(dict(row)) for row in result.mappings().all() if row["id"] is not None]


def _normalised_search(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    _, normalized_name = normalise_teaching_name(value)
    return normalized_name


async def list_mappings(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    reporting_period_id: UUID | None = None,
    programme_code: str | None = None,
    posting_code: str | None = None,
    r_year: str | None = None,
    state: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return only exact-scope mapping management data and target candidates."""

    _require_mapping_read_actor(actor)
    if state not in {None, "pending", "mapped"}:
        _raise_validation("state must be pending or mapped")
    if programme_code is not None:
        programme_code = programme_code.strip().upper()
        if not programme_code:
            _raise_validation("programme_code is required when supplied")
        _require_actor_scope(actor, programme_code=programme_code)

    where: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if reporting_period_id is not None:
        where.append("mapping.reporting_period_id = :reporting_period_id")
        params["reporting_period_id"] = str(reporting_period_id)
    if programme_code is not None:
        where.append("mapping.programme_code = :programme_code")
        params["programme_code"] = programme_code
    if posting_code is not None and posting_code.strip():
        where.append("mapping.posting_code = :posting_code")
        params["posting_code"] = posting_code.strip()
    if r_year is not None and r_year.strip():
        where.append("mapping.r_year = :r_year")
        params["r_year"] = r_year.strip().upper()
    if state == "pending":
        where.append("mapping.teaching_target_id IS NULL")
    if state == "mapped":
        where.append("mapping.teaching_target_id IS NOT NULL")
    normalized_search = _normalised_search(search)
    if normalized_search is not None:
        where.append("name.normalized_name LIKE :normalized_search")
        params["normalized_search"] = f"%{normalized_search}%"
    if actor.kind != "master_admin":
        where.append("mapping.programme_code = ANY(CAST(:programme_scope AS text[]))")
        params["programme_scope"] = sorted(_normalised_scope(actor.programme_scope))

    predicate = " AND ".join(where) if where else "true"
    from_sql = """
        FROM teaching_name_mappings AS mapping
        JOIN teaching_names AS name
          ON name.id = mapping.teaching_name_id
        LEFT JOIN teaching_targets AS target
          ON target.id = mapping.teaching_target_id
        LEFT JOIN session_types AS session_type
          ON session_type.id = target.session_type_id
    """
    rows_result = await db.execute(
        text(
            f"""
            SELECT {_MAPPING_COLUMNS}
            {from_sql}
            WHERE {predicate}
            ORDER BY
                mapping.reporting_period_id ASC,
                mapping.programme_code ASC,
                mapping.posting_code ASC,
                mapping.r_year ASC,
                name.display_name ASC,
                mapping.id ASC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    count_result = await db.execute(
        text(
            f"""
            SELECT COUNT(*)
            {from_sql}
            WHERE {predicate}
            """
        ),
        params,
    )
    rows = [dict(row) for row in rows_result.mappings().all()]
    items: list[dict[str, Any]] = []
    for row in rows:
        options = await _target_options(
            db,
            reporting_period_id=row["reporting_period_id"],
            programme_code=str(row["programme_code"]),
            posting_code=str(row["posting_code"]),
            r_year=str(row["r_year"]),
        )
        items.append(_mapping_response(row, options=options))
    return {
        "items": items,
        "total": int(count_result.scalar_one()),
        "limit": limit,
        "offset": offset,
    }


async def _mapping_row(
    db: AsyncSession,
    *,
    mapping_id: UUID,
    lock: bool = False,
) -> dict[str, Any]:
    lock_clause = "FOR UPDATE OF mapping" if lock else ""
    result = await db.execute(
        text(
            f"""
            SELECT {_MAPPING_COLUMNS}
            FROM teaching_name_mappings AS mapping
            JOIN teaching_names AS name ON name.id = mapping.teaching_name_id
            LEFT JOIN teaching_targets AS target ON target.id = mapping.teaching_target_id
            LEFT JOIN session_types AS session_type ON session_type.id = target.session_type_id
            WHERE mapping.id = :mapping_id
            {lock_clause}
            """
        ),
        {"mapping_id": str(mapping_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        _raise_not_found()
    return dict(row)


async def _locked_target(
    db: AsyncSession,
    *,
    target_id: UUID,
    mapping: dict[str, Any],
) -> dict[str, Any]:
    result = await db.execute(
        text(
            f"""
            SELECT
                {_TARGET_COLUMNS},
                target.reporting_period_id,
                target.programme_code,
                target.posting_code,
                target.r_year
            FROM teaching_targets AS target
            JOIN session_types AS session_type ON session_type.id = target.session_type_id
            WHERE target.id = :target_id
            FOR UPDATE OF target
            """
        ),
        {"target_id": str(target_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        _raise_validation("teaching_target_id is invalid")
    target = dict(row)
    exact_scope = (
        str(mapping["reporting_period_id"]),
        str(mapping["programme_code"]),
        str(mapping["posting_code"]),
        str(mapping["r_year"]),
    )
    if tuple(str(target[key]) for key in (
        "reporting_period_id", "programme_code", "posting_code", "r_year"
    )) != exact_scope:
        _raise_validation("teaching_target_id must belong to the mapping's exact scope")
    return target


async def _mapping_impact_counts(
    db: AsyncSession,
    *,
    mapping: dict[str, Any],
) -> dict[str, int]:
    """Count only event/attendance evidence tied through explicit stable IDs.

    Legacy text-only rows are intentionally excluded rather than matched by
    display text. A mapped name can be moved to a target with a different
    display session type, and an event has no R-year field. The impact therefore
    conservatively covers the full stable name/posting identity rather than
    undercounting a same-name/posting event that may be resolved by the mapping.
    """

    result = await db.execute(
        text(
            """
            WITH source_mapping AS (
                SELECT
                    mapping.id,
                    mapping.teaching_name_id,
                    mapping.reporting_period_id,
                    mapping.programme_code,
                    mapping.posting_code
                FROM teaching_name_mappings AS mapping
                WHERE mapping.id = :mapping_id
            ), safe_events AS (
                SELECT DISTINCT event.id
                FROM source_mapping AS mapping
                JOIN teaching_events AS event
                  ON event.teaching_name_id = mapping.teaching_name_id
                  AND event.source_reporting_period_id = mapping.reporting_period_id
                  AND event.source_programme_code = mapping.programme_code
                  AND event.posting_code = mapping.posting_code
                  AND event.global_session_type_id IS NULL
                  AND event.is_adhoc = false
            )
            SELECT
                COUNT(DISTINCT event.id) AS affected_event_count,
                COUNT(DISTINCT native_attendance.id) AS native_attendance_count,
                COUNT(DISTINCT external_attendance.id) AS external_attendance_count
            FROM safe_events
            LEFT JOIN teaching_events AS event ON event.id = safe_events.id
            LEFT JOIN attendance_records AS native_attendance
              ON native_attendance.teaching_event_id = event.id
             AND native_attendance.status = 'submitted'
            LEFT JOIN external_attendance_records AS external_attendance
              ON external_attendance.teaching_event_id = event.id
             AND external_attendance.status = 'submitted'
            """
        ),
        {"mapping_id": str(mapping["id"])},
    )
    row = result.mappings().one_or_none() or {}
    return {
        "affected_event_count": int(row.get("affected_event_count") or 0),
        "affected_attendance_count": int(row.get("native_attendance_count") or 0)
        + int(row.get("external_attendance_count") or 0),
    }


def _require_revision(mapping: dict[str, Any], expected_revision: int) -> None:
    if int(mapping["revision"]) != expected_revision:
        _raise_conflict("Teaching Name mapping has changed; refresh and retry")


def _change_required(mapping: dict[str, Any], target_id: UUID | None) -> None:
    current_target_id = (
        str(mapping["teaching_target_id"])
        if mapping.get("teaching_target_id") is not None
        else None
    )
    requested_target_id = str(target_id) if target_id is not None else None
    if current_target_id == requested_target_id:
        _raise_validation("mapping change does not modify the selected target")


def _revalidation_context(
    *,
    actor: TeachingNamePoolActor,
    mapping: dict[str, Any],
    target_id: UUID | None,
    impact: dict[str, int],
    bulk_operation_id: UUID | None,
) -> DataRevalidationContext:
    return DataRevalidationContext(
        trigger_source=DataRevalidationTriggerSource.PC_CONFIG_CHANGE,
        changed_entity=DataRevalidationChangedEntity.TEACHING_NAME_MAPPING,
        action=DataRevalidationAction.UPDATE,
        scope=DataRevalidationScope.PROGRAMME_REPORTING_PERIOD,
        entity_id=str(mapping["id"]),
        programme_code=str(mapping["programme_code"]),
        reporting_period_id=str(mapping["reporting_period_id"]),
        changed_fields=["teaching_target_id"],
        source_metadata={
            "mapping_id": str(mapping["id"]),
            "teaching_name_id": str(mapping["teaching_name_id"]),
            "posting_code": str(mapping["posting_code"]),
            "r_year": str(mapping["r_year"]),
            "prior_target_id": (
                str(mapping["teaching_target_id"])
                if mapping.get("teaching_target_id") is not None
                else None
            ),
            "new_target_id": str(target_id) if target_id is not None else None,
            "affected_event_count": impact["affected_event_count"],
            "affected_attendance_count": impact["affected_attendance_count"],
            "bulk_operation_id": str(bulk_operation_id) if bulk_operation_id else None,
        },
        actor_user_id=str(actor.user_id),
        actor_role=actor.staff_actor.actor_role,
    )


def _audit_snapshot(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        "mapping_id": str(mapping["id"]),
        "teaching_name_id": str(mapping["teaching_name_id"]),
        "reporting_period_id": str(mapping["reporting_period_id"]),
        "programme_code": str(mapping["programme_code"]),
        "posting_code": str(mapping["posting_code"]),
        "r_year": str(mapping["r_year"]),
        "teaching_target_id": (
            str(mapping["teaching_target_id"])
            if mapping.get("teaching_target_id") is not None
            else None
        ),
        "revision": int(mapping["revision"]),
    }


async def _write_mapping_audit(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    before: dict[str, Any],
    after: dict[str, Any],
    impact: dict[str, int],
    confirmation_required: bool,
    confirmation_supplied: bool,
    data_revalidation: Any,
    bulk_operation_id: UUID | None,
) -> None:
    await write_audit_log(
        db,
        actor=actor.staff_actor,
        action="programme_pc.teaching_name_mapping.update",
        entity_type="teaching_name_mapping",
        entity_id=after["id"],
        before=_audit_snapshot(before),
        after=_audit_snapshot(after),
        metadata={
            "route_context": "teaching_name_mapping",
            "teaching_name_id": str(after["teaching_name_id"]),
            "reporting_period_id": str(after["reporting_period_id"]),
            "programme_code": str(after["programme_code"]),
            "posting_code": str(after["posting_code"]),
            "r_year": str(after["r_year"]),
            "prior_target_id": _audit_snapshot(before)["teaching_target_id"],
            "new_target_id": _audit_snapshot(after)["teaching_target_id"],
            "prior_revision": int(before["revision"]),
            "resulting_revision": int(after["revision"]),
            "affected_event_count": impact["affected_event_count"],
            "affected_attendance_count": impact["affected_attendance_count"],
            "confirmation_required": confirmation_required,
            "confirmation_supplied": confirmation_supplied,
            "bulk_operation_id": str(bulk_operation_id) if bulk_operation_id else None,
            "data_revalidation": data_revalidation.audit_metadata,
        },
    )


def _invalidate_after_commit(mappings: Iterable[dict[str, Any]]) -> None:
    for mapping in mappings:
        try:
            cache_invalidation.invalidate_after_teaching_name_mapping_change(
                mapping_id=mapping["id"],
                teaching_name_id=mapping["teaching_name_id"],
                reporting_period_id=mapping["reporting_period_id"],
                programme_code=mapping["programme_code"],
                posting_code=mapping["posting_code"],
            )
        except Exception as exc:
            log_safe_exception(
                logger,
                "teaching_name_mapping_cache_invalidation_failed",
                exc,
                category="cache_invalidation",
            )


async def get_mapping_impact(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    mapping_id: UUID,
    expected_revision: int,
    teaching_target_id: UUID | None,
) -> dict[str, int]:
    """Return count-only impact for a prospective change without mutating state."""

    _require_mapping_read_actor(actor)
    mapping = await _mapping_row(db, mapping_id=mapping_id)
    _require_actor_scope(actor, programme_code=str(mapping["programme_code"]), id_lookup=True)
    _require_revision(mapping, expected_revision)
    if teaching_target_id is not None:
        # Read validation deliberately uses the same exact-scope predicate as apply.
        target_result = await db.execute(
            text(
                """
                SELECT 1
                FROM teaching_targets
                WHERE id = :target_id
                  AND reporting_period_id = :reporting_period_id
                  AND programme_code = :programme_code
                  AND posting_code = :posting_code
                  AND r_year = :r_year
                """
            ),
            {
                "target_id": str(teaching_target_id),
                "reporting_period_id": str(mapping["reporting_period_id"]),
                "programme_code": mapping["programme_code"],
                "posting_code": mapping["posting_code"],
                "r_year": mapping["r_year"],
            },
        )
        if target_result.scalar_one_or_none() is None:
            _raise_validation("teaching_target_id must belong to the mapping's exact scope")
    return await _mapping_impact_counts(db, mapping=mapping)


async def _prepare_locked_change(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    mapping: dict[str, Any],
    expected_revision: int,
    teaching_target_id: UUID | None,
    confirm_impact: bool,
    target_already_locked: bool = False,
) -> tuple[dict[str, int], bool]:
    _require_actor_scope(actor, programme_code=str(mapping["programme_code"]), id_lookup=True)
    _require_revision(mapping, expected_revision)
    _change_required(mapping, teaching_target_id)
    if teaching_target_id is not None and not target_already_locked:
        await _locked_target(db, target_id=teaching_target_id, mapping=mapping)

    impact = await _mapping_impact_counts(db, mapping=mapping)
    confirmation_required = (
        impact["affected_event_count"] > 0 or impact["affected_attendance_count"] > 0
    )
    if confirmation_required and not confirm_impact:
        _raise_conflict(
            "Mapping change requires impact confirmation",
            metadata={
                "impact": impact,
                "confirmation_required": True,
            },
        )

    return impact, confirmation_required


async def _persist_prepared_change(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    mapping: dict[str, Any],
    expected_revision: int,
    teaching_target_id: UUID | None,
    confirm_impact: bool,
    impact: dict[str, int],
    confirmation_required: bool,
    bulk_operation_id: UUID | None,
) -> tuple[dict[str, Any], Any]:
    result = await db.execute(
        text(
            """
            UPDATE teaching_name_mappings
            SET teaching_target_id = :teaching_target_id,
                revision = revision + 1,
                updated_by_user_id = :actor_user_id,
                updated_at = now()
            WHERE id = :mapping_id
              AND revision = :expected_revision
            RETURNING id
            """
        ),
        {
            "mapping_id": str(mapping["id"]),
            "teaching_target_id": str(teaching_target_id) if teaching_target_id else None,
            "actor_user_id": str(actor.user_id),
            "expected_revision": expected_revision,
        },
    )
    if result.scalar_one_or_none() is None:
        _raise_conflict("Teaching Name mapping has changed; refresh and retry")
    after = await _mapping_row(db, mapping_id=mapping["id"])
    data_revalidation = await data_revalidation_service.revalidate_after_config_change(
        context=_revalidation_context(
            actor=actor,
            mapping=mapping,
            target_id=teaching_target_id,
            impact=impact,
            bulk_operation_id=bulk_operation_id,
        ),
        db_session=db,
    )
    await _write_mapping_audit(
        db,
        actor=actor,
        before=mapping,
        after=after,
        impact=impact,
        confirmation_required=confirmation_required,
        confirmation_supplied=confirm_impact,
        data_revalidation=data_revalidation,
        bulk_operation_id=bulk_operation_id,
    )
    return after, data_revalidation


async def apply_mapping_change(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    mapping_id: UUID,
    expected_revision: int,
    teaching_target_id: UUID | None,
    confirm_impact: bool,
) -> dict[str, Any]:
    _require_mapping_mutation_actor(actor)
    before_scope = await _mapping_row(db, mapping_id=mapping_id)
    _require_actor_scope(actor, programme_code=str(before_scope["programme_code"]), id_lookup=True)
    try:
        await _acquire_scope_lock(
            db,
            reporting_period_id=before_scope["reporting_period_id"],
            programme_code=str(before_scope["programme_code"]),
        )
        before = await _mapping_row(db, mapping_id=mapping_id, lock=True)
        impact, confirmation_required = await _prepare_locked_change(
            db,
            actor=actor,
            mapping=before,
            expected_revision=expected_revision,
            teaching_target_id=teaching_target_id,
            confirm_impact=confirm_impact,
        )
        after, data_revalidation = await _persist_prepared_change(
            db,
            actor=actor,
            mapping=before,
            expected_revision=expected_revision,
            teaching_target_id=teaching_target_id,
            confirm_impact=confirm_impact,
            impact=impact,
            confirmation_required=confirmation_required,
            bulk_operation_id=None,
        )
        await sync_pool_event_timings(
            db,
            scopes=[
                PoolEventTimingScope(
                    teaching_name_id=after["teaching_name_id"],
                    reporting_period_id=after["reporting_period_id"],
                    programme_code=str(after["programme_code"]),
                    posting_code=str(after["posting_code"]),
                )
            ],
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    _invalidate_after_commit([after])
    options = await _target_options(
        db,
        reporting_period_id=after["reporting_period_id"],
        programme_code=str(after["programme_code"]),
        posting_code=str(after["posting_code"]),
        r_year=str(after["r_year"]),
    )
    return {
        **_mapping_response(after, options=options),
        "impact": impact,
        "data_revalidation": data_revalidation,
    }


async def _locked_mappings_for_bulk(
    db: AsyncSession,
    *,
    mapping_ids: Sequence[UUID],
) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            f"""
            SELECT {_MAPPING_COLUMNS}
            FROM teaching_name_mappings AS mapping
            JOIN teaching_names AS name ON name.id = mapping.teaching_name_id
            LEFT JOIN teaching_targets AS target ON target.id = mapping.teaching_target_id
            LEFT JOIN session_types AS session_type ON session_type.id = target.session_type_id
            WHERE mapping.id = ANY(CAST(:mapping_ids AS uuid[]))
            ORDER BY mapping.id ASC
            FOR UPDATE OF mapping
            """
        ),
        {"mapping_ids": [str(mapping_id) for mapping_id in mapping_ids]},
    )
    rows = [dict(row) for row in result.mappings().all()]
    if len(rows) != len(mapping_ids):
        _raise_not_found()
    return rows


async def _locked_targets_for_bulk(
    db: AsyncSession,
    *,
    target_ids: Sequence[UUID],
) -> dict[UUID, dict[str, Any]]:
    if not target_ids:
        return {}
    result = await db.execute(
        text(
            """
            SELECT id, reporting_period_id, programme_code, posting_code, r_year
            FROM teaching_targets
            WHERE id = ANY(CAST(:target_ids AS uuid[]))
            ORDER BY id ASC
            FOR UPDATE OF teaching_targets
            """
        ),
        {"target_ids": [str(target_id) for target_id in sorted(set(target_ids), key=str)]},
    )
    rows = [dict(row) for row in result.mappings().all()]
    if len(rows) != len(set(target_ids)):
        _raise_validation("teaching_target_id is invalid")
    return {row["id"]: row for row in rows}


def _require_exact_locked_target(
    *,
    mapping: dict[str, Any],
    target: dict[str, Any],
) -> None:
    mapping_scope = (
        str(mapping["reporting_period_id"]),
        str(mapping["programme_code"]),
        str(mapping["posting_code"]),
        str(mapping["r_year"]),
    )
    target_scope = (
        str(target["reporting_period_id"]),
        str(target["programme_code"]),
        str(target["posting_code"]),
        str(target["r_year"]),
    )
    if target_scope != mapping_scope:
        _raise_validation("teaching_target_id must belong to the mapping's exact scope")


async def apply_bulk_mapping_changes(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    items: Sequence[Any],
) -> dict[str, int]:
    _require_mapping_mutation_actor(actor)
    if not items:
        _raise_validation("items is required")
    if len(items) > 100:
        _raise_validation("items may contain at most 100 mapping changes")
    mapping_ids = [item.mapping_id for item in items]
    if len(set(mapping_ids)) != len(mapping_ids):
        _raise_validation("mapping_id values must be unique")

    # Read scopes before taking locks only to derive deterministic lock order.
    preflight: list[dict[str, Any]] = []
    for mapping_id in sorted(mapping_ids, key=str):
        row = await _mapping_row(db, mapping_id=mapping_id)
        _require_actor_scope(actor, programme_code=str(row["programme_code"]), id_lookup=True)
        preflight.append(row)
    scopes = sorted(
        {
            (str(row["reporting_period_id"]), str(row["programme_code"]))
            for row in preflight
        }
    )
    bulk_operation_id = uuid4()
    try:
        for reporting_period_id, programme_code in scopes:
            await _acquire_scope_lock(
                db,
                reporting_period_id=reporting_period_id,
                programme_code=programme_code,
            )
        locked_rows = await _locked_mappings_for_bulk(
            db,
            mapping_ids=sorted(mapping_ids, key=str),
        )
        by_id = {row["id"]: row for row in locked_rows}
        ordered_items = sorted(items, key=lambda item: str(item.mapping_id))
        locked_targets = await _locked_targets_for_bulk(
            db,
            target_ids=[
                item.teaching_target_id
                for item in ordered_items
                if item.teaching_target_id is not None
            ],
        )
        prepared: list[tuple[Any, dict[str, Any], dict[str, int], bool]] = []
        total_events = 0
        total_attendance = 0
        for item in ordered_items:
            before = by_id[item.mapping_id]
            if item.teaching_target_id is not None:
                _require_exact_locked_target(
                    mapping=before,
                    target=locked_targets[item.teaching_target_id],
                )
            impact, confirmation_required = await _prepare_locked_change(
                db,
                actor=actor,
                mapping=before,
                expected_revision=item.expected_revision,
                teaching_target_id=item.teaching_target_id,
                confirm_impact=item.confirm_impact,
                target_already_locked=item.teaching_target_id is not None,
            )
            total_events += impact["affected_event_count"]
            total_attendance += impact["affected_attendance_count"]
            prepared.append((item, before, impact, confirmation_required))

        updated: list[dict[str, Any]] = []
        for item, before, impact, confirmation_required in prepared:
            after, _ = await _persist_prepared_change(
                db,
                actor=actor,
                mapping=before,
                expected_revision=item.expected_revision,
                teaching_target_id=item.teaching_target_id,
                confirm_impact=item.confirm_impact,
                impact=impact,
                confirmation_required=confirmation_required,
                bulk_operation_id=bulk_operation_id,
            )
            updated.append(after)
        await sync_pool_event_timings(
            db,
            scopes=[
                PoolEventTimingScope(
                    teaching_name_id=row["teaching_name_id"],
                    reporting_period_id=row["reporting_period_id"],
                    programme_code=str(row["programme_code"]),
                    posting_code=str(row["posting_code"]),
                )
                for row in updated
            ],
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    _invalidate_after_commit(updated)
    return {
        "requested_count": len(items),
        "updated_count": len(updated),
        "mapped_count": sum(1 for row in updated if row.get("teaching_target_id") is not None),
        "pending_count": sum(1 for row in updated if row.get("teaching_target_id") is None),
        "affected_event_count": total_events,
        "affected_attendance_count": total_attendance,
    }
