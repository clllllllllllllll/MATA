from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any
from uuid import UUID

from fastapi import Header

from app.errors import ApiError, ErrorCode

STAFF_ACTOR_FALLBACK_NAME = "Unknown actor"


@dataclass(slots=True)
class StaffActorContext:
    actor_user_id: UUID | None
    actor_role: str
    actor_name: str
    actor_site: str | None = None
    actor_programme: str | None = None
    actor_admin_level: str | None = None
    raw_scope_metadata: dict[str, Any] = field(default_factory=dict)


def _normalise_optional_header(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _parse_scope(raw_programme: str | None) -> list[str]:
    if raw_programme is None:
        return []
    return [token.strip() for token in raw_programme.split(",") if token.strip()]


def _parse_actor_user_id(raw_user_id: str | None) -> UUID | None:
    value = _normalise_optional_header(raw_user_id)
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise ApiError(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        ) from exc


async def require_staff_actor(
    x_user_role: Annotated[str | None, Header(alias="X-User-Role")] = None,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_user_site: Annotated[str | None, Header(alias="X-User-Site")] = None,
    x_user_programme: Annotated[str | None, Header(alias="X-User-Programme")] = None,
    x_admin_level: Annotated[str | None, Header(alias="X-Admin-Level")] = None,
) -> StaffActorContext:
    actor_role = (_normalise_optional_header(x_user_role) or "").lower()
    if actor_role not in {"admin", "secretary"}:
        raise ApiError(
            status_code=403,
            detail="Forbidden - staff role required",
            error_code=ErrorCode.FORBIDDEN.value,
        )

    programme_scope = _parse_scope(x_user_programme)
    actor_site = _normalise_optional_header(x_user_site)
    actor_programme = _normalise_optional_header(x_user_programme)
    actor_admin_level = _normalise_optional_header(x_admin_level)
    raw_scope_metadata: dict[str, Any] = {}
    if programme_scope:
        raw_scope_metadata["programme_scope"] = programme_scope
    if actor_site:
        raw_scope_metadata["site"] = actor_site
    if actor_admin_level:
        raw_scope_metadata["admin_level"] = actor_admin_level

    return StaffActorContext(
        actor_user_id=_parse_actor_user_id(x_user_id),
        actor_role=actor_role,
        actor_name=STAFF_ACTOR_FALLBACK_NAME,
        actor_site=actor_site,
        actor_programme=actor_programme,
        actor_admin_level=actor_admin_level,
        raw_scope_metadata=raw_scope_metadata,
    )
