from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, desc, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_logs_created_at", desc("created_at")),
        Index("idx_audit_logs_actor_user_created", "actor_user_id", desc("created_at")),
        Index("idx_audit_logs_entity_created", "entity_type", "entity_id", desc("created_at")),
        Index("idx_audit_logs_action_created", "action", desc("created_at")),
        Index("idx_audit_logs_actor_role_created", "actor_role", desc("created_at")),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    actor_role: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_site: Mapped[str | None] = mapped_column(String(50), nullable=True)
    actor_programme: Mapped[str | None] = mapped_column(String(50), nullable=True)
    actor_admin_level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
