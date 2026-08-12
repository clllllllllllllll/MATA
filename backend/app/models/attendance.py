from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDTimestampMixin


class AttendanceRecord(UUIDTimestampMixin, Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        CheckConstraint(
            "status IN ('submitted', 'flagged', 'removed')",
            name="ck_attendance_records_status",
        ),
        Index(
            "idx_attendance_records_resident_status",
            "resident_id",
            "status",
        ),
        Index(
            "idx_attendance_records_event_status",
            "teaching_event_id",
            "status",
        ),
        Index("idx_attendance_records_submitted_at", "submitted_at"),
        Index(
            "idx_attendance_records_submitted_resident_event",
            "resident_id",
            "teaching_event_id",
            unique=True,
            postgresql_where=text("status = 'submitted'"),
        ),
    )

    resident_id: Mapped[UUID] = mapped_column(ForeignKey("residents.id"), nullable=False)
    teaching_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("teaching_events.id"),
        nullable=False,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'submitted'"),
    )
    posting_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    submitted_during_loa: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    loa_resident_posting_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("resident_postings.id", ondelete="SET NULL"),
        nullable=True,
    )
    loa_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    loa_classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class ExternalAttendanceRecord(UUIDTimestampMixin, Base):
    __tablename__ = "external_attendance_records"
    __table_args__ = (
        CheckConstraint(
            "status IN ('submitted', 'flagged', 'removed')",
            name="ck_external_attendance_records_status",
        ),
        Index(
            "idx_external_attendance_external_status",
            "external_resident_id",
            "status",
        ),
        Index(
            "idx_external_attendance_event_status",
            "teaching_event_id",
            "status",
        ),
        Index(
            "idx_external_attendance_submitted_external_event",
            "external_resident_id",
            "teaching_event_id",
            unique=True,
            postgresql_where=text("status = 'submitted'"),
        ),
    )

    external_resident_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_residents.id"),
        nullable=False,
    )
    teaching_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("teaching_events.id"),
        nullable=False,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'submitted'"),
    )
    posting_code: Mapped[str | None] = mapped_column(String(50), nullable=True)


class SurplusLedger(UUIDTimestampMixin, Base):
    __tablename__ = "surplus_ledger"
    __table_args__ = (
        Index(
            "idx_surplus_ledger_lookup",
            "reporting_period_id",
            "resident_id",
            "posting_code",
            "session_type_id",
        ),
        Index(
            "idx_surplus_ledger_hibernation",
            "reporting_period_id",
            "is_hibernating",
        ),
    )

    resident_id: Mapped[UUID] = mapped_column(ForeignKey("residents.id"), nullable=False)
    posting_code: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=False,
    )
    session_type_id: Mapped[UUID] = mapped_column(
        ForeignKey("session_types.id"),
        nullable=False,
    )
    reporting_period_id: Mapped[UUID] = mapped_column(
        ForeignKey("reporting_periods.id"),
        nullable=False,
    )
    surplus: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_hibernating: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
