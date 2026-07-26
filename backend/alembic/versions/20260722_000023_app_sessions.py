"""add durable backend-owned application sessions

Revision ID: 20260722_000023
Revises: 20260721_000022
Create Date: 2026-07-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260722_000023"
down_revision = "20260721_000022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table_name in ("users", "residents", "external_residents"):
        op.add_column(
            table_name,
            sa.Column(
                "session_generation",
                sa.BigInteger(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )
        op.create_check_constraint(
            f"ck_{table_name}_session_generation_nonnegative",
            table_name,
            "session_generation >= 0",
        )

    op.add_column(
        "users",
        sa.Column(
            "session_issuance_blocked",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    op.create_table(
        "app_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("token_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("subject_type", sa.String(length=30), nullable=False),
        sa.Column(
            "subject_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "subject_session_generation",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "session_family_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("auth_source", sa.String(length=30), nullable=False),
        sa.Column("csrf_token_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column(
            "rotated_from_session_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("user_agent_hash", sa.LargeBinary(length=32), nullable=True),
        sa.CheckConstraint(
            "subject_type IN ('staff', 'resident', 'external_resident')",
            name="ck_app_sessions_subject_type",
        ),
        sa.CheckConstraint(
            "auth_source IN ('supabase_staff', 'mata_resident')",
            name="ck_app_sessions_auth_source",
        ),
        sa.CheckConstraint(
            "((subject_type = 'staff' AND auth_source = 'supabase_staff') OR "
            "(subject_type IN ('resident', 'external_resident') "
            "AND auth_source = 'mata_resident'))",
            name="ck_app_sessions_subject_auth_source",
        ),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="ck_app_sessions_idle_before_absolute",
        ),
        sa.CheckConstraint(
            "subject_session_generation >= 0",
            name="ck_app_sessions_subject_session_generation_nonnegative",
        ),
        sa.CheckConstraint(
            "rotated_from_session_id IS NOT NULL OR session_family_id = id",
            name="ck_app_sessions_root_self_family",
        ),
        sa.CheckConstraint(
            "octet_length(token_digest) = 32",
            name="ck_app_sessions_token_digest_length",
        ),
        sa.CheckConstraint(
            "octet_length(csrf_token_digest) = 32",
            name="ck_app_sessions_csrf_token_digest_length",
        ),
        sa.CheckConstraint(
            "user_agent_hash IS NULL OR octet_length(user_agent_hash) = 32",
            name="ck_app_sessions_user_agent_hash_length",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "token_digest",
            name="uq_app_sessions_token_digest",
        ),
        sa.UniqueConstraint(
            "rotated_from_session_id",
            name="uq_app_sessions_rotated_from_session_id",
        ),
    )
    op.create_index(
        "idx_app_sessions_active_expiry",
        "app_sessions",
        ["revoked_at", "idle_expires_at", "absolute_expires_at"],
    )
    op.create_index(
        "idx_app_sessions_subject",
        "app_sessions",
        ["subject_type", "subject_id"],
    )
    op.create_index(
        "idx_app_sessions_family_revoked",
        "app_sessions",
        ["session_family_id", "revoked_at"],
    )
    op.create_index(
        "idx_app_sessions_revoked_at",
        "app_sessions",
        ["revoked_at"],
    )
    op.create_index(
        "idx_app_sessions_absolute_expires_at",
        "app_sessions",
        ["absolute_expires_at"],
    )
    op.create_index(
        "idx_app_sessions_idle_expires_at",
        "app_sessions",
        ["idle_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_app_sessions_idle_expires_at", table_name="app_sessions")
    op.drop_index("idx_app_sessions_absolute_expires_at", table_name="app_sessions")
    op.drop_index("idx_app_sessions_revoked_at", table_name="app_sessions")
    op.drop_index("idx_app_sessions_family_revoked", table_name="app_sessions")
    op.drop_index("idx_app_sessions_subject", table_name="app_sessions")
    op.drop_index("idx_app_sessions_active_expiry", table_name="app_sessions")
    op.drop_table("app_sessions")
    op.drop_column("users", "session_issuance_blocked")
    for table_name in ("external_residents", "residents", "users"):
        op.drop_constraint(
            f"ck_{table_name}_session_generation_nonnegative",
            table_name,
            type_="check",
        )
        op.drop_column(table_name, "session_generation")
