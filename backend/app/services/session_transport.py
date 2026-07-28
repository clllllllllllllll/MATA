from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from app.config import Settings


AUTH_COOKIE_COORDINATION_HEADER_NAME = "X-MATA-Session-Coordination"
AUTH_COOKIE_COORDINATION_PROTOCOL = "web-locks-v1"


def auth_cookie_coordination_required(settings: Settings) -> bool:
    return (
        settings.environment == "production"
        and settings.auth_mode == "supabase"
        and settings.auth_transport == "cookie"
    )


def has_auth_cookie_coordination(
    request: Request,
    *,
    settings: Settings,
) -> bool:
    if not auth_cookie_coordination_required(settings):
        return True
    return (
        request.headers.get(AUTH_COOKIE_COORDINATION_HEADER_NAME)
        == AUTH_COOKIE_COORDINATION_PROTOCOL
    )


def session_cookie_name(settings: Settings) -> str:
    if settings.environment == "production":
        return settings.mata_session_cookie_name
    return settings.mata_local_session_cookie_name


def set_session_cookie(
    response: Response,
    *,
    settings: Settings,
    session_token: str,
) -> None:
    """Issue an intentionally non-persistent browser-session cookie.

    A relative Max-Age calculated before transaction commit or response
    delivery cannot be proven to end by the PostgreSQL absolute deadline.
    Server-side idle/absolute checks therefore remain the sole expiry
    authority and the browser receives no persistent lifetime directive.
    """

    response.set_cookie(
        key=session_cookie_name(settings),
        value=session_token,
        path="/",
        secure=settings.environment == "production",
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response, *, settings: Settings) -> None:
    response.delete_cookie(
        key=session_cookie_name(settings),
        path="/",
        secure=settings.environment == "production",
        httponly=True,
        samesite="strict",
    )
