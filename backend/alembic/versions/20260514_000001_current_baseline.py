"""Current clean baseline schema and seed data.

Revision ID: 20260514_000001
Revises:
Create Date: 2026-05-14 00:00:01
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260514_000001"
down_revision = None
branch_labels = None
depends_on = None


PROGRAMME_SEED_ROWS = [
    {"code": "AIM", "name": "Advanced Internal Medicine", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "ANAES", "name": "Anaesthesiology", "r_year_required": True, "is_subspecialty": False, "rdb_alias": None},
    {"code": "CARDIO", "name": "Cardiology", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "DERM", "name": "Dermatology", "r_year_required": True, "is_subspecialty": False, "rdb_alias": None},
    {"code": "DR", "name": "Diagnostic Radiology", "r_year_required": True, "is_subspecialty": False, "rdb_alias": None},
    {"code": "EM", "name": "Emergency Medicine", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "ENDO", "name": "Endocrinology", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "ENT", "name": "Otorhinolaryngology", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "EYE", "name": "Ophthalmology", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "FM", "name": "Family Medicine", "r_year_required": True, "is_subspecialty": False, "rdb_alias": None},
    {"code": "GASTRO", "name": "Gastroenterology", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "GERI", "name": "Geriatric Medicine", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "GS", "name": "General Surgery", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "ID", "name": "Infectious Diseases", "r_year_required": False, "is_subspecialty": False, "rdb_alias": "Infectious Disease"},
    {"code": "IM", "name": "Internal Medicine", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "MEDONCO", "name": "Medical Oncology", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "ORTHO", "name": "Orthopaedic Surgery", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "PATH", "name": "Pathology", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "PSY", "name": "Psychiatry", "r_year_required": True, "is_subspecialty": False, "rdb_alias": None},
    {"code": "REHAB", "name": "Rehabilitation Medicine", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "RENAL", "name": "Renal Medicine", "r_year_required": False, "is_subspecialty": False, "rdb_alias": "Renal Medicine Extended"},
    {"code": "RESPI", "name": "Respiratory Medicine", "r_year_required": True, "is_subspecialty": False, "rdb_alias": None},
    {"code": "RHEUM", "name": "Rheumatology", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "SPORTSMED", "name": "Sports Medicine", "r_year_required": False, "is_subspecialty": True, "rdb_alias": None},
    {"code": "SIG", "name": "Surgery-In-General", "r_year_required": False, "is_subspecialty": False, "rdb_alias": "Surgery-in-General"},
    {"code": "URO", "name": "Urology", "r_year_required": False, "is_subspecialty": False, "rdb_alias": None},
    {"code": "MICROB", "name": "Pathology (Microbiology)", "r_year_required": False, "is_subspecialty": False, "rdb_alias": "Microbiology"},
    {"code": "PALLMED", "name": "Palliative Medicine", "r_year_required": False, "is_subspecialty": True, "rdb_alias": None},
]

LOA_TYPE_SEED_ROWS = [
    {"code": "Annual Leaves", "description": None},
    {"code": "Childcare Leave", "description": None},
    {"code": "Compassionate Leave", "description": None},
    {"code": "Family Care Leave", "description": None},
    {"code": "Hospitalisation Leave", "description": None},
    {"code": "Marriage Leave", "description": None},
    {"code": "Maternity Leave", "description": None},
    {"code": "Medical Leave", "description": None},
    {"code": "National Service (NS)", "description": None},
    {"code": "No-Pay-Leave", "description": None},
    {"code": "Paternity Leave", "description": None},
    {"code": "Training Leave", "description": None},
    {"code": "Unrecorded Leave", "description": None},
    {"code": "Unpaid Infant Care Leave", "description": None},
]

POSTING_CODE_SEED_ROWS = [
    "A",
    "Anaes Elective",
    "B",
    "CGHAnaes",
    "CGHAnaes & TTSHPallia",
    "DPHPallia",
    "DPPallia",
    "DoverHospice",
    "IMHGrPsyc",
    "IMHGrPsyc & TTSHPsychi",
    "KKHAccEmg",
    "KKHObsGyn",
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
    "NUHEndocr & TTSHEndocr",
    "NUHGas",
    "NUHObsGyn",
    "NUHPaedia",
    "SGHEndocr",
    "SGHEndocr & TTSHEndocr",
    "SGHNuclea",
    "TTSHAnaes",
    "TTSHCardio",
    "TTSHDiagRd",
    "TTSHDiagRd & NNINeuRad",
    "TTSHEmgMed",
    "TTSHEndocr",
    "TTSHEndocr & KKHPaedia",
    "TTSHEndocr & KKHReprod",
    "TTSHEndocr & SGHNuclea",
    "TTSHEndocr & TTSHLabMed",
    "TTSHGas",
    "TTSHGenMed",
    "TTSHGerMed",
    "TTSHLabMed",
    "TTSHOphtha",
    "TTSHOtolar",
    "TTSHOtolar & TTSHCardio",
    "TTSHOtolar & TTSHOphtha",
    "TTSHPallia",
    "TTSHPsychi",
    "WHEmgMed",
    "WHGerMed",
]

MULTI_POSTING_RULE_SEED_ROWS = [
    {"programme_code": "FM", "posting_code_1": "KTPHGenMed", "posting_code_2": None, "rule_type": "main_posting", "combined_label": None, "main_posting_code": "KTPHGenMed", "exclusion_code": "NHGPlyNHGPly"},
    {"programme_code": "FM", "posting_code_1": "TTSHGenMed", "posting_code_2": None, "rule_type": "main_posting", "combined_label": None, "main_posting_code": "TTSHGenMed", "exclusion_code": "NHGPlyNHGPly"},
    {"programme_code": "FM", "posting_code_1": "KTPHGerMed", "posting_code_2": None, "rule_type": "main_posting", "combined_label": None, "main_posting_code": "KTPHGerMed", "exclusion_code": "NHGPlyNHGPly"},
    {"programme_code": "FM", "posting_code_1": "TTSHGerMed", "posting_code_2": None, "rule_type": "main_posting", "combined_label": None, "main_posting_code": "TTSHGerMed", "exclusion_code": "NHGPlyNHGPly"},
    {"programme_code": "FM", "posting_code_1": "KTPHAccEmg", "posting_code_2": None, "rule_type": "main_posting", "combined_label": None, "main_posting_code": "KTPHAccEmg", "exclusion_code": "NHGPlyNHGPly"},
    {"programme_code": "FM", "posting_code_1": "KKHAccEmg", "posting_code_2": None, "rule_type": "main_posting", "combined_label": None, "main_posting_code": "KKHAccEmg", "exclusion_code": "NHGPlyNHGPly"},
    {"programme_code": "FM", "posting_code_1": "TTSHEmgMed", "posting_code_2": None, "rule_type": "main_posting", "combined_label": None, "main_posting_code": "TTSHEmgMed", "exclusion_code": "NHGPlyNHGPly"},
    {"programme_code": "FM", "posting_code_1": "NUHPaedia", "posting_code_2": None, "rule_type": "main_posting", "combined_label": None, "main_posting_code": "NUHPaedia", "exclusion_code": "NHGPlyNHGPly"},
    {"programme_code": "FM", "posting_code_1": "WHGerMed", "posting_code_2": None, "rule_type": "main_posting", "combined_label": None, "main_posting_code": "WHGerMed", "exclusion_code": "NHGPlyNHGPly"},
    {"programme_code": "FM", "posting_code_1": "WHEmgMed", "posting_code_2": None, "rule_type": "main_posting", "combined_label": None, "main_posting_code": "WHEmgMed", "exclusion_code": "NHGPlyNHGPly"},
    {"programme_code": "FM", "posting_code_1": "NUHObsGyn", "posting_code_2": None, "rule_type": "main_posting", "combined_label": None, "main_posting_code": "NUHObsGyn", "exclusion_code": "NHGPlyNHGPly"},
    {"programme_code": "FM", "posting_code_1": "KKHObsGyn", "posting_code_2": None, "rule_type": "main_posting", "combined_label": None, "main_posting_code": "KKHObsGyn", "exclusion_code": "NHGPlyNHGPly"},
    {"programme_code": "EM", "posting_code_1": "TTSHDiagRd", "posting_code_2": "NNINeuRad", "rule_type": "combine", "combined_label": "TTSHDiagRd & NNINeuRad", "main_posting_code": None, "exclusion_code": None},
    {"programme_code": "EM", "posting_code_1": "TTSHOtolar", "posting_code_2": "TTSHOphtha", "rule_type": "combine", "combined_label": "TTSHOtolar & TTSHOphtha", "main_posting_code": None, "exclusion_code": None},
    {"programme_code": "EM", "posting_code_1": "TTSHOtolar", "posting_code_2": "TTSHCardio", "rule_type": "combine", "combined_label": "TTSHOtolar & TTSHCardio", "main_posting_code": None, "exclusion_code": None},
    {"programme_code": "GERI", "posting_code_1": "IMHGrPsyc", "posting_code_2": "TTSHPsychi", "rule_type": "combine", "combined_label": "IMHGrPsyc & TTSHPsychi", "main_posting_code": None, "exclusion_code": None},
    {"programme_code": "ENDO", "posting_code_1": "SGHEndocr", "posting_code_2": "TTSHEndocr", "rule_type": "combine", "combined_label": "SGHEndocr & TTSHEndocr", "main_posting_code": None, "exclusion_code": None},
    {"programme_code": "ENDO", "posting_code_1": "NUHEndocr", "posting_code_2": "TTSHEndocr", "rule_type": "combine", "combined_label": "NUHEndocr & TTSHEndocr", "main_posting_code": None, "exclusion_code": None},
    {"programme_code": "ENDO", "posting_code_1": "TTSHEndocr", "posting_code_2": "TTSHLabMed", "rule_type": "combine", "combined_label": "TTSHEndocr & TTSHLabMed", "main_posting_code": None, "exclusion_code": None},
    {"programme_code": "ENDO", "posting_code_1": "TTSHEndocr", "posting_code_2": "SGHNuclea", "rule_type": "combine", "combined_label": "TTSHEndocr & SGHNuclea", "main_posting_code": None, "exclusion_code": None},
    {"programme_code": "ENDO", "posting_code_1": "TTSHEndocr", "posting_code_2": "KKHPaedia", "rule_type": "combine", "combined_label": "TTSHEndocr & KKHPaedia", "main_posting_code": None, "exclusion_code": None},
    {"programme_code": "ENDO", "posting_code_1": "TTSHEndocr", "posting_code_2": "KKHReprod", "rule_type": "combine", "combined_label": "TTSHEndocr & KKHReprod", "main_posting_code": None, "exclusion_code": None},
    {"programme_code": "ANAES", "posting_code_1": "KTPHAnaes", "posting_code_2": "KTPHCardio", "rule_type": "combine", "combined_label": "Anaes Elective", "main_posting_code": None, "exclusion_code": None},
    {"programme_code": "ANAES", "posting_code_1": "DPHPallia", "posting_code_2": "TTSHAnaes", "rule_type": "combine", "combined_label": "Anaes Elective", "main_posting_code": None, "exclusion_code": None},
    {"programme_code": "ANAES", "posting_code_1": "TTSHCardio", "posting_code_2": "TTSHAnaes", "rule_type": "combine", "combined_label": "Anaes Elective", "main_posting_code": None, "exclusion_code": None},
    {"programme_code": "ANAES", "posting_code_1": "KTPHCardio", "posting_code_2": "KTPHAnaes", "rule_type": "combine", "combined_label": "Anaes Elective", "main_posting_code": None, "exclusion_code": None},
    {"programme_code": "GASTRO", "posting_code_1": "TTSHGas", "posting_code_2": "NUHGas", "rule_type": "half_month", "combined_label": None, "main_posting_code": None, "exclusion_code": None},
]


def _seed_programmes() -> None:
    programme_table = sa.table(
        "programmes",
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("r_year_required", sa.Boolean()),
        sa.column("is_subspecialty", sa.Boolean()),
        sa.column("rdb_alias", sa.String()),
    )
    op.bulk_insert(programme_table, PROGRAMME_SEED_ROWS)


def _seed_loa_types() -> None:
    loa_type_table = sa.table(
        "loa_types",
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
    )
    op.bulk_insert(loa_type_table, LOA_TYPE_SEED_ROWS)


def _seed_posting_codes() -> None:
    posting_code_table = sa.table(
        "posting_codes",
        sa.column("code", sa.String()),
    )
    op.bulk_insert(
        posting_code_table,
        [{"code": code} for code in POSTING_CODE_SEED_ROWS],
    )


def _seed_session_type_and_weekend_config(bind) -> None:
    session_type_table = sa.table(
        "session_types",
        sa.column("name", sa.String()),
        sa.column("duration_hours", sa.Numeric()),
        sa.column("duration_label", sa.String()),
    )
    op.bulk_insert(
        session_type_table,
        [
            {
                "name": "National Teaching [2h]",
                "duration_hours": Decimal("2.00"),
                "duration_label": "[2h]",
            },
            {
                "name": "National Didactics & Department Teaching [1h]",
                "duration_hours": Decimal("1.00"),
                "duration_label": "[1h]",
            },
        ],
    )

    global_session_type_table = sa.table(
        "global_session_types",
        sa.column("name", sa.String()),
        sa.column("duration_hours", sa.Numeric()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        global_session_type_table,
        [
            {
                "name": "Department Meeting [1h]",
                "duration_hours": Decimal("1.00"),
                "is_active": True,
            },
        ],
    )

    rows = bind.execute(
        sa.text(
            """
            SELECT id, name
            FROM session_types
            WHERE name IN (:national_teaching, :national_didactics)
            """
        ),
        {
            "national_teaching": "National Teaching [2h]",
            "national_didactics": "National Didactics & Department Teaching [1h]",
        },
    ).mappings()
    session_type_id_by_name = {row["name"]: row["id"] for row in rows}

    weekend_exceptions_table = sa.table(
        "weekend_exceptions",
        sa.column("programme_code", sa.String()),
        sa.column("posting_code", sa.String()),
        sa.column("day_type", sa.String()),
        sa.column("start_time_min", sa.Time()),
        sa.column("end_time_max", sa.Time()),
        sa.column("session_type_id", postgresql.UUID(as_uuid=True)),
        sa.column("session_name_pattern", sa.String()),
        sa.column("mutates_to_session_type_id", postgresql.UUID(as_uuid=True)),
        sa.column("adjusted_duration_hours", sa.Numeric()),
    )
    op.bulk_insert(
        weekend_exceptions_table,
        [
            {
                "programme_code": "URO",
                "posting_code": None,
                "day_type": "sat",
                "start_time_min": None,
                "end_time_max": None,
                "session_type_id": None,
                "session_name_pattern": "Urology National Teaching (Sat)",
                "mutates_to_session_type_id": None,
                "adjusted_duration_hours": None,
            },
            {
                "programme_code": "URO",
                "posting_code": None,
                "day_type": "sat",
                "start_time_min": None,
                "end_time_max": None,
                "session_type_id": session_type_id_by_name["National Teaching [2h]"],
                "session_name_pattern": None,
                "mutates_to_session_type_id": None,
                "adjusted_duration_hours": None,
            },
            {
                "programme_code": "DERM",
                "posting_code": None,
                "day_type": "sat",
                "start_time_min": None,
                "end_time_max": None,
                "session_type_id": None,
                "session_name_pattern": None,
                "mutates_to_session_type_id": None,
                "adjusted_duration_hours": None,
            },
            {
                "programme_code": "ORTHO",
                "posting_code": None,
                "day_type": "sat",
                "start_time_min": time(8, 30),
                "end_time_max": time(10, 30),
                "session_type_id": None,
                "session_name_pattern": None,
                "mutates_to_session_type_id": session_type_id_by_name[
                    "National Didactics & Department Teaching [1h]"
                ],
                "adjusted_duration_hours": Decimal("1.00"),
            },
        ],
    )


def _seed_multi_posting_rules() -> None:
    multi_posting_rules_table = sa.table(
        "multi_posting_rules",
        sa.column("programme_code", sa.String()),
        sa.column("posting_code_1", sa.String()),
        sa.column("posting_code_2", sa.String()),
        sa.column("rule_type", sa.String()),
        sa.column("combined_label", sa.String()),
        sa.column("main_posting_code", sa.String()),
        sa.column("exclusion_code", sa.String()),
    )
    op.bulk_insert(multi_posting_rules_table, MULTI_POSTING_RULE_SEED_ROWS)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    op.create_table(
        "global_session_types",
        sa.Column("name", sa.String(length=100), nullable=False, unique=True),
        sa.Column("duration_hours", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_global_session_types_active_name", "global_session_types", ["name"], postgresql_where=sa.text("is_active = true"))

    op.create_table(
        "loa_types",
        sa.Column("code", sa.String(length=50), nullable=False, unique=True),
        sa.Column("description", sa.String(length=100), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "posting_codes",
        sa.Column("code", sa.String(length=50), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("institution", sa.String(length=50), nullable=True),
        sa.Column("department", sa.String(length=50), nullable=True),
        sa.Column("billing_dept", sa.String(length=50), nullable=True),
        sa.Column("is_emergency", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_posting_codes_institution_department", "posting_codes", ["institution", "department"])

    op.create_table(
        "programmes",
        sa.Column("code", sa.String(length=20), nullable=False, unique=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("classification", sa.String(length=20), nullable=True),
        sa.Column("r_year_required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_subspecialty", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rdb_alias", sa.String(length=100), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_programmes_rdb_alias", "programmes", ["rdb_alias"], postgresql_where=sa.text("rdb_alias IS NOT NULL"))

    op.create_table(
        "public_holidays",
        sa.Column("holiday_date", sa.Date(), nullable=False, unique=True),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("day_of_week", sa.String(length=10), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_public_holidays_year", "public_holidays", [sa.text("EXTRACT(YEAR FROM holiday_date)")])

    op.create_table(
        "reporting_periods",
        sa.Column("label", sa.String(length=30), nullable=False, unique=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False, server_default=sa.text("'open'")),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_reporting_periods_date_range", "reporting_periods", ["start_date", "end_date"])
    op.create_index("idx_reporting_periods_status", "reporting_periods", ["status"])

    op.create_table(
        "session_types",
        sa.Column("name", sa.String(length=100), nullable=False, unique=True),
        sa.Column("duration_hours", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column("duration_label", sa.String(length=10), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "event_series",
        sa.Column("posting_code", sa.String(length=50), sa.ForeignKey("posting_codes.code"), nullable=True),
        sa.Column("recurrence_pattern", sa.String(length=20), nullable=True),
        sa.Column("recurrence_interval", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("days_of_week", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("end_type", sa.String(length=10), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("end_after_count", sa.Integer(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_event_series_posting", "event_series", ["posting_code"])

    op.create_table(
        "multi_posting_rules",
        sa.Column("programme_code", sa.String(length=20), sa.ForeignKey("programmes.code"), nullable=False),
        sa.Column("posting_code_1", sa.String(length=50), sa.ForeignKey("posting_codes.code"), nullable=False),
        sa.Column("posting_code_2", sa.String(length=50), sa.ForeignKey("posting_codes.code"), nullable=True),
        sa.Column("rule_type", sa.String(length=20), nullable=False),
        sa.Column("combined_label", sa.String(length=100), nullable=True),
        sa.Column("main_posting_code", sa.String(length=50), sa.ForeignKey("posting_codes.code"), nullable=True),
        sa.Column("exclusion_code", sa.String(length=50), sa.ForeignKey("posting_codes.code"), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("programme_code", "posting_code_1", "posting_code_2", "rule_type", name="uq_multi_posting_rules_scope"),
    )
    op.create_index("idx_multi_posting_rules_lookup", "multi_posting_rules", ["programme_code", "posting_code_1", "posting_code_2", "rule_type"])
    op.create_index("idx_multi_posting_rules_reverse_lookup", "multi_posting_rules", ["programme_code", "posting_code_2", "posting_code_1", "rule_type"])

    op.create_table(
        "posting_groups",
        sa.Column("group_code", sa.String(length=100), nullable=False),
        sa.Column("posting_code", sa.String(length=50), sa.ForeignKey("posting_codes.code"), nullable=False),
        sa.Column("programme_code", sa.String(length=20), sa.ForeignKey("programmes.code"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("posting_code", "programme_code", name="uq_posting_groups_posting_programme"),
    )
    op.create_index("idx_posting_groups_group_programme", "posting_groups", ["group_code", "programme_code"])
    op.create_index("idx_posting_groups_posting_programme", "posting_groups", ["posting_code", "programme_code"])

    op.create_table(
        "residents",
        sa.Column("employee_code", sa.String(length=20), nullable=True, unique=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("mcr", sa.String(length=20), nullable=False, unique=True),
        sa.Column("classification", sa.String(length=20), nullable=True),
        sa.Column("programme_code", sa.String(length=20), sa.ForeignKey("programmes.code"), nullable=True),
        sa.Column("r_year", sa.String(length=10), nullable=True),
        sa.Column("reg_type", sa.String(length=20), nullable=True),
        sa.Column("base_institution", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=100), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("employer_tag", sa.String(length=20), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_residents_employer_tag", "residents", ["employer_tag"], postgresql_where=sa.text("employer_tag IS NOT NULL"))
    op.create_index("idx_residents_programme_status", "residents", ["programme_code", "status"])

    op.create_table(
        "teaching_name_catalogue",
        sa.Column("keyword", sa.String(length=200), nullable=False),
        sa.Column("session_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("session_types.id"), nullable=False),
        sa.Column("posting_code", sa.String(length=50), sa.ForeignKey("posting_codes.code"), nullable=False),
        sa.Column("programme_code", sa.String(length=20), sa.ForeignKey("programmes.code"), nullable=False),
        sa.Column("r_year", sa.String(length=10), nullable=False),
        sa.Column("reporting_period_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reporting_periods.id"), nullable=False),
        sa.Column("duration_hours", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column("is_tracked", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("keyword", "posting_code", "programme_code", "r_year", "reporting_period_id", name="uq_teaching_name_catalogue_resolution"),
    )
    op.create_index("idx_teaching_name_catalogue_resolution", "teaching_name_catalogue", ["reporting_period_id", "programme_code", "posting_code", "r_year", "keyword"])
    op.create_index("idx_teaching_name_catalogue_session_type", "teaching_name_catalogue", ["session_type_id"])
    op.create_index("idx_teaching_name_catalogue_tracked", "teaching_name_catalogue", ["reporting_period_id", "programme_code", "posting_code", "r_year", "is_tracked"])

    op.create_table(
        "teaching_targets",
        sa.Column("reporting_period_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reporting_periods.id"), nullable=False),
        sa.Column("programme_code", sa.String(length=20), sa.ForeignKey("programmes.code"), nullable=False),
        sa.Column("r_year", sa.String(length=10), nullable=False),
        sa.Column("posting_code", sa.String(length=50), sa.ForeignKey("posting_codes.code"), nullable=False),
        sa.Column("session_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("session_types.id"), nullable=False),
        sa.Column("monthly_target", sa.Integer(), nullable=False),
        sa.Column("is_tracked", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_reallocatable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tag", sa.String(length=10), nullable=True),
        sa.Column("details_of_training", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("reporting_period_id", "programme_code", "r_year", "posting_code", "session_type_id", name="uq_teaching_targets_scope"),
    )
    op.create_index("idx_teaching_targets_lookup", "teaching_targets", ["reporting_period_id", "programme_code", "posting_code", "r_year"])
    op.create_index("idx_teaching_targets_reallocation", "teaching_targets", ["reporting_period_id", "programme_code", "posting_code", "tag"], postgresql_where=sa.text("is_reallocatable = true"))

    op.create_table(
        "users",
        sa.Column("email", sa.String(length=100), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("posting_code", sa.String(length=50), sa.ForeignKey("posting_codes.code"), nullable=True),
        sa.Column("programme_scope", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_users_posting_code", "users", ["posting_code"], postgresql_where=sa.text("posting_code IS NOT NULL"))
    op.create_index("idx_users_programme_scope_gin", "users", ["programme_scope"], postgresql_using="gin")
    op.create_index("idx_users_role", "users", ["role"])

    op.create_table(
        "weekend_exceptions",
        sa.Column("programme_code", sa.String(length=20), sa.ForeignKey("programmes.code"), nullable=True),
        sa.Column("posting_code", sa.String(length=50), sa.ForeignKey("posting_codes.code"), nullable=True),
        sa.Column("day_type", sa.String(length=3), nullable=False),
        sa.Column("start_time_min", sa.Time(), nullable=True),
        sa.Column("end_time_max", sa.Time(), nullable=True),
        sa.Column("session_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("session_types.id"), nullable=True),
        sa.Column("session_name_pattern", sa.String(length=100), nullable=True),
        sa.Column("mutates_to_session_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("session_types.id"), nullable=True),
        sa.Column("adjusted_duration_hours", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_weekend_exceptions_lookup", "weekend_exceptions", ["programme_code", "posting_code", "day_type"])
    op.create_index("idx_weekend_exceptions_session_type", "weekend_exceptions", ["session_type_id"], postgresql_where=sa.text("session_type_id IS NOT NULL"))

    op.create_table(
        "clawback_records",
        sa.Column("reporting_period_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reporting_periods.id"), nullable=False),
        sa.Column("resident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("residents.id"), nullable=False),
        sa.Column("posting_code", sa.String(length=50), sa.ForeignKey("posting_codes.code"), nullable=False),
        sa.Column("programme_code", sa.String(length=20), nullable=False),
        sa.Column("r_year", sa.String(length=10), nullable=False),
        sa.Column("active_months", sa.Numeric(precision=4, scale=1), nullable=False),
        sa.Column("compliance_percentage", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("clawback_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("clawback_suppressed_reason", sa.String(length=50), nullable=True),
        sa.Column("billing_dept", sa.String(length=50), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_clawback_records_period_programme", "clawback_records", ["reporting_period_id", "programme_code"])
    op.create_index("idx_clawback_records_resident", "clawback_records", ["resident_id"])

    op.create_table(
        "period_snapshots",
        sa.Column("reporting_period_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reporting_periods.id"), nullable=False),
        sa.Column("programme_code", sa.String(length=20), nullable=False),
        sa.Column("snapshot_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("generated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("reporting_period_id", "programme_code", name="uq_period_snapshots_scope"),
    )
    op.create_index("idx_period_snapshots_period_programme", "period_snapshots", ["reporting_period_id", "programme_code"])

    op.create_table(
        "resident_postings",
        sa.Column("resident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("residents.id"), nullable=False),
        sa.Column("posting_code", sa.String(length=50), sa.ForeignKey("posting_codes.code"), nullable=True),
        sa.Column("reporting_period_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reporting_periods.id"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("day_part", sa.String(length=2), nullable=True),
        sa.Column("month_label", sa.String(length=10), nullable=True),
        sa.Column("r_year", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("loa_type", sa.String(length=50), nullable=True),
        sa.Column("loa_start_date", sa.Date(), nullable=True),
        sa.Column("loa_end_date", sa.Date(), nullable=True),
        sa.Column("refresher_training_type", sa.String(length=50), nullable=True),
        sa.Column("refresher_training_start", sa.Date(), nullable=True),
        sa.Column("refresher_training_end", sa.Date(), nullable=True),
        sa.Column("active_months_weight", sa.Numeric(precision=3, scale=1), nullable=False, server_default=sa.text("1.0")),
        sa.Column("working_days_in_month", sa.Integer(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("resident_id", "reporting_period_id", "start_date", "day_part", name="uq_resident_postings_period_phase", postgresql_nulls_not_distinct=True),
        sa.CheckConstraint("day_part IS NULL OR day_part IN ('AM', 'PM')", name="ck_resident_postings_day_part"),
    )
    op.create_index("idx_resident_postings_compliance_phase", "resident_postings", ["reporting_period_id", "resident_id", "posting_code", "r_year", "status"])
    op.create_index("idx_resident_postings_month_label", "resident_postings", ["reporting_period_id", "month_label"])
    op.create_index("idx_resident_postings_period_posting_status", "resident_postings", ["reporting_period_id", "posting_code", "status"])
    op.create_index("idx_resident_postings_period_resident", "resident_postings", ["reporting_period_id", "resident_id"])
    op.create_index("idx_resident_postings_resident_period_dates", "resident_postings", ["resident_id", "reporting_period_id", "start_date", "end_date"])

    op.create_table(
        "surplus_ledger",
        sa.Column("resident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("residents.id"), nullable=False),
        sa.Column("posting_code", sa.String(length=50), sa.ForeignKey("posting_codes.code"), nullable=False),
        sa.Column("session_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("session_types.id"), nullable=False),
        sa.Column("reporting_period_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reporting_periods.id"), nullable=False),
        sa.Column("surplus", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_hibernating", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_surplus_ledger_hibernation", "surplus_ledger", ["reporting_period_id", "is_hibernating"])
    op.create_index("idx_surplus_ledger_lookup", "surplus_ledger", ["reporting_period_id", "resident_id", "posting_code", "session_type_id"])

    op.create_table(
        "teaching_events",
        sa.Column("posting_code", sa.String(length=50), sa.ForeignKey("posting_codes.code"), nullable=False),
        sa.Column("teaching_name", sa.String(length=200), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("duration_hours", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("session_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("session_types.id"), nullable=True),
        sa.Column("series_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("event_series.id"), nullable=True),
        sa.Column("cme_points_awarded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("smc_event_code", sa.String(length=50), nullable=True),
        sa.Column("is_adhoc", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by_role", sa.String(length=20), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_teaching_events_adhoc", "teaching_events", ["is_adhoc", "event_date"], postgresql_where=sa.text("is_adhoc = true"))
    op.create_index("idx_teaching_events_name_date", "teaching_events", ["teaching_name", "event_date"])
    op.create_index("idx_teaching_events_posting_date", "teaching_events", ["posting_code", "event_date"])
    op.create_index("idx_teaching_events_series", "teaching_events", ["series_id"], postgresql_where=sa.text("series_id IS NOT NULL"))

    op.create_table(
        "upload_logs",
        sa.Column("upload_type", sa.String(length=20), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("reporting_period_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reporting_periods.id"), nullable=True),
        sa.Column("programme_code", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_upload_logs_period_programme", "upload_logs", ["reporting_period_id", "programme_code"])
    op.create_index("idx_upload_logs_type_created", "upload_logs", ["upload_type", sa.text("created_at DESC")])
    op.create_index("idx_upload_logs_uploaded_by", "upload_logs", ["uploaded_by"])

    op.create_table(
        "attendance_records",
        sa.Column("resident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("residents.id"), nullable=False),
        sa.Column("teaching_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teaching_events.id"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'submitted'")),
        sa.Column("posting_code", sa.String(length=50), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("resident_id", "teaching_event_id", name="uq_attendance_records_resident_event"),
    )
    op.create_index("idx_attendance_records_event_status", "attendance_records", ["teaching_event_id", "status"])
    op.create_index("idx_attendance_records_resident_status", "attendance_records", ["resident_id", "status"])
    op.create_index("idx_attendance_records_submitted_at", "attendance_records", ["submitted_at"])
    op.create_index("idx_attendance_records_submitted_resident_event", "attendance_records", ["resident_id", "teaching_event_id"], postgresql_where=sa.text("status = 'submitted'"))

    op.create_table(
        "form_f1_records",
        sa.Column("reporting_period_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reporting_periods.id"), nullable=False),
        sa.Column("mcr", sa.String(length=20), nullable=False),
        sa.Column("month_label", sa.String(length=10), nullable=False),
        sa.Column("status_raw", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("promotion_date", sa.Date(), nullable=True),
        sa.Column("upload_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("upload_logs.id"), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("reporting_period_id", "mcr", "month_label", name="uq_form_f1_records_scope"),
    )
    op.create_index("idx_form_f1_records_active_lookup", "form_f1_records", ["reporting_period_id", "mcr", "month_label", "is_active"])
    op.create_index("idx_form_f1_records_upload", "form_f1_records", ["upload_id"], postgresql_where=sa.text("upload_id IS NOT NULL"))

    _seed_programmes()
    _seed_loa_types()
    _seed_posting_codes()
    _seed_session_type_and_weekend_config(bind)
    _seed_multi_posting_rules()


def downgrade() -> None:
    op.drop_index("idx_form_f1_records_upload", table_name="form_f1_records")
    op.drop_index("idx_form_f1_records_active_lookup", table_name="form_f1_records")
    op.drop_table("form_f1_records")

    op.drop_index("idx_attendance_records_submitted_resident_event", table_name="attendance_records")
    op.drop_index("idx_attendance_records_submitted_at", table_name="attendance_records")
    op.drop_index("idx_attendance_records_resident_status", table_name="attendance_records")
    op.drop_index("idx_attendance_records_event_status", table_name="attendance_records")
    op.drop_table("attendance_records")

    op.drop_index("idx_upload_logs_uploaded_by", table_name="upload_logs")
    op.drop_index("idx_upload_logs_type_created", table_name="upload_logs")
    op.drop_index("idx_upload_logs_period_programme", table_name="upload_logs")
    op.drop_table("upload_logs")

    op.drop_index("idx_teaching_events_series", table_name="teaching_events")
    op.drop_index("idx_teaching_events_posting_date", table_name="teaching_events")
    op.drop_index("idx_teaching_events_name_date", table_name="teaching_events")
    op.drop_index("idx_teaching_events_adhoc", table_name="teaching_events")
    op.drop_table("teaching_events")

    op.drop_index("idx_surplus_ledger_lookup", table_name="surplus_ledger")
    op.drop_index("idx_surplus_ledger_hibernation", table_name="surplus_ledger")
    op.drop_table("surplus_ledger")

    op.drop_index("idx_resident_postings_resident_period_dates", table_name="resident_postings")
    op.drop_index("idx_resident_postings_period_resident", table_name="resident_postings")
    op.drop_index("idx_resident_postings_period_posting_status", table_name="resident_postings")
    op.drop_index("idx_resident_postings_month_label", table_name="resident_postings")
    op.drop_index("idx_resident_postings_compliance_phase", table_name="resident_postings")
    op.drop_table("resident_postings")

    op.drop_index("idx_period_snapshots_period_programme", table_name="period_snapshots")
    op.drop_table("period_snapshots")

    op.drop_index("idx_clawback_records_resident", table_name="clawback_records")
    op.drop_index("idx_clawback_records_period_programme", table_name="clawback_records")
    op.drop_table("clawback_records")

    op.drop_index("idx_weekend_exceptions_session_type", table_name="weekend_exceptions")
    op.drop_index("idx_weekend_exceptions_lookup", table_name="weekend_exceptions")
    op.drop_table("weekend_exceptions")

    op.drop_index("idx_users_role", table_name="users")
    op.drop_index("idx_users_programme_scope_gin", table_name="users")
    op.drop_index("idx_users_posting_code", table_name="users")
    op.drop_table("users")

    op.drop_index("idx_teaching_targets_reallocation", table_name="teaching_targets")
    op.drop_index("idx_teaching_targets_lookup", table_name="teaching_targets")
    op.drop_table("teaching_targets")

    op.drop_index("idx_teaching_name_catalogue_tracked", table_name="teaching_name_catalogue")
    op.drop_index("idx_teaching_name_catalogue_session_type", table_name="teaching_name_catalogue")
    op.drop_index("idx_teaching_name_catalogue_resolution", table_name="teaching_name_catalogue")
    op.drop_table("teaching_name_catalogue")

    op.drop_index("idx_residents_programme_status", table_name="residents")
    op.drop_index("idx_residents_employer_tag", table_name="residents")
    op.drop_table("residents")

    op.drop_index("idx_posting_groups_posting_programme", table_name="posting_groups")
    op.drop_index("idx_posting_groups_group_programme", table_name="posting_groups")
    op.drop_table("posting_groups")

    op.drop_index("idx_multi_posting_rules_reverse_lookup", table_name="multi_posting_rules")
    op.drop_index("idx_multi_posting_rules_lookup", table_name="multi_posting_rules")
    op.drop_table("multi_posting_rules")

    op.drop_index("idx_event_series_posting", table_name="event_series")
    op.drop_table("event_series")

    op.drop_table("session_types")

    op.drop_index("idx_reporting_periods_status", table_name="reporting_periods")
    op.drop_index("idx_reporting_periods_date_range", table_name="reporting_periods")
    op.drop_table("reporting_periods")

    op.drop_index("idx_public_holidays_year", table_name="public_holidays")
    op.drop_table("public_holidays")

    op.drop_index("idx_programmes_rdb_alias", table_name="programmes")
    op.drop_table("programmes")

    op.drop_index("idx_posting_codes_institution_department", table_name="posting_codes")
    op.drop_table("posting_codes")

    op.drop_table("loa_types")

    op.drop_index("idx_global_session_types_active_name", table_name="global_session_types")
    op.drop_table("global_session_types")
