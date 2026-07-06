"""add programme native teaching posting mapping

Revision ID: 20260704_000014
Revises: 20260703_000013
Create Date: 2026-07-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260704_000014"
down_revision = "20260703_000013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "programmes",
        sa.Column("native_teaching_posting_code", sa.String(length=50), nullable=True),
    )
    op.create_foreign_key(
        "fk_programmes_native_teaching_posting_code",
        "programmes",
        "posting_codes",
        ["native_teaching_posting_code"],
        ["code"],
    )
    op.create_index(
        "idx_programmes_native_teaching_posting",
        "programmes",
        ["native_teaching_posting_code"],
        postgresql_where=sa.text("native_teaching_posting_code IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_programmes_native_teaching_posting", table_name="programmes")
    op.drop_constraint(
        "fk_programmes_native_teaching_posting_code",
        "programmes",
        type_="foreignkey",
    )
    op.drop_column("programmes", "native_teaching_posting_code")
