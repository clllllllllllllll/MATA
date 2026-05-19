"""Add external resident submission schema and secretary-event capability flag.

Revision ID: 20260519_000003
Revises: 20260515_000002
Create Date: 2026-05-19 00:00:03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260519_000003"
down_revision = "20260515_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "posting_codes",
        sa.Column(
            "supports_secretary_events",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "idx_posting_codes_supports_secretary_events",
        "posting_codes",
        ["supports_secretary_events"],
    )

    op.create_table(
        "external_residents",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("mcr", sa.String(length=20), nullable=False),
        sa.Column("home_cluster", sa.String(length=20), nullable=False),
        sa.Column(
            "current_nhg_posting_code",
            sa.String(length=50),
            sa.ForeignKey("posting_codes.code"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "home_cluster IN ('NUH', 'SingHealth')",
            name="ck_external_residents_home_cluster",
        ),
    )
    op.create_index("idx_external_residents_mcr", "external_residents", ["mcr"], unique=True)
    op.create_index(
        "idx_external_residents_current_posting",
        "external_residents",
        ["current_nhg_posting_code", "status"],
    )
    op.create_index(
        "idx_external_residents_home_cluster",
        "external_residents",
        ["home_cluster"],
    )

    op.create_table(
        "external_resident_postings",
        sa.Column(
            "external_resident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("external_residents.id"),
            nullable=False,
        ),
        sa.Column(
            "posting_code",
            sa.String(length=50),
            sa.ForeignKey("posting_codes.code"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_external_resident_postings_external_current",
        "external_resident_postings",
        ["external_resident_id", "is_current"],
    )
    op.create_index(
        "idx_external_resident_postings_external_dates",
        "external_resident_postings",
        ["external_resident_id", "start_date", "end_date"],
    )

    op.create_table(
        "external_attendance_records",
        sa.Column(
            "external_resident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("external_residents.id"),
            nullable=False,
        ),
        sa.Column(
            "teaching_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teaching_events.id"),
            nullable=False,
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'submitted'"),
        ),
        sa.Column("posting_code", sa.String(length=50), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_external_attendance_external_status",
        "external_attendance_records",
        ["external_resident_id", "status"],
    )
    op.create_index(
        "idx_external_attendance_event_status",
        "external_attendance_records",
        ["teaching_event_id", "status"],
    )
    op.create_index(
        "idx_external_attendance_submitted_external_event",
        "external_attendance_records",
        ["external_resident_id", "teaching_event_id"],
        unique=True,
        postgresql_where=sa.text("status = 'submitted'"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_external_attendance_submitted_external_event",
        table_name="external_attendance_records",
    )
    op.drop_index(
        "idx_external_attendance_event_status",
        table_name="external_attendance_records",
    )
    op.drop_index(
        "idx_external_attendance_external_status",
        table_name="external_attendance_records",
    )
    op.drop_table("external_attendance_records")

    op.drop_index(
        "idx_external_resident_postings_external_dates",
        table_name="external_resident_postings",
    )
    op.drop_index(
        "idx_external_resident_postings_external_current",
        table_name="external_resident_postings",
    )
    op.drop_table("external_resident_postings")

    op.drop_index("idx_external_residents_home_cluster", table_name="external_residents")
    op.drop_index("idx_external_residents_current_posting", table_name="external_residents")
    op.drop_index("idx_external_residents_mcr", table_name="external_residents")
    op.drop_table("external_residents")

    op.drop_index(
        "idx_posting_codes_supports_secretary_events",
        table_name="posting_codes",
    )
    op.drop_column("posting_codes", "supports_secretary_events")
