"""Add resident posting day-part support.

Revision ID: 20260508_000002
Revises: 20260505_000001
Create Date: 2026-05-08 00:00:02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260508_000002"
down_revision = "20260505_000001"
branch_labels = None
depends_on = None


POSTING_CODE_SEED_ROWS = [
    "A",
    "B",
    "CGHAnaes",
    "DPPallia",
    "DoverHospice",
    "IMHGrPsyc",
    "KKHAccEmg",
    "KKHPaedia",
    "KKHReprod",
    "KTPHAccEmg",
    "KTPHAnaes",
    "KTPHCardio",
    "KTPHGenMed",
    "KTPHGerMed",
    "NA",
    "NHGPlyNHGPly",
    "NNINeuRad",
    "NUHEndocr",
    "NUHGas",
    "SGHEndocr",
    "SGHNuclea",
    "TTSHCardio",
    "TTSHDiagRd",
    "TTSHEndocr",
    "TTSHEmgMed",
    "TTSHGas",
    "TTSHGenMed",
    "TTSHGerMed",
    "TTSHOphtha",
    "TTSHOtolar",
    "TTSHPsychi",
    "TTSHPallia",
    "TTSHLabMed",
    "TTSHDiagRd & NNINeuRad",
    "TTSHOtolar & TTSHOphtha",
    "TTSHOtolar & TTSHCardio",
    "IMHGrPsyc & TTSHPsychi",
    "CGHAnaes & TTSHPallia",
    "SGHEndocr & TTSHEndocr",
    "NUHEndocr & TTSHEndocr",
    "TTSHEndocr & TTSHLabMed",
    "TTSHEndocr & SGHNuclea",
    "TTSHEndocr & KKHPaedia",
    "TTSHEndocr & KKHReprod",
]


MULTI_POSTING_RULE_SEED_ROWS = [
    {
        "programme_code": "FM",
        "posting_code_1": "KTPHGenMed",
        "posting_code_2": None,
        "rule_type": "main_posting",
        "combined_label": None,
        "main_posting_code": "KTPHGenMed",
        "exclusion_code": "NHGPlyNHGPly",
    },
    {
        "programme_code": "FM",
        "posting_code_1": "TTSHGenMed",
        "posting_code_2": None,
        "rule_type": "main_posting",
        "combined_label": None,
        "main_posting_code": "TTSHGenMed",
        "exclusion_code": "NHGPlyNHGPly",
    },
    {
        "programme_code": "FM",
        "posting_code_1": "KTPHGerMed",
        "posting_code_2": None,
        "rule_type": "main_posting",
        "combined_label": None,
        "main_posting_code": "KTPHGerMed",
        "exclusion_code": "NHGPlyNHGPly",
    },
    {
        "programme_code": "FM",
        "posting_code_1": "TTSHGerMed",
        "posting_code_2": None,
        "rule_type": "main_posting",
        "combined_label": None,
        "main_posting_code": "TTSHGerMed",
        "exclusion_code": "NHGPlyNHGPly",
    },
    {
        "programme_code": "FM",
        "posting_code_1": "KTPHAccEmg",
        "posting_code_2": None,
        "rule_type": "main_posting",
        "combined_label": None,
        "main_posting_code": "KTPHAccEmg",
        "exclusion_code": "NHGPlyNHGPly",
    },
    {
        "programme_code": "FM",
        "posting_code_1": "KKHAccEmg",
        "posting_code_2": None,
        "rule_type": "main_posting",
        "combined_label": None,
        "main_posting_code": "KKHAccEmg",
        "exclusion_code": "NHGPlyNHGPly",
    },
    {
        "programme_code": "FM",
        "posting_code_1": "TTSHEmgMed",
        "posting_code_2": None,
        "rule_type": "main_posting",
        "combined_label": None,
        "main_posting_code": "TTSHEmgMed",
        "exclusion_code": "NHGPlyNHGPly",
    },
    {
        "programme_code": "ANAES",
        "posting_code_1": "KTPHAnaes",
        "posting_code_2": "KTPHCardio",
        "rule_type": "main_posting",
        "combined_label": None,
        "main_posting_code": "KTPHAnaes",
        "exclusion_code": None,
    },
    {
        "programme_code": "EM",
        "posting_code_1": "TTSHDiagRd",
        "posting_code_2": "NNINeuRad",
        "rule_type": "combine",
        "combined_label": "TTSHDiagRd & NNINeuRad",
        "main_posting_code": None,
        "exclusion_code": None,
    },
    {
        "programme_code": "EM",
        "posting_code_1": "TTSHOtolar",
        "posting_code_2": "TTSHOphtha",
        "rule_type": "combine",
        "combined_label": "TTSHOtolar & TTSHOphtha",
        "main_posting_code": None,
        "exclusion_code": None,
    },
    {
        "programme_code": "EM",
        "posting_code_1": "TTSHOtolar",
        "posting_code_2": "TTSHCardio",
        "rule_type": "combine",
        "combined_label": "TTSHOtolar & TTSHCardio",
        "main_posting_code": None,
        "exclusion_code": None,
    },
    {
        "programme_code": "GERI",
        "posting_code_1": "IMHGrPsyc",
        "posting_code_2": "TTSHPsychi",
        "rule_type": "combine",
        "combined_label": "IMHGrPsyc & TTSHPsychi",
        "main_posting_code": None,
        "exclusion_code": None,
    },
    {
        "programme_code": "ANAES",
        "posting_code_1": "CGHAnaes",
        "posting_code_2": "DPPallia",
        "rule_type": "combine",
        "combined_label": "CGHAnaes & TTSHPallia",
        "main_posting_code": None,
        "exclusion_code": None,
    },
    {
        "programme_code": "ANAES",
        "posting_code_1": "CGHAnaes",
        "posting_code_2": "DoverHospice",
        "rule_type": "combine",
        "combined_label": "CGHAnaes & TTSHPallia",
        "main_posting_code": None,
        "exclusion_code": None,
    },
    {
        "programme_code": "ANAES",
        "posting_code_1": "CGHAnaes",
        "posting_code_2": "NA",
        "rule_type": "combine",
        "combined_label": "CGHAnaes & TTSHPallia",
        "main_posting_code": None,
        "exclusion_code": None,
    },
    {
        "programme_code": "ANAES",
        "posting_code_1": "DPPallia",
        "posting_code_2": "NA",
        "rule_type": "combine",
        "combined_label": "CGHAnaes & TTSHPallia",
        "main_posting_code": None,
        "exclusion_code": None,
    },
    {
        "programme_code": "ENDO",
        "posting_code_1": "SGHEndocr",
        "posting_code_2": "TTSHEndocr",
        "rule_type": "combine",
        "combined_label": "SGHEndocr & TTSHEndocr",
        "main_posting_code": None,
        "exclusion_code": None,
    },
    {
        "programme_code": "ENDO",
        "posting_code_1": "NUHEndocr",
        "posting_code_2": "TTSHEndocr",
        "rule_type": "combine",
        "combined_label": "NUHEndocr & TTSHEndocr",
        "main_posting_code": None,
        "exclusion_code": None,
    },
    {
        "programme_code": "ENDO",
        "posting_code_1": "TTSHEndocr",
        "posting_code_2": "TTSHLabMed",
        "rule_type": "combine",
        "combined_label": "TTSHEndocr & TTSHLabMed",
        "main_posting_code": None,
        "exclusion_code": None,
    },
    {
        "programme_code": "ENDO",
        "posting_code_1": "TTSHEndocr",
        "posting_code_2": "SGHNuclea",
        "rule_type": "combine",
        "combined_label": "TTSHEndocr & SGHNuclea",
        "main_posting_code": None,
        "exclusion_code": None,
    },
    {
        "programme_code": "ENDO",
        "posting_code_1": "TTSHEndocr",
        "posting_code_2": "KKHPaedia",
        "rule_type": "combine",
        "combined_label": "TTSHEndocr & KKHPaedia",
        "main_posting_code": None,
        "exclusion_code": None,
    },
    {
        "programme_code": "ENDO",
        "posting_code_1": "TTSHEndocr",
        "posting_code_2": "KKHReprod",
        "rule_type": "combine",
        "combined_label": "TTSHEndocr & KKHReprod",
        "main_posting_code": None,
        "exclusion_code": None,
    },
    {
        "programme_code": "GASTRO",
        "posting_code_1": "TTSHGas",
        "posting_code_2": "NUHGas",
        "rule_type": "half_month",
        "combined_label": None,
        "main_posting_code": None,
        "exclusion_code": None,
    },
]


def _seed_multi_posting_rules() -> None:
    bind = op.get_bind()
    for code in POSTING_CODE_SEED_ROWS:
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

    for row in MULTI_POSTING_RULE_SEED_ROWS:
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
            row,
        )


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            ALTER TABLE resident_postings
            ADD COLUMN IF NOT EXISTS day_part VARCHAR(2)
            """
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'ck_resident_postings_day_part'
                    AND conrelid = 'resident_postings'::regclass
                ) THEN
                    ALTER TABLE resident_postings
                    ADD CONSTRAINT ck_resident_postings_day_part
                    CHECK (day_part IS NULL OR day_part IN ('AM', 'PM'));
                END IF;
            END $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE resident_postings
            DROP CONSTRAINT IF EXISTS uq_resident_postings_period_phase
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE resident_postings
            ADD CONSTRAINT uq_resident_postings_period_phase
            UNIQUE NULLS NOT DISTINCT (
                resident_id,
                reporting_period_id,
                start_date,
                day_part
            )
            """
        )
    )
    _seed_multi_posting_rules()


def downgrade() -> None:
    bind = op.get_bind()
    for row in MULTI_POSTING_RULE_SEED_ROWS:
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
            row,
        )
    op.execute(
        sa.text(
            """
            ALTER TABLE resident_postings
            DROP CONSTRAINT IF EXISTS uq_resident_postings_period_phase
            """
        )
    )
    op.create_unique_constraint(
        "uq_resident_postings_period_phase",
        "resident_postings",
        ["resident_id", "reporting_period_id", "start_date"],
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE resident_postings
            DROP CONSTRAINT IF EXISTS ck_resident_postings_day_part
            """
        )
    )
    op.drop_column("resident_postings", "day_part")
