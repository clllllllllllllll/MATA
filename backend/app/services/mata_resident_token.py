from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from jwt import InvalidTokenError

from app.config import Settings


class MataResidentTokenError(Exception):
    """Raised when a MATA resident session token cannot be trusted."""


MATA_RESIDENT_SESSION_ROLES = {"resident", "external_resident"}
EXTERNAL_FORBIDDEN_CLAIMS = {
    "current_nhg_posting_code",
    "current_posting",
    "posting_code",
    "posting_schedule",
    "programme_code",
    "programme_scope",
    "admin_level",
    "current_staff_actor_name",
}


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise MataResidentTokenError("Missing Authorization header")

    scheme, separator, token = authorization.strip().partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise MataResidentTokenError("Invalid Authorization header")
    return token.strip()


def _resident_secret(settings: Settings) -> str:
    configured_secret = (settings.mata_resident_session_secret or "").strip()
    if configured_secret:
        return configured_secret

    if settings.environment != "production":
        return "development-only-mata-resident-session-secret"

    raise MataResidentTokenError("MATA_RESIDENT_SESSION_SECRET is required")


def sign_mata_resident_token(
    resident: Mapping[str, Any],
    *,
    settings: Settings,
) -> str:
    resident_id = str(resident.get("id") or "")
    mcr = str(resident.get("mcr") or "").strip().upper()
    programme_code = str(resident.get("programme_code") or "").strip()
    if not resident_id or not mcr or not programme_code:
        raise MataResidentTokenError("Resident token claims are incomplete")

    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=max(1, settings.mata_resident_session_ttl_minutes))
    return jwt.encode(
        {
            "iss": settings.mata_resident_session_issuer,
            "aud": settings.mata_resident_session_audience,
            "sub": resident_id,
            "role": "resident",
            "app_role": "resident",
            "mcr": mcr,
            "programme_code": programme_code,
            "iat": now,
            "exp": expires_at,
        },
        _resident_secret(settings),
        algorithm="HS256",
    )


def sign_mata_external_resident_token(
    external_resident: Mapping[str, Any],
    *,
    settings: Settings,
) -> str:
    external_resident_id = str(external_resident.get("id") or "")
    mcr = str(external_resident.get("mcr") or "").strip().upper()
    home_cluster = _normalise_home_cluster(external_resident.get("home_cluster"))
    if not external_resident_id or not mcr or home_cluster is None:
        raise MataResidentTokenError("External resident token claims are incomplete")

    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=max(1, settings.mata_resident_session_ttl_minutes))
    return jwt.encode(
        {
            "iss": settings.mata_resident_session_issuer,
            "aud": settings.mata_resident_session_audience,
            "sub": external_resident_id,
            "role": "external_resident",
            "app_role": "external_resident",
            "mcr": mcr,
            "home_cluster": home_cluster,
            "iat": now,
            "exp": expires_at,
        },
        _resident_secret(settings),
        algorithm="HS256",
    )


def _normalise_home_cluster(raw_value: object) -> str | None:
    value = str(raw_value or "").strip()
    if value.upper() == "NUH":
        return "NUH"
    if value.lower() == "singhealth":
        return "SingHealth"
    return None


def verify_mata_resident_token(
    token: str,
    *,
    settings: Settings,
) -> dict[str, Any]:
    try:
        claims = jwt.decode(
            token,
            _resident_secret(settings),
            algorithms=["HS256"],
            audience=settings.mata_resident_session_audience,
            issuer=settings.mata_resident_session_issuer,
            options={"require": ["iss", "aud", "sub", "exp", "iat"]},
        )
    except InvalidTokenError as exc:
        raise MataResidentTokenError("Invalid MATA resident token") from exc

    if not isinstance(claims, dict):
        raise MataResidentTokenError("Invalid MATA resident claims")
    role = claims.get("role")
    app_role = claims.get("app_role")
    if role != app_role or role not in MATA_RESIDENT_SESSION_ROLES:
        raise MataResidentTokenError("Invalid MATA resident role")
    if not isinstance(claims.get("sub"), str):
        raise MataResidentTokenError("Invalid MATA resident subject")
    try:
        UUID(claims["sub"])
    except ValueError as exc:
        raise MataResidentTokenError("Invalid MATA resident subject") from exc
    if not isinstance(claims.get("mcr"), str) or not claims["mcr"].strip():
        raise MataResidentTokenError("Invalid MATA resident MCR")
    if role == "resident":
        if (
            not isinstance(claims.get("programme_code"), str)
            or not claims["programme_code"].strip()
        ):
            raise MataResidentTokenError("Invalid MATA resident programme")
    if role == "external_resident":
        if _normalise_home_cluster(claims.get("home_cluster")) is None:
            raise MataResidentTokenError("Invalid MATA external resident home cluster")
        if any(claim in claims for claim in EXTERNAL_FORBIDDEN_CLAIMS):
            raise MataResidentTokenError("Invalid MATA external resident claims")
    return claims


def is_mata_resident_token(token: str, *, settings: Settings) -> bool:
    try:
        claims = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
                "verify_iss": False,
                "verify_iat": False,
            },
        )
    except InvalidTokenError:
        return False

    if not isinstance(claims, dict):
        return False
    audience = claims.get("aud")
    if isinstance(audience, str):
        has_audience = audience == settings.mata_resident_session_audience
    elif isinstance(audience, list):
        has_audience = settings.mata_resident_session_audience in audience
    else:
        has_audience = False
    return (
        claims.get("iss") == settings.mata_resident_session_issuer
        and has_audience
        and claims.get("app_role") in MATA_RESIDENT_SESSION_ROLES
    )
