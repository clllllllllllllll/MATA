from __future__ import annotations

from datetime import date

import pytest

from app.services.rdb_parser import (
    ParsedPostingCell,
    classify_posting_cell,
    compute_working_days,
    normalize_rdb_cell,
)


def _context(**overrides: object) -> dict[str, object]:
    context: dict[str, object] = {
        "known_loa_types": {
            "Maternity Leave",
            "Annual Leaves",
            "No-Pay-Leave",
        },
        "phase_start": date(2025, 9, 1),
        "phase_end": date(2025, 9, 30),
    }
    context.update(overrides)
    return context


def test_classify_posting_cell_empty_returns_none() -> None:
    normalized = normalize_rdb_cell("  \r\n ")
    parsed = classify_posting_cell(normalized, _context())

    assert parsed is None
    assert normalized.normalized_lines == []


def test_classify_posting_cell_simple_posting_is_active() -> None:
    normalized = normalize_rdb_cell("TTSHAnaes")
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code == "TTSHAnaes"
    assert parsed.status == "active"
    assert parsed.loa_type is None
    assert parsed.multi_posting_fragments == []
    assert parsed.raw_cell == "TTSHAnaes"
    assert parsed.normalized_lines == ["TTSHAnaes"]
    assert parsed.warnings == []


def test_classify_posting_cell_pure_loa_sets_loa_status_and_null_posting_code() -> None:
    normalized = normalize_rdb_cell("LOA (Maternity Leave from 01-Sep-2025 to 30-Sep-2025)")
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code is None
    assert parsed.status == "loa"
    assert parsed.loa_type == "Maternity Leave"
    assert parsed.loa_start == date(2025, 9, 1)
    assert parsed.loa_end == date(2025, 9, 30)
    assert parsed.working_days == 0
    assert parsed.annotations[0]["kind"] == "pure_loa"
    assert parsed.warnings == []


def test_classify_posting_cell_pure_loa_accepts_trailing_whitespace_before_closing_bracket() -> None:
    normalized = normalize_rdb_cell("LOA (Maternity Leave from 01-Sep-2025 to 30-Sep-2025 )")
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.status == "loa"
    assert parsed.loa_type == "Maternity Leave"
    assert parsed.loa_start == date(2025, 9, 1)
    assert parsed.loa_end == date(2025, 9, 30)


def test_classify_posting_cell_pure_loa_supports_spaced_date_hyphens() -> None:
    normalized = normalize_rdb_cell("LOA (Maternity Leave from 01 - Sep - 2025 to 30 - Sep - 2025 )")
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.status == "loa"
    assert parsed.loa_type == "Maternity Leave"
    assert parsed.loa_start == date(2025, 9, 1)
    assert parsed.loa_end == date(2025, 9, 30)
    assert parsed.normalized_lines == ["LOA (Maternity Leave from 01-Sep-2025 to 30-Sep-2025 )"]


def test_classify_posting_cell_same_line_continue_working_is_loa_working_and_not_loa_type() -> None:
    normalized = normalize_rdb_cell(
        "TTSHAnaes (Continue working during LOA from 01-Sep-2025 to 05-Oct-2025)"
    )
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code == "TTSHAnaes"
    assert parsed.status == "loa_working"
    assert parsed.loa_type is None
    assert parsed.loa_start == date(2025, 9, 1)
    assert parsed.loa_end == date(2025, 10, 5)
    assert parsed.warnings == []


@pytest.mark.parametrize(
    ("start_token", "end_token"),
    [
        ("06-Apr-2026", "03-May-2026"),
        ("06 - Apr - 2026", "03 - May - 2026"),
        ("06- Apr -2026", "03- May -2026"),
        ("06 Apr 2026", "03 May 2026"),
        ("06 \u2013 Apr \u2013 2026", "03 \u2013 May \u2013 2026"),
        ("06 \u2014 Apr \u2014 2026", "03 \u2014 May \u2014 2026"),
    ],
)
def test_classify_posting_cell_hybrid_loa_working_date_variants_parse_equivalently(
    start_token: str,
    end_token: str,
) -> None:
    parsed = classify_posting_cell(
        normalize_rdb_cell(
            f"TTSHAnaes (Continue working during LOA from {start_token} to {end_token} )"
        ),
        _context(phase_start=date(2026, 4, 6), phase_end=date(2026, 5, 3)),
    )

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code == "TTSHAnaes"
    assert parsed.status == "loa_working"
    assert parsed.loa_type is None
    assert parsed.loa_start == date(2026, 4, 6)
    assert parsed.loa_end == date(2026, 5, 3)
    assert parsed.warnings == []


@pytest.mark.parametrize(
    "cell_text",
    [
        "TTSHAnaes( Continue working during LOA from 06 - Apr - 2026 to 03 - May - 2026)",
        "TTSHAnaes\n(Continue working during LOA from 06 Apr 2026 to 03 May 2026)",
        "TTSHAnaes\u00a0(continue working during loa from 06\u00a0Apr\u00a02026 to 03\u00a0May\u00a02026)",
        "TTSHAnaes\t(CONTINUE WORKING DURING LOA from 06-Apr-2026 to 03-May-2026 )",
    ],
)
def test_classify_posting_cell_hybrid_loa_working_parenthesis_and_phrase_drift(
    cell_text: str,
) -> None:
    parsed = classify_posting_cell(
        normalize_rdb_cell(cell_text),
        _context(phase_start=date(2026, 4, 6), phase_end=date(2026, 5, 3)),
    )

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code == "TTSHAnaes"
    assert parsed.status == "loa_working"
    assert parsed.loa_type is None
    assert parsed.loa_start == date(2026, 4, 6)
    assert parsed.loa_end == date(2026, 5, 3)
    assert parsed.warnings == []


def test_classify_posting_cell_loa_wrapped_continue_working_marker_is_not_unknown_loa() -> None:
    parsed = classify_posting_cell(
        normalize_rdb_cell(
            "LOA (Continue working during LOA from 01-Dec-2025 to 05-Jan-2026 )"
        ),
        _context(phase_start=date(2025, 12, 1), phase_end=date(2026, 1, 5)),
    )

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code is None
    assert parsed.status == "loa_working"
    assert parsed.loa_type is None
    assert parsed.loa_start == date(2025, 12, 1)
    assert parsed.loa_end == date(2026, 1, 5)
    assert parsed.warnings == []


def test_classify_posting_cell_multiline_posting_plus_pure_loa_is_loa_working() -> None:
    normalized = normalize_rdb_cell(
        "TTSHGenMed\nLOA (Maternity Leave from 30-Aug-2025 to 31-Aug-2025)"
    )
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code == "TTSHGenMed"
    assert parsed.status == "loa_working"
    assert parsed.loa_type == "Maternity Leave"
    assert parsed.loa_start == date(2025, 8, 30)
    assert parsed.loa_end == date(2025, 8, 31)


def test_classify_posting_cell_multiline_posting_plus_pure_loa_accepts_date_variants() -> None:
    parsed = classify_posting_cell(
        normalize_rdb_cell(
            "TTSHGenMed\r\n"
            " LOA (Maternity Leave from 30 \u2013 Aug \u2013 2025 to 31 Aug 2025 ) "
        ),
        _context(phase_start=date(2025, 8, 1), phase_end=date(2025, 8, 31)),
    )

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code == "TTSHGenMed"
    assert parsed.status == "loa_working"
    assert parsed.loa_type == "Maternity Leave"
    assert parsed.loa_start == date(2025, 8, 30)
    assert parsed.loa_end == date(2025, 8, 31)


def test_classify_posting_cell_multiline_continue_working_plus_pure_loa_prefers_pure_loa_fields() -> None:
    normalized = normalize_rdb_cell(
        "TTSHAnaes (Continue working during LOA from 02-Jun-2026 to 02-Jun-2026)\n"
        "LOA (Maternity Leave from 03-Jun-2026 to 06-Jul-2026)"
    )
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code == "TTSHAnaes"
    assert parsed.status == "loa_working"
    assert parsed.loa_type == "Maternity Leave"
    assert parsed.loa_start == date(2026, 6, 3)
    assert parsed.loa_end == date(2026, 7, 6)
    assert len(parsed.annotations) == 2
    assert parsed.annotations[0]["kind"] == "continue_working_during_loa"
    assert parsed.annotations[1]["kind"] == "pure_loa"


@pytest.mark.parametrize(
    ("start_token", "end_token"),
    [
        ("01-Sep-2025", "30-Sep-2025"),
        ("01 - Sep - 2025", "30 - Sep - 2025"),
        ("01- Sep -2025", "30- Sep -2025"),
        ("01 Sep 2025", "30 Sep 2025"),
    ],
)
def test_classify_posting_cell_pure_loa_date_variants_parse_equivalently(
    start_token: str,
    end_token: str,
) -> None:
    parsed = classify_posting_cell(
        normalize_rdb_cell(f"LOA (Maternity Leave from {start_token} to {end_token} )"),
        _context(),
    )

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code is None
    assert parsed.status == "loa"
    assert parsed.loa_type == "Maternity Leave"
    assert parsed.loa_start == date(2025, 9, 1)
    assert parsed.loa_end == date(2025, 9, 30)
    assert parsed.warnings == []


def test_classify_posting_cell_multiple_pure_loa_lines_preserves_annotations_and_compatibility_fields() -> None:
    normalized = normalize_rdb_cell(
        "LOA (Maternity Leave from 01-Aug-2025 to 20-Aug-2025)\n"
        "LOA (Annual Leaves from 21-Aug-2025 to 31-Aug-2025)"
    )
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.status == "loa"
    assert parsed.posting_code is None
    assert parsed.loa_type == "Maternity Leave"
    assert parsed.loa_start == date(2025, 8, 1)
    assert parsed.loa_end == date(2025, 8, 20)
    assert [item["loa_type"] for item in parsed.annotations if item["kind"] == "pure_loa"] == [
        "Maternity Leave",
        "Annual Leaves",
    ]


def test_classify_posting_cell_pending_sr_promotion_is_annotation_not_loa() -> None:
    normalized = normalize_rdb_cell(
        "TTSHEmgMed (Pending for SR Promotion from 06-Apr-2026 to 03-May-2026)"
    )
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code == "TTSHEmgMed"
    assert parsed.status == "active"
    assert parsed.loa_type is None
    assert parsed.pending_sr_promotion_start == date(2026, 4, 6)
    assert parsed.pending_sr_promotion_end == date(2026, 5, 3)
    assert parsed.working_days == 30


def test_classify_posting_cell_refresher_training_add_to_max_cand() -> None:
    normalized = normalize_rdb_cell(
        "PostingCode (Refresher Training (add to Max Cand) from 01-Sep-2025 to 05-Oct-2025)"
    )
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code == "PostingCode"
    assert parsed.status == "active"
    assert parsed.loa_type is None
    assert parsed.refresher_training_type == "add to Max Cand"
    assert parsed.refresher_training_start == date(2025, 9, 1)
    assert parsed.refresher_training_end == date(2025, 10, 5)


def test_classify_posting_cell_refresher_training_dont_add_to_max_cand() -> None:
    normalized = normalize_rdb_cell(
        "PostingCode (Refresher Training (don't add to Max Cand) from 01-Sep-2025 to 05-Oct-2025)"
    )
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code == "PostingCode"
    assert parsed.status == "active"
    assert parsed.refresher_training_type == "don't add to Max Cand"
    assert parsed.refresher_training_start == date(2025, 9, 1)
    assert parsed.refresher_training_end == date(2025, 10, 5)


def test_classify_posting_cell_refresher_training_curly_apostrophe_and_date_variants() -> None:
    parsed = classify_posting_cell(
        normalize_rdb_cell(
            "PostingCode (Refresher Training (don\u2019t add to Max Cand) "
            "from 01 Sep 2025 to 05 \u2013 Oct \u2013 2025 )"
        ),
        _context(),
    )

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code == "PostingCode"
    assert parsed.status == "active"
    assert parsed.refresher_training_type == "don't add to Max Cand"
    assert parsed.refresher_training_start == date(2025, 9, 1)
    assert parsed.refresher_training_end == date(2025, 10, 5)


def test_classify_posting_cell_loa_with_refresher_line_uses_clean_posting_code() -> None:
    normalized = normalize_rdb_cell(
        "LOA (Annual Leaves from 02-Feb-2026 to 18-Feb-2026)\n"
        "LOA (Family Care Leave from 19-Feb-2026 to 19-Feb-2026)\n"
        "CGHPsyMed (Refresher Training (don't add to Max Cand) from 20-Feb-2026 to 01-Mar-2026)"
    )
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.status == "loa_working"
    assert parsed.posting_code == "CGHPsyMed"
    assert parsed.loa_type == "Annual Leaves"
    assert parsed.refresher_training_type == "don't add to Max Cand"
    assert parsed.refresher_training_start == date(2026, 2, 20)
    assert parsed.refresher_training_end == date(2026, 3, 1)


def test_classify_posting_cell_malformed_refresher_warns_and_avoids_oversized_posting_code() -> None:
    malformed_line = (
        "CGHPsyMed (Refresher Training (dont add to Max Cand) from 20-Feb-2026 to 01-Mar-2026)"
    )
    normalized = normalize_rdb_cell(
        "LOA (Annual Leaves from 02-Feb-2026 to 18-Feb-2026)\n"
        f"{malformed_line}"
    )
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.status == "loa_working"
    assert parsed.posting_code == "CGHPsyMed"
    assert len(parsed.posting_code or "") <= 50
    assert parsed.refresher_training_type is None
    assert any("Malformed refresher" in warning for warning in parsed.warnings)


def test_classify_posting_cell_employed_variants_set_employer_tag_and_no_posting_code() -> None:
    parsed_upper = classify_posting_cell(normalize_rdb_cell("SAF-Employed"), _context())
    parsed_lower = classify_posting_cell(normalize_rdb_cell("TTSH-employed"), _context())

    assert isinstance(parsed_upper, ParsedPostingCell)
    assert isinstance(parsed_lower, ParsedPostingCell)
    assert parsed_upper.status == "employed"
    assert parsed_upper.employer_tag == "SAF"
    assert parsed_upper.posting_code is None
    assert parsed_lower.status == "employed"
    assert parsed_lower.employer_tag == "TTSH"
    assert parsed_lower.posting_code is None


def test_classify_posting_cell_future_employed_prefix_is_supported_generically() -> None:
    parsed = classify_posting_cell(normalize_rdb_cell("ABC-Employed"), _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.status == "employed"
    assert parsed.employer_tag == "ABC"
    assert parsed.posting_code is None


@pytest.mark.parametrize(
    ("raw_cell", "expected_tag", "expected_normalized"),
    [
        ("SAF-Employed", "SAF", "SAF-Employed"),
        ("SAF-employed", "SAF", "SAF-Employed"),
        ("SAF Employed", "SAF", "SAF-Employed"),
        ("SAF employed", "SAF", "SAF-Employed"),
        ("SAF - Employed", "SAF", "SAF-Employed"),
        ("SCDF-Employed", "SCDF", "SCDF-Employed"),
        ("SCDF Employed", "SCDF", "SCDF-Employed"),
        ("ABC-Employed", "ABC", "ABC-Employed"),
        ("ABC Employed", "ABC", "ABC-Employed"),
        ("ABC-employed", "ABC", "ABC-Employed"),
    ],
)
def test_classify_posting_cell_generic_employed_marker_variants_canonicalize(
    raw_cell: str,
    expected_tag: str,
    expected_normalized: str,
) -> None:
    normalized = normalize_rdb_cell(raw_cell)
    parsed = classify_posting_cell(normalized, _context())

    assert normalized.normalized_value == expected_normalized
    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.status == "employed"
    assert parsed.employer_tag == expected_tag
    assert parsed.posting_code is None
    assert parsed.warnings == []


@pytest.mark.parametrize(
    "raw_cell",
    [
        "Employed only",
        "SAF Employed extra text",
        "SAF/SCDF currently employed",
        "SAF SCDF Employed",
        "This resident is employed elsewhere",
    ],
)
def test_classify_posting_cell_malformed_employed_markers_warn_without_creating_posting(
    raw_cell: str,
) -> None:
    parsed = classify_posting_cell(normalize_rdb_cell(raw_cell), _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.status == "active"
    assert parsed.posting_code is None
    assert parsed.employer_tag is None
    assert any("Malformed employed marker" in warning for warning in parsed.warnings)


def test_classify_posting_cell_numeric_fm_code_stays_string_posting_code() -> None:
    normalized = normalize_rdb_cell(270)
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code == "270"
    assert parsed.status == "active"
    assert parsed.raw_cell == 270
    assert parsed.normalized_lines == ["270"]


def test_classify_posting_cell_explicit_multi_posting_date_ranges_with_optional_am_pm() -> None:
    normalized = normalize_rdb_cell(
        "NUHPaedia\n"
        "(from 08-Jul-2025 to 09-Jul-2025 )\n"
        "(from 10 - Jul - 2025 to 10 - Jul - 2025 AM)\n"
        "(from 11-Jul-2025 to 11-Jul-2025 )\n"
        "NHGPlyNHGPly\n"
        "(from 10-Jul-2025 to 10-Jul-2025 PM)\n"
        "(from 12-Jul-2025 to 12-Jul-2025 )\n"
        "NUHPaedia\n"
        "(from 13-Jul-2025 to 13-Jul-2025 PM)\n"
    )
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.posting_code is None
    assert parsed.status == "active"
    assert len(parsed.multi_posting_fragments) == 6
    assert [
        fragment.posting_code for fragment in parsed.multi_posting_fragments
    ] == [
        "NUHPaedia",
        "NUHPaedia",
        "NUHPaedia",
        "NHGPlyNHGPly",
        "NHGPlyNHGPly",
        "NUHPaedia",
    ]
    assert parsed.multi_posting_fragments[0].start_date == date(2025, 7, 8)
    assert parsed.multi_posting_fragments[0].end_date == date(2025, 7, 9)
    assert parsed.multi_posting_fragments[0].day_part is None
    assert parsed.multi_posting_fragments[1].day_part == "AM"
    assert parsed.multi_posting_fragments[3].day_part == "PM"
    assert parsed.multi_posting_fragments[5].day_part == "PM"
    assert parsed.warnings == []


def test_classify_posting_cell_explicit_multi_posting_date_variants_preserve_day_part() -> None:
    parsed = classify_posting_cell(
        normalize_rdb_cell(
            "TTSHCardio\n"
            "(from 01 Dec 2025 to 01 \u2013 Dec \u2013 2025 AM)\n"
            "NHCCardio\n"
            "(from 01 - Dec - 2025 to 01-Dec-2025 PM)"
        ),
        _context(phase_start=date(2025, 12, 1), phase_end=date(2026, 1, 5)),
    )

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.status == "active"
    assert len(parsed.multi_posting_fragments) == 2
    assert parsed.multi_posting_fragments[0].posting_code == "TTSHCardio"
    assert parsed.multi_posting_fragments[0].start_date == date(2025, 12, 1)
    assert parsed.multi_posting_fragments[0].day_part == "AM"
    assert parsed.multi_posting_fragments[1].posting_code == "NHCCardio"
    assert parsed.multi_posting_fragments[1].start_date == date(2025, 12, 1)
    assert parsed.multi_posting_fragments[1].day_part == "PM"
    assert parsed.warnings == []


def test_classify_posting_cell_unknown_loa_type_warns_and_keeps_raw_type() -> None:
    normalized = normalize_rdb_cell("LOA (Exam Leave from 01-Sep-2025 to 15-Sep-2025)")
    parsed = classify_posting_cell(normalized, _context())

    assert isinstance(parsed, ParsedPostingCell)
    assert parsed.status == "loa"
    assert parsed.loa_type == "Exam Leave"
    assert parsed.warnings == ["Unknown LOA type: Exam Leave"]


def test_compute_working_days_uses_calendar_days_and_clips_loa_to_phase_boundaries() -> None:
    computed = compute_working_days(
        phase_start=date(2025, 9, 10),
        phase_end=date(2025, 9, 20),
        loa_start=date(2025, 9, 1),
        loa_end=date(2025, 9, 13),
    )

    assert computed == 7


def test_classify_posting_cell_does_not_write_to_database_layer() -> None:
    class WriteGuard:
        called = False

        def execute(self, *args: object, **kwargs: object) -> None:
            self.called = True

    guard = WriteGuard()
    parsed = classify_posting_cell(
        normalize_rdb_cell("TTSHAnaes"),
        _context(db_session=guard),
    )

    assert isinstance(parsed, ParsedPostingCell)
    assert guard.called is False
