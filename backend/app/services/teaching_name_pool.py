from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.staff_actor import StaffActorContext
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
from app.services.database_context import session_uses_rls
from app.services.teaching_event_locks import acquire_teaching_event_locks
from app.services.ttf_scope_lock import acquire_ttf_scope_lock
from app.services.reporting_period_status import resolve_explicit_reporting_period
from app.services.teaching_name_programme_scopes import (
    reconcile_teaching_name_programme_scopes,
)


logger = logging.getLogger(__name__)

TeachingNameActorKind = Literal["secretary", "programme_pc", "master_admin"]


@dataclass(frozen=True, slots=True)
class TeachingNamePoolActor:
    kind: TeachingNameActorKind
    user_id: UUID
    staff_actor: StaffActorContext
    posting_code: str | None = None
    programme_scope: frozenset[str] = frozenset()


_NAME_COLUMNS = """
    id,
    reporting_period_id,
    programme_code,
    display_name AS teaching_name,
    created_by_role,
    visibility_scope,
    origin_posting_code,
    is_active,
    revision,
    created_at,
    updated_at,
    deactivated_at
"""

_LOCKED_NAME_COLUMNS = """
    id,
    reporting_period_id,
    programme_code,
    display_name AS teaching_name,
    normalized_name,
    created_by_role,
    visibility_scope,
    origin_posting_code,
    is_active,
    revision,
    created_at,
    updated_at,
    deactivated_at
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
        detail="Teaching Name not found",
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


def _contains_control_character(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def normalise_teaching_name(value: str) -> tuple[str, str]:
    """Return the display value and the server-owned uniqueness comparison key."""

    if not isinstance(value, str):
        _raise_validation("Teaching Name is required")
    canonical = unicodedata.normalize("NFC", value)
    display_name = " ".join(canonical.split())
    if _contains_control_character(display_name):
        _raise_validation("Teaching Name cannot contain control characters")
    if not display_name:
        _raise_validation("Teaching Name is required")
    if len(display_name) > 200:
        _raise_validation("Teaching Name must not exceed 200 characters")
    normalized_name = unicodedata.normalize("NFC", display_name.casefold())
    if len(normalized_name) > 200:
        _raise_validation("Teaching Name must not exceed 200 characters after normalization")
    return display_name, normalized_name


def _normalise_programme_code(value: str) -> str:
    canonical = unicodedata.normalize("NFC", value)
    if _contains_control_character(canonical):
        _raise_validation("programme_code cannot contain control characters")
    programme_code = canonical.strip().upper()
    if not programme_code or len(programme_code) > 20:
        _raise_validation("programme_code is invalid")
    return programme_code


def _normalised_scope(values: frozenset[str]) -> frozenset[str]:
    return frozenset(
        value.strip().upper()
        for value in values
        if isinstance(value, str) and value.strip()
    )


def _actor_trigger_source(actor: TeachingNamePoolActor) -> DataRevalidationTriggerSource:
    if actor.kind == "secretary":
        return DataRevalidationTriggerSource.SECRETARY_CONFIG_CHANGE
    if actor.kind == "programme_pc":
        return DataRevalidationTriggerSource.PC_CONFIG_CHANGE
    return DataRevalidationTriggerSource.ADMIN_CONFIG_CHANGE


def _audit_action(actor: TeachingNamePoolActor, action: str) -> str:
    prefix = {
        "secretary": "secretary",
        "programme_pc": "programme_pc",
        "master_admin": "admin",
    }[actor.kind]
    return f"{prefix}.teaching_name.{action}"


def _public_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in (
            "id",
            "reporting_period_id",
            "programme_code",
            "teaching_name",
            "created_by_role",
            "visibility_scope",
            "origin_posting_code",
            "is_active",
            "revision",
            "created_at",
            "updated_at",
            "deactivated_at",
        )
    }


def _actor_can_manage_name(
    actor: TeachingNamePoolActor,
    row: dict[str, Any],
) -> bool:
    owner_programme = str(row["programme_code"])
    if actor.kind == "programme_pc":
        return owner_programme in _normalised_scope(actor.programme_scope)
    if actor.kind == "secretary":
        return (
            row.get("created_by_role") == "secretary"
            and actor.posting_code is not None
            and str(row.get("origin_posting_code") or "") == actor.posting_code
        )
    return False


def _response_row(
    row: dict[str, Any],
    *,
    actor: TeachingNamePoolActor,
    admission_reason: str | None = None,
) -> dict[str, Any]:
    return {
        **row,
        "admission_reason": admission_reason
        or str(
            row.get("admission_reason")
            or (
                "pc_private"
                if row.get("visibility_scope") == "programme_private"
                else "owner_programme"
            )
        ),
        "can_manage_name": _actor_can_manage_name(actor, row),
    }


def _database_exception_chain(exc: BaseException) -> tuple[Any, ...]:
    """Return wrapped DBAPI exceptions without inspecting their message text."""

    pending: list[Any] = [exc]
    collected: list[Any] = []
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        collected.append(current)
        pending.extend(
            candidate
            for candidate in (
                getattr(current, "orig", None),
                getattr(current, "__cause__", None),
                getattr(current, "__context__", None),
            )
            if candidate is not None
        )
    return tuple(collected)


def _sqlstate(exc: BaseException) -> str | None:
    for original in _database_exception_chain(exc):
        sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
        if sqlstate:
            return str(sqlstate)
    return None


def _constraint_name(exc: BaseException) -> str | None:
    for original in _database_exception_chain(exc):
        name = getattr(original, "constraint_name", None)
        if not name:
            diagnostic = getattr(original, "diag", None)
            name = getattr(diagnostic, "constraint_name", None)
        if name:
            return str(name)
    return None


def _is_named_unique_violation(exc: IntegrityError, constraint_name: str) -> bool:
    return _sqlstate(exc) == "23505" and _constraint_name(exc) == constraint_name


def _guarded_used_delete(exc: DBAPIError) -> bool:
    original = getattr(exc, "orig", None)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return sqlstate == "42501" and "Master Admin may delete a Teaching Name" in str(original)


async def _require_scope_exists(
    db: AsyncSession,
    *,
    reporting_period_id: UUID,
    programme_code: str,
) -> None:
    reporting_period = await db.execute(
        text("SELECT id FROM reporting_periods WHERE id = :reporting_period_id"),
        {"reporting_period_id": str(reporting_period_id)},
    )
    if reporting_period.scalar_one_or_none() is None:
        _raise_validation("reporting_period_id is invalid")
    programme = await db.execute(
        text("SELECT code FROM programmes WHERE code = :programme_code"),
        {"programme_code": programme_code},
    )
    if programme.scalar_one_or_none() is None:
        _raise_validation("programme_code is invalid")


async def _require_active_period(
    db: AsyncSession,
    *,
    reporting_period_id: UUID,
) -> None:
    period = await resolve_explicit_reporting_period(
        db,
        reporting_period_id=reporting_period_id,
        require_effectively_active=True,
    )
    if period is None:
        _raise_validation("reporting_period_id must be effectively active")


async def _secretary_scope_allowed(
    db: AsyncSession,
    *,
    posting_code: str,
    programme_code: str,
) -> bool:
    result = await db.execute(
        text(
            """
            SELECT 1
            FROM secretary_programme_pools
            WHERE posting_code = :posting_code
              AND programme_code = :programme_code
              AND is_active = true
              AND can_manage_teaching_names = true
            LIMIT 1
            """
        ),
        {
            "posting_code": posting_code,
            "programme_code": programme_code,
        },
    )
    return result.scalar_one_or_none() is not None


async def _require_actor_scope(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    programme_code: str,
    scoped_id_lookup: bool = False,
) -> None:
    if actor.kind == "master_admin":
        return
    if actor.kind == "programme_pc":
        if programme_code in _normalised_scope(actor.programme_scope):
            return
        if scoped_id_lookup:
            _raise_not_found()
        _raise_forbidden("Forbidden - programme not in admin scope")
    if not actor.posting_code:
        if scoped_id_lookup:
            _raise_not_found()
        _raise_forbidden("Forbidden - Secretary posting is required")
    if await _secretary_scope_allowed(
        db,
        posting_code=actor.posting_code,
        programme_code=programme_code,
    ):
        return
    if scoped_id_lookup:
        _raise_not_found()
    _raise_forbidden("Forbidden - Secretary cannot manage this Teaching Name pool")


def _require_non_master_lifecycle_actor(actor: TeachingNamePoolActor) -> None:
    if actor.kind == "master_admin":
        _raise_forbidden(
            "Forbidden - Master Admin Teaching Name access is limited to oversight and deletion"
        )


async def _require_scope_lock(
    db: AsyncSession,
    *,
    reporting_period_id: UUID,
    programme_code: str,
) -> None:
    if not await acquire_ttf_scope_lock(
        db,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
    ):
        _raise_conflict(
            "A Teaching Name lifecycle change for this reporting period and programme is already in progress"
        )


async def _find_duplicate(
    db: AsyncSession,
    *,
    reporting_period_id: UUID,
    programme_code: str,
    normalized_name: str,
) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT id, is_active
            FROM teaching_names
            WHERE reporting_period_id = :reporting_period_id
              AND programme_code = :programme_code
              AND normalized_name = :normalized_name
            """
        ),
        {
            "reporting_period_id": str(reporting_period_id),
            "programme_code": programme_code,
            "normalized_name": normalized_name,
        },
    )
    row = result.mappings().one_or_none()
    return dict(row) if row is not None else None


async def _raise_duplicate_conflict(
    db: AsyncSession,
    *,
    reporting_period_id: UUID,
    programme_code: str,
    normalized_name: str,
) -> None:
    duplicate = await _find_duplicate(
        db,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
        normalized_name=normalized_name,
    )
    metadata: dict[str, Any] = {}
    if duplicate is not None:
        metadata = {
            "existing_teaching_name_id": str(duplicate["id"]),
            "may_reactivate": not bool(duplicate["is_active"]),
        }
    _raise_conflict("A Teaching Name with this normalized value already exists", metadata=metadata)


async def _locked_name(
    db: AsyncSession,
    *,
    teaching_name_id: UUID,
    actor: TeachingNamePoolActor,
    lock: bool = True,
) -> dict[str, Any]:
    lock_clause = "FOR UPDATE" if lock else ""
    result = await db.execute(
        text(
            f"""
            SELECT {_LOCKED_NAME_COLUMNS}
            FROM teaching_names
            WHERE id = :teaching_name_id
            {lock_clause}
            """
        ),
        {"teaching_name_id": str(teaching_name_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        _raise_not_found()
    payload = dict(row)
    await _require_actor_scope(
        db,
        actor=actor,
        programme_code=str(payload["programme_code"]),
        scoped_id_lookup=True,
    )
    if not _actor_can_manage_name(actor, payload) and actor.kind != "master_admin":
        _raise_forbidden(
            "Forbidden - only the Teaching Name source owner may change its lifecycle"
        )
    return payload


async def _lock_master_teaching_name_for_delete(
    db: AsyncSession,
    *,
    teaching_name_id: UUID,
) -> None:
    """Hold the definer-owned row lock before counting Master delete impact."""

    await db.execute(
        text(
            """
            SELECT mata_rls.lock_master_teaching_name_delete(
                CAST(:teaching_name_id AS uuid)
            )
            """
        ),
        {"teaching_name_id": str(teaching_name_id)},
    )


def _require_expected_revision(row: dict[str, Any], expected_revision: int) -> None:
    if int(row["revision"]) != expected_revision:
        _raise_conflict("Teaching Name has changed; refresh and retry")


def _revalidation_context(
    *,
    actor: TeachingNamePoolActor,
    action: DataRevalidationAction,
    row: dict[str, Any],
    changed_fields: list[str],
    reason: str | None = None,
) -> DataRevalidationContext:
    return DataRevalidationContext(
        trigger_source=_actor_trigger_source(actor),
        changed_entity=DataRevalidationChangedEntity.TEACHING_NAME,
        action=action,
        scope=DataRevalidationScope.PROGRAMME_REPORTING_PERIOD,
        entity_id=str(row["id"]),
        programme_code=str(row["programme_code"]),
        reporting_period_id=str(row["reporting_period_id"]),
        changed_fields=changed_fields,
        source_metadata={
            "teaching_name": row["teaching_name"],
            "is_active": bool(row["is_active"]),
        },
        actor_user_id=str(actor.user_id),
        actor_role=actor.staff_actor.actor_role,
        reason=reason,
    )


async def _write_lifecycle_audit(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    data_revalidation: Any,
    metadata: dict[str, Any] | None = None,
) -> None:
    snapshot = after or before
    if snapshot is None:
        raise RuntimeError("Teaching Name audit snapshot is required")
    audit_metadata = {
        "route_context": "teaching_name_pool",
        "reporting_period_id": str(snapshot["reporting_period_id"]),
        "programme_code": snapshot["programme_code"],
        "actor_kind": actor.kind,
        "data_revalidation": data_revalidation.audit_metadata,
    }
    if metadata:
        audit_metadata.update(metadata)
    await write_audit_log(
        db,
        actor=actor.staff_actor,
        action=_audit_action(actor, action),
        entity_type="teaching_name",
        entity_id=snapshot["id"],
        before=_public_snapshot(before) if before is not None else None,
        after=_public_snapshot(after) if after is not None else None,
        metadata=audit_metadata,
    )


def _invalidate_after_commit(
    *,
    row: dict[str, Any],
    event_references_cleared: bool = False,
) -> None:
    try:
        cache_invalidation.invalidate_after_teaching_name_pool_change(
            teaching_name_id=row["id"],
            reporting_period_id=row["reporting_period_id"],
            programme_code=row["programme_code"],
            event_references_cleared=event_references_cleared,
        )
    except Exception as exc:
        log_safe_exception(
            logger,
            "teaching_name_pool_cache_invalidation_failed",
            exc,
            category="cache_invalidation",
        )


async def list_secretary_programmes(
    db: AsyncSession,
    *,
    posting_code: str,
) -> list[dict[str, Any]]:
    if not posting_code.strip():
        _raise_forbidden("Forbidden - Secretary posting is required")
    result = await db.execute(
        text(
            """
            SELECT programme_code
            FROM secretary_programme_pools
            WHERE posting_code = :posting_code
              AND is_active = true
              AND can_manage_teaching_names = true
            ORDER BY programme_code ASC
            """
        ),
        {"posting_code": posting_code},
    )
    return [dict(row) for row in result.mappings().all()]


async def list_teaching_names(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    reporting_period_id: UUID,
    programme_code: str,
    is_active: bool | None,
    search: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    programme_code = _normalise_programme_code(programme_code)
    await _require_scope_exists(
        db,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
    )
    await _require_active_period(db, reporting_period_id=reporting_period_id)
    await _require_actor_scope(db, actor=actor, programme_code=programme_code)
    if actor.kind == "secretary":
        from_sql = """
            FROM teaching_names AS name
            JOIN teaching_name_programme_scopes AS scope
              ON scope.teaching_name_id = name.id
             AND scope.reporting_period_id = name.reporting_period_id
             AND scope.programme_code = name.programme_code
        """
        where = [
            "name.reporting_period_id = :reporting_period_id",
            "name.programme_code = :programme_code",
            "(name.origin_posting_code = :actor_posting_code OR "
            "(name.visibility_scope = 'programme_private' AND EXISTS ("
            "SELECT 1 FROM programmes AS native_programme "
            "WHERE native_programme.code = name.programme_code "
            "AND native_programme.native_teaching_posting_code = :actor_posting_code)))",
        ]
    else:
        from_sql = """
            FROM teaching_name_programme_scopes AS scope
            JOIN teaching_names AS name
              ON name.id = scope.teaching_name_id
             AND name.reporting_period_id = scope.reporting_period_id
        """
        where = [
            "scope.reporting_period_id = :reporting_period_id",
            "scope.programme_code = :programme_code",
        ]
    params: dict[str, Any] = {
        "reporting_period_id": str(reporting_period_id),
        "programme_code": programme_code,
        "limit": limit,
        "offset": offset,
        "actor_posting_code": actor.posting_code,
    }
    if is_active is not None:
        where.append("name.is_active = :is_active")
        params["is_active"] = is_active
    if search is not None and search.strip():
        where.append("name.display_name ILIKE :search")
        params["search"] = f"%{search.strip()}%"
    predicate = " AND ".join(where)
    rows_result = await db.execute(
        text(
            f"""
            SELECT
                name.id,
                name.reporting_period_id,
                name.programme_code,
                name.display_name AS teaching_name,
                name.created_by_role,
                name.visibility_scope,
                name.origin_posting_code,
                scope.admission_reason,
                name.is_active,
                name.revision,
                name.created_at,
                name.updated_at,
                name.deactivated_at
            {from_sql}
            WHERE {predicate}
            ORDER BY name.display_name ASC, name.id ASC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    count_result = await db.execute(
        text(f"SELECT COUNT(*) {from_sql} WHERE {predicate}"),
        params,
    )
    return {
        "items": [
            _response_row(dict(row), actor=actor)
            for row in rows_result.mappings().all()
        ],
        "total": int(count_result.scalar_one()),
        "limit": limit,
        "offset": offset,
    }


async def create_teaching_name(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    reporting_period_id: UUID,
    programme_code: str,
    teaching_name: str,
) -> dict[str, Any]:
    _require_non_master_lifecycle_actor(actor)
    programme_code = _normalise_programme_code(programme_code)
    display_name, normalized_name = normalise_teaching_name(teaching_name)
    try:
        await _require_scope_exists(
            db,
            reporting_period_id=reporting_period_id,
            programme_code=programme_code,
        )
        await _require_actor_scope(db, actor=actor, programme_code=programme_code)
        await _require_scope_lock(
            db,
            reporting_period_id=reporting_period_id,
            programme_code=programme_code,
        )
        await _require_active_period(db, reporting_period_id=reporting_period_id)
        created_result = await db.execute(
            text(
                f"""
                INSERT INTO teaching_names (
                    reporting_period_id,
                    programme_code,
                    display_name,
                    normalized_name,
                    created_by_role,
                    visibility_scope,
                    origin_posting_code,
                    created_by_user_id,
                    updated_by_user_id
                )
                VALUES (
                    :reporting_period_id,
                    :programme_code,
                    :display_name,
                    :normalized_name,
                    :created_by_role,
                    :visibility_scope,
                    :origin_posting_code,
                    :actor_user_id,
                    :actor_user_id
                )
                RETURNING {_NAME_COLUMNS}
                """
            ),
            {
                "reporting_period_id": str(reporting_period_id),
                "programme_code": programme_code,
                "display_name": display_name,
                "normalized_name": normalized_name,
                "actor_user_id": str(actor.user_id),
                "created_by_role": actor.kind,
                "visibility_scope": (
                    "department_shared"
                    if actor.kind == "secretary"
                    else "programme_private"
                ),
                "origin_posting_code": (
                    actor.posting_code if actor.kind == "secretary" else None
                ),
            },
        )
        created = dict(created_result.mappings().one())
        scope_counts = await reconcile_teaching_name_programme_scopes(
            db,
            reporting_period_id=reporting_period_id,
            programme_code=programme_code,
        )
        data_revalidation = await data_revalidation_service.revalidate_after_config_change(
            context=_revalidation_context(
                actor=actor,
                action=DataRevalidationAction.CREATE,
                row=created,
                changed_fields=["teaching_name", "is_active"],
            ),
            db_session=db,
        )
        await _write_lifecycle_audit(
            db,
            actor=actor,
            action="create",
            before=None,
            after=created,
            data_revalidation=data_revalidation,
            metadata={
                "programme_scopes_created": scope_counts["programme_scopes_created"],
                "pending_mappings_created": scope_counts["pending_mappings_created"],
            },
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _is_named_unique_violation(exc, "uq_teaching_names_pool_normalized_name"):
            await _raise_duplicate_conflict(
                db,
                reporting_period_id=reporting_period_id,
                programme_code=programme_code,
                normalized_name=normalized_name,
            )
        raise
    except Exception:
        await db.rollback()
        raise
    _invalidate_after_commit(row=created)
    return {
        **_response_row(created, actor=actor),
        "data_revalidation": data_revalidation,
    }


async def update_teaching_name(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    teaching_name_id: UUID,
    teaching_name: str,
    expected_revision: int,
) -> dict[str, Any]:
    _require_non_master_lifecycle_actor(actor)
    display_name, normalized_name = normalise_teaching_name(teaching_name)
    try:
        before = await _locked_name(db, teaching_name_id=teaching_name_id, actor=actor)
        _require_expected_revision(before, expected_revision)
        updated_result = await db.execute(
            text(
                f"""
                UPDATE teaching_names
                SET display_name = :display_name,
                    normalized_name = :normalized_name,
                    revision = revision + 1,
                    updated_by_user_id = :actor_user_id,
                    updated_at = now()
                WHERE id = :teaching_name_id
                  AND revision = :expected_revision
                RETURNING {_NAME_COLUMNS}
                """
            ),
            {
                "teaching_name_id": str(teaching_name_id),
                "display_name": display_name,
                "normalized_name": normalized_name,
                "actor_user_id": str(actor.user_id),
                "expected_revision": expected_revision,
            },
        )
        updated_row = updated_result.mappings().one_or_none()
        if updated_row is None:
            _raise_conflict("Teaching Name has changed; refresh and retry")
        updated = dict(updated_row)
        data_revalidation = await data_revalidation_service.revalidate_after_config_change(
            context=_revalidation_context(
                actor=actor,
                action=DataRevalidationAction.UPDATE,
                row=updated,
                changed_fields=["teaching_name"],
            ),
            db_session=db,
        )
        await _write_lifecycle_audit(
            db,
            actor=actor,
            action="rename",
            before=before,
            after=updated,
            data_revalidation=data_revalidation,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _is_named_unique_violation(exc, "uq_teaching_names_pool_normalized_name"):
            await _raise_duplicate_conflict(
                db,
                reporting_period_id=before["reporting_period_id"],
                programme_code=str(before["programme_code"]),
                normalized_name=normalized_name,
            )
        raise
    except Exception:
        await db.rollback()
        raise
    _invalidate_after_commit(row=updated)
    return {
        **_response_row(updated, actor=actor),
        "data_revalidation": data_revalidation,
    }


async def deactivate_teaching_name(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    teaching_name_id: UUID,
    expected_revision: int,
) -> dict[str, Any]:
    _require_non_master_lifecycle_actor(actor)
    try:
        before = await _locked_name(db, teaching_name_id=teaching_name_id, actor=actor)
        _require_expected_revision(before, expected_revision)
        if not bool(before["is_active"]):
            _raise_validation("Teaching Name is already inactive")
        updated_result = await db.execute(
            text(
                f"""
                UPDATE teaching_names
                SET is_active = false,
                    revision = revision + 1,
                    updated_by_user_id = :actor_user_id,
                    deactivated_by_user_id = :actor_user_id,
                    deactivated_at = now(),
                    updated_at = now()
                WHERE id = :teaching_name_id
                  AND revision = :expected_revision
                RETURNING {_NAME_COLUMNS}
                """
            ),
            {
                "teaching_name_id": str(teaching_name_id),
                "actor_user_id": str(actor.user_id),
                "expected_revision": expected_revision,
            },
        )
        updated_row = updated_result.mappings().one_or_none()
        if updated_row is None:
            _raise_conflict("Teaching Name has changed; refresh and retry")
        updated = dict(updated_row)
        data_revalidation = await data_revalidation_service.revalidate_after_config_change(
            context=_revalidation_context(
                actor=actor,
                action=DataRevalidationAction.DEACTIVATE,
                row=updated,
                changed_fields=["is_active"],
            ),
            db_session=db,
        )
        await _write_lifecycle_audit(
            db,
            actor=actor,
            action="deactivate",
            before=before,
            after=updated,
            data_revalidation=data_revalidation,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    _invalidate_after_commit(row=updated)
    return {
        **_response_row(updated, actor=actor),
        "data_revalidation": data_revalidation,
    }


async def reactivate_teaching_name(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    teaching_name_id: UUID,
    expected_revision: int,
) -> dict[str, Any]:
    _require_non_master_lifecycle_actor(actor)
    try:
        before = await _locked_name(db, teaching_name_id=teaching_name_id, actor=actor)
        _require_expected_revision(before, expected_revision)
        if bool(before["is_active"]):
            _raise_validation("Teaching Name is already active")
        await _require_scope_lock(
            db,
            reporting_period_id=before["reporting_period_id"],
            programme_code=str(before["programme_code"]),
        )
        updated_result = await db.execute(
            text(
                f"""
                UPDATE teaching_names
                SET is_active = true,
                    revision = revision + 1,
                    updated_by_user_id = :actor_user_id,
                    deactivated_by_user_id = NULL,
                    deactivated_at = NULL,
                    updated_at = now()
                WHERE id = :teaching_name_id
                  AND revision = :expected_revision
                RETURNING {_NAME_COLUMNS}
                """
            ),
            {
                "teaching_name_id": str(teaching_name_id),
                "actor_user_id": str(actor.user_id),
                "expected_revision": expected_revision,
            },
        )
        updated_row = updated_result.mappings().one_or_none()
        if updated_row is None:
            _raise_conflict("Teaching Name has changed; refresh and retry")
        updated = dict(updated_row)
        scope_counts = await reconcile_teaching_name_programme_scopes(
            db,
            reporting_period_id=updated["reporting_period_id"],
            programme_code=str(updated["programme_code"]),
        )
        data_revalidation = await data_revalidation_service.revalidate_after_config_change(
            context=_revalidation_context(
                actor=actor,
                action=DataRevalidationAction.ACTIVATE,
                row=updated,
                changed_fields=["is_active"],
            ),
            db_session=db,
        )
        await _write_lifecycle_audit(
            db,
            actor=actor,
            action="reactivate",
            before=before,
            after=updated,
            data_revalidation=data_revalidation,
            metadata={
                "programme_scopes_created": scope_counts["programme_scopes_created"],
                "pending_mappings_created": scope_counts["pending_mappings_created"],
            },
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    _invalidate_after_commit(row=updated)
    return {
        **_response_row(updated, actor=actor),
        "data_revalidation": data_revalidation,
    }


async def _locked_event_ids(
    db: AsyncSession,
    *,
    teaching_name_id: UUID,
) -> list[UUID]:
    initial_result = await db.execute(
        text(
            """
            SELECT id
            FROM teaching_events
            WHERE teaching_name_id = :teaching_name_id
            ORDER BY id ASC
            """
        ),
        {"teaching_name_id": str(teaching_name_id)},
    )
    initial_event_ids = [row[0] for row in initial_result.all()]
    if initial_event_ids:
        await acquire_teaching_event_locks(db, event_ids=initial_event_ids)
    locked_result = await db.execute(
        text(
            """
            SELECT id
            FROM teaching_events
            WHERE teaching_name_id = :teaching_name_id
            ORDER BY id ASC
            FOR UPDATE
            """
        ),
        {"teaching_name_id": str(teaching_name_id)},
    )
    return [row[0] for row in locked_result.all()]


async def _attendance_count(
    db: AsyncSession,
    *,
    table_name: Literal["attendance_records", "external_attendance_records"],
    teaching_name_id: UUID,
) -> int:
    result = await db.execute(
        text(
            f"""
            SELECT COUNT(*) AS count
            FROM {table_name} AS attendance
            JOIN teaching_events AS event
              ON event.id = attendance.teaching_event_id
            WHERE event.teaching_name_id = :teaching_name_id
            """
        ),
        {"teaching_name_id": str(teaching_name_id)},
    )
    return int(result.scalar_one())


async def delete_teaching_name(
    db: AsyncSession,
    *,
    actor: TeachingNamePoolActor,
    teaching_name_id: UUID,
    expected_revision: int,
    force_delete: bool,
    reason: str | None,
    confirmation: str | None,
) -> dict[str, Any]:
    try:
        uses_master_delete_lock = actor.kind == "master_admin" and session_uses_rls(db)
        if uses_master_delete_lock:
            await _lock_master_teaching_name_for_delete(
                db,
                teaching_name_id=teaching_name_id,
            )
        before = await _locked_name(
            db,
            teaching_name_id=teaching_name_id,
            actor=actor,
            lock=not uses_master_delete_lock,
        )
        _require_expected_revision(before, expected_revision)
        await _require_scope_lock(
            db,
            reporting_period_id=before["reporting_period_id"],
            programme_code=str(before["programme_code"]),
        )
        event_ids = await _locked_event_ids(db, teaching_name_id=teaching_name_id)
        used_name = bool(event_ids)
        native_attendance_count = 0
        non_nhg_attendance_count = 0
        deletion_reason: str | None = None

        if used_name:
            if actor.kind != "master_admin":
                _raise_conflict("Teaching Name is in use; deactivate it instead")
            if not force_delete or confirmation != "DELETE":
                _raise_conflict('Used Teaching Name deletion requires confirmation exactly "DELETE"')
            deletion_reason = (reason or "").strip()
            if not deletion_reason:
                _raise_validation("Deletion reason is required")
            # _locked_event_ids has already acquired the shared event locks that
            # serialize attendance changes.  A row lock on attendance would
            # require ordinary attendance UPDATE authority, which Master Admins
            # intentionally do not have.
            native_attendance_count = await _attendance_count(
                db,
                table_name="attendance_records",
                teaching_name_id=teaching_name_id,
            )
            non_nhg_attendance_count = await _attendance_count(
                db,
                table_name="external_attendance_records",
                teaching_name_id=teaching_name_id,
            )

        deleted_result = await db.execute(
            text(
                """
                DELETE FROM teaching_names
                WHERE id = :teaching_name_id
                  AND revision = :expected_revision
                RETURNING id
                """
            ),
            {
                "teaching_name_id": str(teaching_name_id),
                "expected_revision": expected_revision,
            },
        )
        if deleted_result.scalar_one_or_none() is None:
            _raise_conflict("Teaching Name has changed; refresh and retry")
        revalidation_row = dict(before)
        data_revalidation = await data_revalidation_service.revalidate_after_config_change(
            context=_revalidation_context(
                actor=actor,
                action=DataRevalidationAction.DELETE,
                row=revalidation_row,
                changed_fields=["deleted"],
                reason=deletion_reason,
            ),
            db_session=db,
        )
        await _write_lifecycle_audit(
            db,
            actor=actor,
            action="force_delete" if used_name else "delete",
            before=before,
            after=None,
            data_revalidation=data_revalidation,
            metadata={
                "used_name": used_name,
                "event_reference_count": len(event_ids),
                "native_attendance_count": native_attendance_count,
                "non_nhg_attendance_count": non_nhg_attendance_count,
                "deletion_reason": deletion_reason,
                "event_identifiers_included": False,
                "attendance_identifiers_included": False,
            },
        )
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        if _guarded_used_delete(exc):
            _raise_conflict("Teaching Name is in use; deactivate it instead")
        raise
    except Exception:
        await db.rollback()
        raise
    _invalidate_after_commit(row=before, event_references_cleared=used_name)
    return {
        "teaching_name_id": teaching_name_id,
        "deleted": True,
        "used_name": used_name,
        "event_reference_count": len(event_ids),
        "native_attendance_count": native_attendance_count,
        "non_nhg_attendance_count": non_nhg_attendance_count,
        "data_revalidation": data_revalidation,
    }
