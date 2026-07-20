"""add pending programme/institution posting mappings

Revision ID: 20260717_000019
Revises: 20260717_000018
Create Date: 2026-07-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260717_000019"
down_revision = "20260717_000018"
branch_labels = None
depends_on = None


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


def _verify_programme_baseline() -> None:
    connection = op.get_bind()
    actual_codes = tuple(
        connection.execute(sa.text("SELECT code FROM programmes ORDER BY code")).scalars()
    )
    expected_codes = tuple(sorted(EXPECTED_PROGRAMME_CODES))
    if len(actual_codes) != 28 or actual_codes != expected_codes:
        raise RuntimeError(
            "programme_institution_posting_map requires exactly the expected "
            "28-programme baseline"
        )


def upgrade() -> None:
    op.create_table(
        "programme_institution_posting_map",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("programme_code", sa.String(length=20), nullable=False),
        sa.Column("institution_code", sa.String(length=20), nullable=False),
        sa.Column("posting_code", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "display_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'inactive')",
            name="ck_programme_institution_posting_map_status",
        ),
        sa.CheckConstraint(
            "status <> 'active' OR posting_code IS NOT NULL",
            name="ck_programme_institution_posting_map_active_posting",
        ),
        sa.ForeignKeyConstraint(
            ["programme_code"],
            ["programmes.code"],
            name="fk_programme_institution_posting_map_programme",
        ),
        sa.ForeignKeyConstraint(
            ["posting_code"],
            ["posting_codes.code"],
            name="fk_programme_institution_posting_map_posting",
        ),
        sa.UniqueConstraint(
            "programme_code",
            "institution_code",
            name="uq_programme_institution_posting_map_scope",
        ),
    )
    op.create_index(
        "idx_programme_institution_posting_map_institution_status",
        "programme_institution_posting_map",
        ["institution_code", "status"],
    )
    op.create_index(
        "idx_programme_institution_posting_map_programme_status",
        "programme_institution_posting_map",
        ["programme_code", "status"],
    )
    op.create_index(
        "idx_programme_institution_posting_map_posting",
        "programme_institution_posting_map",
        ["posting_code"],
        postgresql_where=sa.text("posting_code IS NOT NULL"),
    )

    _verify_programme_baseline()
    mapping_table = sa.table(
        "programme_institution_posting_map",
        sa.column("programme_code", sa.String()),
        sa.column("institution_code", sa.String()),
        sa.column("posting_code", sa.String()),
        sa.column("status", sa.String()),
        sa.column("display_order", sa.Integer()),
    )
    op.bulk_insert(
        mapping_table,
        [
            {
                "programme_code": programme_code,
                "institution_code": "TTSH",
                "posting_code": None,
                "status": "pending",
                "display_order": display_order,
            }
            for display_order, programme_code in enumerate(EXPECTED_PROGRAMME_CODES)
        ],
    )


def downgrade() -> None:
    op.drop_table("programme_institution_posting_map")
