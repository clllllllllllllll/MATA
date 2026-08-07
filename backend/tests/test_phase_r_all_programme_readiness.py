"""Focused, in-memory Phase R all-28 final A–J readiness harness.

This layer deliberately exercises metadata, parser behaviour, and target/mapping
reconciliation without opening a database or relying on a real workbook.  The
separate PostgreSQL/RLS suite remains responsible for database authorization
evidence.
"""

from __future__ import annotations

import json
from uuid import uuid5

import pytest

from app.services.rdb_parser import _load_programme_lookup
from app.services.ttf_parser import parse_ttf_upload
from tests.phase_r_readiness_fixtures import (
    FIXED_ADHOC_SESSION_TYPE,
    POOL_MAPPABLE_SESSION_TYPE,
    PhaseRInMemoryMappingResult,
    PhaseRInMemoryTTFSession,
    build_final_aj_ttf_fixture,
    build_ttf_reconciliation_fixture,
    final_aj_workbook_bytes,
)
from tests.phase_r_readiness_manifest import (
    ACTUAL_R_YEAR_PROGRAMME_CODES,
    ALL_R_YEAR_PROGRAMME_CODES,
    CANONICAL_PROGRAMME_CODES,
    CANONICAL_PROGRAMME_CODE_SET,
    IM_SUBSPECIALTY_AY_PROGRAMME_CODES,
    NON_IM_SUBSPECIALTY_AY_PROGRAMME_CODES,
    PHASE_R_REQUIRED_CHECKS,
    PROGRAMME_CONFIGS,
    PROGRAMME_READINESS_EXPECTATIONS,
    RDB_ALIAS_TO_PROGRAMME_CODE,
    build_readiness_matrix,
    readiness_matrix_json,
)


class _PhaseRProgrammeLookupSession:
    """Minimal read-only RDB configuration response for alias lookup coverage."""

    async def execute(self, statement):  # noqa: ANN001 - mirrors AsyncSession protocol.
        assert "FROM programmes" in str(statement)
        return PhaseRInMemoryMappingResult(
            [
                {
                    "code": expectation.code,
                    "name": expectation.name,
                    "r_year_required": expectation.r_year_required,
                    "is_subspecialty": False,
                    "rdb_alias": expectation.rdb_alias,
                }
                for expectation in PROGRAMME_READINESS_EXPECTATIONS
            ]
        )


def _target_ids_by_scope_and_session(
    session: PhaseRInMemoryTTFSession,
) -> dict[tuple[str, str, str], str]:
    session_type_names_by_id = {
        str(session_type["id"]): name
        for name, session_type in session.session_types.items()
    }
    return {
        (
            str(target["r_year"]),
            str(target["posting_code"]),
            session_type_names_by_id[str(target["session_type_id"])],
        ): str(target["id"])
        for target in session.teaching_targets
    }


def test_phase_r_manifest_has_exact_nonduplicated_28_programme_contract() -> None:
    assert len(PROGRAMME_READINESS_EXPECTATIONS) == 28
    assert len(CANONICAL_PROGRAMME_CODES) == 28
    assert len(CANONICAL_PROGRAMME_CODE_SET) == 28
    assert tuple(row.code for row in PROGRAMME_READINESS_EXPECTATIONS) == CANONICAL_PROGRAMME_CODES
    assert len(ALL_R_YEAR_PROGRAMME_CODES) == 20
    assert len(ACTUAL_R_YEAR_PROGRAMME_CODES) == 8
    assert set(ALL_R_YEAR_PROGRAMME_CODES).isdisjoint(ACTUAL_R_YEAR_PROGRAMME_CODES)
    assert set(ALL_R_YEAR_PROGRAMME_CODES) | set(ACTUAL_R_YEAR_PROGRAMME_CODES) == CANONICAL_PROGRAMME_CODE_SET
    assert ACTUAL_R_YEAR_PROGRAMME_CODES == (
        "ANAES",
        "DERM",
        "DR",
        "FM",
        "PSY",
        "RESPI",
        "SPORTSMED",
        "PALLMED",
    )
    assert len(IM_SUBSPECIALTY_AY_PROGRAMME_CODES) == 14
    assert len(NON_IM_SUBSPECIALTY_AY_PROGRAMME_CODES) == 14
    assert set(IM_SUBSPECIALTY_AY_PROGRAMME_CODES).isdisjoint(NON_IM_SUBSPECIALTY_AY_PROGRAMME_CODES)
    assert (
        set(IM_SUBSPECIALTY_AY_PROGRAMME_CODES)
        | set(NON_IM_SUBSPECIALTY_AY_PROGRAMME_CODES)
        == CANONICAL_PROGRAMME_CODE_SET
    )
    assert RDB_ALIAS_TO_PROGRAMME_CODE == {
        "Infectious Disease": "ID",
        "Renal Medicine Extended": "RENAL",
        "Surgery-in-General": "SIG",
        "Microbiology": "MICROB",
    }
    for programme_code in ("SPORTSMED", "PALLMED"):
        expectation = next(
            row for row in PROGRAMME_READINESS_EXPECTATIONS if row.code == programme_code
        )
        assert expectation.r_year_required is True
        assert expectation.expected_fixture_r_years == ("R4", "R5", "R6")


@pytest.mark.asyncio
async def test_phase_r_rdb_aliases_are_resolved_from_loaded_programme_configuration() -> None:
    programme_lookup = await _load_programme_lookup(_PhaseRProgrammeLookupSession())

    for alias, expected_code in RDB_ALIAS_TO_PROGRAMME_CODE.items():
        assert programme_lookup[alias.casefold()].code == expected_code
    for programme_code in CANONICAL_PROGRAMME_CODES:
        assert programme_lookup[programme_code.casefold()].code == programme_code


def test_phase_r_status_matrix_is_deterministic_and_never_assumes_missing_evidence() -> None:
    unassessed = build_readiness_matrix()
    assert len(unassessed) == 28
    assert all(row["status"] == "not_assessed" for row in unassessed)
    assert all(
        set(row["checks"]) == set(PHASE_R_REQUIRED_CHECKS)  # type: ignore[arg-type]
        for row in unassessed
    )

    complete_checks = {
        programme_code: {check_name: True for check_name in PHASE_R_REQUIRED_CHECKS}
        for programme_code in CANONICAL_PROGRAMME_CODES
    }
    matrix = build_readiness_matrix(
        complete_checks,
        requires_staging_data=frozenset({"FM", "PATH", "SPORTSMED", "PALLMED"}),
    )
    status_by_programme = {str(row["programme"]): row["status"] for row in matrix}
    assert status_by_programme["FM"] == "application_ready_requires_staging_data"
    assert status_by_programme["SPORTSMED"] == "application_ready_requires_staging_data"
    assert status_by_programme["AIM"] == "ready"
    assert json.loads(
        readiness_matrix_json(
            complete_checks,
            requires_staging_data=frozenset({"FM", "PATH", "SPORTSMED", "PALLMED"}),
        )
    ) == list(matrix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expectation",
    PROGRAMME_READINESS_EXPECTATIONS,
    ids=lambda expectation: expectation.code,
)
async def test_final_aj_in_memory_parser_path_accepts_every_canonical_programme(
    expectation,
) -> None:
    fixture = build_final_aj_ttf_fixture(expectation.code)
    result = await parse_ttf_upload(
        file_bytes=final_aj_workbook_bytes(fixture),
        original_filename=f"phase-r-{fixture.programme_code}.xlsx",
        reporting_period_id=fixture.reporting_period_id,
        reporting_period_label=fixture.reporting_period_label,
        programme_code=fixture.programme_code,
        programme_configs=PROGRAMME_CONFIGS,
    )

    assert result.errors == []
    assert result.metadata is not None
    targets = result.metadata["targets"]
    assert {target["programme_code"] for target in targets} == {fixture.programme_code}
    assert {target["r_year"] for target in targets} == set(fixture.expected_r_years)
    assert tuple(
        (
            target["reporting_period_id"],
            target["programme_code"],
            target["r_year"],
            target["posting_code"],
            target["session_type"],
        )
        for target in targets
    ) == fixture.expected_target_natural_keys
    assert all("details_of_training" not in target for target in targets)
    assert "catalogue_rows" not in result.metadata


@pytest.mark.asyncio
async def test_final_aj_upload_rejects_cross_programme_workbook_content() -> None:
    fixture = build_final_aj_ttf_fixture("DR")
    result = await parse_ttf_upload(
        file_bytes=final_aj_workbook_bytes(fixture, cross_programme_code="ANAES"),
        original_filename="phase-r-cross-programme.xlsx",
        reporting_period_id=fixture.reporting_period_id,
        reporting_period_label=fixture.reporting_period_label,
        programme_code="DR",
        programme_configs=PROGRAMME_CONFIGS,
    )

    assert any(
        error["message"] == "Column B programme code does not match the selected programme."
        for error in result.errors
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "expected_column", "expected_row", "expected_message"),
    [
        (
            {"populated_column_k": "legacy value"},
            "K",
            2,
            "TTF accepts columns Aâ€“J only.",
        ),
        (
            {"populated_column_k": "=1+1"},
            "K",
            2,
            "TTF accepts columns Aâ€“J only.",
        ),
        (
            {"formula_cell": "J2"},
            "J",
            2,
            "Formula cells are not allowed in final Aâ€“J TTF content.",
        ),
        (
            {"sparse_unsupported_cell": "XFD1048576"},
            "XFD",
            1048576,
            "TTF accepts columns Aâ€“J only.",
        ),
    ],
)
async def test_final_aj_schema_guards_reject_column_k_formulas_and_sparse_bypasses(
    kwargs: dict[str, object],
    expected_column: str,
    expected_row: int,
    expected_message: str,
) -> None:
    fixture = build_final_aj_ttf_fixture("SPORTSMED")
    result = await parse_ttf_upload(
        file_bytes=final_aj_workbook_bytes(fixture, **kwargs),
        original_filename="phase-r-schema-guard.xlsx",
        reporting_period_id=fixture.reporting_period_id,
        reporting_period_label=fixture.reporting_period_label,
        programme_code=fixture.programme_code,
        programme_configs=PROGRAMME_CONFIGS,
    )

    assert any(
        error.get("column") == expected_column
        and error.get("row") == expected_row
        and expected_message.split(" ", 1)[0] in error["message"]
        for error in result.errors
    )
    assert "legacy value" not in str(result.errors)
    assert "phase-r unsupported sparse content" not in str(result.errors)


@pytest.mark.asyncio
async def test_empty_formatted_trailing_cells_do_not_reintroduce_logical_column_k() -> None:
    fixture = build_final_aj_ttf_fixture("PALLMED")
    result = await parse_ttf_upload(
        file_bytes=final_aj_workbook_bytes(
            fixture,
            formatted_blank_columns_after_j=2,
        ),
        original_filename="phase-r-formatted-blank-columns.xlsx",
        reporting_period_id=fixture.reporting_period_id,
        reporting_period_label=fixture.reporting_period_label,
        programme_code=fixture.programme_code,
        programme_configs=PROGRAMME_CONFIGS,
    )

    assert result.errors == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expectation",
    PROGRAMME_READINESS_EXPECTATIONS,
    ids=lambda expectation: expectation.code,
)
async def test_all_28_ttf_reconciliation_preserves_stable_targets_and_pending_mappings(
    expectation,
) -> None:
    reconciliation = build_ttf_reconciliation_fixture(expectation.code)
    fixture = reconciliation.initial
    session = PhaseRInMemoryTTFSession()
    teaching_name_id = str(uuid5(fixture.reporting_period_id, "phase-r-pool-name"))
    session.teaching_names.append(
        {
            "id": teaching_name_id,
            "reporting_period_id": str(fixture.reporting_period_id),
            "programme_code": fixture.programme_code,
            "is_active": True,
        }
    )

    initial_result = await parse_ttf_upload(
        file_bytes=final_aj_workbook_bytes(fixture),
        original_filename=f"phase-r-initial-{fixture.programme_code}.xlsx",
        reporting_period_id=fixture.reporting_period_id,
        reporting_period_label=fixture.reporting_period_label,
        programme_code=fixture.programme_code,
        db_session=session,
    )
    assert initial_result.errors == []
    initial_target_ids = _target_ids_by_scope_and_session(session)
    assert set(initial_target_ids) == {
        (r_year, fixture.posting_code, session_type)
        for session_type in fixture.session_types
        for r_year in fixture.expected_r_years
    }
    mapped_mapping = next(
        mapping
        for mapping in session.teaching_name_mappings
        if mapping["programme_code"] == fixture.programme_code
        and mapping["posting_code"] == fixture.posting_code
        and mapping["r_year"] == reconciliation.mapped_scope_r_year
    )
    mapped_mapping["teaching_target_id"] = initial_target_ids[
        (
            reconciliation.mapped_scope_r_year,
            fixture.posting_code,
            reconciliation.mapped_target_session_type,
        )
    ]
    mapping_id = str(mapped_mapping["id"])

    equivalent_result = await parse_ttf_upload(
        file_bytes=final_aj_workbook_bytes(reconciliation.equivalent_reupload),
        original_filename=f"phase-r-equivalent-{fixture.programme_code}.xlsx",
        reporting_period_id=fixture.reporting_period_id,
        reporting_period_label=fixture.reporting_period_label,
        programme_code=fixture.programme_code,
        db_session=session,
    )
    assert equivalent_result.errors == []
    assert _target_ids_by_scope_and_session(session) == initial_target_ids
    assert mapped_mapping["teaching_target_id"] == initial_target_ids[
        (
            reconciliation.mapped_scope_r_year,
            fixture.posting_code,
            reconciliation.mapped_target_session_type,
        )
    ]
    assert equivalent_result.metadata["targets_unchanged"] == len(initial_target_ids)
    assert equivalent_result.metadata["mappings_preserved"] == 1

    removed_result = await parse_ttf_upload(
        file_bytes=final_aj_workbook_bytes(reconciliation.remove_pool_target_reupload),
        original_filename=f"phase-r-remove-pool-{fixture.programme_code}.xlsx",
        reporting_period_id=fixture.reporting_period_id,
        reporting_period_label=fixture.reporting_period_label,
        programme_code=fixture.programme_code,
        db_session=session,
    )
    assert removed_result.errors == []
    remaining_target_ids = _target_ids_by_scope_and_session(session)
    assert set(remaining_target_ids) == {
        (r_year, fixture.posting_code, FIXED_ADHOC_SESSION_TYPE)
        for r_year in fixture.expected_r_years
    }
    assert all(
        remaining_target_ids[(r_year, fixture.posting_code, FIXED_ADHOC_SESSION_TYPE)]
        == initial_target_ids[(r_year, fixture.posting_code, FIXED_ADHOC_SESSION_TYPE)]
        for r_year in fixture.expected_r_years
    )
    pending_mapping = next(
        mapping
        for mapping in session.teaching_name_mappings
        if str(mapping["id"]) == mapping_id
    )
    assert pending_mapping["teaching_target_id"] is None
    assert pending_mapping["revision"] == 2
    assert removed_result.metadata["targets_removed"] == len(fixture.expected_r_years)
    assert removed_result.metadata["mappings_invalidated"] == 1
    assert POOL_MAPPABLE_SESSION_TYPE not in {
        key[2] for key in remaining_target_ids
    }
