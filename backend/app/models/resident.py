from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDTimestampMixin


class Resident(UUIDTimestampMixin, Base):
    __tablename__ = "residents"
    __table_args__ = (
        Index(
            "idx_residents_programme_status",
            "programme_code",
            "status",
        ),
        Index(
            "idx_residents_employer_tag",
            "employer_tag",
            postgresql_where=text("employer_tag IS NOT NULL"),
        ),
    )

    employee_code: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    mcr: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    classification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    programme_code: Mapped[str | None] = mapped_column(
        String(20),
        ForeignKey("programmes.code"),
        nullable=True,
    )
    r_year: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reg_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    base_institution: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'active'"),
    )
    employer_tag: Mapped[str | None] = mapped_column(String(20), nullable=True)


class ResidentPosting(UUIDTimestampMixin, Base):
    __tablename__ = "resident_postings"
    __table_args__ = (
        UniqueConstraint(
            "resident_id",
            "reporting_period_id",
            "start_date",
            name="uq_resident_postings_period_phase",
        ),
        Index(
            "idx_resident_postings_period_resident",
            "reporting_period_id",
            "resident_id",
        ),
        Index(
            "idx_resident_postings_resident_period_dates",
            "resident_id",
            "reporting_period_id",
            "start_date",
            "end_date",
        ),
        Index(
            "idx_resident_postings_period_posting_status",
            "reporting_period_id",
            "posting_code",
            "status",
        ),
        Index(
            "idx_resident_postings_compliance_phase",
            "reporting_period_id",
            "resident_id",
            "posting_code",
            "r_year",
            "status",
        ),
        Index(
            "idx_resident_postings_month_label",
            "reporting_period_id",
            "month_label",
        ),
    )

    resident_id: Mapped[UUID] = mapped_column(ForeignKey("residents.id"), nullable=False)
    posting_code: Mapped[str | None] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=True,
    )
    reporting_period_id: Mapped[UUID] = mapped_column(
        ForeignKey("reporting_periods.id"),
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    month_label: Mapped[str | None] = mapped_column(String(10), nullable=True)
    r_year: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'active'"),
    )
    loa_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    loa_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    loa_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    refresher_training_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    refresher_training_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    refresher_training_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    active_months_weight: Mapped[Decimal] = mapped_column(
        Numeric(3, 1),
        nullable=False,
        server_default=text("1.0"),
    )
    working_days_in_month: Mapped[int | None] = mapped_column(Integer, nullable=True)


class User(UUIDTimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("idx_users_role", "role"),
        Index(
            "idx_users_posting_code",
            "posting_code",
            postgresql_where=text("posting_code IS NOT NULL"),
        ),
        Index(
            "idx_users_programme_scope_gin",
            "programme_scope",
            postgresql_using="gin",
        ),
    )

    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    posting_code: Mapped[str | None] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=True,
    )
    programme_scope: Mapped[list[str] | None] = mapped_column(
        ARRAY(String()),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
