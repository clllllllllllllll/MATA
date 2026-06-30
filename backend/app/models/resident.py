from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
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
            "day_part",
            name="uq_resident_postings_period_phase",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "day_part IS NULL OR day_part IN ('AM', 'PM')",
            name="ck_resident_postings_day_part",
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
    day_part: Mapped[str | None] = mapped_column(String(2), nullable=True)
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


class ExternalResident(UUIDTimestampMixin, Base):
    __tablename__ = "external_residents"
    __table_args__ = (
        CheckConstraint(
            "home_cluster IN ('NUH', 'SingHealth')",
            name="ck_external_residents_home_cluster",
        ),
        Index("idx_external_residents_mcr", "mcr", unique=True),
        Index(
            "idx_external_residents_current_posting",
            "current_nhg_posting_code",
            "status",
        ),
        Index("idx_external_residents_home_cluster", "home_cluster"),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    mcr: Mapped[str] = mapped_column(String(20), nullable=False)
    home_cluster: Mapped[str] = mapped_column(String(20), nullable=False)
    current_nhg_posting_code: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'active'"),
    )


class ExternalResidentPosting(UUIDTimestampMixin, Base):
    __tablename__ = "external_resident_postings"
    __table_args__ = (
        Index(
            "idx_external_resident_postings_external_current",
            "external_resident_id",
            "is_current",
        ),
        Index(
            "idx_external_resident_postings_external_dates",
            "external_resident_id",
            "start_date",
            "end_date",
        ),
    )

    external_resident_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_residents.id"),
        nullable=False,
    )
    posting_code: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )


class User(UUIDTimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "admin_level IN ('programme', 'master')",
            name="ck_users_admin_level",
        ),
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
    admin_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'programme'"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
