from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDTimestampMixin


class RateLimitBucket(UUIDTimestampMixin, Base):
    __tablename__ = "rate_limit_buckets"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "key_hash",
            "window_start",
            "window_seconds",
            name="uq_rate_limit_buckets_window",
        ),
        CheckConstraint("window_seconds > 0", name="ck_rate_limit_buckets_window_positive"),
        CheckConstraint("request_count >= 1", name="ck_rate_limit_buckets_count_positive"),
        Index("idx_rate_limit_buckets_scope_key_window", "scope", "key_hash", "window_start"),
        Index("idx_rate_limit_buckets_expires_at", "expires_at"),
    )

    scope: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
