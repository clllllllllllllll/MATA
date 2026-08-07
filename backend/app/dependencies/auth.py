from __future__ import annotations

from fastapi import Depends, Request

from app.errors import ApiError, ErrorCode
from app.middleware.auth_stub import AuthIdentity


def _unauthorized() -> ApiError:
    return ApiError(
        status_code=401,
        detail="Unauthorized",
        error_code=ErrorCode.UNAUTHORIZED.value,
    )


def _forbidden(detail: str = "Forbidden") -> ApiError:
    return ApiError(
        status_code=403,
        detail=detail,
        error_code=ErrorCode.FORBIDDEN.value,
    )


def _normalise_admin_level(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    value = raw_value.strip().lower()
    if value == "master_admin":
        return "master"
    if value in {"programme", "master"}:
        return value
    return None


def normalise_programme_scope(raw_scope: list[str] | None) -> list[str]:
    if raw_scope is None:
        return []
    seen: set[str] = set()
    normalised: list[str] = []
    for raw in raw_scope:
        value = raw.strip().upper() if isinstance(raw, str) else ""
        if value and value not in seen:
            seen.add(value)
            normalised.append(value)
    return normalised


async def get_current_identity(request: Request) -> AuthIdentity:
    identity = getattr(request.state, "identity", None)
    if not isinstance(identity, AuthIdentity):
        raise _unauthorized()
    return identity


async def require_authenticated(
    identity: AuthIdentity = Depends(get_current_identity),
) -> AuthIdentity:
    return identity


async def require_admin(
    identity: AuthIdentity = Depends(require_authenticated),
) -> AuthIdentity:
    if identity.role != "admin":
        raise _forbidden("Forbidden - admin role required")
    return identity


def is_master_admin(identity: AuthIdentity) -> bool:
    return (
        identity.role == "admin"
        and _normalise_admin_level(identity.admin_level) == "master"
    )


async def require_master_admin(
    identity: AuthIdentity = Depends(require_admin),
) -> AuthIdentity:
    if not is_master_admin(identity):
        raise _forbidden("Forbidden - master admin access required")
    return identity


async def require_programme_pc(
    identity: AuthIdentity = Depends(require_admin),
) -> AuthIdentity:
    if is_master_admin(identity):
        raise _forbidden("Forbidden - programme PC access required")
    identity.programme_scope = normalise_programme_scope(identity.programme_scope)
    if not identity.programme_scope:
        raise _forbidden("Forbidden - admin programme scope is empty")
    return identity


def ensure_programme_in_scope(identity: AuthIdentity, programme_code: str) -> None:
    identity.programme_scope = normalise_programme_scope(identity.programme_scope)
    if not identity.programme_scope:
        raise _forbidden("Forbidden - admin programme scope is empty")
    if programme_code.strip().upper() not in identity.programme_scope:
        raise _forbidden("Forbidden - programme not in admin scope")


async def require_secretary(
    identity: AuthIdentity = Depends(require_authenticated),
) -> AuthIdentity:
    if identity.role != "secretary":
        raise _forbidden("Forbidden - secretary role required")
    if not identity.posting_code:
        raise _forbidden("Forbidden - secretary posting scope is empty")
    return identity


async def require_resident(
    identity: AuthIdentity = Depends(require_authenticated),
) -> AuthIdentity:
    if identity.role != "resident":
        raise _forbidden("Forbidden - resident role required")
    return identity


async def require_resident_or_external(
    identity: AuthIdentity = Depends(require_authenticated),
) -> AuthIdentity:
    if identity.role not in {"resident", "external_resident"}:
        raise _forbidden("Forbidden - resident role required")
    return identity


async def require_external_resident(
    identity: AuthIdentity = Depends(require_authenticated),
) -> AuthIdentity:
    if identity.role != "external_resident":
        raise _forbidden("Forbidden - external_resident role required")
    return identity
