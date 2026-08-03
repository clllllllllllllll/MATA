"""preserve events when teaching names are deleted

Revision ID: 20260803_000030
Revises: 20260802_000029
Create Date: 2026-08-03

Teaching events retain their immutable ``teaching_name`` snapshot when the
optional future-state Teaching Name identity is removed.  This revision changes
only the optional identity foreign key action; it does not alter events,
attendance, source-identity exclusivity, or any legacy catalogue behavior.
"""

from __future__ import annotations

from alembic import op


revision = "20260803_000030"
down_revision = "20260802_000029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "fk_teaching_events_teaching_name",
        "teaching_events",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_teaching_events_teaching_name",
        "teaching_events",
        "teaching_names",
        ["teaching_name_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_teaching_events_teaching_name",
        "teaching_events",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_teaching_events_teaching_name",
        "teaching_events",
        "teaching_names",
        ["teaching_name_id"],
        ["id"],
        ondelete="RESTRICT",
    )
