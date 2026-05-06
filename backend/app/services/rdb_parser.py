from __future__ import annotations

from typing import Any
from uuid import UUID

from app.services.parser_common import ParserResult


async def parse_rdb_upload(
    *,
    file_bytes: bytes,
    original_filename: str,
    reporting_period_id: UUID | None,
    programme_code: str | None = None,
) -> ParserResult:
    metadata: dict[str, Any] = {
        "original_filename": original_filename,
        "reporting_period_id": str(reporting_period_id) if reporting_period_id else None,
        "byte_count": len(file_bytes),
        "phase": "skeleton",
    }
    if programme_code:
        metadata["programme_code"] = programme_code

    return ParserResult(
        upload_type="rdb",
        created_count=0,
        updated_count=0,
        warnings=["RDB parser skeleton in place. Full parsing logic is not implemented in this phase."],
        errors=[],
        metadata=metadata,
    )
