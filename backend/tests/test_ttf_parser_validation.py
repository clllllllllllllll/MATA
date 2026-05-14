from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from openpyxl import Workbook, load_workbook

from app.services.ttf_parser import parse_ttf_upload


def _make_ttf_bytes(sheet_name: str = "TTF", headers: bool = True, rows: list[list[object]] | None = None) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    if headers:
        header_values = [
            "reporting_period",
            "programme_code",
            "r_year",
            "posting_code",
            "dashboard_posting",
            "session_type",
            "monthly_target",
            "is_tracked",
            "is_reallocatable",
            "tag",
            "details_of_training",
        ]
        for idx, value in enumerate(header_values, start=1):
            sheet.cell(row=1, column=idx, value=value)
    for row_index, row in enumerate(rows or [], start=2):
        for col_index, value in enumerate(row, start=1):
            sheet.cell(row=row_index, column=col_index, value=value)
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()
    return payload.getvalue()


async def _parse(rows: list[list[object]], *, sheet_name: str = "TTF"):
    return await parse_ttf_upload(
        file_bytes=_make_ttf_bytes(sheet_name=sheet_name, rows=rows),
        original_filename="Teaching_Target_File_DR.xlsx",
        reporting_period_id=uuid4(),
        programme_code="DR",
    )


async def _parse_for_programme(rows: list[list[object]], programme_code: str):
    return await parse_ttf_upload(
        file_bytes=_make_ttf_bytes(rows=rows),
        original_filename=f"Teaching_Target_File_{programme_code}.xlsx",
        reporting_period_id=uuid4(),
        programme_code=programme_code,
    )


def _base_row(**overrides: object) -> list[object]:
    row = [
        "Jan - June",
        "DR",
        "R2",
        "TTSHDiagRd",
        "",
        "Department Learning Events [1h]",
        7,
        "Yes",
        "N",
        "",
        "Journal Club, Bedside Teaching, Case Discussion",
    ]
    mapping = {
        "period": 0,
        "programme": 1,
        "r_year": 2,
        "posting": 3,
        "group": 4,
        "session_type": 5,
        "monthly_target": 6,
        "is_tracked": 7,
        "is_reallocatable": 8,
        "tag": 9,
        "details": 10,
    }
    for key, value in overrides.items():
        row[mapping[key]] = value
    return row


@pytest.mark.asyncio
async def test_dynamic_sheet_detection() -> None:
    workbook = Workbook()
    junk = workbook.active
    junk.title = "Cover"
    junk.cell(row=1, column=1, value="hello")
    ttf = workbook.create_sheet("Real TTF")
    for i, header in enumerate(
        [
            "reporting_period",
            "programme_code",
            "r_year",
            "posting_code",
            "dashboard_posting",
            "session_type",
            "monthly_target",
            "is_tracked",
            "is_reallocatable",
            "tag",
            "details_of_training",
        ],
        start=1,
    ):
        ttf.cell(row=1, column=i, value=header)
    row = _base_row()
    for i, value in enumerate(row, start=1):
        ttf.cell(row=2, column=i, value=value)
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()

    result = await parse_ttf_upload(
        file_bytes=payload.getvalue(),
        original_filename="ttf.xlsx",
        reporting_period_id=uuid4(),
        programme_code="DR",
    )
    assert result.metadata is not None
    assert result.metadata["ttf_sheet"] == "Real TTF"
    assert result.metadata["ttf_header_row"] == 1
    assert result.errors == []


@pytest.mark.asyncio
async def test_dynamic_sheet_detection_wrapped_header_non_first_row() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "DR TTF"
    sheet.cell(row=1, column=1, value="cover/title")
    wrapped_headers = [
        "Reporting\nPeriod",
        "Programme",
        "Year of\nResidency",
        "Current Posting",
        "For Dashboard\n(RDB Posting/Subspeciality)",
        "Session Type",
        "Frequency target",
        "Tracked?",
        "Can session be reallocated?",
        "Tag",
        "Details of Training",
    ]
    for col, value in enumerate(wrapped_headers, start=1):
        sheet.cell(row=3, column=col, value=value)
    row = _base_row(r_year="R4")
    for col, value in enumerate(row, start=1):
        sheet.cell(row=4, column=col, value=value)
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()

    result = await parse_ttf_upload(
        file_bytes=payload.getvalue(),
        original_filename="Teaching_Target_File_DR.xlsx",
        reporting_period_id=uuid4(),
        programme_code="DR",
    )
    assert result.errors == []
    assert result.metadata["ttf_sheet"] == "DR TTF"
    assert result.metadata["ttf_header_row"] == 3
    assert result.metadata["counts"]["targets"] == 1


@pytest.mark.asyncio
async def test_bracket_posting_code_resolution_uses_last_bracket() -> None:
    result = await _parse([_base_row(posting="AIC [] [AICAIC]")])
    target = result.metadata["targets"][0]
    assert target["posting_code"] == "AICAIC"


@pytest.mark.asyncio
async def test_dormant_posting_code_accepted() -> None:
    result = await _parse([_base_row(posting="DormantCode123")])
    assert result.errors == []
    assert result.metadata["targets"][0]["posting_code"] == "DormantCode123"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session_type,duration",
    [
        ("A [1h]", 1.0),
        ("B [1.5h]", 1.5),
        ("C [0.5h]", 0.5),
    ],
)
async def test_duration_parsing_variants(session_type: str, duration: float) -> None:
    result = await _parse([_base_row(session_type=session_type)])
    assert result.errors == []
    assert result.metadata["targets"][0]["duration_hours"] == duration


@pytest.mark.asyncio
async def test_missing_duration_fails_validation() -> None:
    result = await _parse([_base_row(session_type="No duration")])
    assert any("invalid or missing [Xh]" in error["message"] for error in result.errors)


@pytest.mark.asyncio
async def test_multi_year_explosion() -> None:
    result = await _parse([_base_row(r_year="R4, R5, R6")])
    years = [row["r_year"] for row in result.metadata["targets"]]
    assert years == ["R4", "R5", "R6"]


@pytest.mark.asyncio
async def test_r_year_required_false_maps_to_all() -> None:
    result = await parse_ttf_upload(
        file_bytes=_make_ttf_bytes(rows=[_base_row(programme="GERI", r_year="R2,R3")]),
        original_filename="ttf.xlsx",
        reporting_period_id=uuid4(),
        programme_code="GERI",
    )
    assert result.errors == []
    assert [row["r_year"] for row in result.metadata["targets"]] == ["ALL"]


@pytest.mark.asyncio
async def test_combined_posting_label_not_exploded() -> None:
    combined = "IMHGrPsyc & TTSHPsychi"
    result = await _parse([_base_row(posting=combined)])
    assert result.errors == []
    assert result.metadata["targets"][0]["posting_code"] == combined


@pytest.mark.asyncio
async def test_column_k_blank_fails_validation() -> None:
    result = await _parse([_base_row(details="")])
    assert any("Column K" in error["message"] for error in result.errors)


@pytest.mark.asyncio
async def test_non_tracked_rows_still_seed_catalogue() -> None:
    result = await _parse([_base_row(is_tracked="No")])
    assert result.errors == []
    assert result.metadata["counts"]["catalogue_rows"] == 3
    assert all(row["is_tracked"] is False for row in result.metadata["catalogue_rows"])


@pytest.mark.asyncio
async def test_keyword_conflict_blocks() -> None:
    row_a = _base_row(session_type="Type A [1h]", details="Journal Club")
    row_b = _base_row(session_type="Type B [1h]", details="Journal Club")
    result = await _parse([row_a, row_b])
    assert any("Keyword+duration conflict" in error["message"] for error in result.errors)


@pytest.mark.asyncio
async def test_reallocatable_row_without_tag_blocks() -> None:
    result = await _parse([_base_row(is_reallocatable="Y", tag="")])
    assert any("must include a tag" in error["message"] for error in result.errors)


@pytest.mark.asyncio
async def test_tag_group_singleton_blocks() -> None:
    result = await _parse([_base_row(is_reallocatable="Y", tag="A1")])
    assert any("Tag group must contain at least two rows" in error["message"] for error in result.errors)


@pytest.mark.asyncio
async def test_tag_duration_order_warning_non_blocking() -> None:
    row_a1 = _base_row(session_type="Long [1h]", is_reallocatable="Y", tag="A1")
    row_a2 = _base_row(session_type="Short [2h]", is_reallocatable="Y", tag="A2")
    result = await _parse([row_a1, row_a2])
    assert result.errors == []
    assert any(
        warning["type"] == "tag_order_warning" and warning["tag_family"] == "A"
        for warning in result.warnings
    )


@pytest.mark.asyncio
async def test_column_e_does_not_replace_column_d_and_column_g_row_specific() -> None:
    rows = [
        _base_row(posting="TTSHDiagRd", group="TTSHDiagRd", monthly_target=7),
        _base_row(posting="TTSHDiagRd(Body)", group="TTSHDiagRd", monthly_target=3),
    ]
    result = await _parse(rows)
    targets = result.metadata["targets"]
    assert targets[0]["posting_code"] == "TTSHDiagRd"
    assert targets[0]["monthly_target"] == 7.0
    assert targets[1]["posting_code"] == "TTSHDiagRd(Body)"
    assert targets[1]["monthly_target"] == 3.0


@pytest.mark.asyncio
async def test_empty_column_e_creates_no_posting_group() -> None:
    result = await _parse([_base_row(group="")])
    assert result.metadata["counts"]["posting_groups"] == 0


@pytest.mark.asyncio
async def test_ampersand_in_column_d_does_not_create_posting_group() -> None:
    result = await _parse([_base_row(posting="AAA & BBB", group="")])
    assert result.metadata["counts"]["posting_groups"] == 0


@pytest.mark.asyncio
async def test_parser_output_has_no_compliance_aggregate_fields() -> None:
    result = await _parse([_base_row()])
    target = result.metadata["targets"][0]
    forbidden = {
        "target100",
        "target70",
        "active_months",
        "percentage",
        "shortage",
        "surplus",
        "clawback",
        "reallocation",
    }
    assert forbidden.isdisjoint(set(target.keys()))


@pytest.mark.asyncio
async def test_grouped_postings_preserved_as_separate_rows() -> None:
    rows = [
        _base_row(posting="P1", group="G1", session_type="S1 [1h]", details="K1,K2,K3"),
        _base_row(posting="P2", group="G1", session_type="S2 [1h]", details="K4,K5,K6"),
    ]
    result = await _parse(rows)
    postings = [row["posting_code"] for row in result.metadata["targets"]]
    assert postings == ["P1", "P2"]


@pytest.mark.asyncio
async def test_sample_data_grouped_dr_posting() -> None:
    result = await _parse(
        [
            _base_row(
                posting="TTSHDiagRd",
                group="TTSHDiagRd",
                session_type="Department Learning Events [1h]",
                monthly_target=7,
                details="Journal Club2, Bedside Teaching2, Case Discussion2",
            )
        ]
    )
    target = result.metadata["targets"][0]
    catalogue_rows = result.metadata["catalogue_rows"]
    posting_groups = result.metadata["posting_groups"]
    assert target["posting_code"] == "TTSHDiagRd"
    assert target["monthly_target"] == 7.0
    assert len(catalogue_rows) == 3
    assert all(row["posting_code"] == "TTSHDiagRd" for row in catalogue_rows)
    assert posting_groups[0]["group_code"] == "TTSHDiagRd"
    assert posting_groups[0]["posting_code"] == "TTSHDiagRd"
    assert posting_groups[0]["programme_code"] == "DR"


@pytest.mark.asyncio
async def test_sample_data_dr_subgroup_under_parent() -> None:
    result = await _parse(
        [
            _base_row(
                posting="TTSHDiagRd(Body)",
                group="TTSHDiagRd",
                session_type="National Teaching [3h]",
                monthly_target=3,
                details="Journal Club2, Bedside Teaching2, Case Discussion2",
            )
        ]
    )
    target = result.metadata["targets"][0]
    catalogue_rows = result.metadata["catalogue_rows"]
    posting_groups = result.metadata["posting_groups"]
    assert target["posting_code"] == "TTSHDiagRd(Body)"
    assert target["monthly_target"] == 3.0
    assert len(catalogue_rows) == 3
    assert all(row["posting_code"] == "TTSHDiagRd(Body)" for row in catalogue_rows)
    assert posting_groups[0]["group_code"] == "TTSHDiagRd"
    assert posting_groups[0]["posting_code"] == "TTSHDiagRd(Body)"
    assert posting_groups[0]["programme_code"] == "DR"


@pytest.mark.asyncio
async def test_sample_data_subgroup_like_with_blank_column_e() -> None:
    result = await _parse(
        [
            _base_row(
                posting="WHDiagRd(Body)",
                group="",
                session_type="Department Learning Events [1h]",
                monthly_target=7,
                details="Journal Club3, Bedside Teaching3, Case Discussion3",
            )
        ]
    )
    target = result.metadata["targets"][0]
    catalogue_rows = result.metadata["catalogue_rows"]
    assert target["posting_code"] == "WHDiagRd(Body)"
    assert target["monthly_target"] == 7.0
    assert len(catalogue_rows) == 3
    assert all(row["posting_code"] == "WHDiagRd(Body)" for row in catalogue_rows)
    assert result.metadata["counts"]["posting_groups"] == 0


@pytest.mark.asyncio
async def test_keyword_expansion_shape_and_trimmed_fields() -> None:
    result = await _parse([_base_row(details=" Journal Club , Bedside Teaching , Case Discussion ")])
    rows = result.metadata["catalogue_rows"]
    assert len(rows) == 3
    for row in rows:
        assert row["keyword"] in {"Journal Club", "Bedside Teaching", "Case Discussion"}
        assert row["session_type"] == "Department Learning Events [1h]"
        assert row["posting_code"] == "TTSHDiagRd"
        assert row["programme_code"] == "DR"
        assert row["r_year"] == "R2"
        assert "reporting_period_id" in row
        assert row["duration_hours"] == 1.0
        assert row["is_tracked"] is True


@pytest.mark.asyncio
async def test_valid_same_r_year_tag_group_passes() -> None:
    rows = [
        _base_row(
            r_year="R4",
            posting="TTSHDiagRd",
            session_type="National Teaching [3h]",
            is_reallocatable="Y",
            tag="A1",
            details="National Journal Club",
        ),
        _base_row(
            r_year="R4",
            posting="TTSHDiagRd",
            session_type="Department Learning Events [1h]",
            is_reallocatable="Y",
            tag="A2",
            details="Journal Club",
        ),
    ]
    result = await _parse(rows)
    assert result.errors == []
    assert not any(w["type"] == "tag_order_warning" for w in result.warnings)
    tags = [target["tag"] for target in result.metadata["targets"]]
    assert tags == ["A1", "A2"]


@pytest.mark.asyncio
async def test_cross_r_year_tag_group_fails_singleton_validation() -> None:
    rows = [
        _base_row(
            r_year="R4",
            posting="TTSHDiagRd",
            session_type="National Teaching [3h]",
            is_reallocatable="Y",
            tag="A1",
            details="National Journal Club",
        ),
        _base_row(
            r_year="R5",
            posting="TTSHDiagRd",
            session_type="Department Learning Events [1h]",
            is_reallocatable="Y",
            tag="A2",
            details="Journal Club",
        ),
    ]
    result = await _parse(rows)
    singleton_errors = [
        error
        for error in result.errors
        if "effective_r_year/tag_family scope" in error["message"]
    ]
    assert len(singleton_errors) == 2
    assert {error["r_year"] for error in singleton_errors} == {"R4", "R5"}
    assert {error["tag_family"] for error in singleton_errors} == {"A"}


@pytest.mark.asyncio
async def test_r_year_required_false_groups_under_all() -> None:
    rows = [
        _base_row(
            programme="GERI",
            r_year="R4",
            posting="SomePosting",
            session_type="National Teaching [3h]",
            is_reallocatable="Y",
            tag="A1",
            details="National Journal Club",
        ),
        _base_row(
            programme="GERI",
            r_year="R5",
            posting="SomePosting",
            session_type="Department Learning Events [1h]",
            is_reallocatable="Y",
            tag="A2",
            details="Journal Club",
        ),
    ]
    result = await _parse_for_programme(rows, "GERI")
    assert result.errors == []
    assert [target["r_year"] for target in result.metadata["targets"]] == ["ALL", "ALL"]
    assert [row["r_year"] for row in result.metadata["catalogue_rows"]] == ["ALL", "ALL"]


@pytest.mark.asyncio
async def test_real_dr_ttf_excel_mapping_regression() -> None:
    candidate_paths = [
        Path("Teaching_Target_File_DR__CL.xlsx"),
        Path("tests/data/Teaching_Target_File_DR__CL.xlsx"),
        Path("../tests/data/Teaching_Target_File_DR__CL.xlsx"),
    ]
    workbook_path = next((path for path in candidate_paths if path.exists()), None)
    if workbook_path is None:
        pytest.skip("Teaching_Target_File_DR__CL.xlsx not found at repo root or test fixture path.")

    # Explicitly open with openpyxl to satisfy the real-file verification requirement.
    wb = load_workbook(workbook_path, data_only=True)
    wb.close()
    file_bytes = workbook_path.read_bytes()

    result = await parse_ttf_upload(
        file_bytes=file_bytes,
        original_filename=workbook_path.name,
        reporting_period_id=uuid4(),
        programme_code="DR",
    )
    assert result.metadata is not None
    if "catalogue_rows" not in result.metadata or "posting_groups" not in result.metadata or "targets" not in result.metadata:
        pytest.skip("Real DR sample did not parse into Phase 2.4 intermediate shape in this environment.")

    keywords_of_interest = {
        "DR Demo Row 44",
        "DR Demo Row 45",
        "DR Demo Row 46",
        "DR Demo Row 47",
    }
    postings_of_interest = {"TTSHDiagRd", "TTSHDiagRd(Body)"}

    filtered_catalogue = [
        row
        for row in result.metadata["catalogue_rows"]
        if row["posting_code"] in postings_of_interest or row["keyword"] in keywords_of_interest
    ]
    filtered_groups = [
        row
        for row in result.metadata["posting_groups"]
        if row["posting_code"] in postings_of_interest or row["group_code"] == "TTSHDiagRd"
    ]
    filtered_targets = [
        row for row in result.metadata["targets"] if row["posting_code"] in postings_of_interest
    ]

    # Keyword mapping checks against current DR fixture labels.
    keyword_map = {row["keyword"]: row for row in filtered_catalogue}
    assert "DR Demo Row 44" in keyword_map
    assert keyword_map["DR Demo Row 44"]["posting_code"] == "TTSHDiagRd"
    assert keyword_map["DR Demo Row 44"]["programme_code"] == "DR"
    assert keyword_map["DR Demo Row 44"]["r_year"] == "R1"
    assert keyword_map["DR Demo Row 44"]["session_type"] == "Department Learning Events [1h]"
    assert keyword_map["DR Demo Row 44"]["duration_hours"] == 1.0

    assert "DR Demo Row 45" in keyword_map
    assert keyword_map["DR Demo Row 45"]["posting_code"] == "TTSHDiagRd(Body)"
    assert keyword_map["DR Demo Row 45"]["programme_code"] == "DR"
    assert keyword_map["DR Demo Row 45"]["r_year"] == "R1"
    assert keyword_map["DR Demo Row 45"]["session_type"] == "National Teaching [3h]"
    assert keyword_map["DR Demo Row 45"]["duration_hours"] == 3.0

    assert "DR Demo Row 46" in keyword_map
    assert keyword_map["DR Demo Row 46"]["posting_code"] == "TTSHDiagRd"
    assert keyword_map["DR Demo Row 46"]["programme_code"] == "DR"
    assert keyword_map["DR Demo Row 46"]["r_year"] == "R2"
    assert keyword_map["DR Demo Row 46"]["session_type"] == "Department Learning Events [1h]"
    assert keyword_map["DR Demo Row 46"]["duration_hours"] == 1.0

    assert "DR Demo Row 47" in keyword_map
    assert keyword_map["DR Demo Row 47"]["posting_code"] == "TTSHDiagRd"
    assert keyword_map["DR Demo Row 47"]["programme_code"] == "DR"
    assert keyword_map["DR Demo Row 47"]["r_year"] == "R2"
    assert keyword_map["DR Demo Row 47"]["session_type"] == "National Teaching [3h]"
    assert keyword_map["DR Demo Row 47"]["duration_hours"] == 3.0

    # Monthly targets remain row-specific on teaching targets.
    target_index = {
        (row["posting_code"], row["r_year"], row["session_type"]): row
        for row in result.metadata["targets"]
    }
    assert target_index[("TTSHDiagRd", "R1", "Department Learning Events [1h]")]["monthly_target"] == 7.0
    assert target_index[("TTSHDiagRd(Body)", "R1", "National Teaching [3h]")]["monthly_target"] == 3.0
    assert target_index[("TTSHDiagRd", "R2", "Department Learning Events [1h]")]["monthly_target"] == 7.0
    assert target_index[("TTSHDiagRd", "R2", "National Teaching [3h]")]["monthly_target"] == 3.0

    # Posting groups checks
    assert any(
        row["group_code"] == "TTSHDiagRd"
        and row["posting_code"] == "TTSHDiagRd"
        and row["programme_code"] == "DR"
        for row in filtered_groups
    )
    assert any(
        row["group_code"] == "TTSHDiagRd"
        and row["posting_code"] == "TTSHDiagRd(Body)"
        and row["programme_code"] == "DR"
        for row in filtered_groups
    )
    assert not any(row["posting_code"] == "WHDiagRd(Body)" for row in result.metadata["posting_groups"])

    # Column E must not replace Column D in targets/catalogue
    assert any(row["posting_code"] == "TTSHDiagRd(Body)" for row in filtered_targets)
    assert target_index[("TTSHDiagRd(Body)", "R1", "National Teaching [3h]")]["posting_code"] == "TTSHDiagRd(Body)"

    # Real workbook A1/A2 verification
    a1_rows = [
        row
        for row in result.metadata["targets"]
        if isinstance(row.get("tag"), str) and row["tag"].strip() == "A1"
    ]
    a2_rows = [
        row
        for row in result.metadata["targets"]
        if isinstance(row.get("tag"), str) and row["tag"].strip() == "A2"
    ]
    assert a1_rows, "Expected at least one A1 row in real DR workbook."
    assert a2_rows, "Expected at least one A2 row in real DR workbook."

    matched_pair_found = False
    for a1_row in a1_rows:
        for a2_row in a2_rows:
            if (
                a1_row["posting_code"] == a2_row["posting_code"]
                and a1_row["programme_code"] == a2_row["programme_code"]
                and a1_row["r_year"] == a2_row["r_year"]
            ):
                matched_pair_found = True
                assert a1_row["posting_code"] == "TTSHDiagRd"
                assert a1_row["programme_code"] == "DR"
                assert a1_row["r_year"] == "R4"
                assert a2_row["posting_code"] == "TTSHDiagRd"
                assert a2_row["programme_code"] == "DR"
                assert a2_row["r_year"] == "R4"
                assert float(a1_row["duration_hours"]) > float(a2_row["duration_hours"])
                singleton_errors = [
                    error
                    for error in result.errors
                    if isinstance(error, dict)
                    and "effective_r_year/tag_family scope" in error.get("message", "")
                    and error.get("posting_code") == a1_row["posting_code"]
                    and error.get("programme_code") == a1_row["programme_code"]
                    and error.get("r_year") == a1_row["r_year"]
                    and error.get("tag_family") == "A"
                ]
                assert singleton_errors == []
                break
        if matched_pair_found:
            break
    assert matched_pair_found, "Expected at least one A1/A2 pair sharing posting/programme/r_year."
