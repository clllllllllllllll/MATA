from __future__ import annotations

from typing import Any
from uuid import UUID

from app.services.parser_common import ParserResult


async def parse_public_holiday_upload(
    *,
    file_bytes: bytes,
    original_filename: str,
    reporting_period_id: UUID | None = None,
    programme_code: str | None = None,
) -> ParserResult:
    metadata: dict[str, Any] = {
        "original_filename": original_filename,
        "byte_count": len(file_bytes),
        "phase": "skeleton",
    }
    if reporting_period_id:
        metadata["reporting_period_id"] = str(reporting_period_id)
    if programme_code:
        metadata["programme_code"] = programme_code

    return ParserResult(
        upload_type="public_holidays",
        created_count=0,
        updated_count=0,
        warnings=[
            "Public holiday parser skeleton in place. Full parsing logic is not implemented in this phase."
        ],
        errors=[],
        metadata=metadata,
    )
