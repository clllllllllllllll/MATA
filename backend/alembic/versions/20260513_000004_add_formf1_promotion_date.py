"""Add promotion_date to form_f1_records.

Revision ID: 20260513_000004
Revises: 20260512_000003
Create Date: 2026-05-13 00:00:04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260513_000004"
down_revision = "20260512_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("form_f1_records", sa.Column("promotion_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("form_f1_records", "promotion_date")
