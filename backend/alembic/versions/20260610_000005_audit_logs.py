"""Add audit logs table.

Revision ID: 20260610_000005
Revises: 20260520_000004
Create Date: 2026-06-10 00:00:05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260610_000005"
down_revision = "20260520_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("actor_role", sa.String(length=30), nullable=False),
        sa.Column("actor_name", sa.String(length=120), nullable=False),
        sa.Column("actor_site", sa.String(length=50), nullable=True),
        sa.Column("actor_programme", sa.String(length=50), nullable=True),
        sa.Column("actor_admin_level", sa.String(length=30), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("before_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_audit_logs_created_at",
        "audit_logs",
        [sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_audit_logs_actor_user_created",
        "audit_logs",
        ["actor_user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_audit_logs_entity_created",
        "audit_logs",
        ["entity_type", "entity_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_audit_logs_action_created",
        "audit_logs",
        ["action", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_audit_logs_actor_role_created",
        "audit_logs",
        ["actor_role", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_audit_logs_actor_role_created", table_name="audit_logs")
    op.drop_index("idx_audit_logs_action_created", table_name="audit_logs")
    op.drop_index("idx_audit_logs_entity_created", table_name="audit_logs")
    op.drop_index("idx_audit_logs_actor_user_created", table_name="audit_logs")
    op.drop_index("idx_audit_logs_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")
