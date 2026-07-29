from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import attest_database_boundaries, dispose_database_engines
from app.errors import ErrorCode, build_error_response
from app.middleware import (
    AuthStubMiddleware,
    RateLimitMiddleware,
    RequestBodyLimitMiddleware,
    SecurityHeadersMiddleware,
    UploadGuardMiddleware,
    configure_cors,
    configure_trusted_hosts,
    install_error_handlers,
)
from app.routers import admin, auth, external_residents, resident, secretary
from app.schemas import HealthResponse
from app.services.database_context import RlsContextInvalidError


@asynccontextmanager
async def _database_lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        await attest_database_boundaries()
        yield
    finally:
        await dispose_database_engines()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.project_name,
        version="0.1.0",
        lifespan=_database_lifespan,
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None if settings.environment == "production" else "/redoc",
        openapi_url=None if settings.environment == "production" else "/openapi.json",
    )

    install_error_handlers(app)

    @app.exception_handler(RlsContextInvalidError)
    async def rls_context_invalid_handler(
        _: Request,
        __: RlsContextInvalidError,
    ) -> JSONResponse:
        return build_error_response(
            status_code=401,
            detail="Unauthorized",
            error_code=ErrorCode.UNAUTHORIZED.value,
        )

    # Starlette wraps middleware in reverse registration order. Register from
    # innermost to outermost so the effective perimeter is:
    # Security headers -> trusted host -> CORS -> body limit -> auth -> upload
    # content type -> rate limit.
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(UploadGuardMiddleware, settings=settings)
    app.add_middleware(AuthStubMiddleware, settings=settings)
    app.add_middleware(
        RequestBodyLimitMiddleware,
        global_limit_bytes=settings.max_request_body_size_bytes,
        upload_limit_bytes=settings.max_upload_request_size_bytes,
        api_prefix=settings.api_prefix,
    )
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
