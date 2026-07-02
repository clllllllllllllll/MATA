"""add users supabase user mapping

Revision ID: 20260702_000012
Revises: 20260629_000011
Create Date: 2026-07-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260702_000012"
down_revision = "20260629_000011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("supabase_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_users_supabase_user_id",
        "users",
        ["supabase_user_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_users_supabase_user_id", "users", type_="unique")
    op.drop_column("users", "supabase_user_id")
