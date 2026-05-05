"""Initial backend foundation schema and seed data.

Revision ID: 20260505_000001
Revises:
Create Date: 2026-05-05 00:00:01
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal

from alembic import op
import sqlalchemy as sa

from app import models


# revision identifiers, used by Alembic.
revision = "20260505_000001"
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
            """,
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
        sa.column("session_type_id", sa.Uuid()),
        sa.column("session_name_pattern", sa.String()),
        sa.column("mutates_to_session_type_id", sa.Uuid()),
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
                "session_type_id": session_type_id_by_name.get("National Teaching [2h]"),
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
                "mutates_to_session_type_id": session_type_id_by_name.get(
                    "National Didactics & Department Teaching [1h]",
                ),
                "adjusted_duration_hours": Decimal("1.00"),
            },
        ],
    )


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    models.Base.metadata.create_all(bind=bind)

    _seed_programmes()
    _seed_loa_types()
    _seed_session_type_and_weekend_config(bind)


def downgrade() -> None:
    bind = op.get_bind()
    models.Base.metadata.drop_all(bind=bind)
