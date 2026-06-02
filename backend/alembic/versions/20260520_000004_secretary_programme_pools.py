"""Add secretary programme pool mapping table for data-driven site-to-programme resolution.

Revision ID: 20260520_000004
Revises: 20260519_000003
Create Date: 2026-05-20 00:00:04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260520_000004"
down_revision = "20260519_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "secretary_programme_pools",
        sa.Column(
            "posting_code",
            sa.String(length=50),
            sa.ForeignKey("posting_codes.code"),
            nullable=False,
        ),
        sa.Column(
            "programme_code",
            sa.String(length=20),
            sa.ForeignKey("programmes.code"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
        sa.UniqueConstraint(
            "posting_code",
            "programme_code",
            name="uq_secretary_programme_pools_posting_programme",
        ),
    )
    op.create_index(
        "idx_secretary_programme_pools_posting_active",
        "secretary_programme_pools",
        ["posting_code", "is_active"],
    )
    op.create_index(
        "idx_secretary_programme_pools_programme_active",
        "secretary_programme_pools",
        ["programme_code", "is_active"],
    )

    secretary_programme_pool_table = sa.table(
        "secretary_programme_pools",
        sa.column("posting_code", sa.String()),
        sa.column("programme_code", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        secretary_programme_pool_table,
        [
            {
                "posting_code": "TTSHGerMed",
                "programme_code": "GERI",
                "is_active": True,
            }
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_secretary_programme_pools_programme_active",
        table_name="secretary_programme_pools",
    )
    op.drop_index(
        "idx_secretary_programme_pools_posting_active",
        table_name="secretary_programme_pools",
    )
    op.drop_table("secretary_programme_pools")
