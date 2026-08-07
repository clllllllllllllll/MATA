from __future__ import annotations

import pytest

from app.services.rdb_parser import ProgrammeConfig, RDBParserError, resolve_r_year


_ALL_R_YEAR_PROGRAMMES = frozenset(
    {
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
        "SIG",
        "URO",
        "MICROB",
    }
)
_ACTUAL_R_YEAR_PROGRAMMES = frozenset(
    {
        "ANAES",
        "DERM",
        "DR",
        "FM",
        "PSY",
        "RESPI",
        "SPORTSMED",
        "PALLMED",
    }
)
_CANONICAL_PROGRAMME_CODES = frozenset(
    {
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
)


def test_r_year_mode_matrix_covers_the_canonical_28_programmes() -> None:
    assert _ALL_R_YEAR_PROGRAMMES.isdisjoint(_ACTUAL_R_YEAR_PROGRAMMES)
    assert (
        _ALL_R_YEAR_PROGRAMMES | _ACTUAL_R_YEAR_PROGRAMMES
        == _CANONICAL_PROGRAMME_CODES
    )


@pytest.mark.parametrize("programme_code", sorted(_ALL_R_YEAR_PROGRAMMES))
def test_all_r_year_programmes_use_the_all_sentinel(programme_code: str) -> None:
    programme = ProgrammeConfig(
        code=programme_code,
        r_year_required=False,
        is_subspecialty=False,
    )

    assert resolve_r_year(" r4 ", programme) == "ALL"


@pytest.mark.parametrize("programme_code", sorted(_ACTUAL_R_YEAR_PROGRAMMES))
def test_actual_r_year_programmes_normalize_and_preserve_r_year(
    programme_code: str,
) -> None:
    programme = ProgrammeConfig(
        code=programme_code,
        r_year_required=True,
        is_subspecialty=False,
    )

    assert resolve_r_year(" r4 ", programme) == "R4"


@pytest.mark.parametrize(
    ("raw_r_year", "expected_r_year"),
    [("r1", "R1"), (" R4 ", "R4"), ("r7", "R7")],
)
def test_actual_r_year_validation_accepts_normalized_generic_values(
    raw_r_year: str,
    expected_r_year: str,
) -> None:
    programme = ProgrammeConfig(
        code="ANAES",
        r_year_required=True,
        is_subspecialty=False,
    )

    assert resolve_r_year(raw_r_year, programme) == expected_r_year


@pytest.mark.parametrize("raw_r_year", ["", "   ", "ALL", "SS1", "R0", "R8", "4"])
def test_actual_r_year_validation_rejects_blank_and_unsupported_values(
    raw_r_year: str,
) -> None:
    programme = ProgrammeConfig(
        code="SPORTSMED",
        r_year_required=True,
        is_subspecialty=False,
    )

    with pytest.raises(RDBParserError, match="R-year"):
        resolve_r_year(raw_r_year, programme)


def test_subspecialty_flag_does_not_remap_actual_r_years() -> None:
    legacy_config = ProgrammeConfig(
        code="PALLMED",
        r_year_required=True,
        is_subspecialty=True,
    )

    assert resolve_r_year("R5", legacy_config) == "R5"
