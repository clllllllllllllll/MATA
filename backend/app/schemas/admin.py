from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReportingPeriodResponse(BaseModel):
    id: UUID
    label: str
    start_date: date
    end_date: date
    status: str
    created_at: datetime
    updated_at: datetime


class PublicHolidayResponse(BaseModel):
    id: UUID
    holiday_date: date
    name: str | None
    day_of_week: str | None
    year: int | None
    created_at: datetime
    updated_at: datetime


class ProgrammeResponse(BaseModel):
    id: UUID
    code: str
    name: str
    classification: str | None
    ay_date_category: str
    r_year_required: bool
    is_subspecialty: bool
    rdb_alias: str | None
    created_at: datetime
    updated_at: datetime


class LoaTypeResponse(BaseModel):
    id: UUID
    code: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class MultiPostingRuleResponse(BaseModel):
    id: UUID
    programme_code: str
    posting_code_1: str
    posting_code_2: str | None
    rule_type: str
    combined_label: str | None
    main_posting_code: str | None
    exclusion_code: str | None
    created_at: datetime
    updated_at: datetime


class PostingGroupResponse(BaseModel):
    id: UUID
    group_code: str
    posting_code: str
    programme_code: str
    created_at: datetime
    updated_at: datetime


class WeekendExceptionResponse(BaseModel):
    id: UUID
    programme_code: str | None
    posting_code: str | None
    day_type: str
    start_time_min: time | None
    end_time_max: time | None
    session_type_id: UUID | None
    session_name_pattern: str | None
    mutates_to_session_type_id: UUID | None
    adjusted_duration_hours: Decimal | None
    created_at: datetime
    updated_at: datetime


class GlobalSessionTypeResponse(BaseModel):
    id: UUID
    name: str
    duration_hours: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UploadLogResponse(BaseModel):
    id: UUID
    upload_type: str
    uploaded_by: UUID
    uploaded_at: datetime
    reporting_period_id: UUID | None
    programme_code: str | None
    status: str
    summary: dict
    created_at: datetime
    updated_at: datetime


class ResidentResponse(BaseModel):
    id: UUID
    employee_code: str | None
    name: str
    mcr: str
    classification: str | None
    programme_code: str | None
    r_year: str | None
    reg_type: str | None
    base_institution: str | None
    email: str | None
    phone: str | None
    status: str
    employer_tag: str | None
    created_at: datetime
    updated_at: datetime


class ResidentPostingResponse(BaseModel):
    id: UUID
    resident_id: UUID
    posting_code: str | None
    reporting_period_id: UUID
    start_date: date
    end_date: date
    day_part: str | None
    month_label: str | None
    r_year: str
    status: str
    loa_type: str | None
    loa_start_date: date | None
    loa_end_date: date | None
    refresher_training_type: str | None
    refresher_training_start: date | None
    refresher_training_end: date | None
    active_months_weight: Decimal
    working_days_in_month: int | None
    created_at: datetime
    updated_at: datetime
    resident_mcr: str | None = None
    resident_name: str | None = None
    resident_programme_code: str | None = None


class PostingCodeResponse(BaseModel):
    id: UUID
    code: str
    display_name: str | None
    institution: str | None
    department: str | None
    billing_dept: str | None
    is_emergency: bool
    created_at: datetime
    updated_at: datetime


class SessionTypeResponse(BaseModel):
    id: UUID
    name: str
    duration_hours: Decimal
    duration_label: str | None
    created_at: datetime
    updated_at: datetime


class TeachingTargetResponse(BaseModel):
    id: UUID
    reporting_period_id: UUID
    programme_code: str
    r_year: str
    posting_code: str
    session_type_id: UUID
    monthly_target: int
    is_tracked: bool
    is_reallocatable: bool
    tag: str | None
    details_of_training: str | None
    created_at: datetime
    updated_at: datetime


class TeachingNameCatalogueResponse(BaseModel):
    id: UUID
    keyword: str
    session_type_id: UUID
    posting_code: str
    programme_code: str
    r_year: str
    reporting_period_id: UUID
    duration_hours: Decimal
    is_tracked: bool
    created_at: datetime
    updated_at: datetime


class AcademicMonthBoundaryResponse(BaseModel):
    id: UUID
    academic_year_label: str
    ay_date_category: str
    month_label: str
    start_date: date
    end_date: date
    upload_id: UUID | None
    created_at: datetime
    updated_at: datetime


class FormF1RecordResponse(BaseModel):
    id: UUID
    reporting_period_id: UUID
    mcr: str
    month_label: str
    status_raw: str
    is_active: bool
    promotion_date: date | None
    upload_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ReportingPeriodCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=30)
    start_date: date
    end_date: date

    @field_validator("label")
    @classmethod
    def _trim_label(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("label is required")
        return trimmed

    @model_validator(mode="after")
    def _validate_date_range(self) -> "ReportingPeriodCreateRequest":
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class ReportingPeriodUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=30)
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None

    @field_validator("label")
    @classmethod
    def _trim_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("label is required")
        return trimmed

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        lowered = value.strip().lower()
        if lowered not in {"open", "closed"}:
            raise ValueError("status must be one of: open, closed")
        return lowered


class PublicHolidayUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holiday_date: date
    name: str = Field(min_length=1, max_length=100)
    day_of_week: str | None = Field(default=None, max_length=10)
    year: int | None = None

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name is required")
        return trimmed

    @field_validator("day_of_week")
    @classmethod
    def _trim_day_of_week(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class ProgrammeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    r_year_required: bool | None = None
    is_subspecialty: bool | None = None
    rdb_alias: str | None = Field(default=None, max_length=100)

    @field_validator("rdb_alias")
    @classmethod
    def _trim_alias(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class LoaTypeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=100)

    @field_validator("code", "description")
    @classmethod
    def _trim_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class LoaTypeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=100)

    @field_validator("code", "description")
    @classmethod
    def _trim_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class MultiPostingRuleMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    programme_code: str = Field(min_length=1, max_length=20)
    posting_code_1: str = Field(min_length=1, max_length=50)
    posting_code_2: str | None = Field(default=None, max_length=50)
    rule_type: str = Field(min_length=1, max_length=20)
    combined_label: str | None = Field(default=None, max_length=100)
    main_posting_code: str | None = Field(default=None, max_length=50)
    exclusion_code: str | None = Field(default=None, max_length=50)

    @field_validator(
        "programme_code",
        "posting_code_1",
        "posting_code_2",
        "rule_type",
        "combined_label",
        "main_posting_code",
        "exclusion_code",
    )
    @classmethod
    def _trim_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class PostingGroupMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_code: str = Field(min_length=1, max_length=100)
    posting_code: str = Field(min_length=1, max_length=50)
    programme_code: str = Field(min_length=1, max_length=20)

    @field_validator("group_code", "posting_code", "programme_code")
    @classmethod
    def _trim_fields(cls, value: str) -> str:
        return value.strip()


class WeekendExceptionMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    programme_code: str | None = Field(default=None, max_length=20)
    posting_code: str | None = Field(default=None, max_length=50)
    day_type: str = Field(min_length=1, max_length=3)
    start_time_min: time | None = None
    end_time_max: time | None = None
    session_type_id: UUID | None = None
    session_name_pattern: str | None = Field(default=None, max_length=100)
    mutates_to_session_type_id: UUID | None = None
    adjusted_duration_hours: Decimal | None = Field(default=None, ge=0)

    @field_validator("programme_code", "posting_code", "session_name_pattern")
    @classmethod
    def _trim_optional_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @field_validator("day_type")
    @classmethod
    def _normalise_day_type(cls, value: str) -> str:
        lowered = value.strip().lower()
        if lowered not in {"sat", "sun"}:
            raise ValueError("day_type must be one of: sat, sun")
        return lowered


class GlobalSessionTypeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    duration_hours: Decimal = Field(gt=0)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str) -> str:
        return value.strip()


class GlobalSessionTypeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    duration_hours: Decimal | None = Field(default=None, gt=0)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()
