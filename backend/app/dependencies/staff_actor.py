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


def _validate_actor_name(raw_actor_name: str | None) -> str:
    actor_name = _normalise_optional_header(raw_actor_name)
    if actor_name is None:
        # TODO(StaffActor): Re-enable explicit staff actor name workflow when audit UX is finalized.
        return STAFF_ACTOR_FALLBACK_NAME
    if len(actor_name) > 120:
        raise ApiError(
            status_code=422,
            detail="X-Actor-Name must be 120 characters or fewer",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in actor_name):
        raise ApiError(
            status_code=422,
            detail="X-Actor-Name must not contain control characters",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    return actor_name


async def require_staff_actor(
    x_actor_name: Annotated[str | None, Header(alias="X-Actor-Name")] = None,
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

    actor_name = _validate_actor_name(x_actor_name)
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
        actor_name=actor_name,
        actor_site=actor_site,
        actor_programme=actor_programme,
        actor_admin_level=actor_admin_level,
        raw_scope_metadata=raw_scope_metadata,
    )
