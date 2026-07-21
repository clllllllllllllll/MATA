"""seed approved TTSH external-resident registration mappings

Revision ID: 20260721_000021
Revises: 20260721_000020
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260721_000021"
down_revision = "20260721_000020"
branch_labels = None
depends_on = None


INSTITUTION_CODE = "TTSH"

EXPECTED_PROGRAMME_CODES = (
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
)

ACTIVE_MAPPINGS = (
    ("AIM", "TTSHGenMed"),
    ("ANAES", "TTSHAnaes"),
    ("CARDIO", "TTSHCardio"),
    ("DERM", "NSCDermat"),
    ("DR", "TTSHDiagRd"),
    ("EM", "TTSHEmgMed"),
    ("ENDO", "TTSHEndocr"),
    ("ENT", "TTSHOtolar"),
    ("EYE", "TTSHOphtha"),
    ("GASTRO", "TTSHGas"),
    ("GERI", "TTSHGerMed"),
    ("GS", "TTSHGenSrg"),
    ("ID", "TTSHInfect"),
    ("IM", "TTSHGenMed"),
    ("MEDONCO", "TTSHMedOnc"),
    ("ORTHO", "TTSHOrtSrg"),
    ("PSY", "TTSHPsychi"),
    ("REHAB", "TTSHRehabi"),
    ("RENAL", "TTSHRenal"),
    ("RESPI", "TTSHRespir"),
    ("RHEUM", "TTSHRheuma"),
    ("SIG", "TTSHGenSrg"),
    ("URO", "TTSHUrolog"),
    ("MICROB", "TTSHLabMed"),
)

INACTIVE_PROGRAMME_CODES = (
    "FM",
    "PATH",
    "SPORTSMED",
    "PALLMED",
)


def _validate_configuration() -> tuple[dict[str, str], set[str]]:
    if not INSTITUTION_CODE or INSTITUTION_CODE != INSTITUTION_CODE.strip():
        raise RuntimeError("TTSH mapping institution code must be non-blank and trimmed")

    active_mapping = dict(ACTIVE_MAPPINGS)
    active_programmes = [programme_code for programme_code, _ in ACTIVE_MAPPINGS]
    inactive_programmes = set(INACTIVE_PROGRAMME_CODES)
    expected_programmes = set(EXPECTED_PROGRAMME_CODES)

    if len(EXPECTED_PROGRAMME_CODES) != 28 or len(expected_programmes) != 28:
        raise RuntimeError("TTSH mapping baseline must contain exactly 28 unique programmes")
    if any(not code or code != code.strip() for code in EXPECTED_PROGRAMME_CODES):
        raise RuntimeError("TTSH mapping baseline contains a blank or untrimmed programme code")
    if len(ACTIVE_MAPPINGS) != 24 or len(active_programmes) != len(set(active_programmes)):
        raise RuntimeError("TTSH active mapping list must contain exactly 24 unique programmes")
    if len(INACTIVE_PROGRAMME_CODES) != 4 or len(inactive_programmes) != 4:
        raise RuntimeError("TTSH inactive mapping list must contain exactly 4 unique programmes")
    if any(
        not programme_code
        or programme_code != programme_code.strip()
        or not posting_code
        or posting_code != posting_code.strip()
        for programme_code, posting_code in ACTIVE_MAPPINGS
    ):
        raise RuntimeError("TTSH active mappings contain a blank or untrimmed value")
    if any(not code or code != code.strip() for code in INACTIVE_PROGRAMME_CODES):
        raise RuntimeError("TTSH inactive mapping list contains a blank or untrimmed value")
    if set(active_programmes) & inactive_programmes:
        raise RuntimeError("TTSH active and inactive programme lists overlap")
    if set(active_programmes) | inactive_programmes != expected_programmes:
        raise RuntimeError("TTSH active and inactive programmes do not match the baseline")

    return active_mapping, inactive_programmes


def _snapshot_other_institutions(connection: Any) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        tuple(row)
        for row in connection.execute(
            sa.text(
                """
                SELECT id,
                       programme_code,
                       institution_code,
                       posting_code,
                       status,
                       display_order,
                       created_at,
                       updated_at
                FROM programme_institution_posting_map
                WHERE institution_code <> :institution_code
                ORDER BY institution_code, programme_code, id
                """
            ),
            {"institution_code": INSTITUTION_CODE},
        )
    )


def _load_ttsh_rows(connection: Any) -> list[Mapping[str, Any]]:
    return list(
        connection.execute(
            sa.text(
                """
                SELECT programme_code, posting_code, status, display_order
                FROM programme_institution_posting_map
                WHERE institution_code = :institution_code
                ORDER BY display_order, programme_code
                """
            ),
            {"institution_code": INSTITUTION_CODE},
        )
        .mappings()
        .all()
    )


def _validate_database_baseline(connection: Any) -> list[Mapping[str, Any]]:
    duplicate_pairs = connection.execute(
        sa.text(
            """
            SELECT programme_code, institution_code
            FROM programme_institution_posting_map
            GROUP BY programme_code, institution_code
            HAVING count(*) <> 1
            """
        )
    ).all()
    if duplicate_pairs:
        raise RuntimeError("programme/institution mapping pairs must be unique")

    rows = _load_ttsh_rows(connection)
    actual_programmes = [str(row["programme_code"]) for row in rows]
    if (
        len(rows) != 28
        or len(set(actual_programmes)) != 28
        or set(actual_programmes) != set(EXPECTED_PROGRAMME_CODES)
    ):
        raise RuntimeError("TTSH mapping rows do not match the expected 28-programme baseline")

    existing_programmes = set(
        connection.execute(sa.text("SELECT code FROM programmes")).scalars().all()
    )
    if not set(EXPECTED_PROGRAMME_CODES).issubset(existing_programmes):
        missing = sorted(set(EXPECTED_PROGRAMME_CODES) - existing_programmes)
        raise RuntimeError(f"TTSH mapping programmes are missing: {', '.join(missing)}")

    approved_posting_codes = {posting_code for _, posting_code in ACTIVE_MAPPINGS}
    existing_posting_codes = set(
        connection.execute(sa.text("SELECT code FROM posting_codes")).scalars().all()
    )
    if not approved_posting_codes.issubset(existing_posting_codes):
        missing = sorted(approved_posting_codes - existing_posting_codes)
        raise RuntimeError(f"TTSH mapping posting codes are missing: {', '.join(missing)}")

    return rows


def _validate_stage_one_state(rows: list[Mapping[str, Any]]) -> None:
    expected_order = {code: order for order, code in enumerate(EXPECTED_PROGRAMME_CODES)}
    if any(
        row["status"] != "pending"
        or row["posting_code"] is not None
        or row["display_order"] != expected_order[str(row["programme_code"])]
        for row in rows
    ):
        raise RuntimeError("TTSH mapping rows are not in the expected Stage 1 pending state")


def _validate_stage_two_state(
    connection: Any,
    *,
    active_mapping: dict[str, str],
    inactive_programmes: set[str],
) -> None:
    rows = _load_ttsh_rows(connection)
    expected_order = {code: order for order, code in enumerate(EXPECTED_PROGRAMME_CODES)}
    actual = {str(row["programme_code"]): row for row in rows}

    if len(rows) != 28 or set(actual) != set(EXPECTED_PROGRAMME_CODES):
        raise RuntimeError("TTSH Stage 2 verification found an unexpected row set")
    for programme_code, posting_code in active_mapping.items():
        row = actual[programme_code]
        if row["status"] != "active" or row["posting_code"] != posting_code:
            raise RuntimeError(f"TTSH active mapping verification failed for {programme_code}")
    for programme_code in inactive_programmes:
        row = actual[programme_code]
        if row["status"] != "inactive" or row["posting_code"] is not None:
            raise RuntimeError(f"TTSH inactive mapping verification failed for {programme_code}")
    if any(
        row["display_order"] != expected_order[programme_code]
        for programme_code, row in actual.items()
    ):
        raise RuntimeError("TTSH mapping display order verification failed")

    counts = {
        str(row["status"]): int(row["row_count"])
        for row in connection.execute(
            sa.text(
                """
                SELECT status, count(*) AS row_count
                FROM programme_institution_posting_map
                WHERE institution_code = :institution_code
                GROUP BY status
                """
            ),
            {"institution_code": INSTITUTION_CODE},
        )
        .mappings()
        .all()
    }
    active_null_count = connection.execute(
        sa.text(
            """
            SELECT count(*)
            FROM programme_institution_posting_map
            WHERE institution_code = :institution_code
              AND status = 'active'
              AND posting_code IS NULL
            """
        ),
        {"institution_code": INSTITUTION_CODE},
    ).scalar_one()
    if counts != {"active": 24, "inactive": 4} or active_null_count != 0:
        raise RuntimeError("TTSH Stage 2 status-count verification failed")


def upgrade() -> None:
    active_mapping, inactive_programmes = _validate_configuration()
    connection = op.get_bind()
    stage_one_rows = _validate_database_baseline(connection)
    _validate_stage_one_state(stage_one_rows)
    other_institutions_before = _snapshot_other_institutions(connection)
    expected_order = {code: order for order, code in enumerate(EXPECTED_PROGRAMME_CODES)}

    update_statement = sa.text(
        """
        UPDATE programme_institution_posting_map
        SET posting_code = :posting_code,
            status = :status,
            display_order = :display_order,
            updated_at = now()
        WHERE programme_code = :programme_code
          AND institution_code = :institution_code
        """
    )
    for programme_code in EXPECTED_PROGRAMME_CODES:
        is_active = programme_code in active_mapping
        result = connection.execute(
            update_statement,
            {
                "posting_code": active_mapping.get(programme_code),
                "status": "active" if is_active else "inactive",
                "display_order": expected_order[programme_code],
                "programme_code": programme_code,
                "institution_code": INSTITUTION_CODE,
            },
        )
        if result.rowcount != 1:
            raise RuntimeError(f"TTSH mapping update affected {result.rowcount} rows")

    _validate_stage_two_state(
        connection,
        active_mapping=active_mapping,
        inactive_programmes=inactive_programmes,
    )
    if _snapshot_other_institutions(connection) != other_institutions_before:
        raise RuntimeError("Stage 2 migration changed mappings for another institution")


def downgrade() -> None:
    active_mapping, inactive_programmes = _validate_configuration()
    connection = op.get_bind()
    _validate_database_baseline(connection)
    _validate_stage_two_state(
        connection,
        active_mapping=active_mapping,
        inactive_programmes=inactive_programmes,
    )
    other_institutions_before = _snapshot_other_institutions(connection)
    expected_order = {code: order for order, code in enumerate(EXPECTED_PROGRAMME_CODES)}

    update_statement = sa.text(
        """
        UPDATE programme_institution_posting_map
        SET posting_code = NULL,
            status = 'pending',
            display_order = :display_order,
            updated_at = now()
        WHERE programme_code = :programme_code
          AND institution_code = :institution_code
        """
    )
    for programme_code in EXPECTED_PROGRAMME_CODES:
        result = connection.execute(
            update_statement,
            {
                "display_order": expected_order[programme_code],
                "programme_code": programme_code,
                "institution_code": INSTITUTION_CODE,
            },
        )
        if result.rowcount != 1:
            raise RuntimeError(f"TTSH mapping downgrade affected {result.rowcount} rows")

    stage_one_rows = _validate_database_baseline(connection)
    _validate_stage_one_state(stage_one_rows)
    if _snapshot_other_institutions(connection) != other_institutions_before:
        raise RuntimeError("Stage 2 downgrade changed mappings for another institution")
