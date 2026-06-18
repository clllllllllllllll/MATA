"""Add first-class upload warning issues.

Revision ID: 20260617_000007
Revises: 20260617_000006
Create Date: 2026-06-17 00:00:07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260617_000007"
down_revision = "20260617_000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "warning_issues",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("warning_type", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("first_seen_upload_log_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_seen_upload_log_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reporting_period_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("programme_code", sa.String(length=20), nullable=True),
        sa.Column("resident_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mcr", sa.String(length=20), nullable=True),
        sa.Column("month_label", sa.String(length=20), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolution_source_type", sa.String(length=50), nullable=True),
        sa.Column("resolution_source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "severity IN ('critical', 'warning', 'info')",
            name="ck_warning_issues_severity",
        ),
        sa.CheckConstraint(
            "status IN ('unresolved', 'resolved', 'dismissed', 'superseded', 'reappeared')",
            name="ck_warning_issues_status",
        ),
        sa.ForeignKeyConstraint(["first_seen_upload_log_id"], ["upload_logs.id"]),
        sa.ForeignKeyConstraint(["last_seen_upload_log_id"], ["upload_logs.id"]),
        sa.ForeignKeyConstraint(["reporting_period_id"], ["reporting_periods.id"]),
        sa.ForeignKeyConstraint(["resident_id"], ["residents.id"]),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint", name="uq_warning_issues_fingerprint"),
    )
    op.create_index("idx_warning_issues_status", "warning_issues", ["status"])
    op.create_index("idx_warning_issues_warning_type", "warning_issues", ["warning_type"])
    op.create_index(
        "idx_warning_issues_period_programme",
        "warning_issues",
        ["reporting_period_id", "programme_code"],
    )

    op.create_table(
        "upload_warnings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("upload_log_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warning_type", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("reporting_period_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("programme_code", sa.String(length=20), nullable=True),
        sa.Column("resident_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mcr", sa.String(length=20), nullable=True),
        sa.Column("resident_name", sa.String(length=200), nullable=True),
        sa.Column("month_label", sa.String(length=20), nullable=True),
        sa.Column("sheet_name", sa.String(length=200), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("cell_ref", sa.String(length=20), nullable=True),
        sa.Column("source_table", sa.String(length=100), nullable=True),
        sa.Column("source_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "source_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("suggested_action", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["issue_id"], ["warning_issues.id"]),
        sa.ForeignKeyConstraint(["upload_log_id"], ["upload_logs.id"]),
        sa.ForeignKeyConstraint(["reporting_period_id"], ["reporting_periods.id"]),
        sa.ForeignKeyConstraint(["resident_id"], ["residents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "upload_log_id",
            "fingerprint",
            name="uq_upload_warnings_upload_fingerprint",
        ),
    )
    op.create_index("idx_upload_warnings_upload_log", "upload_warnings", ["upload_log_id"])
    op.create_index("idx_upload_warnings_issue", "upload_warnings", ["issue_id"])
    op.create_index("idx_upload_warnings_warning_type", "upload_warnings", ["warning_type"])
    op.create_index(
        "idx_upload_warnings_period_programme",
        "upload_warnings",
        ["reporting_period_id", "programme_code"],
    )
    op.create_index("idx_upload_warnings_mcr", "upload_warnings", ["mcr"])


def downgrade() -> None:
    op.drop_index("idx_upload_warnings_mcr", table_name="upload_warnings")
    op.drop_index("idx_upload_warnings_period_programme", table_name="upload_warnings")
    op.drop_index("idx_upload_warnings_warning_type", table_name="upload_warnings")
    op.drop_index("idx_upload_warnings_issue", table_name="upload_warnings")
    op.drop_index("idx_upload_warnings_upload_log", table_name="upload_warnings")
    op.drop_table("upload_warnings")

    op.drop_index("idx_warning_issues_period_programme", table_name="warning_issues")
    op.drop_index("idx_warning_issues_warning_type", table_name="warning_issues")
    op.drop_index("idx_warning_issues_status", table_name="warning_issues")
    op.drop_table("warning_issues")
