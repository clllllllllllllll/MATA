from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AppSession(Base):
    """Opaque, backend-owned browser session state.

    The browser token and CSRF token are never persisted.  Only keyed digests
    are stored so a read-only database disclosure does not expose reusable
    browser credentials.
    """

    __tablename__ = "app_sessions"
    __table_args__ = (
        UniqueConstraint(
            "token_digest",
            name="uq_app_sessions_token_digest",
        ),
        CheckConstraint(
            "subject_type IN ('staff', 'resident', 'external_resident')",
            name="ck_app_sessions_subject_type",
        ),
        CheckConstraint(
            "auth_source IN ('supabase_staff', 'mata_resident')",
            name="ck_app_sessions_auth_source",
        ),
        CheckConstraint(
            "((subject_type = 'staff' AND auth_source = 'supabase_staff') OR "
            "(subject_type IN ('resident', 'external_resident') "
            "AND auth_source = 'mata_resident'))",
            name="ck_app_sessions_subject_auth_source",
        ),
        CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="ck_app_sessions_idle_before_absolute",
        ),
        CheckConstraint(
            "subject_session_generation >= 0",
            name="ck_app_sessions_subject_session_generation_nonnegative",
        ),
        CheckConstraint(
            "rotated_from_session_id IS NOT NULL OR session_family_id = id",
            name="ck_app_sessions_root_self_family",
        ),
        CheckConstraint(
            "octet_length(token_digest) = 32",
            name="ck_app_sessions_token_digest_length",
        ),
        CheckConstraint(
            "octet_length(csrf_token_digest) = 32",
            name="ck_app_sessions_csrf_token_digest_length",
        ),
        CheckConstraint(
            "user_agent_hash IS NULL OR octet_length(user_agent_hash) = 32",
            name="ck_app_sessions_user_agent_hash_length",
        ),
        UniqueConstraint(
            "rotated_from_session_id",
            name="uq_app_sessions_rotated_from_session_id",
        ),
        Index(
            "idx_app_sessions_active_expiry",
            "revoked_at",
            "idle_expires_at",
            "absolute_expires_at",
        ),
        Index("idx_app_sessions_subject", "subject_type", "subject_id"),
        Index(
            "idx_app_sessions_family_revoked",
            "session_family_id",
            "revoked_at",
        ),
        Index("idx_app_sessions_revoked_at", "revoked_at"),
        Index("idx_app_sessions_absolute_expires_at", "absolute_expires_at"),
        Index("idx_app_sessions_idle_expires_at", "idle_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    token_digest: Mapped[bytes] = mapped_column(
        LargeBinary(32),
        nullable=False,
    )
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    subject_session_generation: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    session_family_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    auth_source: Mapped[str] = mapped_column(String(30), nullable=False)
    csrf_token_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    idle_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    absolute_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rotated_from_session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
    )
    user_agent_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary(32),
        nullable=True,
    )
