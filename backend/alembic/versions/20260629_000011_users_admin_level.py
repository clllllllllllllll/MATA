"""add explicit users admin level

Revision ID: 20260629_000011
Revises: 20260629_000010
Create Date: 2026-06-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260629_000011"
down_revision = "20260629_000010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "admin_level",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'programme'"),
        ),
    )
    op.execute("UPDATE users SET admin_level = 'programme' WHERE admin_level IS NULL")
    op.create_check_constraint(
        "ck_users_admin_level",
        "users",
        "admin_level IN ('programme', 'master')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_admin_level", "users", type_="check")
    op.drop_column("users", "admin_level")
