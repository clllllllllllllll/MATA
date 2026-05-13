from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Any
from uuid import UUID

from app.services.parser_common import ParserResult

_DEFAULT_PROGRAMMES = {
    "AIM",
    "ANAES",
    "CARDIO",
    "DERM",
    "DR",
    "EM",
    "ENDO",
    "ENT",
    "EYE",
    "FM",
    "GASTRO",
    "GERI",
    "GS",
    "ID",
    "IM",
    "MEDONCO",
    "ORTHO",
    "PATH",
    "PSY",
    "REHAB",
    "RENAL",
    "RESPI",
    "RHEUM",
    "SPORTSMED",
    "SIG",
    "URO",
    "MICROB",
    "PALLMED",
}
_R_YEAR_NOT_REQUIRED = {
    "AIM",
    "CARDIO",
    "EM",
    "ENDO",
    "ENT",
    "EYE",
    "GASTRO",
    "GERI",
    "GS",
    "ID",
    "IM",
    "MEDONCO",
    "ORTHO",
    "PATH",
    "REHAB",
    "RENAL",
    "RHEUM",
    "SPORTSMED",
    "SIG",
    "URO",
    "MICROB",
    "PALLMED",
}
_SUBSPECIALTY_R_YEAR_MAP = {"R4": "SS1", "R5": "SS2", "R6": "SS3"}
_TTF_HEADERS = {
    1: "reporting_period",
    2: "programme_code",
    3: "r_year",
    4: "posting_code",
    5: "dashboard_posting",
    6: "session_type",
    7: "monthly_target",
    8: "is_tracked",
    9: "is_reallocatable",
    10: "tag",
    11: "details_of_training",
}
_DURATION_PATTERN = re.compile(r"\[(\d+(?:\.\d+)?)h\]")
_POSTING_BRACKET_PATTERN = re.compile(r"\[([^\]]+)\]\s*$")
_TAG_FAMILY_PATTERN = re.compile(r"^(?P<prefix>[A-Za-z]+)(?P<suffix>\d+)$")
_HEADER_WORD_RE = re.compile(r"[a-z0-9]+")

_HEADER_ALIASES: dict[int, tuple[tuple[str, ...], ...]] = {
    1: (("reporting", "period"),),
    2: (("programme",), ("program",)),
    3: (("year", "residency"), ("residency", "year"), ("r", "year")),
    4: (("current", "posting"), ("posting",)),
    5: (("dashboard",), ("for", "dashboard")),
    6: (("session", "type"),),
    7: (("frequency", "target"), ("monthly", "target"), ("target",)),
    8: (("tracked",),),
    9: (("reallocated",), ("reallocatable",), ("can", "session", "reallocated")),
    10: (("tag",),),
    11: (("details", "training"), ("detail", "training")),
}


@dataclass(slots=True, frozen=True)
class ParsedTeachingTargetRow:
    source_row: int
    reporting_period: str
    reporting_period_id: str
    programme_code: str
    r_year: str
    posting_code: str
    dashboard_posting: str | None
    session_type: str
    duration_hours: float
    monthly_target: float
    is_tracked: bool
    is_reallocatable: bool
    tag: str | None
    details_of_training: str
    keywords: list[str]


@dataclass(slots=True, frozen=True)
class ParsedCatalogueRow:
    source_row: int
    keyword: str
    session_type: str
    posting_code: str
    programme_code: str
    r_year: str
    reporting_period_id: str
    duration_hours: float
    is_tracked: bool


@dataclass(slots=True, frozen=True)
class ParsedPostingGroupRow:
    source_row: int
    group_code: str
    posting_code: str
    programme_code: str


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalise_header_text(value: Any) -> str:
    text = _cell_text(value).casefold()
    return " ".join(_HEADER_WORD_RE.findall(text))


def _header_cell_matches(column_index: int, value: Any) -> bool:
    normalised = _normalise_header_text(value)
    if not normalised:
        return False
    for alias_words in _HEADER_ALIASES[column_index]:
        if all(word in normalised for word in alias_words):
            return True
    return False


def _row_looks_like_ttf_header(ws: Any, row_idx: int) -> bool:
    matched_columns = [
        col_idx
        for col_idx in range(1, 12)
        if _header_cell_matches(col_idx, ws.cell(row=row_idx, column=col_idx).value)
    ]
    if len(matched_columns) < 9:
        return False
    # Anchor columns reduce false positives on unrelated sheets.
    for required_col in (2, 4, 6, 11):
        if required_col not in matched_columns:
            return False
    return True


def _has_ttf_like_data_row(ws: Any, header_row: int) -> bool:
    max_scan_row = min(ws.max_row, header_row + 30)
    for row_idx in range(header_row + 1, max_scan_row + 1):
        programme = _cell_text(ws.cell(row=row_idx, column=2).value).upper()
        posting = _cell_text(ws.cell(row=row_idx, column=4).value)
        session_type = _cell_text(ws.cell(row=row_idx, column=6).value)
        if (
            re.fullmatch(r"[A-Z][A-Z0-9]{1,19}", programme)
            and posting
            and session_type
        ):
            return True
    return False


def detect_ttf_sheet_layout(workbook: Any) -> tuple[str, int] | None:
    for name in workbook.sheetnames:
        ws = workbook[name]
        max_header_scan = min(ws.max_row, 20)
        for row_idx in range(1, max_header_scan + 1):
            if not _row_looks_like_ttf_header(ws, row_idx):
                continue
            if _has_ttf_like_data_row(ws, row_idx):
                return name, row_idx
    return None


def detect_ttf_sheet(workbook: Any) -> str | None:
    layout = detect_ttf_sheet_layout(workbook)
    if layout is None:
        return None
    return layout[0]


def parse_posting_code(raw: str) -> str:
    text = raw.strip()
    bracket_match = _POSTING_BRACKET_PATTERN.search(text)
    if bracket_match is not None:
        return bracket_match.group(1).strip()
    return text


def parse_session_type_duration(session_type: str) -> float:
    match = _DURATION_PATTERN.search(session_type)
    if match is None:
        raise ValueError("Session type must include a valid [Xh] duration bracket.")
    return float(match.group(1))


def parse_bool_cell(value: str, *, true_values: set[str]) -> bool:
    return value.strip().casefold() in {entry.casefold() for entry in true_values}


def explode_r_years(raw_r_year: str, programme_code: str) -> list[str]:
    if programme_code in _R_YEAR_NOT_REQUIRED:
        return ["ALL"]
    tokens = [token.strip() for token in raw_r_year.split(",") if token.strip()]
    if not tokens:
        return []
    if programme_code in {"SPORTSMED", "PALLMED"}:
        return [_SUBSPECIALTY_R_YEAR_MAP.get(token, token) for token in tokens]
    return tokens


def split_keywords(raw: str) -> list[str]:
    return [keyword.strip() for keyword in raw.split(",") if keyword.strip()]


def extract_tag_family(tag: str) -> str:
    cleaned = tag.strip()
    if not cleaned:
        return cleaned
    match = _TAG_FAMILY_PATTERN.match(cleaned)
    if match is not None:
        return match.group("prefix")
    # Keep flexible support for non A1/A2 style tags by falling back to the full tag string.
    return cleaned


async def parse_ttf_upload(
    *,
    file_bytes: bytes,
    original_filename: str,
    reporting_period_id: UUID | None,
    programme_code: str | None = None,
    known_programmes: set[str] | None = None,
) -> ParserResult:
    metadata: dict[str, Any] = {
        "original_filename": original_filename,
        "reporting_period_id": str(reporting_period_id) if reporting_period_id else None,
        "programme_code": programme_code,
        "byte_count": len(file_bytes),
    }
    if reporting_period_id is None:
        return ParserResult(
            upload_type="ttf",
            errors=["reporting_period_id is required for TTF parsing."],
            metadata=metadata,
        )

    try:
        from openpyxl import load_workbook

        workbook = load_workbook(filename=BytesIO(file_bytes), data_only=True)
    except Exception as exc:
        return ParserResult(
            upload_type="ttf",
            errors=[
                "Workbook could not be read. Please upload a valid, non-password-protected Excel file."
            ],
            metadata={**metadata, "exception": str(exc)},
        )

    known = known_programmes or _DEFAULT_PROGRAMMES
    warnings: list[Any] = []
    errors: list[Any] = []
    teaching_targets: list[ParsedTeachingTargetRow] = []
    catalogue_rows: list[ParsedCatalogueRow] = []
    posting_group_rows: list[ParsedPostingGroupRow] = []
    detected_layout = detect_ttf_sheet_layout(workbook)
    if detected_layout is None:
        workbook.close()
        return ParserResult(
            upload_type="ttf",
            errors=["Unable to detect a valid TTF worksheet with expected headers."],
            metadata=metadata,
        )
    sheet_name, header_row = detected_layout
    ws = workbook[sheet_name]
    period_id_str = str(reporting_period_id)
    for row_idx in range(header_row + 1, ws.max_row + 1):
        period_label = _cell_text(ws.cell(row=row_idx, column=1).value)
        row_programme = _cell_text(ws.cell(row=row_idx, column=2).value).upper()
        if not any(
            _cell_text(ws.cell(row=row_idx, column=c).value) for c in range(1, 12)
        ):
            continue

        if not row_programme:
            errors.append({"row": row_idx, "message": "Programme code is required in column B."})
            continue
        if row_programme not in known:
            errors.append({"row": row_idx, "message": f"Unknown programme code: {row_programme}"})
            continue
        if programme_code and row_programme != programme_code:
            errors.append(
                {
                    "row": row_idx,
                    "message": f"Row programme_code {row_programme} does not match selected programme {programme_code}.",
                }
            )
            continue

        raw_r_year = _cell_text(ws.cell(row=row_idx, column=3).value)
        raw_posting = _cell_text(ws.cell(row=row_idx, column=4).value)
        dashboard_posting = _cell_text(ws.cell(row=row_idx, column=5).value) or None
        session_type = _cell_text(ws.cell(row=row_idx, column=6).value)
        monthly_target_raw = _cell_text(ws.cell(row=row_idx, column=7).value)
        is_tracked_raw = _cell_text(ws.cell(row=row_idx, column=8).value)
        is_reallocatable_raw = _cell_text(ws.cell(row=row_idx, column=9).value)
        tag = _cell_text(ws.cell(row=row_idx, column=10).value) or None
        details_of_training = _cell_text(ws.cell(row=row_idx, column=11).value)

        if not raw_posting:
            errors.append({"row": row_idx, "message": "Posting code (column D) is required."})
            continue
        posting_code = parse_posting_code(raw_posting)

        try:
            duration_hours = parse_session_type_duration(session_type)
        except Exception:
            errors.append({"row": row_idx, "message": f"Session type '{session_type}' has invalid or missing [Xh]."})
            continue

        try:
            monthly_target = float(monthly_target_raw)
        except Exception:
            errors.append({"row": row_idx, "message": f"Monthly target '{monthly_target_raw}' is not numeric."})
            continue
        if monthly_target <= 0:
            errors.append({"row": row_idx, "message": "Monthly target must be positive."})
            continue

        exploded_years = explode_r_years(raw_r_year, row_programme)
        if not exploded_years:
            errors.append({"row": row_idx, "message": "Column C r_year is required."})
            continue

        is_tracked = parse_bool_cell(is_tracked_raw, true_values={"yes", "y", "true"})
        is_reallocatable = parse_bool_cell(is_reallocatable_raw, true_values={"y", "yes", "true"})
        if is_reallocatable and not tag:
            errors.append({"row": row_idx, "message": "Reallocatable rows must include a tag (column J)."})
            continue

        keywords = split_keywords(details_of_training)
        if not keywords:
            errors.append({"row": row_idx, "message": "Column K details_of_training is mandatory and must contain at least one keyword."})
            continue

        for exploded_r_year in exploded_years:
            target_row = ParsedTeachingTargetRow(
                source_row=row_idx,
                reporting_period=period_label,
                reporting_period_id=period_id_str,
                programme_code=row_programme,
                r_year=exploded_r_year,
                posting_code=posting_code,
                dashboard_posting=dashboard_posting,
                session_type=session_type,
                duration_hours=duration_hours,
                monthly_target=monthly_target,
                is_tracked=is_tracked,
                is_reallocatable=is_reallocatable,
                tag=tag,
                details_of_training=details_of_training,
                keywords=keywords,
            )
            teaching_targets.append(target_row)
            for keyword in keywords:
                catalogue_rows.append(
                    ParsedCatalogueRow(
                        source_row=row_idx,
                        keyword=keyword,
                        session_type=session_type,
                        posting_code=posting_code,
                        programme_code=row_programme,
                        r_year=exploded_r_year,
                        reporting_period_id=period_id_str,
                        duration_hours=duration_hours,
                        is_tracked=is_tracked,
                    )
                )
            if dashboard_posting:
                posting_group_rows.append(
                    ParsedPostingGroupRow(
                        source_row=row_idx,
                        group_code=dashboard_posting,
                        posting_code=posting_code,
                        programme_code=row_programme,
                    )
                )

    workbook.close()

    duplicate_key_seen: dict[tuple[str, str, str, str, str], int] = {}
    for row in teaching_targets:
        dedupe_key = (
            row.reporting_period_id,
            row.programme_code,
            row.r_year,
            row.posting_code,
            row.session_type,
        )
        duplicate_key_seen[dedupe_key] = duplicate_key_seen.get(dedupe_key, 0) + 1
    for key, count in duplicate_key_seen.items():
        if count > 1:
            errors.append(
                {
                    "message": "Duplicate teaching target after row explosion.",
                    "key": {
                        "reporting_period_id": key[0],
                        "programme_code": key[1],
                        "r_year": key[2],
                        "posting_code": key[3],
                        "session_type": key[4],
                    },
                }
            )

    tag_counts: dict[tuple[str, str, str, str, str], int] = {}
    for row in teaching_targets:
        if row.tag:
            tag_family = extract_tag_family(row.tag)
            tag_key = (
                row.reporting_period_id,
                row.programme_code,
                row.posting_code,
                row.r_year,
                tag_family,
            )
            tag_counts[tag_key] = tag_counts.get(tag_key, 0) + 1
    for row in teaching_targets:
        if row.tag:
            tag_family = extract_tag_family(row.tag)
            tag_key = (
                row.reporting_period_id,
                row.programme_code,
                row.posting_code,
                row.r_year,
                tag_family,
            )
            if tag_counts.get(tag_key, 0) < 2:
                errors.append(
                    {
                        "row": row.source_row,
                        "message": (
                            "Tag group must contain at least two rows in the same posting/programme/"
                            "effective_r_year/tag_family scope."
                        ),
                        "tag": row.tag,
                        "tag_family": tag_family,
                        "posting_code": row.posting_code,
                        "programme_code": row.programme_code,
                        "r_year": row.r_year,
                    }
                )

    keyword_duration_map: dict[tuple[str, str, str, str, str, float], str] = {}
    for row in catalogue_rows:
        key = (
            row.reporting_period_id,
            row.programme_code,
            row.r_year,
            row.posting_code,
            row.keyword.casefold(),
            row.duration_hours,
        )
        existing_session = keyword_duration_map.get(key)
        if existing_session and existing_session != row.session_type:
            errors.append(
                {
                    "row": row.source_row,
                    "message": "Keyword+duration conflict maps to multiple session types.",
                    "keyword": row.keyword,
                    "posting_code": row.posting_code,
                    "r_year": row.r_year,
                    "session_type_a": existing_session,
                    "session_type_b": row.session_type,
                }
            )
        else:
            keyword_duration_map[key] = row.session_type

    posting_tag_durations: dict[tuple[str, str, str, str, str], dict[str, float]] = {}
    for row in teaching_targets:
        if not row.tag:
            continue
        tag_family = extract_tag_family(row.tag)
        group_key = (
            row.reporting_period_id,
            row.programme_code,
            row.posting_code,
            row.r_year,
            tag_family,
        )
        posting_tag_durations.setdefault(group_key, {})
        existing = posting_tag_durations[group_key].get(row.tag)
        if existing is None or row.duration_hours > existing:
            posting_tag_durations[group_key][row.tag] = row.duration_hours
    for group_key, durations in posting_tag_durations.items():
        ordered_tags = sorted(durations.keys())
        for index in range(len(ordered_tags) - 1):
            left_tag = ordered_tags[index]
            right_tag = ordered_tags[index + 1]
            if durations[left_tag] < durations[right_tag]:
                warnings.append(
                    {
                        "type": "tag_order_warning",
                        "reporting_period_id": group_key[0],
                        "programme_code": group_key[1],
                        "posting_code": group_key[2],
                        "r_year": group_key[3],
                        "tag_family": group_key[4],
                        "message": f"Tag order {left_tag}->{right_tag} maps {durations[left_tag]}h->{durations[right_tag]}h (shorter to longer).",
                    }
                )

    deduped_posting_groups = {
        (row.group_code, row.posting_code, row.programme_code): row
        for row in posting_group_rows
    }
    metadata.update(
        {
            "ttf_sheet": sheet_name,
            "ttf_header_row": header_row,
            "targets": [asdict(row) for row in teaching_targets],
            "catalogue_rows": [asdict(row) for row in catalogue_rows],
            "posting_groups": [asdict(row) for row in deduped_posting_groups.values()],
            "counts": {
                "targets": len(teaching_targets),
                "catalogue_rows": len(catalogue_rows),
                "posting_groups": len(deduped_posting_groups),
            },
        }
    )
    return ParserResult(
        upload_type="ttf",
        warnings=warnings,
        errors=errors,
        metadata=metadata,
    )
