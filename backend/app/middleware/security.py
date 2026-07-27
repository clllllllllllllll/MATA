from __future__ import annotations

import re

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import PlainTextResponse
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.middleware.errors import safe_unexpected_error_response


_HOST_HEADER_PATTERN = re.compile(
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?"
    r"|\[[0-9A-Fa-f:.]+\])(?::([0-9]{1,5}))?"
)


class StrictHostSyntaxMiddleware(BaseHTTPMiddleware):
    """Reject malformed Host values before framework URL reconstruction."""

    async def dispatch(self, request: Request, call_next):
        raw_host = request.headers.get("host", "")
        match = _HOST_HEADER_PATTERN.fullmatch(raw_host)
        if match is None:
            return PlainTextResponse("Invalid host header", status_code=400)
        raw_port = match.group(1)
        if raw_port is not None and int(raw_port) > 65535:
            return PlainTextResponse("Invalid host header", status_code=400)
        return await call_next(request)


def configure_cors(app: FastAPI, settings: Settings) -> None:
    allowed_headers = [
        "Accept",
        "Content-Type",
        settings.csrf_header_name,
        "X-Requested-With",
    ]
    if settings.auth_transport == "bearer_compat":
        allowed_headers.append("Authorization")
    if settings.environment != "production" and settings.auth_mode in {"stub", "demo"}:
        allowed_headers.extend(
            [
                "X-User-Role",
                "X-User-Id",
                "X-User-Programme",
                "X-User-Site",
                "X-User-MCR",
                "X-Admin-Level",
            ]
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=allowed_headers,
        expose_headers=["Retry-After", "X-Correlation-ID"],
        max_age=600,
    )


def configure_trusted_hosts(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(StrictHostSyntaxMiddleware)


def is_unsafe_method(method: str) -> bool:
    return method.upper() in {"POST", "PUT", "PATCH", "DELETE"}


def is_approved_origin(origin: str | None, settings: Settings) -> bool:
    if origin is None:
        return False
    candidate = origin.strip()
    return bool(candidate) and candidate in set(settings.cors_origins)


def merge_vary_header(existing: str | None, *values: str) -> str:
    seen: dict[str, str] = {}
    for item in (existing or "").split(","):
        cleaned = item.strip()
        if cleaned:
            seen[cleaned.lower()] = cleaned
    for value in values:
        cleaned = value.strip()
        if cleaned:
            seen.setdefault(cleaned.lower(), cleaned)
    return ", ".join(seen.values())


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, settings: Settings) -> None:  # type: ignore[override]
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
        except SQLAlchemyError as exc:
            response = safe_unexpected_error_response(
                request,
                exc,
                category="database",
            )
        except Exception as exc:
            response = safe_unexpected_error_response(
                request,
                exc,
                category="unhandled",
            )
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; object-src 'none'; "
            "base-uri 'none'; form-action 'none'"
        )
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        response.headers["Cache-Control"] = "no-store, private, max-age=0"
        response.headers["CDN-Cache-Control"] = "no-store"
        response.headers["Vercel-CDN-Cache-Control"] = "no-store"
        response.headers["Surrogate-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["Vary"] = merge_vary_header(
            response.headers.get("Vary"),
            "Origin",
            "Cookie",
        )
        correlation_id = getattr(request.state, "correlation_id", None)
        if isinstance(correlation_id, str) and correlation_id:
            response.headers["X-Correlation-ID"] = correlation_id
        return response
