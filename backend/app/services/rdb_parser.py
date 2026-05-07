from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.services.parser_common import ParserResult


class RDBParserError(ValueError):
    """Controlled parser error for RDB parsing failures."""


@dataclass(slots=True, frozen=True)
class PostingColumnHeader:
    column_index: int
    month_label: str
    start_date: date
    end_date: date


@dataclass(slots=True, frozen=True)
class NormalizedRDBCell:
    raw_value: Any
    normalized_value: str
    normalized_lines: list[str]


_MCR_LIKE_PATTERN = re.compile(r"^[A-Za-z]\d+[A-Za-z]$")
_DATE_RANGE_PATTERN = re.compile(
    r"^\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})\s*-\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})\s*$"
)
_DATE_TOKEN_HYPHEN_PATTERN = re.compile(
    r"\b(\d{1,2})\s*-\s*([A-Za-z]{3})\s*-\s*(\d{2,4})\b"
)
_PURE_LOA_LINE_PATTERN = re.compile(
    r"^LOA\s*\(\s*(?P<loa_type>.+?)\s+from\s+(?P<start>\d{1,2}\s*-\s*[A-Za-z]{3}\s*-\s*\d{2,4})\s+to\s+(?P<end>\d{1,2}\s*-\s*[A-Za-z]{3}\s*-\s*\d{2,4})\s*\)\s*$",
    re.IGNORECASE,
)
_CONTINUE_WORKING_LOA_PATTERN = re.compile(
    r"Continue\s+working\s+during\s+LOA\s+from\s+(?P<start>\d{1,2}\s*-\s*[A-Za-z]{3}\s*-\s*\d{2,4})\s+to\s+(?P<end>\d{1,2}\s*-\s*[A-Za-z]{3}\s*-\s*\d{2,4})\s*\)?",
    re.IGNORECASE,
)


def _to_cell_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _normalize_hyphens_in_date_tokens(value: str) -> str:
    return _DATE_TOKEN_HYPHEN_PATTERN.sub(
        lambda match: f"{match.group(1)}-{match.group(2)}-{match.group(3)}",
        value,
    )


def _parse_date_token(token: str) -> date:
    normalized = _normalize_hyphens_in_date_tokens(token.strip())
    for fmt in ("%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    raise RDBParserError(f"Cannot parse LOA date token: {token}")


def parse_date_range(header: str) -> tuple[date, date]:
    match = _DATE_RANGE_PATTERN.match((header or "").strip())
    if match is None:
        raise RDBParserError(f"Cannot parse date range: {header}")

    left = match.group(1).strip()
    right = match.group(2).strip()
    formats = ("%d %b %y", "%d %b %Y", "%d %B %y", "%d %B %Y")

    left_date: date | None = None
    right_date: date | None = None
    for fmt in formats:
        if left_date is None:
            try:
                left_date = datetime.strptime(left, fmt).date()
            except ValueError:
                pass
        if right_date is None:
            try:
                right_date = datetime.strptime(right, fmt).date()
            except ValueError:
                pass
        if left_date is not None and right_date is not None:
            return left_date, right_date

    raise RDBParserError(f"Cannot parse date range with known formats: {header}")


def detect_posting_columns(sheet: Any) -> list[PostingColumnHeader]:
    detected: list[PostingColumnHeader] = []
    for column_index in range(1, sheet.max_column + 1):
        header = _to_cell_text(sheet.cell(row=2, column=column_index).value).strip()
        if not header:
            continue

        try:
            start_date, end_date = parse_date_range(header)
        except ValueError:
            continue

        month_label = _to_cell_text(sheet.cell(row=1, column=column_index).value).strip()
        detected.append(
            PostingColumnHeader(
                column_index=column_index,
                month_label=month_label,
                start_date=start_date,
                end_date=end_date,
            )
        )
    return detected


def detect_rdb_sheets(workbook: Any) -> dict[str, str]:
    detected: dict[str, str] = {}
    for sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
        has_date_ranges = bool(detect_posting_columns(sheet))
        has_mcr_like = any(
            _MCR_LIKE_PATTERN.fullmatch(
                _to_cell_text(sheet.cell(row=row_index, column=3).value).strip()
            )
            is not None
            for row_index in range(3, sheet.max_row + 1)
        )

        if has_date_ranges and has_mcr_like:
            detected[sheet_name] = "standard"
            continue

        if not has_date_ranges:
            sheet_name_upper = sheet_name.upper()
            row_text = " ".join(
                _to_cell_text(sheet.cell(row=row_index, column=column_index).value).upper()
                for row_index in (1, 2)
                for column_index in range(1, sheet.max_column + 1)
            )
            has_ssr_marker = (
                "SSR" in sheet_name_upper
                or "SSR" in row_text
                or "SUB-SPECIALTY" in row_text
                or "SUB SPECIALTY" in row_text
            )
            if has_ssr_marker:
                detected[sheet_name] = "ssr"
                continue

        detected[sheet_name] = "skip"

    return detected


def normalize_rdb_cell(raw_value: Any) -> NormalizedRDBCell:
    text = _to_cell_text(raw_value)
    text = text.replace("\u00A0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    normalized_lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        normalized_lines.append(_normalize_hyphens_in_date_tokens(stripped))

    return NormalizedRDBCell(
        raw_value=raw_value,
        normalized_value="\n".join(normalized_lines),
        normalized_lines=normalized_lines,
    )


def parse_loa_annotation(cell_value: Any) -> dict[str, Any]:
    normalized_cell = normalize_rdb_cell(cell_value)
    normalized_value = normalized_cell.normalized_value
    normalized_lines = normalized_cell.normalized_lines

    result: dict[str, Any] = {
        "status": "active",
        "loa_type": None,
        "loa_start": None,
        "loa_end": None,
        "annotations": [],
    }
    if not normalized_value:
        return result

    pure_annotations: list[dict[str, Any]] = []
    continue_annotations: list[dict[str, Any]] = []

    for line in normalized_lines:
        pure_match = _PURE_LOA_LINE_PATTERN.match(line)
        if pure_match is not None:
            pure_annotations.append(
                {
                    "kind": "pure_loa",
                    "loa_type": pure_match.group("loa_type").strip(),
                    "start": _parse_date_token(pure_match.group("start")),
                    "end": _parse_date_token(pure_match.group("end")),
                    "raw_line": line,
                }
            )
            continue

        continue_match = _CONTINUE_WORKING_LOA_PATTERN.search(line)
        if continue_match is not None:
            continue_annotations.append(
                {
                    "kind": "continue_working_during_loa",
                    "loa_type": None,
                    "start": _parse_date_token(continue_match.group("start")),
                    "end": _parse_date_token(continue_match.group("end")),
                    "raw_line": line,
                }
            )

    if pure_annotations:
        result["annotations"] = [*continue_annotations, *pure_annotations]
        first_pure = pure_annotations[0]
        result["loa_type"] = first_pure["loa_type"]
        result["loa_start"] = first_pure["start"]
        result["loa_end"] = first_pure["end"]
        has_non_loa_lines = any(
            _PURE_LOA_LINE_PATTERN.match(line) is None for line in normalized_lines
        )
        result["status"] = "loa_working" if has_non_loa_lines else "loa"
        return result

    if continue_annotations:
        result["annotations"] = continue_annotations
        first_continue = continue_annotations[0]
        result["status"] = "loa_working"
        result["loa_start"] = first_continue["start"]
        result["loa_end"] = first_continue["end"]
    return result


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
