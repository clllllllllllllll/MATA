from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.errors import (
    ApiError,
    ErrorCode,
    build_error_response,
    envelope_from_http_exception,
)


logger = logging.getLogger(__name__)


def _to_json_safe_validation_error(value: Any) -> Any:
    if isinstance(value, BaseException):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): _to_json_safe_validation_error(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_to_json_safe_validation_error(item) for item in value]
    return jsonable_encoder(value)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_envelope())

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        validation_errors = [
            _to_json_safe_validation_error(item) for item in exc.errors()
        ]
        readable_errors: list[str] = []
        for item in validation_errors:
            location = ".".join(str(part) for part in item.get("loc", []))
            message = str(item.get("msg", "Invalid value"))
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
            content=envelope,
            headers=exc.headers,
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("Database error: %s", exc.__class__.__name__)
        return build_error_response(
            status_code=500,
            detail="Internal server error",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server error: %s", exc.__class__.__name__)
        return build_error_response(
            status_code=500,
            detail="Internal server error",
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
