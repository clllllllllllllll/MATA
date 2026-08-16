"""seed permanent Department Secretary Teaching Name programme pools

Revision ID: 20260816_000044
Revises: 20260816_000043
Create Date: 2026-08-16
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260816_000044"
down_revision = "20260816_000043"
branch_labels = None
depends_on = None


# This is the independent Department Secretary ownership configuration.  It is
# intentionally not derived from users, programme_institution_posting_map, TTF
# rows, resident postings, or posting-code text.
DEPARTMENT_PROGRAMME_POOLS = (
    ("AIM", "TTSHGenMed"),
    ("ANAES", "TTSHAnaes"),
    ("CARDIO", "TTSHCardio"),
    ("DERM", "NSCDermat"),
    ("DR", "TTSHDiagRd"),
    ("EM", "TTSHEmgMed"),
    ("ENDO", "TTSHEndocr"),
    ("ENT", "TTSHOtolar"),
    ("EYE", "TTSHOphtha"),
    ("FM", "NHGPlyNHGPly"),
    ("GASTRO", "TTSHGas"),
    ("GERI", "TTSHGerMed"),
    ("GS", "TTSHGenSrg"),
    ("ID", "TTSHInfect"),
    ("IM", "TTSHGenMed"),
    ("MEDONCO", "TTSHMedOnc"),
    ("ORTHO", "TTSHOrtSrg"),
    ("PATH", "TTSHLabMed"),
    ("PSY", "TTSHPsychi"),
    ("REHAB", "TTSHRehabi"),
    ("RENAL", "TTSHRenal"),
    ("RESPI", "TTSHRespir"),
    ("RHEUM", "TTSHRheuma"),
    ("SPORTSMED", "TTSHOrtSrg(Sports)"),
    ("SIG", "TTSHGenSrg"),
    ("URO", "TTSHUrolog"),
    ("MICROB", "TTSHLabMed"),
    ("PALLMED", "TTSHPallia"),
)

SPORTS_MEDICINE_POSTING_CODE = "TTSHOrtSrg(Sports)"


def _validate_configuration() -> tuple[tuple[str, str], ...]:
    rows = tuple(DEPARTMENT_PROGRAMME_POOLS)
    programme_codes = [programme_code for programme_code, _posting_code in rows]
    posting_codes = [posting_code for _programme_code, posting_code in rows]
    if len(rows) != 28 or len(set(programme_codes)) != 28:
        raise RuntimeError(
            "Department Secretary pool baseline must contain exactly 28 unique programmes"
        )
    if len(set(rows)) != len(rows):
        raise RuntimeError("Department Secretary pool baseline contains a duplicate pair")
    if any(
        not value or value != value.strip()
        for row in rows
        for value in row
    ):
        raise RuntimeError(
            "Department Secretary pool baseline contains a blank or untrimmed value"
        )
    if len(set(posting_codes)) != 25:
        raise RuntimeError(
            "Department Secretary pool baseline must contain exactly 25 department postings"
        )
    return rows


def _ensure_sports_medicine_posting(connection: Any) -> None:
    existing_count = int(
        connection.scalar(
            sa.text("SELECT count(*) FROM posting_codes WHERE code = :posting_code"),
            {"posting_code": SPORTS_MEDICINE_POSTING_CODE},
        )
        or 0
    )
    if existing_count == 1:
        return
    if existing_count != 0:
        raise RuntimeError("Sports Medicine posting code is not unique")
    result = connection.execute(
        sa.text(
            """
            INSERT INTO posting_codes (code)
            VALUES (:posting_code)
            """
        ),
        {"posting_code": SPORTS_MEDICINE_POSTING_CODE},
    )
    if result.rowcount != 1:
        raise RuntimeError("Sports Medicine posting prerequisite insert failed")


def _validate_references(connection: Any, rows: tuple[tuple[str, str], ...]) -> None:
    configured_programmes = {programme_code for programme_code, _ in rows}
    database_programmes = set(
        connection.execute(sa.text("SELECT code FROM programmes")).scalars()
    )
    if database_programmes != configured_programmes:
        missing = sorted(database_programmes - configured_programmes)
        unknown = sorted(configured_programmes - database_programmes)
        raise RuntimeError(
            "Department Secretary pool programme baseline mismatch; "
            f"missing configuration={missing}, unknown configuration={unknown}"
        )

    configured_postings = {posting_code for _, posting_code in rows}
    existing_postings = set(
        connection.execute(
            sa.text("SELECT code FROM posting_codes WHERE code = ANY(:posting_codes)"),
            {"posting_codes": sorted(configured_postings)},
        ).scalars()
    )
    if existing_postings != configured_postings:
        missing = sorted(configured_postings - existing_postings)
        raise RuntimeError(
            "Department Secretary pool posting codes are missing: " + ", ".join(missing)
        )


def _validate_seeded_rows(connection: Any, rows: tuple[tuple[str, str], ...]) -> None:
    actual = {
        (str(row["programme_code"]), str(row["posting_code"]))
        for row in connection.execute(
            sa.text(
                """
                SELECT programme_code, posting_code
                FROM secretary_programme_pools
                WHERE is_active = true
                  AND can_manage_teaching_names = true
                """
            )
        ).mappings()
    }
    expected = set(rows)
    if not expected.issubset(actual):
        missing = sorted(expected - actual)
        raise RuntimeError(
            f"Department Secretary pool seed verification failed; missing={missing}"
        )


def upgrade() -> None:
    rows = _validate_configuration()
    connection = op.get_bind()
    _ensure_sports_medicine_posting(connection)
    _validate_references(connection, rows)

    statement = sa.text(
        """
        INSERT INTO secretary_programme_pools (
            posting_code,
            programme_code,
            is_active,
            can_manage_teaching_names
        ) VALUES (
            :posting_code,
            :programme_code,
            true,
            true
        )
        ON CONFLICT (posting_code, programme_code) DO UPDATE
        SET is_active = true,
            can_manage_teaching_names = true,
            updated_at = now()
        WHERE NOT secretary_programme_pools.is_active
           OR NOT secretary_programme_pools.can_manage_teaching_names
        """
    )
    for programme_code, posting_code in rows:
        connection.execute(
            statement,
            {
                "posting_code": posting_code,
                "programme_code": programme_code,
            },
        )

    _validate_seeded_rows(connection, rows)


def downgrade() -> None:
    # Department ownership is durable configuration, not account/test data.
    # Removing it would revoke valid Secretary authority, so a revision-only
    # downgrade intentionally retains the idempotent baseline.
    pass
