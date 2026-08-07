"""Test-only canonical expectations for Phase R all-programme readiness.

The application continues to resolve programme configuration from persisted
``programmes`` rows.  This module deliberately keeps its explicit inventory in
the test package so readiness tests can attest the migration/seed contract
without creating a second runtime registry.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal, Mapping, TypeAlias


AyDateCategory: TypeAlias = Literal["im_subspec", "non_im_subspec"]
RYearMode: TypeAlias = Literal["ALL", "actual"]
NonNhgAvailabilityState: TypeAlias = Literal["active", "pending", "inactive", "missing"]
FinalReadinessStatus: TypeAlias = Literal[
    "ready",
    "application_ready_requires_staging_data",
    "blocked",
]
ReadinessStatus: TypeAlias = FinalReadinessStatus | Literal["not_assessed"]


# These checks mirror the Phase R audit matrix.  A final status is deliberately
# not derived as ready until every listed evidence point is explicitly true.
PHASE_R_REQUIRED_CHECKS = (
    "canonical_programme_row",
    "ay_date_category",
    "r_year_mode",
    "alias_behavior",
    "synthetic_posting_relationship",
    "final_aj_ttf_generation",
    "ttf_parse",
    "ttf_persistence",
    "target_reconciliation",
    "teaching_name_lifecycle",
    "pending_mapping",
    "mapped_mapping",
    "secretary_capability",
    "pc_scope",
    "scheduled_pool_event",
    "fixed_adhoc_event",
    "resident_visibility",
    "attendance_submission",
    "resolver",
    "audit_evidence",
    "restricted_role_isolation",
    "non_nhg_boundary",
)


@dataclass(frozen=True, slots=True)
class ProgrammeReadinessExpectation:
    """One canonical programme row expected by the Phase R readiness suite."""

    code: str
    name: str
    ay_date_category: AyDateCategory
    r_year_required: bool
    rdb_alias: str | None
    non_nhg_ttsh_state: NonNhgAvailabilityState
    non_nhg_ttsh_posting_code: str | None

    @property
    def r_year_mode(self) -> RYearMode:
        return "actual" if self.r_year_required else "ALL"

    @property
    def expected_fixture_r_years(self) -> tuple[str, ...]:
        """Representative valid values for generated final A–J fixtures."""

        return ("R4", "R5", "R6") if self.r_year_required else ("ALL",)


# Exact current 28-programme contract.  Keep this immutable tuple test-only;
# production behaviour is driven by persisted programme configuration.
PROGRAMME_READINESS_EXPECTATIONS: tuple[ProgrammeReadinessExpectation, ...] = (
    ProgrammeReadinessExpectation(
        "AIM", "Advanced Internal Medicine", "im_subspec", False, None, "active", "TTSHGenMed"
    ),
    ProgrammeReadinessExpectation(
        "ANAES", "Anaesthesiology", "non_im_subspec", True, None, "active", "TTSHAnaes"
    ),
    ProgrammeReadinessExpectation(
        "CARDIO", "Cardiology", "im_subspec", False, None, "active", "TTSHCardio"
    ),
    ProgrammeReadinessExpectation(
        "DERM", "Dermatology", "im_subspec", True, None, "active", "NSCDermat"
    ),
    ProgrammeReadinessExpectation(
        "DR", "Diagnostic Radiology", "non_im_subspec", True, None, "active", "TTSHDiagRd"
    ),
    ProgrammeReadinessExpectation(
        "EM", "Emergency Medicine", "non_im_subspec", False, None, "active", "TTSHEmgMed"
    ),
    ProgrammeReadinessExpectation(
        "ENDO", "Endocrinology", "im_subspec", False, None, "active", "TTSHEndocr"
    ),
    ProgrammeReadinessExpectation(
        "ENT", "Otorhinolaryngology", "non_im_subspec", False, None, "active", "TTSHOtolar"
    ),
    ProgrammeReadinessExpectation(
        "EYE", "Ophthalmology", "non_im_subspec", False, None, "active", "TTSHOphtha"
    ),
    ProgrammeReadinessExpectation(
        "FM", "Family Medicine", "non_im_subspec", True, None, "inactive", None
    ),
    ProgrammeReadinessExpectation(
        "GASTRO", "Gastroenterology", "im_subspec", False, None, "active", "TTSHGas"
    ),
    ProgrammeReadinessExpectation(
        "GERI", "Geriatric Medicine", "im_subspec", False, None, "active", "TTSHGerMed"
    ),
    ProgrammeReadinessExpectation(
        "GS", "General Surgery", "non_im_subspec", False, None, "active", "TTSHGenSrg"
    ),
    ProgrammeReadinessExpectation(
        "ID", "Infectious Diseases", "im_subspec", False, "Infectious Disease", "active", "TTSHInfect"
    ),
    ProgrammeReadinessExpectation(
        "IM", "Internal Medicine", "im_subspec", False, None, "active", "TTSHGenMed"
    ),
    ProgrammeReadinessExpectation(
        "MEDONCO", "Medical Oncology", "im_subspec", False, None, "active", "TTSHMedOnc"
    ),
    ProgrammeReadinessExpectation(
        "ORTHO", "Orthopaedic Surgery", "non_im_subspec", False, None, "active", "TTSHOrtSrg"
    ),
    ProgrammeReadinessExpectation(
        "PATH", "Pathology", "non_im_subspec", False, None, "inactive", None
    ),
    ProgrammeReadinessExpectation(
        "PSY", "Psychiatry", "non_im_subspec", True, None, "active", "TTSHPsychi"
    ),
    ProgrammeReadinessExpectation(
        "REHAB", "Rehabilitation Medicine", "im_subspec", False, None, "active", "TTSHRehabi"
    ),
    ProgrammeReadinessExpectation(
        "RENAL", "Renal Medicine", "im_subspec", False, "Renal Medicine Extended", "active", "TTSHRenal"
    ),
    ProgrammeReadinessExpectation(
        "RESPI", "Respiratory Medicine", "im_subspec", True, None, "active", "TTSHRespir"
    ),
    ProgrammeReadinessExpectation(
        "RHEUM", "Rheumatology", "im_subspec", False, None, "active", "TTSHRheuma"
    ),
    ProgrammeReadinessExpectation(
        "SPORTSMED", "Sports Medicine", "non_im_subspec", True, None, "inactive", None
    ),
    ProgrammeReadinessExpectation(
        "SIG", "Surgery-In-General", "non_im_subspec", False, "Surgery-in-General", "active", "TTSHGenSrg"
    ),
    ProgrammeReadinessExpectation(
        "URO", "Urology", "non_im_subspec", False, None, "active", "TTSHUrolog"
    ),
    ProgrammeReadinessExpectation(
        "MICROB", "Pathology (Microbiology)", "non_im_subspec", False, "Microbiology", "active", "TTSHLabMed"
    ),
    ProgrammeReadinessExpectation(
        "PALLMED", "Palliative Medicine", "im_subspec", True, None, "inactive", None
    ),
)

CANONICAL_PROGRAMME_CODES = tuple(row.code for row in PROGRAMME_READINESS_EXPECTATIONS)
CANONICAL_PROGRAMME_CODE_SET = frozenset(CANONICAL_PROGRAMME_CODES)
ALL_R_YEAR_PROGRAMME_CODES = tuple(
    row.code for row in PROGRAMME_READINESS_EXPECTATIONS if not row.r_year_required
)
ACTUAL_R_YEAR_PROGRAMME_CODES = tuple(
    row.code for row in PROGRAMME_READINESS_EXPECTATIONS if row.r_year_required
)
IM_SUBSPECIALTY_AY_PROGRAMME_CODES = tuple(
    row.code
    for row in PROGRAMME_READINESS_EXPECTATIONS
    if row.ay_date_category == "im_subspec"
)
NON_IM_SUBSPECIALTY_AY_PROGRAMME_CODES = tuple(
    row.code
    for row in PROGRAMME_READINESS_EXPECTATIONS
    if row.ay_date_category == "non_im_subspec"
)
RDB_ALIAS_TO_PROGRAMME_CODE = {
    row.rdb_alias: row.code
    for row in PROGRAMME_READINESS_EXPECTATIONS
    if row.rdb_alias is not None
}
PROGRAMME_EXPECTATION_BY_CODE = {
    row.code: row for row in PROGRAMME_READINESS_EXPECTATIONS
}

# Shape accepted by ``parse_ttf_upload(..., programme_configs=...)``.  It is
# intentionally generated from the one test-only manifest rather than copied
# into every all-programme parameterization.
PROGRAMME_CONFIGS = {
    row.code: {
        "code": row.code,
        "r_year_required": row.r_year_required,
        "is_subspecialty": False,
    }
    for row in PROGRAMME_READINESS_EXPECTATIONS
}


def expectation_for(programme_code: str) -> ProgrammeReadinessExpectation:
    """Return one canonical expectation or fail closed for an unexpected code."""

    try:
        return PROGRAMME_EXPECTATION_BY_CODE[programme_code.strip().upper()]
    except (AttributeError, KeyError) as error:
        raise ValueError("Phase R fixture requested an unknown programme code") from error


def derive_readiness_status(
    checks: Mapping[str, bool | None],
    *,
    requires_staging_data: bool,
) -> ReadinessStatus:
    """Derive a conservative readiness label from the complete audit matrix."""

    required_values = tuple(checks.get(check_name) for check_name in PHASE_R_REQUIRED_CHECKS)
    if any(value is False for value in required_values):
        return "blocked"
    if any(value is not True for value in required_values):
        return "not_assessed"
    if requires_staging_data:
        return "application_ready_requires_staging_data"
    return "ready"


def build_readiness_matrix(
    checks_by_programme: Mapping[str, Mapping[str, bool | None]] | None = None,
    *,
    requires_staging_data: frozenset[str] = frozenset(),
) -> tuple[dict[str, object], ...]:
    """Return a deterministic JSON-ready all-28 Phase R status matrix.

    Missing evidence intentionally produces ``not_assessed`` instead of a
    premature ready claim.  Supplying a false check produces ``blocked``.
    """

    checks_by_programme = checks_by_programme or {}
    unknown_check_codes = set(checks_by_programme) - CANONICAL_PROGRAMME_CODE_SET
    unknown_staging_codes = set(requires_staging_data) - CANONICAL_PROGRAMME_CODE_SET
    if unknown_check_codes or unknown_staging_codes:
        raise ValueError("Phase R matrix contains an unknown programme code")

    matrix: list[dict[str, object]] = []
    for expectation in PROGRAMME_READINESS_EXPECTATIONS:
        checks = checks_by_programme.get(expectation.code, {})
        matrix.append(
            {
                "programme": expectation.code,
                "r_year_mode": expectation.r_year_mode,
                "ay_date_category": expectation.ay_date_category,
                "rdb_alias": expectation.rdb_alias,
                "non_nhg_ttsh_state": expectation.non_nhg_ttsh_state,
                "non_nhg_ttsh_posting_code": expectation.non_nhg_ttsh_posting_code,
                "checks": {
                    check_name: checks.get(check_name)
                    for check_name in PHASE_R_REQUIRED_CHECKS
                },
                "requires_staging_data": expectation.code in requires_staging_data,
                "status": derive_readiness_status(
                    checks,
                    requires_staging_data=expectation.code in requires_staging_data,
                ),
            }
        )
    return tuple(matrix)


def readiness_matrix_json(
    checks_by_programme: Mapping[str, Mapping[str, bool | None]] | None = None,
    *,
    requires_staging_data: frozenset[str] = frozenset(),
) -> str:
    """Encode ``build_readiness_matrix`` deterministically for test artifacts."""

    return json.dumps(
        build_readiness_matrix(
            checks_by_programme,
            requires_staging_data=requires_staging_data,
        ),
        sort_keys=True,
        separators=(",", ":"),
    )
