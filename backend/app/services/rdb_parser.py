from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping
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


@dataclass(slots=True, frozen=True)
class ParsedMultiPostingFragment:
    posting_code: str
    start_date: date
    end_date: date
    day_part: str | None
    raw_line: str


@dataclass(slots=True, frozen=True)
class ParsedPostingCell:
    posting_code: str | None
    status: str
    loa_type: str | None
    loa_start: date | None
    loa_end: date | None
    employer_tag: str | None
    refresher_training_type: str | None
    refresher_training_start: date | None
    refresher_training_end: date | None
    pending_sr_promotion_start: date | None
    pending_sr_promotion_end: date | None
    multi_posting_fragments: list[ParsedMultiPostingFragment]
    working_days: int | None
    warnings: list[str]
    annotations: list[dict[str, Any]]
    raw_cell: Any
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
_EMPLOYED_PATTERN = re.compile(r"^(?P<tag>[\w]+)-[Ee]mployed$")
_REFRESHER_PATTERN = re.compile(
    r"^(?P<posting>.+?)\s*\(\s*Refresher\s+Training\s+\((?P<kind>add\s+to\s+Max\s+Cand|don't\s+add\s+to\s+Max\s+Cand)\)\s+from\s+(?P<start>\d{1,2}\s*-\s*[A-Za-z]{3}\s*-\s*\d{2,4})\s+to\s+(?P<end>\d{1,2}\s*-\s*[A-Za-z]{3}\s*-\s*\d{2,4})\s*\)\s*$",
    re.IGNORECASE,
)
_PENDING_SR_PROMOTION_PATTERN = re.compile(
    r"^(?P<posting>.+?)\s*\(\s*Pending\s+for\s+SR\s+Promotion\s+from\s+(?P<start>\d{1,2}\s*-\s*[A-Za-z]{3}\s*-\s*\d{2,4})\s+to\s+(?P<end>\d{1,2}\s*-\s*[A-Za-z]{3}\s*-\s*\d{2,4})\s*\)\s*$",
    re.IGNORECASE,
)
_MULTI_POSTING_DATE_RANGE_PATTERN = re.compile(
    r"^\(\s*from\s+(?P<start>\d{1,2}\s*-\s*[A-Za-z]{3}\s*-\s*\d{2,4})\s+to\s+(?P<end>\d{1,2}\s*-\s*[A-Za-z]{3}\s*-\s*\d{2,4})(?:\s+(?P<day_part>AM|PM))?\s*\)\s*$",
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


def validate_loa_type(
    loa_type: str | None, context: Mapping[str, Any] | None = None
) -> tuple[str | None, list[str]]:
    if loa_type is None:
        return None, []

    if context is None:
        return loa_type, []

    known_loa_types = context.get("known_loa_types")
    if known_loa_types is None:
        return loa_type, []

    normalized_known = {str(item).strip() for item in known_loa_types}
    if loa_type in normalized_known:
        return loa_type, []

    return loa_type, [f"Unknown LOA type: {loa_type}"]


def parse_refresher_training_annotation(cell_line: str) -> dict[str, Any] | None:
    match = _REFRESHER_PATTERN.match(cell_line.strip())
    if match is None:
        return None

    kind_raw = re.sub(r"\s+", " ", match.group("kind").strip()).lower()
    if kind_raw.startswith("add"):
        refresher_type = "add to Max Cand"
    else:
        refresher_type = "don't add to Max Cand"

    return {
        "kind": "refresher_training",
        "posting_code": match.group("posting").strip(),
        "refresher_training_type": refresher_type,
        "refresher_training_start": _parse_date_token(match.group("start")),
        "refresher_training_end": _parse_date_token(match.group("end")),
        "raw_line": cell_line.strip(),
    }


def parse_pending_sr_promotion_annotation(cell_line: str) -> dict[str, Any] | None:
    match = _PENDING_SR_PROMOTION_PATTERN.match(cell_line.strip())
    if match is None:
        return None

    return {
        "kind": "pending_sr_promotion",
        "posting_code": match.group("posting").strip(),
        "pending_sr_promotion_start": _parse_date_token(match.group("start")),
        "pending_sr_promotion_end": _parse_date_token(match.group("end")),
        "raw_line": cell_line.strip(),
    }


def compute_working_days(
    *,
    phase_start: date,
    phase_end: date,
    loa_start: date | None,
    loa_end: date | None,
) -> int:
    total_days = (phase_end - phase_start).days + 1
    if loa_start is not None and loa_end is not None:
        overlap_start = max(phase_start, loa_start)
        overlap_end = min(phase_end, loa_end)
        if overlap_start <= overlap_end:
            total_days -= (overlap_end - overlap_start).days + 1
    return max(0, total_days)


def _resolve_normalized_cell(normalized_cell: Any) -> NormalizedRDBCell:
    if isinstance(normalized_cell, NormalizedRDBCell):
        return normalized_cell
    return normalize_rdb_cell(normalized_cell)


def _extract_posting_code_from_continue_line(line: str) -> str | None:
    match = _CONTINUE_WORKING_LOA_PATTERN.search(line)
    if match is None:
        return None
    prefix = line[: match.start()].rstrip()
    if prefix.endswith("("):
        prefix = prefix[:-1].rstrip()
    return prefix or None


def _extract_posting_code_for_loa_working(lines: list[str]) -> str | None:
    for line in lines:
        if _PURE_LOA_LINE_PATTERN.match(line):
            continue

        continue_line_posting = _extract_posting_code_from_continue_line(line)
        if continue_line_posting:
            return continue_line_posting

        return line.strip() or None

    return None


def _parse_multi_posting_fragments(
    normalized_lines: list[str],
) -> tuple[list[ParsedMultiPostingFragment], list[str]]:
    warnings: list[str] = []
    fragments: list[ParsedMultiPostingFragment] = []
    current_posting_code: str | None = None
    saw_date_range = False

    for line in normalized_lines:
        match = _MULTI_POSTING_DATE_RANGE_PATTERN.match(line)
        if match is not None:
            saw_date_range = True
            if current_posting_code is None:
                warnings.append(
                    f"Unattached multi-posting date fragment ignored: {line}"
                )
                continue

            day_part_raw = match.group("day_part")
            day_part = day_part_raw.upper() if day_part_raw else None
            fragments.append(
                ParsedMultiPostingFragment(
                    posting_code=current_posting_code,
                    start_date=_parse_date_token(match.group("start")),
                    end_date=_parse_date_token(match.group("end")),
                    day_part=day_part,
                    raw_line=line,
                )
            )
            continue

        current_posting_code = line.strip() or None

    if not saw_date_range:
        return [], []
    return fragments, warnings


def _compute_working_days_from_context(
    context: Mapping[str, Any],
    loa_start: date | None,
    loa_end: date | None,
) -> int | None:
    phase_start = context.get("phase_start")
    phase_end = context.get("phase_end")
    if not isinstance(phase_start, date) or not isinstance(phase_end, date):
        return None
    return compute_working_days(
        phase_start=phase_start,
        phase_end=phase_end,
        loa_start=loa_start,
        loa_end=loa_end,
    )


def classify_posting_cell(
    normalized_cell: NormalizedRDBCell | Any, context: Mapping[str, Any]
) -> ParsedPostingCell | None:
    normalized = _resolve_normalized_cell(normalized_cell)
    if not normalized.normalized_value:
        return None

    warnings: list[str] = []

    if len(normalized.normalized_lines) == 1:
        employed_match = _EMPLOYED_PATTERN.match(normalized.normalized_lines[0])
        if employed_match is not None:
            return ParsedPostingCell(
                posting_code=None,
                status="employed",
                loa_type=None,
                loa_start=None,
                loa_end=None,
                employer_tag=employed_match.group("tag"),
                refresher_training_type=None,
                refresher_training_start=None,
                refresher_training_end=None,
                pending_sr_promotion_start=None,
                pending_sr_promotion_end=None,
                multi_posting_fragments=[],
                working_days=None,
                warnings=[],
                annotations=[
                    {
                        "kind": "employed",
                        "employer_tag": employed_match.group("tag"),
                        "raw_line": normalized.normalized_lines[0],
                    }
                ],
                raw_cell=normalized.raw_value,
                normalized_lines=normalized.normalized_lines,
            )

    multi_posting_fragments, multi_warnings = _parse_multi_posting_fragments(
        normalized.normalized_lines
    )
    if multi_posting_fragments:
        warnings.extend(multi_warnings)
        return ParsedPostingCell(
            posting_code=None,
            status="active",
            loa_type=None,
            loa_start=None,
            loa_end=None,
            employer_tag=None,
            refresher_training_type=None,
            refresher_training_start=None,
            refresher_training_end=None,
            pending_sr_promotion_start=None,
            pending_sr_promotion_end=None,
            multi_posting_fragments=multi_posting_fragments,
            working_days=_compute_working_days_from_context(context, None, None),
            warnings=warnings,
            annotations=[],
            raw_cell=normalized.raw_value,
            normalized_lines=normalized.normalized_lines,
        )

    if len(normalized.normalized_lines) == 1:
        pending = parse_pending_sr_promotion_annotation(normalized.normalized_lines[0])
        if pending is not None:
            return ParsedPostingCell(
                posting_code=pending["posting_code"],
                status="active",
                loa_type=None,
                loa_start=None,
                loa_end=None,
                employer_tag=None,
                refresher_training_type=None,
                refresher_training_start=None,
                refresher_training_end=None,
                pending_sr_promotion_start=pending["pending_sr_promotion_start"],
                pending_sr_promotion_end=pending["pending_sr_promotion_end"],
                multi_posting_fragments=[],
                working_days=_compute_working_days_from_context(context, None, None),
                warnings=[],
                annotations=[pending],
                raw_cell=normalized.raw_value,
                normalized_lines=normalized.normalized_lines,
            )

        refresher = parse_refresher_training_annotation(normalized.normalized_lines[0])
        if refresher is not None:
            return ParsedPostingCell(
                posting_code=refresher["posting_code"],
                status="active",
                loa_type=None,
                loa_start=None,
                loa_end=None,
                employer_tag=None,
                refresher_training_type=refresher["refresher_training_type"],
                refresher_training_start=refresher["refresher_training_start"],
                refresher_training_end=refresher["refresher_training_end"],
                pending_sr_promotion_start=None,
                pending_sr_promotion_end=None,
                multi_posting_fragments=[],
                working_days=_compute_working_days_from_context(context, None, None),
                warnings=[],
                annotations=[refresher],
                raw_cell=normalized.raw_value,
                normalized_lines=normalized.normalized_lines,
            )

    loa = parse_loa_annotation(normalized.normalized_value)
    loa_type, loa_warnings = validate_loa_type(loa["loa_type"], context)
    warnings.extend(loa_warnings)

    if loa["status"] == "loa":
        return ParsedPostingCell(
            posting_code=None,
            status="loa",
            loa_type=loa_type,
            loa_start=loa["loa_start"],
            loa_end=loa["loa_end"],
            employer_tag=None,
            refresher_training_type=None,
            refresher_training_start=None,
            refresher_training_end=None,
            pending_sr_promotion_start=None,
            pending_sr_promotion_end=None,
            multi_posting_fragments=[],
            working_days=_compute_working_days_from_context(
                context, loa["loa_start"], loa["loa_end"]
            ),
            warnings=warnings,
            annotations=loa["annotations"],
            raw_cell=normalized.raw_value,
            normalized_lines=normalized.normalized_lines,
        )

    if loa["status"] == "loa_working":
        return ParsedPostingCell(
            posting_code=_extract_posting_code_for_loa_working(normalized.normalized_lines),
            status="loa_working",
            loa_type=loa_type,
            loa_start=loa["loa_start"],
            loa_end=loa["loa_end"],
            employer_tag=None,
            refresher_training_type=None,
            refresher_training_start=None,
            refresher_training_end=None,
            pending_sr_promotion_start=None,
            pending_sr_promotion_end=None,
            multi_posting_fragments=[],
            working_days=_compute_working_days_from_context(
                context, loa["loa_start"], loa["loa_end"]
            ),
            warnings=warnings,
            annotations=loa["annotations"],
            raw_cell=normalized.raw_value,
            normalized_lines=normalized.normalized_lines,
        )

    return ParsedPostingCell(
        posting_code=normalized.normalized_lines[0],
        status="active",
        loa_type=None,
        loa_start=None,
        loa_end=None,
        employer_tag=None,
        refresher_training_type=None,
        refresher_training_start=None,
        refresher_training_end=None,
        pending_sr_promotion_start=None,
        pending_sr_promotion_end=None,
        multi_posting_fragments=[],
        working_days=_compute_working_days_from_context(context, None, None),
        warnings=[],
        annotations=[],
        raw_cell=normalized.raw_value,
        normalized_lines=normalized.normalized_lines,
    )


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
