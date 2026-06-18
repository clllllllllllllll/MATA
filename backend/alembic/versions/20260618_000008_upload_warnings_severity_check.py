"""Constrain upload warning severity values.

Revision ID: 20260618_000008
Revises: 20260617_000007
Create Date: 2026-06-18 00:00:08
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260618_000008"
down_revision = "20260617_000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_upload_warnings_severity",
        "upload_warnings",
        "severity IN ('critical', 'warning', 'info')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_upload_warnings_severity",
        "upload_warnings",
        type_="check",
    )
