from __future__ import annotations

import json
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import PurePath
from typing import Any, Awaitable, Callable, Iterable, Literal, Mapping, Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.workbook_security import (
    WORKBOOK_READ_ERROR,
    WorkbookSecurityLimits,
    preflight_xlsx_archive,
)


UploadType = Literal["rdb", "ttf", "form_f1", "public_holidays"]
UploadStatus = Literal["success", "partial", "failed"]
WarningItem = str | dict[str, Any]
ErrorItem = str | dict[str, Any]
WorkbookReadabilityHook = Callable[[bytes], None]


@dataclass(slots=True)
class ParserResult:
    upload_type: UploadType
    created_count: int = 0
    updated_count: int = 0
    warnings: list[WarningItem] = field(default_factory=list)
    errors: list[ErrorItem] = field(default_factory=list)
    metadata: dict[str, Any] | None = None

    def to_summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "upload_type": self.upload_type,
            "created_count": self.created_count,
            "updated_count": self.updated_count,
            "warnings": self.warnings,
            "errors": self.errors,
        }
        if self.metadata is not None:
            for key, value in self.metadata.items():
                summary.setdefault(key, value)
            summary["metadata"] = self.metadata
        return summary

    @property
    def status(self) -> UploadStatus:
        if self.errors and self.created_count == 0 and self.updated_count == 0:
            return "failed"
        if self.errors:
            return "partial"
        return "success"


@dataclass(slots=True)
class ValidatedUpload:
    upload_type: UploadType
    original_filename: str
    extension: str
    file_bytes: bytes


class UploadValidationError(ValueError):
    pass


class AsyncUploadReader(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


SLOT_EXTENSIONS: Mapping[UploadType, tuple[str, ...]] = {
    "rdb": (".xlsx",),
    "ttf": (".xlsx",),
    "form_f1": (".xlsx",),
    "public_holidays": (".xlsx", ".csv"),
}


def get_allowed_extensions(upload_type: UploadType) -> tuple[str, ...]:
    return SLOT_EXTENSIONS[upload_type]


def validate_allowed_extension(upload_type: UploadType, filename: str | None) -> str:
    safe_filename = (filename or "").strip()
    if not safe_filename:
        raise UploadValidationError("Uploaded file must include a filename.")

    extension = PurePath(safe_filename).suffix.lower()
    if extension not in get_allowed_extensions(upload_type):
        allowed = ", ".join(get_allowed_extensions(upload_type))
        raise UploadValidationError(
            f"Invalid file extension for {upload_type} upload. Allowed extensions: {allowed}."
        )
    return extension


def _upload_limit_label(max_size_bytes: int) -> str:
    max_size_mib = max_size_bytes / (1024 * 1024)
    return (
        f"{int(max_size_mib)} MiB"
        if max_size_mib.is_integer()
        else f"{max_size_mib:.1f} MiB"
    )


async def read_upload_bytes_limited(
    upload: AsyncUploadReader,
    *,
    max_size_bytes: int,
    chunk_size: int = 64 * 1024,
) -> bytes:
    """Read an upload without ever allocating an unbounded file-sized buffer."""

    if max_size_bytes <= 0 or chunk_size <= 0:
        raise ValueError("Upload read limits must be positive")

    payload = bytearray()
    while True:
        remaining_with_sentinel = max_size_bytes + 1 - len(payload)
        read_size = min(chunk_size, remaining_with_sentinel)
        chunk = await upload.read(read_size)
        if not isinstance(chunk, bytes):
            raise UploadValidationError("Uploaded file could not be read.")
        if not chunk:
            break
        payload.extend(chunk)
        if len(payload) > max_size_bytes:
            raise UploadValidationError(
                f"Uploaded file exceeds the {_upload_limit_label(max_size_bytes)} limit."
            )
    return bytes(payload)


def _openpyxl_readability_hook(file_bytes: bytes) -> None:
    from openpyxl import load_workbook

    workbook = load_workbook(
        filename=BytesIO(file_bytes), read_only=True, data_only=True
    )
    workbook.close()


def _validate_xlsx_workbook(
    file_bytes: bytes,
    *,
    readability_hook: WorkbookReadabilityHook,
) -> None:
    try:
        settings = get_settings()
        preflight_xlsx_archive(
            file_bytes,
            limits=WorkbookSecurityLimits.from_settings(settings),
        )
        readability_hook(file_bytes)
    except Exception as exc:
        raise UploadValidationError(WORKBOOK_READ_ERROR) from exc


def default_workbook_readability_hook(file_bytes: bytes) -> None:
    _validate_xlsx_workbook(
        file_bytes,
        readability_hook=_openpyxl_readability_hook,
    )


def validate_upload_payload(
    *,
    upload_type: UploadType,
    filename: str | None,
    file_bytes: bytes,
    max_size_bytes: int | None = None,
    workbook_hook: WorkbookReadabilityHook | None = None,
) -> ValidatedUpload:
    if max_size_bytes is not None and len(file_bytes) > max_size_bytes:
        raise UploadValidationError(
            f"Uploaded file exceeds the {_upload_limit_label(max_size_bytes)} limit."
        )

    extension = validate_allowed_extension(upload_type, filename)
    if extension == ".xlsx":
        if workbook_hook is None:
            default_workbook_readability_hook(file_bytes)
        else:
            _validate_xlsx_workbook(
                file_bytes,
                readability_hook=workbook_hook,
            )

    return ValidatedUpload(
        upload_type=upload_type,
        original_filename=(filename or "").strip(),
        extension=extension,
        file_bytes=file_bytes,
    )


ParserCallable = Callable[..., Awaitable[ParserResult]]


def get_parser_for_upload_type(upload_type: UploadType) -> ParserCallable:
    if upload_type == "rdb":
        from app.services.rdb_parser import parse_rdb_upload

        return parse_rdb_upload
    if upload_type == "ttf":
        from app.services.ttf_parser import parse_ttf_upload

        return parse_ttf_upload
    if upload_type == "form_f1":
        from app.services.formf1_parser import parse_formf1_upload

        return parse_formf1_upload
    from app.services.public_holiday_parser import parse_public_holiday_upload

    return parse_public_holiday_upload


async def dispatch_parser_by_upload_slot(
    *,
    upload_type: UploadType,
    file_bytes: bytes,
    original_filename: str,
    reporting_period_id: UUID | None = None,
    programme_code: str | None = None,
) -> ParserResult:
    parser = get_parser_for_upload_type(upload_type)
    return await parser(
        file_bytes=file_bytes,
        original_filename=original_filename,
        reporting_period_id=reporting_period_id,
        programme_code=programme_code,
    )


async def write_upload_log(
    session: AsyncSession,
    *,
    upload_type: UploadType,
    original_filename: str,
    status: UploadStatus,
    summary: Mapping[str, Any],
    uploaded_by: UUID | str | None = None,
    reporting_period_id: UUID | str | None = None,
    programme_code: str | None = None,
) -> dict[str, Any]:
    summary_payload = dict(summary)
    summary_payload["original_filename"] = original_filename
    upload_log_id = uuid4()

    params = {
        "id": str(upload_log_id),
        "upload_type": upload_type,
        "uploaded_by": str(uploaded_by) if uploaded_by else None,
        "reporting_period_id": (
            str(reporting_period_id) if reporting_period_id else None
        ),
        "programme_code": programme_code,
        "status": status,
        "summary": json.dumps(summary_payload, default=str),
    }

    await session.execute(
        text(
            """
            INSERT INTO upload_logs (
                id,
                upload_type,
                uploaded_by,
                reporting_period_id,
                programme_code,
                status,
                summary
            )
            VALUES (
                :id,
                :upload_type,
                :uploaded_by,
                :reporting_period_id,
                :programme_code,
                :status,
                :summary
            )
            """
        ),
        params,
    )
    await session.commit()
    return params


def normalise_scope_values(raw_scope: str | Iterable[str] | None) -> set[str]:
    if raw_scope is None:
        return set()
    if isinstance(raw_scope, str):
        parts = [segment.strip() for segment in raw_scope.split(",")]
        return {segment for segment in parts if segment}
    return {str(segment).strip() for segment in raw_scope if str(segment).strip()}
