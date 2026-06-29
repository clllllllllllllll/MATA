"""add resident ad-hoc details of session

Revision ID: 20260629_000010
Revises: 20260626_000009
Create Date: 2026-06-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260629_000010"
down_revision = "20260626_000009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "teaching_events",
        sa.Column("details_of_session", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("teaching_events", "details_of_session")
