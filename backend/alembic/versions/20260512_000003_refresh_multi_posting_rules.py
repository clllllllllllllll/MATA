"""Refresh multi-posting rules from updated workbook.

Revision ID: 20260512_000003
Revises: 20260508_000002
Create Date: 2026-05-12 00:00:03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260512_000003"
down_revision = "20260508_000002"
branch_labels = None
depends_on = None


WORKBOOK_RULE_ROWS = [
    # Main posting sheet.
    ("FM", "KTPHGenMed", None, "main_posting", None, "KTPHGenMed", "NHGPlyNHGPly"),
    ("FM", "TTSHGenMed", None, "main_posting", None, "TTSHGenMed", "NHGPlyNHGPly"),
    ("FM", "KTPHGerMed", None, "main_posting", None, "KTPHGerMed", "NHGPlyNHGPly"),
    ("FM", "TTSHGerMed", None, "main_posting", None, "TTSHGerMed", "NHGPlyNHGPly"),
    ("FM", "KTPHAccEmg", None, "main_posting", None, "KTPHAccEmg", "NHGPlyNHGPly"),
    ("FM", "KKHAccEmg", None, "main_posting", None, "KKHAccEmg", "NHGPlyNHGPly"),
    ("FM", "TTSHEmgMed", None, "main_posting", None, "TTSHEmgMed", "NHGPlyNHGPly"),
    ("FM", "NUHPaedia", None, "main_posting", None, "NUHPaedia", "NHGPlyNHGPly"),
    ("FM", "WHGerMed", None, "main_posting", None, "WHGerMed", "NHGPlyNHGPly"),
    ("FM", "WHEmgMed", None, "main_posting", None, "WHEmgMed", "NHGPlyNHGPly"),
    ("FM", "NUHObsGyn", None, "main_posting", None, "NUHObsGyn", "NHGPlyNHGPly"),
    ("FM", "KKHObsGyn", None, "main_posting", None, "KKHObsGyn", "NHGPlyNHGPly"),
    # To combine sheet.
    ("EM", "TTSHDiagRd", "NNINeuRad", "combine", "TTSHDiagRd & NNINeuRad", None, None),
    ("EM", "TTSHOtolar", "TTSHOphtha", "combine", "TTSHOtolar & TTSHOphtha", None, None),
    ("EM", "TTSHOtolar", "TTSHCardio", "combine", "TTSHOtolar & TTSHCardio", None, None),
    ("GERI", "IMHGrPsyc", "TTSHPsychi", "combine", "IMHGrPsyc & TTSHPsychi", None, None),
    ("ENDO", "SGHEndocr", "TTSHEndocr", "combine", "SGHEndocr & TTSHEndocr", None, None),
    ("ENDO", "NUHEndocr", "TTSHEndocr", "combine", "NUHEndocr & TTSHEndocr", None, None),
    ("ENDO", "TTSHEndocr", "TTSHLabMed", "combine", "TTSHEndocr & TTSHLabMed", None, None),
    ("ENDO", "TTSHEndocr", "SGHNuclea", "combine", "TTSHEndocr & SGHNuclea", None, None),
    ("ENDO", "TTSHEndocr", "KKHPaedia", "combine", "TTSHEndocr & KKHPaedia", None, None),
    ("ENDO", "TTSHEndocr", "KKHReprod", "combine", "TTSHEndocr & KKHReprod", None, None),
    ("ANAES", "KTPHAnaes", "KTPHCardio", "combine", "Anaes Elective", None, None),
    ("ANAES", "DPHPallia", "TTSHAnaes", "combine", "Anaes Elective", None, None),
    ("ANAES", "TTSHCardio", "TTSHAnaes", "combine", "Anaes Elective", None, None),
    ("ANAES", "KTPHCardio", "KTPHAnaes", "combine", "Anaes Elective", None, None),
    # Half month posting sheet.
    ("GASTRO", "TTSHGas", "NUHGas", "half_month", None, None, None),
]


OBSOLETE_SEED_RULE_ROWS = [
    ("ANAES", "KTPHAnaes", "KTPHCardio", "main_posting", None, "KTPHAnaes", None),
    ("ANAES", "CGHAnaes", "DPPallia", "combine", "CGHAnaes & TTSHPallia", None, None),
    ("ANAES", "CGHAnaes", "DoverHospice", "combine", "CGHAnaes & TTSHPallia", None, None),
    ("ANAES", "CGHAnaes", "NA", "combine", "CGHAnaes & TTSHPallia", None, None),
    ("ANAES", "DPPallia", "NA", "combine", "CGHAnaes & TTSHPallia", None, None),
]


def _row_dict(row: tuple[str, str, str | None, str, str | None, str | None, str | None]) -> dict[str, str | None]:
    return {
        "programme_code": row[0],
        "posting_code_1": row[1],
        "posting_code_2": row[2],
        "rule_type": row[3],
        "combined_label": row[4],
        "main_posting_code": row[5],
        "exclusion_code": row[6],
    }


def _posting_codes_from_rows() -> list[str]:
    codes: set[str] = set()
    for row in WORKBOOK_RULE_ROWS:
        for value in (row[1], row[2], row[4], row[5], row[6]):
            if value:
                codes.add(value)
    return sorted(codes)


def upgrade() -> None:
    bind = op.get_bind()

    for code in _posting_codes_from_rows():
        bind.execute(
            sa.text(
                """
                INSERT INTO posting_codes (code)
                VALUES (:code)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"code": code},
        )

    # Remove only exact legacy seed rows that the updated workbook supersedes.
    # The output-column predicates avoid deleting rows that PCs have edited.
    for row in OBSOLETE_SEED_RULE_ROWS:
        bind.execute(
            sa.text(
                """
                DELETE FROM multi_posting_rules
                WHERE programme_code = :programme_code
                  AND posting_code_1 = :posting_code_1
                  AND posting_code_2 IS NOT DISTINCT FROM :posting_code_2
                  AND rule_type = :rule_type
                  AND combined_label IS NOT DISTINCT FROM :combined_label
                  AND main_posting_code IS NOT DISTINCT FROM :main_posting_code
                  AND exclusion_code IS NOT DISTINCT FROM :exclusion_code
                """
            ),
            _row_dict(row),
        )

    for row in WORKBOOK_RULE_ROWS:
        bind.execute(
            sa.text(
                """
                UPDATE multi_posting_rules
                SET combined_label = :combined_label,
                    main_posting_code = :main_posting_code,
                    exclusion_code = :exclusion_code
                WHERE programme_code = :programme_code
                  AND posting_code_1 = :posting_code_1
                  AND posting_code_2 IS NOT DISTINCT FROM :posting_code_2
                  AND rule_type = :rule_type
                """
            ),
            _row_dict(row),
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO multi_posting_rules (
                    programme_code,
                    posting_code_1,
                    posting_code_2,
                    rule_type,
                    combined_label,
                    main_posting_code,
                    exclusion_code
                )
                SELECT
                    :programme_code,
                    :posting_code_1,
                    :posting_code_2,
                    :rule_type,
                    :combined_label,
                    :main_posting_code,
                    :exclusion_code
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM multi_posting_rules
                    WHERE programme_code = :programme_code
                      AND posting_code_1 = :posting_code_1
                      AND posting_code_2 IS NOT DISTINCT FROM :posting_code_2
                      AND rule_type = :rule_type
                )
                """
            ),
            _row_dict(row),
        )


def downgrade() -> None:
    bind = op.get_bind()
    for row in WORKBOOK_RULE_ROWS:
        bind.execute(
            sa.text(
                """
                DELETE FROM multi_posting_rules
                WHERE programme_code = :programme_code
                  AND posting_code_1 = :posting_code_1
                  AND posting_code_2 IS NOT DISTINCT FROM :posting_code_2
                  AND rule_type = :rule_type
                """
            ),
            _row_dict(row),
        )
