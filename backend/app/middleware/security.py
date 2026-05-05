from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings


def configure_cors(app: FastAPI, settings: Settings) -> None:
    if settings.environment == "production" and "*" in settings.cors_origins:
        raise ValueError("Wildcard CORS origin is not allowed in production")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, settings: Settings) -> None:  # type: ignore[override]
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = self._settings.referrer_policy
        response.headers["Content-Security-Policy"] = self._settings.csp_default_src
        return response
