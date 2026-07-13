"""add persistent rate limit buckets

Revision ID: 20260709_000016
Revises: 20260708_000015
Create Date: 2026-07-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260709_000016"
down_revision = "20260708_000015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_buckets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("window_seconds > 0", name="ck_rate_limit_buckets_window_positive"),
        sa.CheckConstraint("request_count >= 1", name="ck_rate_limit_buckets_count_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope",
            "key_hash",
            "window_start",
            "window_seconds",
            name="uq_rate_limit_buckets_window",
        ),
    )
    op.create_index(
        "idx_rate_limit_buckets_scope_key_window",
        "rate_limit_buckets",
        ["scope", "key_hash", "window_start"],
    )
    op.create_index(
        "idx_rate_limit_buckets_expires_at",
        "rate_limit_buckets",
        ["expires_at"],
    )
    op.execute("ALTER TABLE rate_limit_buckets ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("idx_rate_limit_buckets_expires_at", table_name="rate_limit_buckets")
    op.drop_index("idx_rate_limit_buckets_scope_key_window", table_name="rate_limit_buckets")
    op.drop_table("rate_limit_buckets")
