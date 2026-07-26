from __future__ import annotations

from fastapi import FastAPI

from app.config import get_settings
from app.middleware import (
    AuthStubMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    UploadGuardMiddleware,
    configure_cors,
    configure_trusted_hosts,
    install_error_handlers,
)
from app.routers import admin, auth, external_residents, resident, secretary
from app.schemas import HealthResponse


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.project_name,
        version="0.1.0",
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None if settings.environment == "production" else "/redoc",
        openapi_url=None if settings.environment == "production" else "/openapi.json",
    )

    install_error_handlers(app)
    # Starlette wraps middleware in reverse registration order. Register from
    # innermost to outermost so the effective perimeter is:
    # Security headers -> trusted host -> CORS -> auth -> upload -> rate limit.
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(UploadGuardMiddleware, settings=settings)
    app.add_middleware(AuthStubMiddleware, settings=settings)
    configure_cors(app, settings)
    configure_trusted_hosts(app, settings)
    # Added last so security/cache headers wrap middleware-generated auth and
    # perimeter failures, unexpected errors, and normal FastAPI responses.
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)

    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(external_residents.router, prefix=settings.api_prefix)
    app.include_router(admin.router, prefix=settings.api_prefix)
    app.include_router(secretary.router, prefix=settings.api_prefix)
    app.include_router(resident.router, prefix=settings.api_prefix)

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health_check() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()
