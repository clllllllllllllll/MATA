from __future__ import annotations

from datetime import UTC, datetime

from starlette.responses import Response

from app.config import Settings


def session_cookie_name(settings: Settings) -> str:
    if settings.environment == "production":
        return settings.mata_session_cookie_name
    return settings.mata_local_session_cookie_name


def set_session_cookie(
    response: Response,
    *,
    settings: Settings,
    session_token: str,
    absolute_expires_at: datetime,
    now: datetime | None = None,
) -> None:
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    max_age = max(1, int((absolute_expires_at - current_time).total_seconds()))
    response.set_cookie(
        key=session_cookie_name(settings),
        value=session_token,
        max_age=max_age,
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
