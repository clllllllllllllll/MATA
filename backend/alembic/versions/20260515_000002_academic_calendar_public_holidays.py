"""Add AY date category and academic month boundaries schema.

Revision ID: 20260515_000002
Revises: 20260514_000001
Create Date: 2026-05-15 00:00:02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260515_000002"
down_revision = "20260514_000001"
branch_labels = None
depends_on = None


PROGRAMME_AY_CATEGORY_MAP: dict[str, str] = {
    "AIM": "im_subspec",
    "CARDIO": "im_subspec",
    "DERM": "im_subspec",
    "ENDO": "im_subspec",
    "GASTRO": "im_subspec",
    "GERI": "im_subspec",
    "ID": "im_subspec",
    "IM": "im_subspec",
    "MEDONCO": "im_subspec",
    "PALLMED": "im_subspec",
    "REHAB": "im_subspec",
    "RENAL": "im_subspec",
    "RESPI": "im_subspec",
    "RHEUM": "im_subspec",
    "ANAES": "non_im_subspec",
    "DR": "non_im_subspec",
    "EM": "non_im_subspec",
    "ENT": "non_im_subspec",
    "EYE": "non_im_subspec",
    "FM": "non_im_subspec",
    "GS": "non_im_subspec",
    "MICROB": "non_im_subspec",
    "ORTHO": "non_im_subspec",
    "PATH": "non_im_subspec",
    "PSY": "non_im_subspec",
    "SIG": "non_im_subspec",
    "SPORTSMED": "non_im_subspec",
    "URO": "non_im_subspec",
}


def upgrade() -> None:
    op.add_column(
        "programmes",
        sa.Column("ay_date_category", sa.String(length=30), nullable=True),
    )

    for programme_code, category in PROGRAMME_AY_CATEGORY_MAP.items():
        op.execute(
            sa.text(
                """
                UPDATE programmes
                SET ay_date_category = :category
                WHERE code = :programme_code
                """
            ).bindparams(
                programme_code=programme_code,
                category=category,
            )
        )

    op.alter_column("programmes", "ay_date_category", nullable=False)
    op.create_check_constraint(
        "ck_programmes_ay_date_category",
        "programmes",
        "ay_date_category IN ('im_subspec', 'non_im_subspec')",
    )

    op.create_table(
        "academic_month_boundaries",
        sa.Column("academic_year_label", sa.String(length=20), nullable=False),
        sa.Column("ay_date_category", sa.String(length=30), nullable=False),
        sa.Column("month_label", sa.String(length=10), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "upload_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("upload_logs.id"),
            nullable=True,
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
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
            "ay_date_category IN ('im_subspec', 'non_im_subspec')",
            name="ck_academic_month_boundaries_ay_date_category",
        ),
        sa.CheckConstraint(
            "start_date <= end_date",
            name="ck_academic_month_boundaries_date_range",
        ),
        sa.UniqueConstraint(
            "academic_year_label",
            "ay_date_category",
            "month_label",
            name="uq_academic_month_boundaries_scope",
        ),
    )
    op.create_index(
        "idx_academic_month_boundaries_lookup",
        "academic_month_boundaries",
        ["academic_year_label", "ay_date_category", "start_date", "end_date"],
    )
    op.create_index(
        "idx_academic_month_boundaries_upload",
        "academic_month_boundaries",
        ["upload_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_academic_month_boundaries_upload",
        table_name="academic_month_boundaries",
    )
    op.drop_index(
        "idx_academic_month_boundaries_lookup",
        table_name="academic_month_boundaries",
    )
    op.drop_table("academic_month_boundaries")

    op.drop_constraint(
        "ck_programmes_ay_date_category",
        "programmes",
        type_="check",
    )
    op.drop_column("programmes", "ay_date_category")
