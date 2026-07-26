from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.errors import (
    ApiError,
    ErrorCode,
    build_error_response,
    envelope_from_http_exception,
)
from app.security.redaction import redact_sensitive_data


logger = logging.getLogger(__name__)


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, object]]:
    # Pydantic includes the rejected `input` and arbitrary validator context in
    # exc.errors(). Neither belongs in an API error response.
    return [
        {
            "loc": [str(part) for part in item.get("loc", ())],
            "type": str(item.get("type") or "value_error"),
            "msg": "Invalid value",
        }
        for item in exc.errors()
    ]


def _correlation_id(request: Request) -> str:
    correlation_id = uuid4().hex
    request.state.correlation_id = correlation_id
    return correlation_id


def safe_unexpected_error_response(
    request: Request,
    exc: BaseException,
    *,
    category: str,
) -> JSONResponse:
    correlation_id = _correlation_id(request)
    logger.error(
        "request_failed correlation_id=%s category=%s exception_class=%s",
        correlation_id,
        category,
        exc.__class__.__name__,
    )
    return build_error_response(
        status_code=500,
        detail="Internal server error",
        error_code=ErrorCode.INTERNAL_ERROR.value,
        metadata={"correlation_id": correlation_id},
        headers={"X-Correlation-ID": correlation_id},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=redact_sensitive_data(exc.to_envelope()),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        validation_errors = _safe_validation_errors(exc)
        readable_errors: list[str] = []
        for item in validation_errors:
            location = ".".join(str(part) for part in item.get("loc", []))
            message = "Invalid value"
            readable_errors.append(f"{location}: {message}" if location else message)

        return build_error_response(
            status_code=422,
            detail="Validation failed",
            error_code=ErrorCode.VALIDATION_FAILED.value,
            errors=readable_errors,
            metadata={"validation_errors": validation_errors},
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        envelope = envelope_from_http_exception(
            status_code=exc.status_code,
            detail=exc.detail,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=redact_sensitive_data(envelope),
            headers=exc.headers,
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(
        request: Request,
        exc: SQLAlchemyError,
    ) -> JSONResponse:
        return safe_unexpected_error_response(
            request,
            exc,
            category="database",
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        return safe_unexpected_error_response(
            request,
            exc,
            category="unhandled",
        )
