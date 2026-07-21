"""add programme provenance to external resident posting rows

Revision ID: 20260721_000022
Revises: 20260721_000021
Create Date: 2026-07-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260721_000022"
down_revision = "20260721_000021"
branch_labels = None
depends_on = None


FOREIGN_KEY_NAME = "fk_external_resident_postings_programme_code_programmes"
INDEX_NAME = "idx_external_resident_postings_external_scope_dates"


def upgrade() -> None:
    op.add_column(
        "external_resident_postings",
        sa.Column("programme_code", sa.String(length=20), nullable=True),
    )
    op.create_foreign_key(
        FOREIGN_KEY_NAME,
        "external_resident_postings",
        "programmes",
        ["programme_code"],
        ["code"],
    )

    # A posting code is not programme identity: multiple programmes can share it.
    # Backfill only when all authoritative mappings carrying that posting agree on
    # exactly one programme, regardless of mapping status. Unmapped and ambiguous
    # legacy rows remain NULL.
    op.execute(
        sa.text(
            """
            WITH candidate_mappings AS (
                SELECT DISTINCT posting_code, programme_code
                FROM programme_institution_posting_map
                WHERE posting_code IS NOT NULL
            ),
            uniquely_resolved_mappings AS (
                SELECT candidate.posting_code, candidate.programme_code
                FROM candidate_mappings AS candidate
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM candidate_mappings AS other
                    WHERE other.posting_code = candidate.posting_code
                      AND other.programme_code <> candidate.programme_code
                )
            )
            UPDATE external_resident_postings AS external_posting
            SET programme_code = resolved.programme_code
            FROM uniquely_resolved_mappings AS resolved
            WHERE external_posting.posting_code = resolved.posting_code
              AND external_posting.programme_code IS NULL
            """
        )
    )

    op.create_index(
        INDEX_NAME,
        "external_resident_postings",
        [
            "external_resident_id",
            "posting_code",
            "programme_code",
            "start_date",
            "end_date",
        ],
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="external_resident_postings")
    op.drop_constraint(
        FOREIGN_KEY_NAME,
        "external_resident_postings",
        type_="foreignkey",
    )
    op.drop_column("external_resident_postings", "programme_code")
