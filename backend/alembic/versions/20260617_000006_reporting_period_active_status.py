"""Use active reporting periods and scheduled status dates.

Revision ID: 20260617_000006
Revises: 20260610_000005
Create Date: 2026-06-17 00:00:06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260617_000006"
down_revision = "20260610_000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reporting_periods", sa.Column("activate_on", sa.Date(), nullable=True))
    op.add_column("reporting_periods", sa.Column("deactivate_on", sa.Date(), nullable=True))
    op.execute("UPDATE reporting_periods SET status = 'active' WHERE status = 'open'")
    op.execute("UPDATE reporting_periods SET status = 'inactive' WHERE status = 'closed'")
    op.alter_column(
        "reporting_periods",
        "status",
        server_default=sa.text("'active'"),
        existing_type=sa.String(length=10),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute("UPDATE reporting_periods SET status = 'open' WHERE status = 'active'")
    op.execute("UPDATE reporting_periods SET status = 'closed' WHERE status = 'inactive'")
    op.alter_column(
        "reporting_periods",
        "status",
        server_default=sa.text("'open'"),
        existing_type=sa.String(length=10),
        existing_nullable=False,
    )
    op.drop_column("reporting_periods", "deactivate_on")
    op.drop_column("reporting_periods", "activate_on")
