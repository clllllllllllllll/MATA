from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import ErrorCode
from app.services.persistent_rate_limit import (
    RateLimitPolicy,
    check_rate_limit,
)


AUTH_LOGIN_IP_POLICY = RateLimitPolicy(
    scope="auth_login_ip",
    limit=5,
    window_seconds=60,
    message="Too many attempts. Please try again later.",
)
AUTH_LOGIN_IDENTIFIER_POLICY = RateLimitPolicy(
    scope="auth_login_identifier",
    limit=10,
    window_seconds=3600,
    message="Too many attempts. Please try again later.",
)
EXTERNAL_REGISTER_IP_POLICY = RateLimitPolicy(
    scope="external_register_ip",
    limit=3,
    window_seconds=600,
    message="Too many registration attempts. Please try again later.",
)
EXTERNAL_REGISTER_MCR_POLICY = RateLimitPolicy(
    scope="external_register_mcr",
    limit=5,
    window_seconds=3600,
    message="Too many registration attempts. Please try again later.",
)
UPLOAD_POLICY = RateLimitPolicy(
    scope="admin_upload",
    limit=10,
    window_seconds=3600,
    message="Too many upload attempts. Please try again later.",
)


def client_ip_identifier(request: Request) -> str:
    # Keep the same conservative source as the existing in-memory middleware.
    return request.client.host if request.client else "unknown"


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalise_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _login_identifier(payload: dict[str, Any]) -> str | None:
    role = (_normalise_text(payload.get("role")) or "unknown").lower()
    bucket_role = (
        "resident"
        if role in {"resident", "external_resident"}
        else role
    )
    if bucket_role == "resident":
        mcr = _normalise_text(payload.get("mcr"))
        return f"{bucket_role}:mcr:{mcr.upper()}" if mcr else None

    email = _normalise_text(payload.get("email"))
    return f"{bucket_role}:email:{email.lower()}" if email else None


def _external_register_mcr_identifier(payload: dict[str, Any]) -> str | None:
    mcr = _normalise_text(payload.get("mcr"))
    return f"mcr:{mcr.upper()}" if mcr else None


def _raise_if_blocked(*, allowed: bool, retry_after_seconds: int, message: str) -> None:
    if allowed:
        return
    raise HTTPException(
        status_code=429,
        detail={
            "detail": message,
            "error_code": ErrorCode.RATE_LIMITED.value,
            "errors": [],
            "warnings": [],
            "metadata": {},
        },
        headers={"Retry-After": str(max(1, retry_after_seconds))},
    )


async def _enforce_policy(
    db: AsyncSession | None,
    *,
    settings: Settings,
    policy: RateLimitPolicy,
    identifier: str,
) -> None:
    if db is None:
        return
    result = await check_rate_limit(
        db,
        settings=settings,
        policy=policy,
        identifier=identifier,
    )
    _raise_if_blocked(
        allowed=result.allowed,
        retry_after_seconds=result.retry_after_seconds,
        message=policy.message,
    )


async def enforce_auth_login_persistent_rate_limit(
    request: Request,
    *,
    db: AsyncSession | None,
    settings: Settings,
) -> None:
    payload = await _json_body(request)
    await _enforce_policy(
        db,
        settings=settings,
        policy=AUTH_LOGIN_IP_POLICY,
        identifier=client_ip_identifier(request),
    )

    identifier = _login_identifier(payload)
    if identifier is None:
        return
    await _enforce_policy(
        db,
        settings=settings,
        policy=AUTH_LOGIN_IDENTIFIER_POLICY,
        identifier=identifier,
    )


async def enforce_external_registration_persistent_rate_limit(
    request: Request,
    *,
    db: AsyncSession | None,
    settings: Settings,
) -> None:
    payload = await _json_body(request)
    await _enforce_policy(
        db,
        settings=settings,
        policy=EXTERNAL_REGISTER_IP_POLICY,
        identifier=client_ip_identifier(request),
    )

    mcr_identifier = _external_register_mcr_identifier(payload)
    if mcr_identifier is None:
        return
    await _enforce_policy(
        db,
        settings=settings,
        policy=EXTERNAL_REGISTER_MCR_POLICY,
        identifier=mcr_identifier,
    )


async def enforce_upload_persistent_rate_limit(
    db: AsyncSession | None,
    *,
    settings: Settings,
    user_id: UUID | None,
    upload_type: str,
    programme_code: str | None = None,
) -> None:
    programme_part = f"|programme:{programme_code.strip().upper()}" if programme_code else ""
    user_part = str(user_id) if user_id is not None else "unknown"
    identifier = f"user:{user_part}|upload:{upload_type.strip().lower()}{programme_part}"
    await _enforce_policy(
        db,
        settings=settings,
        policy=UPLOAD_POLICY,
        identifier=identifier,
    )
