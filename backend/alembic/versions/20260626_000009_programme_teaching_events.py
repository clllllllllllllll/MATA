"""Add programme ownership for scheduled teaching events."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260626_000009"
down_revision = "20260618_000008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "teaching_events",
        sa.Column("created_for_programme_code", sa.String(length=20), nullable=True),
    )
    op.create_foreign_key(
        "fk_teaching_events_created_for_programme_code_programmes",
        "teaching_events",
        "programmes",
        ["created_for_programme_code"],
        ["code"],
    )
    op.create_index(
        "idx_teaching_events_programme_date",
        "teaching_events",
        ["created_for_programme_code", "event_date"],
        postgresql_where=sa.text("created_for_programme_code IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_teaching_events_programme_date", table_name="teaching_events")
    op.drop_constraint(
        "fk_teaching_events_created_for_programme_code_programmes",
        "teaching_events",
        type_="foreignkey",
    )
    op.drop_column("teaching_events", "created_for_programme_code")
