from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDTimestampMixin


class SessionType(UUIDTimestampMixin, Base):
    __tablename__ = "session_types"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    duration_hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    duration_label: Mapped[str | None] = mapped_column(String(10), nullable=True)


class TeachingTarget(UUIDTimestampMixin, Base):
    __tablename__ = "teaching_targets"
    __table_args__ = (
        CheckConstraint(
            "monthly_target >= 0",
            name="ck_teaching_targets_monthly_target_nonnegative",
        ),
        UniqueConstraint(
            "reporting_period_id",
            "programme_code",
            "r_year",
            "posting_code",
            "session_type_id",
            name="uq_teaching_targets_scope",
        ),
        UniqueConstraint(
            "id",
            "reporting_period_id",
            "programme_code",
            "posting_code",
            "r_year",
            name="uq_teaching_targets_id_mapping_scope",
        ),
        Index(
            "idx_teaching_targets_lookup",
            "reporting_period_id",
            "programme_code",
            "posting_code",
            "r_year",
        ),
        Index(
            "idx_teaching_targets_reallocation",
            "reporting_period_id",
            "programme_code",
            "posting_code",
            "tag",
            postgresql_where=text("is_reallocatable = true"),
        ),
    )

    reporting_period_id: Mapped[UUID] = mapped_column(
        ForeignKey("reporting_periods.id"),
        nullable=False,
    )
    programme_code: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("programmes.code"),
        nullable=False,
    )
    r_year: Mapped[str] = mapped_column(String(10), nullable=False)
    posting_code: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=False,
    )
    session_type_id: Mapped[UUID] = mapped_column(
        ForeignKey("session_types.id"),
        nullable=False,
    )
    monthly_target: Mapped[int] = mapped_column(nullable=False)
    is_tracked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    is_reallocatable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    tag: Mapped[str | None] = mapped_column(String(10), nullable=True)


class TeachingName(UUIDTimestampMixin, Base):
    __tablename__ = "teaching_names"
    __table_args__ = (
        UniqueConstraint(
            "reporting_period_id",
            "programme_code",
            "normalized_name",
            name="uq_teaching_names_pool_normalized_name",
        ),
        UniqueConstraint(
            "id",
            "reporting_period_id",
            "programme_code",
            name="uq_teaching_names_id_pool",
        ),
        CheckConstraint(
            "btrim(display_name) <> ''",
            name="ck_teaching_names_display_name_nonblank",
        ),
        CheckConstraint(
            "btrim(normalized_name) <> ''",
            name="ck_teaching_names_normalized_name_nonblank",
        ),
        CheckConstraint(
            "revision > 0",
            name="ck_teaching_names_revision_positive",
        ),
        Index(
            "idx_teaching_names_active_pool",
            "reporting_period_id",
            "programme_code",
            "display_name",
            postgresql_where=text("is_active = true"),
        ),
        Index(
            "idx_teaching_names_normalized_lookup",
            "reporting_period_id",
            "programme_code",
            "normalized_name",
        ),
    )

    reporting_period_id: Mapped[UUID] = mapped_column(
        ForeignKey("reporting_periods.id"),
        nullable=False,
    )
    programme_code: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("programmes.code"),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    deactivated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class TeachingNameMapping(UUIDTimestampMixin, Base):
    __tablename__ = "teaching_name_mappings"
    __table_args__ = (
        UniqueConstraint(
            "teaching_name_id",
            "posting_code",
            "r_year",
            name="uq_teaching_name_mappings_identity",
        ),
        ForeignKeyConstraint(
            ["teaching_name_id", "reporting_period_id", "programme_code"],
            [
                "teaching_names.id",
                "teaching_names.reporting_period_id",
                "teaching_names.programme_code",
            ],
            name="fk_teaching_name_mappings_name_pool",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            [
                "teaching_target_id",
                "reporting_period_id",
                "programme_code",
                "posting_code",
                "r_year",
            ],
            [
                "teaching_targets.id",
                "teaching_targets.reporting_period_id",
                "teaching_targets.programme_code",
                "teaching_targets.posting_code",
                "teaching_targets.r_year",
            ],
            name="fk_teaching_name_mappings_target_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "revision > 0",
            name="ck_teaching_name_mappings_revision_positive",
        ),
        Index(
            "idx_teaching_name_mappings_pending_scope",
            "reporting_period_id",
            "programme_code",
            "posting_code",
            "r_year",
            postgresql_where=text("teaching_target_id IS NULL"),
        ),
        Index(
            "idx_teaching_name_mappings_mapped_scope",
            "reporting_period_id",
            "programme_code",
            "posting_code",
            "r_year",
            "teaching_target_id",
            postgresql_where=text("teaching_target_id IS NOT NULL"),
        ),
        Index(
            "idx_teaching_name_mappings_target_reverse",
            "teaching_target_id",
            postgresql_where=text("teaching_target_id IS NOT NULL"),
        ),
        Index(
            "idx_teaching_name_mappings_name",
            "teaching_name_id",
        ),
    )

    teaching_name_id: Mapped[UUID] = mapped_column(nullable=False)
    reporting_period_id: Mapped[UUID] = mapped_column(nullable=False)
    programme_code: Mapped[str] = mapped_column(String(20), nullable=False)
    posting_code: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=False,
    )
    r_year: Mapped[str] = mapped_column(String(10), nullable=False)
    teaching_target_id: Mapped[UUID | None] = mapped_column(nullable=True)
    revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )


class EventSeries(UUIDTimestampMixin, Base):
    __tablename__ = "event_series"
    __table_args__ = (
        Index("idx_event_series_posting", "posting_code"),
    )

    posting_code: Mapped[str | None] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=True,
    )
    recurrence_pattern: Mapped[str | None] = mapped_column(String(20), nullable=True)
    recurrence_interval: Mapped[int] = mapped_column(
        nullable=False,
        server_default=text("1"),
    )
    days_of_week: Mapped[list[str] | None] = mapped_column(ARRAY(String()), nullable=True)
    end_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_after_count: Mapped[int | None] = mapped_column(nullable=True)


class TeachingEvent(UUIDTimestampMixin, Base):
    __tablename__ = "teaching_events"
    __table_args__ = (
        CheckConstraint(
            "("
            "NOT is_adhoc "
            "AND ("
            "created_by_role IS NULL "
            "OR created_by_role IN ('secretary', 'programme_pc')"
            ") "
            "AND created_by_resident_id IS NULL "
            "AND created_by_external_resident_id IS NULL"
            ") OR ("
            "is_adhoc "
            "AND created_by_role = 'resident' "
            "AND created_for_programme_code IS NULL "
            "AND series_id IS NULL "
            "AND created_by_resident_id IS NOT NULL "
            "AND created_by_external_resident_id IS NULL"
            ") OR ("
            "is_adhoc "
            "AND created_by_role = 'external_resident' "
            "AND created_for_programme_code IS NULL "
            "AND series_id IS NULL "
            "AND created_by_resident_id IS NULL "
            "AND created_by_external_resident_id IS NOT NULL"
            ")",
            name="ck_teaching_events_adhoc_creator_family",
        ),
        CheckConstraint(
            "NOT (teaching_name_id IS NOT NULL "
            "AND global_session_type_id IS NOT NULL)",
            name="ck_teaching_events_source_identity_exclusive",
        ),
        CheckConstraint(
            "(source_programme_code IS NULL) "
            "= (source_reporting_period_id IS NULL)",
            name="ck_teaching_events_source_scope_pair",
        ),
        CheckConstraint(
            "teaching_name_id IS NULL "
            "OR (source_programme_code IS NOT NULL "
            "AND source_reporting_period_id IS NOT NULL)",
            name="ck_teaching_events_pool_source_scope_required",
        ),
        CheckConstraint(
            "NOT is_adhoc OR ("
            "teaching_name_id IS NULL "
            "AND global_session_type_id IS NULL "
            "AND source_programme_code IS NULL "
            "AND source_reporting_period_id IS NULL)",
            name="ck_teaching_events_adhoc_has_no_scheduled_source",
        ),
        CheckConstraint(
            "global_session_type_id IS NULL "
            "OR (source_programme_code IS NULL "
            "AND source_reporting_period_id IS NULL)",
            name="ck_teaching_events_global_has_no_pool_scope",
        ),
        Index(
            "idx_teaching_events_posting_date",
            "posting_code",
            "event_date",
        ),
        Index(
            "idx_teaching_events_series",
            "series_id",
            postgresql_where=text("series_id IS NOT NULL"),
        ),
        Index(
            "idx_teaching_events_name_date",
            "teaching_name",
            "event_date",
        ),
        Index(
            "idx_teaching_events_adhoc",
            "is_adhoc",
            "event_date",
            postgresql_where=text("is_adhoc = true"),
        ),
        Index(
            "idx_teaching_events_programme_date",
            "created_for_programme_code",
            "event_date",
            postgresql_where=text("created_for_programme_code IS NOT NULL"),
        ),
        Index(
            "idx_teaching_events_created_by_resident",
            "created_by_resident_id",
            postgresql_where=text("created_by_resident_id IS NOT NULL"),
        ),
        Index(
            "idx_teaching_events_created_by_external_resident",
            "created_by_external_resident_id",
            postgresql_where=text("created_by_external_resident_id IS NOT NULL"),
        ),
        Index(
            "idx_teaching_events_teaching_name",
            "teaching_name_id",
            postgresql_where=text("teaching_name_id IS NOT NULL"),
        ),
        Index(
            "idx_teaching_events_global_session_type",
            "global_session_type_id",
            postgresql_where=text("global_session_type_id IS NOT NULL"),
        ),
        Index(
            "idx_teaching_events_source_scope",
            "source_reporting_period_id",
            "source_programme_code",
            postgresql_where=text("source_reporting_period_id IS NOT NULL"),
        ),
    )

    posting_code: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("posting_codes.code"),
        nullable=False,
    )
    created_for_programme_code: Mapped[str | None] = mapped_column(
        String(20),
        ForeignKey("programmes.code"),
        nullable=True,
    )
    teaching_name: Mapped[str] = mapped_column(String(200), nullable=False)
    details_of_session: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    duration_hours: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    session_type_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("session_types.id"),
        nullable=True,
    )
    teaching_name_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("teaching_names.id", ondelete="SET NULL"),
        nullable=True,
    )
    global_session_type_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("global_session_types.id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_programme_code: Mapped[str | None] = mapped_column(
        String(20),
        ForeignKey("programmes.code", ondelete="RESTRICT"),
        nullable=True,
    )
    source_reporting_period_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reporting_periods.id", ondelete="RESTRICT"),
        nullable=True,
    )
    series_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("event_series.id"),
        nullable=True,
    )
    cme_points_awarded: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    smc_event_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_adhoc: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    created_by_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_by_resident_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("residents.id"),
        nullable=True,
    )
    created_by_external_resident_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("external_residents.id"),
        nullable=True,
    )


class GlobalSessionType(UUIDTimestampMixin, Base):
    __tablename__ = "global_session_types"
    __table_args__ = (
        Index(
            "idx_global_session_types_active_name",
            "name",
            postgresql_where=text("is_active = true"),
        ),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    duration_hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
