"""repair canonical posting metadata used by external registration

Revision ID: 20260717_000018
Revises: 20260714_000017
Create Date: 2026-07-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260717_000018"
down_revision = "20260714_000017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The secretary programme-pool seed establishes GERI -> TTSHGerMed as an
    # explicit mapping. Registration also validates the selected institution
    # against canonical posting metadata, so repair the missing half of that
    # already-confirmed mapping without deriving or creating a posting code.
    op.execute(
        sa.text(
            """
            UPDATE posting_codes
            SET institution = 'TTSH'
            WHERE code = 'TTSHGerMed'
              AND institution IS NULL
            """
        )
    )


def downgrade() -> None:
    # Keep the canonical metadata repair. Clearing the value on downgrade
    # could erase a subsequently confirmed/admin-maintained institution.
    pass
