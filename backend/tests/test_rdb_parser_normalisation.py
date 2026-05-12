from __future__ import annotations

from datetime import date

import pytest

from app.services.rdb_parser import normalize_rdb_cell, parse_loa_annotation


def test_normalize_rdb_cell_preserves_raw_value() -> None:
    raw = "  TTSHAnaes\r\nLOA (Maternity Leave from 22-Aug-2025 to 31-Aug-2025 )  "

    normalized = normalize_rdb_cell(raw)

    assert normalized.raw_value == raw


def test_normalize_rdb_cell_replaces_nbsp_and_line_endings_and_drops_empty_lines() -> None:
    raw = "TTSHAnaes\u00a0\r\n\r\n LOA (Maternity Leave from 22-Aug-2025 to 31-Aug-2025 )\r"

    normalized = normalize_rdb_cell(raw)

    assert normalized.normalized_lines == [
        "TTSHAnaes",
        "LOA (Maternity Leave from 22-Aug-2025 to 31-Aug-2025 )",
    ]
    assert normalized.normalized_value == "TTSHAnaes\nLOA (Maternity Leave from 22-Aug-2025 to 31-Aug-2025 )"


def test_normalize_rdb_cell_normalizes_spaced_hyphen_dates_only() -> None:
    raw = "TTSHAnaes (Continue working during LOA from 06 - Apr - 2026 to 03 - May - 2026 )"

    normalized = normalize_rdb_cell(raw)

    assert normalized.normalized_value == (
        "TTSHAnaes (Continue working during LOA from 06-Apr-2026 to 03-May-2026 )"
    )


@pytest.mark.parametrize(
    "raw_date",
    [
        "06-Apr-2026",
        "06 - Apr - 2026",
        "06- Apr -2026",
        "06 Apr 2026",
        "06 \u2013 Apr \u2013 2026",
    ],
)
def test_normalize_rdb_cell_canonicalizes_supported_date_token_drift(raw_date: str) -> None:
    normalized = normalize_rdb_cell(f"LOA (Maternity Leave from {raw_date} to 03 May 2026 )")

    assert normalized.normalized_value == (
        "LOA (Maternity Leave from 06-Apr-2026 to 03-May-2026 )"
    )


def test_normalize_rdb_cell_does_not_modify_posting_or_free_text_hyphens() -> None:
    raw = "SAF-Employed"

    normalized = normalize_rdb_cell(raw)

    assert normalized.normalized_value == "SAF-Employed"


def test_normalize_rdb_cell_simple_posting_code_kept_as_single_line() -> None:
    normalized = normalize_rdb_cell("TTSHAnaes")

    assert normalized.normalized_lines == ["TTSHAnaes"]
    assert normalized.normalized_value == "TTSHAnaes"


def test_normalize_rdb_cell_preserves_employed_tags_and_casing() -> None:
    normalized_upper = normalize_rdb_cell("SAF-Employed")
    normalized_mixed = normalize_rdb_cell("TTSH-employed")
    normalized_spaced = normalize_rdb_cell("SCDF Employed")

    assert normalized_upper.normalized_value == "SAF-Employed"
    assert normalized_mixed.normalized_value == "TTSH-Employed"
    assert normalized_spaced.normalized_value == "SCDF-Employed"


def test_normalize_rdb_cell_numeric_fm_posting_code_stays_string() -> None:
    normalized = normalize_rdb_cell(270)

    assert normalized.normalized_value == "270"
    assert normalized.normalized_lines == ["270"]


def test_normalize_rdb_cell_pending_sr_promotion_normalizes_only_date_tokens() -> None:
    raw = "TTSHEmgMed (Pending for SR Promotion from 06 - Apr - 2026 to 03 - May - 2026)"

    normalized = normalize_rdb_cell(raw)

    assert normalized.normalized_value == (
        "TTSHEmgMed (Pending for SR Promotion from 06-Apr-2026 to 03-May-2026)"
    )


def test_normalize_rdb_cell_refresher_training_normalizes_only_date_tokens() -> None:
    raw = "PostingCode (Refresher Training (add to Max Cand) from 01 - Sep - 2025 to 05 - Oct - 2025)"

    normalized = normalize_rdb_cell(raw)

    assert normalized.normalized_value == (
        "PostingCode (Refresher Training (add to Max Cand) from 01-Sep-2025 to 05-Oct-2025)"
    )


def test_normalize_rdb_cell_explicit_multi_posting_date_ranges_preserved() -> None:
    raw = (
        "NUHPaedia\r\n"
        "(from 08-Jul-2025 to 09-Jul-2025 )\r\n"
        "(from 10 - Jul - 2025 to 10 - Jul - 2025 AM)\r\n"
        "NHGPlyNHGPly\r\n"
        "(from 10-Jul-2025 to 10-Jul-2025 PM)\r\n"
        "(from 12-Jul-2025 to 12-Jul-2025 )\r\n"
    )
    normalized = normalize_rdb_cell(raw)

    assert normalized.normalized_lines == [
        "NUHPaedia",
        "(from 08-Jul-2025 to 09-Jul-2025 )",
        "(from 10-Jul-2025 to 10-Jul-2025 AM)",
        "NHGPlyNHGPly",
        "(from 10-Jul-2025 to 10-Jul-2025 PM)",
        "(from 12-Jul-2025 to 12-Jul-2025 )",
    ]


def test_normalize_rdb_cell_keeps_multiple_pure_loa_lines() -> None:
    raw = (
        "LOA (Maternity Leave from 01-Aug-2025 to 20-Aug-2025)\n"
        "LOA (Annual Leaves from 21-Aug-2025 to 31-Aug-2025)"
    )
    normalized = normalize_rdb_cell(raw)

    assert normalized.normalized_lines == [
        "LOA (Maternity Leave from 01-Aug-2025 to 20-Aug-2025)",
        "LOA (Annual Leaves from 21-Aug-2025 to 31-Aug-2025)",
    ]


def test_parse_loa_annotation_handles_pure_loa() -> None:
    parsed = parse_loa_annotation("LOA (Maternity Leave from 01-Sep-2025 to 30-Sep-2025)")

    assert parsed == {
        "status": "loa",
        "loa_type": "Maternity Leave",
        "loa_start": date(2025, 9, 1),
        "loa_end": date(2025, 9, 30),
        "annotations": [
            {
                "kind": "pure_loa",
                "loa_type": "Maternity Leave",
                "start": date(2025, 9, 1),
                "end": date(2025, 9, 30),
                "raw_line": "LOA (Maternity Leave from 01-Sep-2025 to 30-Sep-2025)",
            }
        ],
    }


def test_parse_loa_annotation_handles_pure_loa_spaced_hyphens_and_trailing_bracket_whitespace() -> None:
    parsed = parse_loa_annotation("LOA (Maternity Leave from 01 - Sep - 2025 to 30 - Sep - 2025 )")

    assert parsed == {
        "status": "loa",
        "loa_type": "Maternity Leave",
        "loa_start": date(2025, 9, 1),
        "loa_end": date(2025, 9, 30),
        "annotations": [
            {
                "kind": "pure_loa",
                "loa_type": "Maternity Leave",
                "start": date(2025, 9, 1),
                "end": date(2025, 9, 30),
                "raw_line": "LOA (Maternity Leave from 01-Sep-2025 to 30-Sep-2025 )",
            }
        ],
    }


def test_parse_loa_annotation_handles_same_line_hybrid_without_treating_continue_working_as_loa_type() -> None:
    parsed = parse_loa_annotation(
        "TTSHAnaes (Continue working during LOA from 01-Sep-2025 to 05-Oct-2025)"
    )

    assert parsed == {
        "status": "loa_working",
        "loa_type": None,
        "loa_start": date(2025, 9, 1),
        "loa_end": date(2025, 10, 5),
        "annotations": [
            {
                "kind": "continue_working_during_loa",
                "loa_type": None,
                "start": date(2025, 9, 1),
                "end": date(2025, 10, 5),
                "raw_line": "TTSHAnaes (Continue working during LOA from 01-Sep-2025 to 05-Oct-2025)",
            }
        ],
    }


def test_parse_loa_annotation_handles_multiline_posting_plus_pure_loa() -> None:
    parsed = parse_loa_annotation(
        "TTSHGenMed\nLOA (Maternity Leave from 30-Aug-2025 to 31-Aug-2025)"
    )

    assert parsed == {
        "status": "loa_working",
        "loa_type": "Maternity Leave",
        "loa_start": date(2025, 8, 30),
        "loa_end": date(2025, 8, 31),
        "annotations": [
            {
                "kind": "pure_loa",
                "loa_type": "Maternity Leave",
                "start": date(2025, 8, 30),
                "end": date(2025, 8, 31),
                "raw_line": "LOA (Maternity Leave from 30-Aug-2025 to 31-Aug-2025)",
            }
        ],
    }


def test_parse_loa_annotation_multiline_hybrid_and_pure_loa_prefers_pure_loa_dates_and_type() -> None:
    parsed = parse_loa_annotation(
        "TTSHAnaes (Continue working during LOA from 02-Jun-2026 to 02-Jun-2026)\n"
        "LOA (Maternity Leave from 03-Jun-2026 to 06-Jul-2026)"
    )

    assert parsed == {
        "status": "loa_working",
        "loa_type": "Maternity Leave",
        "loa_start": date(2026, 6, 3),
        "loa_end": date(2026, 7, 6),
        "annotations": [
            {
                "kind": "continue_working_during_loa",
                "loa_type": None,
                "start": date(2026, 6, 2),
                "end": date(2026, 6, 2),
                "raw_line": "TTSHAnaes (Continue working during LOA from 02-Jun-2026 to 02-Jun-2026)",
            },
            {
                "kind": "pure_loa",
                "loa_type": "Maternity Leave",
                "start": date(2026, 6, 3),
                "end": date(2026, 7, 6),
                "raw_line": "LOA (Maternity Leave from 03-Jun-2026 to 06-Jul-2026)",
            },
        ],
    }


def test_parse_loa_annotation_returns_default_when_no_loa_annotation_present() -> None:
    parsed = parse_loa_annotation("TTSHEmgMed")

    assert parsed == {
        "status": "active",
        "loa_type": None,
        "loa_start": None,
        "loa_end": None,
        "annotations": [],
    }


def test_parse_loa_annotation_does_not_infer_pending_sr_promotion_annotation() -> None:
    parsed_pending = parse_loa_annotation(
        "TTSHEmgMed (Pending for SR Promotion from 06-Apr-2026 to 03-May-2026)"
    )
    parsed_refresher_add = parse_loa_annotation(
        "PostingCode (Refresher Training (add to Max Cand) from 01-Sep-2025 to 05-Oct-2025)"
    )
    parsed_refresher_no_add = parse_loa_annotation(
        "PostingCode (Refresher Training (don't add to Max Cand) from 01-Sep-2025 to 05-Oct-2025)"
    )

    for parsed in (parsed_pending, parsed_refresher_add, parsed_refresher_no_add):
        assert parsed == {
            "status": "active",
            "loa_type": None,
            "loa_start": None,
            "loa_end": None,
            "annotations": [],
        }


def test_parse_loa_annotation_with_multiple_pure_loa_lines_returns_first_valid_loa_without_merging() -> None:
    parsed = parse_loa_annotation(
        "LOA (Maternity Leave from 01-Aug-2025 to 20-Aug-2025)\n"
        "LOA (Annual Leaves from 21-Aug-2025 to 31-Aug-2025)"
    )

    assert parsed == {
        "status": "loa",
        "loa_type": "Maternity Leave",
        "loa_start": date(2025, 8, 1),
        "loa_end": date(2025, 8, 20),
        "annotations": [
            {
                "kind": "pure_loa",
                "loa_type": "Maternity Leave",
                "start": date(2025, 8, 1),
                "end": date(2025, 8, 20),
                "raw_line": "LOA (Maternity Leave from 01-Aug-2025 to 20-Aug-2025)",
            },
            {
                "kind": "pure_loa",
                "loa_type": "Annual Leaves",
                "start": date(2025, 8, 21),
                "end": date(2025, 8, 31),
                "raw_line": "LOA (Annual Leaves from 21-Aug-2025 to 31-Aug-2025)",
            },
        ],
    }
