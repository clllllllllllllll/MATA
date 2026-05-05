from __future__ import annotations

from fastapi import HTTPException, status


DEFAULT_ALLOWED_XLSX_EXTENSIONS = {".xlsx"}
DEFAULT_ALLOWED_PH_EXTENSIONS = {".xlsx", ".csv"}


def validate_upload_request(
    *,
    filename: str | None,
    content_type: str | None,
    content_length: int | None,
    max_size_bytes: int,
    allowed_extensions: set[str],
) -> None:
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Upload filename is required",
        )

    lower_name = filename.strip().lower()
    if not any(lower_name.endswith(ext) for ext in allowed_extensions):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file extension. Allowed: {', '.join(sorted(allowed_extensions))}",
        )

    if content_length is not None and content_length > max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Uploaded file exceeds maximum allowed size",
        )

    if content_type and "multipart/form-data" not in content_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid upload content type",
        )


def sanitize_spreadsheet_cell(value: str) -> str:
    """
    Prevent formula injection for exported text cells.
    """
    if value and value[0] in {"=", "+", "-", "@"}:
        return f"'{value}"
    return value
