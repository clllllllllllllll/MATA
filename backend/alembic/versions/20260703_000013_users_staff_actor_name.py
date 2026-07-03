"""add saved staff actor name metadata

Revision ID: 20260703_000013
Revises: 20260702_000012
Create Date: 2026-07-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260703_000013"
down_revision = "20260702_000012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("current_staff_actor_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "staff_actor_name_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "staff_actor_name_updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_users_staff_actor_name_updated_by_user_id",
        "users",
        "users",
        ["staff_actor_name_updated_by_user_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_users_staff_actor_name_updated_by_user_id",
        "users",
        type_="foreignkey",
    )
    op.drop_column("users", "staff_actor_name_updated_by_user_id")
    op.drop_column("users", "staff_actor_name_updated_at")
    op.drop_column("users", "current_staff_actor_name")
