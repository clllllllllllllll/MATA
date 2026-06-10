from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.staff_actor import StaffActorContext
from app.errors import ApiError, ErrorCode


def _require_non_empty_label(value: str, *, field_name: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ApiError(
            status_code=422,
            detail=f"{field_name} is required",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    return trimmed


def _json_payload(value: Mapping[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(dict(value), default=str)


def _metadata_payload(
    actor: StaffActorContext,
    metadata: Mapping[str, Any] | None,
) -> str | None:
    payload: dict[str, Any] = {}
    if metadata:
        payload.update(dict(metadata))
    payload.update(actor.raw_scope_metadata)
    return _json_payload(payload) if payload else None


async def write_audit_log(
    db: AsyncSession,
    *,
    actor: StaffActorContext,
    action: str,
    entity_type: str,
    entity_id: UUID | str | None = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    action_label = _require_non_empty_label(action, field_name="action")
    entity_type_label = _require_non_empty_label(entity_type, field_name="entity_type")
    audit_log_id = uuid4()

    params = {
        "id": str(audit_log_id),
        "actor_user_id": str(actor.actor_user_id) if actor.actor_user_id else None,
        "actor_role": actor.actor_role,
        "actor_name": actor.actor_name,
        "actor_site": actor.actor_site,
        "actor_programme": actor.actor_programme,
        "actor_admin_level": actor.actor_admin_level,
        "action": action_label,
        "entity_type": entity_type_label,
        "entity_id": str(entity_id) if entity_id else None,
        "before_json": _json_payload(before),
        "after_json": _json_payload(after),
        "metadata_json": _metadata_payload(actor, metadata),
    }

    result = await db.execute(
        text(
            """
            INSERT INTO audit_logs (
                id,
                actor_user_id,
                actor_role,
                actor_name,
                actor_site,
                actor_programme,
                actor_admin_level,
                action,
                entity_type,
                entity_id,
                before_json,
                after_json,
                metadata_json
            )
            VALUES (
                :id,
                :actor_user_id,
                :actor_role,
                :actor_name,
                :actor_site,
                :actor_programme,
                :actor_admin_level,
                :action,
                :entity_type,
                :entity_id,
                :before_json,
                :after_json,
                :metadata_json
            )
            RETURNING
                id,
                actor_user_id,
                actor_role,
                actor_name,
                actor_site,
                actor_programme,
                actor_admin_level,
                action,
                entity_type,
                entity_id,
                before_json,
                after_json,
                metadata_json,
                created_at
            """
        ),
        params,
    )
    return dict(result.mappings().one())
