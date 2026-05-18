from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


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
