"""Enforce non-negative teaching targets.

Revision ID: 20260714_000017
Revises: 20260709_000016
Create Date: 2026-07-14
"""

from alembic import op


revision = "20260714_000017"
down_revision = "20260709_000016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_teaching_targets_monthly_target_nonnegative",
        "teaching_targets",
        "monthly_target >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_teaching_targets_monthly_target_nonnegative",
        "teaching_targets",
        type_="check",
    )
