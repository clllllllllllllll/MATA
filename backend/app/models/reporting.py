from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDTimestampMixin


class ReportingPeriod(UUIDTimestampMixin, Base):
    __tablename__ = "reporting_periods"
    __table_args__ = (
        Index("idx_reporting_periods_status", "status"),
        Index("idx_reporting_periods_date_range", "start_date", "end_date"),
    )

    label: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default=text("'active'"),
    )
    activate_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    deactivate_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class LoaType(UUIDTimestampMixin, Base):
    __tablename__ = "loa_types"

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(100), nullable=True)


class UploadLog(UUIDTimestampMixin, Base):
    __tablename__ = "upload_logs"
    __table_args__ = (
        Index("idx_upload_logs_type_created", "upload_type", desc("created_at")),
        Index(
            "idx_upload_logs_period_programme",
            "reporting_period_id",
            "programme_code",
        ),
        Index("idx_upload_logs_uploaded_by", "uploaded_by"),
    )

    upload_type: Mapped[str] = mapped_column(String(20), nullable=False)
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    reporting_period_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reporting_periods.id"),
        nullable=True,
    )
    programme_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)


class WarningIssue(UUIDTimestampMixin, Base):
    __tablename__ = "warning_issues"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('critical', 'warning', 'info')",
            name="ck_warning_issues_severity",
        ),
        CheckConstraint(
            "status IN ('unresolved', 'resolved', 'dismissed', 'superseded', 'reappeared')",
            name="ck_warning_issues_status",
        ),
        Index("idx_warning_issues_status", "status"),
        Index("idx_warning_issues_warning_type", "warning_type"),
        Index(
            "idx_warning_issues_period_programme",
            "reporting_period_id",
            "programme_code",
        ),
        UniqueConstraint("fingerprint", name="uq_warning_issues_fingerprint"),
    )

    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    warning_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    first_seen_upload_log_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("upload_logs.id"),
        nullable=True,
    )
    last_seen_upload_log_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("upload_logs.id"),
        nullable=True,
    )
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reporting_period_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reporting_periods.id"),
        nullable=True,
    )
    programme_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resident_id: Mapped[UUID | None] = mapped_column(ForeignKey("residents.id"), nullable=True)
    mcr: Mapped[str | None] = mapped_column(String(20), nullable=True)
    month_label: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resolution_source_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    resolved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UploadWarning(Base):
    __tablename__ = "upload_warnings"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('critical', 'warning', 'info')",
            name="ck_upload_warnings_severity",
        ),
        UniqueConstraint("upload_log_id", "fingerprint", name="uq_upload_warnings_upload_fingerprint"),
        Index("idx_upload_warnings_upload_log", "upload_log_id"),
        Index("idx_upload_warnings_issue", "issue_id"),
        Index("idx_upload_warnings_warning_type", "warning_type"),
        Index(
            "idx_upload_warnings_period_programme",
            "reporting_period_id",
            "programme_code",
        ),
        Index("idx_upload_warnings_mcr", "mcr"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    issue_id: Mapped[UUID] = mapped_column(ForeignKey("warning_issues.id"), nullable=False)
    upload_log_id: Mapped[UUID] = mapped_column(ForeignKey("upload_logs.id"), nullable=False)
    warning_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    reporting_period_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reporting_periods.id"),
        nullable=True,
    )
    programme_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resident_id: Mapped[UUID | None] = mapped_column(ForeignKey("residents.id"), nullable=True)
    mcr: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resident_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    month_label: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sheet_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cell_ref: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_table: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_record_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    source_payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class AcademicMonthBoundary(UUIDTimestampMixin, Base):
    __tablename__ = "academic_month_boundaries"
    __table_args__ = (
        CheckConstraint(
            "ay_date_category IN ('im_subspec', 'non_im_subspec')",
            name="ck_academic_month_boundaries_ay_date_category",
        ),
        CheckConstraint("start_date <= end_date", name="ck_academic_month_boundaries_date_range"),
        UniqueConstraint(
            "academic_year_label",
            "ay_date_category",
            "month_label",
            name="uq_academic_month_boundaries_scope",
        ),
        Index(
            "idx_academic_month_boundaries_lookup",
            "academic_year_label",
            "ay_date_category",
            "start_date",
            "end_date",
        ),
        Index("idx_academic_month_boundaries_upload", "upload_id"),
    )

    academic_year_label: Mapped[str] = mapped_column(String(20), nullable=False)
    ay_date_category: Mapped[str] = mapped_column(String(30), nullable=False)
    month_label: Mapped[str] = mapped_column(String(10), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    upload_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("upload_logs.id"),
        nullable=True,
    )


class FormF1Record(UUIDTimestampMixin, Base):
    __tablename__ = "form_f1_records"
    __table_args__ = (
        UniqueConstraint(
            "reporting_period_id",
            "mcr",
            "month_label",
            name="uq_form_f1_records_scope",
        ),
        Index(
            "idx_form_f1_records_active_lookup",
            "reporting_period_id",
            "mcr",
            "month_label",
            "is_active",
        ),
        Index(
            "idx_form_f1_records_upload",
            "upload_id",
            postgresql_where=text("upload_id IS NOT NULL"),
        ),
    )

    reporting_period_id: Mapped[UUID] = mapped_column(
        ForeignKey("reporting_periods.id"),
        nullable=False,
    )
    mcr: Mapped[str] = mapped_column(String(20), nullable=False)
    month_label: Mapped[str] = mapped_column(String(10), nullable=False)
    status_raw: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    promotion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    upload_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("upload_logs.id"),
        nullable=True,
    )


class PeriodSnapshot(UUIDTimestampMixin, Base):
    __tablename__ = "period_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "reporting_period_id",
            "programme_code",
            name="uq_period_snapshots_scope",
        ),
        Index(
            "idx_period_snapshots_period_programme",
            "reporting_period_id",
            "programme_code",
        ),
    )

    reporting_period_id: Mapped[UUID] = mapped_column(
        ForeignKey("reporting_periods.id"),
        nullable=False,
    )
    programme_code: Mapped[str] = mapped_column(String(20), nullable=False)
    snapshot_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    generated_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )


class ClawbackRecord(UUIDTimestampMixin, Base):
    __tablename__ = "clawback_records"
    __table_args__ = (
        Index(
            "idx_clawback_records_period_programme",
            "reporting_period_id",
            "programme_code",
        ),
        Index("idx_clawback_records_resident", "resident_id"),
    )

    reporting_period_id: Mapped[UUID] = mapped_column(
        ForeignKey("reporting_periods.id"),
        nullable=False,
    )
    resident_id: Mapped[UUID] = mapped_column(ForeignKey("residents.id"), nullable=False)
    posting_code: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=False,
    )
    programme_code: Mapped[str] = mapped_column(String(20), nullable=False)
    r_year: Mapped[str] = mapped_column(String(10), nullable=False)
    active_months: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    compliance_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    clawback_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    clawback_suppressed_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    billing_dept: Mapped[str | None] = mapped_column(String(50), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
