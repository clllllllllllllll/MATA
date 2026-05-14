from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from fastapi.responses import JSONResponse


class ErrorCode(str, Enum):
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UPLOAD_VALIDATION_FAILED = "UPLOAD_VALIDATION_FAILED"
    FILE_VALIDATION_FAILED = "FILE_VALIDATION_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


_DEFAULT_ERROR_CODE_BY_STATUS: dict[int, ErrorCode] = {
    400: ErrorCode.VALIDATION_FAILED,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_FAILED,
    429: ErrorCode.RATE_LIMITED,
    500: ErrorCode.INTERNAL_ERROR,
}

_DEFAULT_DETAIL_BY_STATUS: dict[int, str] = {
    400: "Bad request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not found",
    409: "Conflict",
    422: "Validation failed",
    429: "Too many requests",
    500: "Internal server error",
}


def default_error_code_for_status(status_code: int) -> str:
    return _DEFAULT_ERROR_CODE_BY_STATUS.get(
        status_code,
        ErrorCode.INTERNAL_ERROR,
    ).value


def default_detail_for_status(status_code: int) -> str:
    return _DEFAULT_DETAIL_BY_STATUS.get(status_code, "Request failed")


def _coerce_list(value: Sequence[Any] | None) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, bytearray)):
        return [value]
    return list(value)


def _coerce_dict(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value) if value is not None else {}


def build_error_envelope(
    *,
    detail: str,
    error_code: str,
    errors: Sequence[Any] | None = None,
    warnings: Sequence[Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "detail": detail,
        "error_code": error_code,
        "errors": _coerce_list(errors),
        "warnings": _coerce_list(warnings),
        "metadata": _coerce_dict(metadata),
    }


def build_error_response(
    *,
    status_code: int,
    detail: str,
    error_code: str | None = None,
    errors: Sequence[Any] | None = None,
    warnings: Sequence[Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    envelope = build_error_envelope(
        detail=detail,
        error_code=error_code or default_error_code_for_status(status_code),
        errors=errors,
        warnings=warnings,
        metadata=metadata,
    )
    return JSONResponse(status_code=status_code, content=envelope, headers=headers)


class ApiError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        detail: str,
        error_code: str | None = None,
        errors: Sequence[Any] | None = None,
        warnings: Sequence[Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code or default_error_code_for_status(status_code)
        self.errors = _coerce_list(errors)
        self.warnings = _coerce_list(warnings)
        self.metadata = _coerce_dict(metadata)

    def to_envelope(self) -> dict[str, Any]:
        return build_error_envelope(
            detail=self.detail,
            error_code=self.error_code,
            errors=self.errors,
            warnings=self.warnings,
            metadata=self.metadata,
        )


class UploadValidationApiError(ApiError):
    def __init__(
        self,
        *,
        detail: str,
        errors: Sequence[Any] | None = None,
        warnings: Sequence[Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=422,
            detail=detail,
            error_code=ErrorCode.UPLOAD_VALIDATION_FAILED.value,
            errors=errors,
            warnings=warnings,
            metadata=metadata,
        )


def envelope_from_http_exception(
    *,
    status_code: int,
    detail: Any,
) -> dict[str, Any]:
    if isinstance(detail, Mapping):
        detail_text = str(detail.get("detail") or default_detail_for_status(status_code))
        error_code = str(
            detail.get("error_code") or default_error_code_for_status(status_code)
        )
        errors = detail.get("errors")
        warnings = detail.get("warnings")
        metadata_value = detail.get("metadata")
        metadata: dict[str, Any]
        if isinstance(metadata_value, Mapping):
            metadata = dict(metadata_value)
        else:
            metadata = {}

        extra_metadata = {
            key: value
            for key, value in detail.items()
            if key not in {"detail", "error_code", "errors", "warnings", "metadata"}
        }
        metadata.update(extra_metadata)

        normalised_errors: list[Any] | None = None
        if isinstance(errors, Sequence) and not isinstance(errors, (str, bytes, bytearray)):
            normalised_errors = list(errors)
        elif errors is not None:
            normalised_errors = [errors]

        normalised_warnings: list[Any] | None = None
        if isinstance(warnings, Sequence) and not isinstance(
            warnings, (str, bytes, bytearray)
        ):
            normalised_warnings = list(warnings)
        elif warnings is not None:
            normalised_warnings = [warnings]

        return build_error_envelope(
            detail=detail_text,
            error_code=error_code,
            errors=normalised_errors,
            warnings=normalised_warnings,
            metadata=metadata,
        )

    if isinstance(detail, str):
        return build_error_envelope(
            detail=detail,
            error_code=default_error_code_for_status(status_code),
        )

    return build_error_envelope(
        detail=default_detail_for_status(status_code),
        error_code=default_error_code_for_status(status_code),
    )
