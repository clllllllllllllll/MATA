from __future__ import annotations

from datetime import date, time
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
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDTimestampMixin


class PostingCode(UUIDTimestampMixin, Base):
    __tablename__ = "posting_codes"
    __table_args__ = (
        Index(
            "idx_posting_codes_institution_department",
            "institution",
            "department",
        ),
        Index(
            "idx_posting_codes_supports_secretary_events",
            "supports_secretary_events",
        ),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    institution: Mapped[str | None] = mapped_column(String(50), nullable=True)
    department: Mapped[str | None] = mapped_column(String(50), nullable=True)
    billing_dept: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_emergency: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    supports_secretary_events: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )


class ProgrammeInstitutionPostingMap(UUIDTimestampMixin, Base):
    __tablename__ = "programme_institution_posting_map"
    __table_args__ = (
        UniqueConstraint(
            "programme_code",
            "institution_code",
            name="uq_programme_institution_posting_map_scope",
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'inactive')",
            name="ck_programme_institution_posting_map_status",
        ),
        CheckConstraint(
            "status <> 'active' OR posting_code IS NOT NULL",
            name="ck_programme_institution_posting_map_active_posting",
        ),
        Index(
            "idx_programme_institution_posting_map_institution_status",
            "institution_code",
            "status",
        ),
        Index(
            "idx_programme_institution_posting_map_programme_status",
            "programme_code",
            "status",
        ),
        Index(
            "idx_programme_institution_posting_map_posting",
            "posting_code",
            postgresql_where=text("posting_code IS NOT NULL"),
        ),
    )

    programme_code: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("programmes.code"),
        nullable=False,
    )
    institution_code: Mapped[str] = mapped_column(String(20), nullable=False)
    posting_code: Mapped[str | None] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )


class PublicHoliday(UUIDTimestampMixin, Base):
    __tablename__ = "public_holidays"
    __table_args__ = (
        Index(
            "idx_public_holidays_year",
            text("EXTRACT(YEAR FROM holiday_date)"),
        ),
    )

    holiday_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    day_of_week: Mapped[str | None] = mapped_column(String(10), nullable=True)
    year: Mapped[int | None] = mapped_column(nullable=True)


class MultiPostingRule(UUIDTimestampMixin, Base):
    __tablename__ = "multi_posting_rules"
    __table_args__ = (
        UniqueConstraint(
            "programme_code",
            "posting_code_1",
            "posting_code_2",
            "rule_type",
            name="uq_multi_posting_rules_scope",
        ),
        Index(
            "idx_multi_posting_rules_lookup",
            "programme_code",
            "posting_code_1",
            "posting_code_2",
            "rule_type",
        ),
        Index(
            "idx_multi_posting_rules_reverse_lookup",
            "programme_code",
            "posting_code_2",
            "posting_code_1",
            "rule_type",
        ),
    )

    programme_code: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("programmes.code"),
        nullable=False,
    )
    posting_code_1: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=False,
    )
    posting_code_2: Mapped[str | None] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=True,
    )
    rule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    combined_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    main_posting_code: Mapped[str | None] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=True,
    )
    exclusion_code: Mapped[str | None] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=True,
    )


class PostingGroup(UUIDTimestampMixin, Base):
    __tablename__ = "posting_groups"
    __table_args__ = (
        UniqueConstraint(
            "posting_code",
            "programme_code",
            name="uq_posting_groups_posting_programme",
        ),
        Index(
            "idx_posting_groups_posting_programme",
            "posting_code",
            "programme_code",
        ),
        Index(
            "idx_posting_groups_group_programme",
            "group_code",
            "programme_code",
        ),
    )

    group_code: Mapped[str] = mapped_column(String(100), nullable=False)
    posting_code: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=False,
    )
    programme_code: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("programmes.code"),
        nullable=False,
    )


class SecretaryProgrammePool(UUIDTimestampMixin, Base):
    __tablename__ = "secretary_programme_pools"
    __table_args__ = (
        UniqueConstraint(
            "posting_code",
            "programme_code",
            name="uq_secretary_programme_pools_posting_programme",
        ),
        Index(
            "idx_secretary_programme_pools_posting_active",
            "posting_code",
            "is_active",
        ),
        Index(
            "idx_secretary_programme_pools_programme_active",
            "programme_code",
            "is_active",
        ),
    )

    posting_code: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=False,
    )
    programme_code: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("programmes.code"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )


class WeekendException(UUIDTimestampMixin, Base):
    __tablename__ = "weekend_exceptions"
    __table_args__ = (
        Index(
            "idx_weekend_exceptions_lookup",
            "programme_code",
            "posting_code",
            "day_type",
        ),
        Index(
            "idx_weekend_exceptions_session_type",
            "session_type_id",
            postgresql_where=text("session_type_id IS NOT NULL"),
        ),
    )

    programme_code: Mapped[str | None] = mapped_column(
        String(20),
        ForeignKey("programmes.code"),
        nullable=True,
    )
    posting_code: Mapped[str | None] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=True,
    )
    day_type: Mapped[str] = mapped_column(String(3), nullable=False)
    start_time_min: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time_max: Mapped[time | None] = mapped_column(Time, nullable=True)
    session_type_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("session_types.id"),
        nullable=True,
    )
    session_name_pattern: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mutates_to_session_type_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("session_types.id"),
        nullable=True,
    )
    adjusted_duration_hours: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2),
        nullable=True,
    )
