from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.data_revalidation import DataRevalidationImpactSummary
from app.services.reporting_period_status import normalise_reporting_period_status


class ReportingPeriodResponse(BaseModel):
    id: UUID
    label: str
    start_date: date
    end_date: date
    status: str
    activate_on: date | None = None
    deactivate_on: date | None = None
    created_at: datetime
    updated_at: datetime


class ReportingPeriodMutationResponse(ReportingPeriodResponse):
    data_revalidation: DataRevalidationImpactSummary


class PublicHolidayResponse(BaseModel):
    id: UUID
    holiday_date: date
    name: str | None
    day_of_week: str | None
    year: int | None
    created_at: datetime
    updated_at: datetime


class PublicHolidayMutationResponse(PublicHolidayResponse):
    data_revalidation: DataRevalidationImpactSummary


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


class ProgrammeMutationResponse(ProgrammeResponse):
    data_revalidation: DataRevalidationImpactSummary


class LoaTypeResponse(BaseModel):
    id: UUID
    code: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class LoaTypeMutationResponse(LoaTypeResponse):
    data_revalidation: DataRevalidationImpactSummary


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


class MultiPostingRuleMutationResponseModel(MultiPostingRuleResponse):
    data_revalidation: DataRevalidationImpactSummary


class PostingGroupResponse(BaseModel):
    id: UUID
    group_code: str
    posting_code: str
    programme_code: str
    created_at: datetime
    updated_at: datetime


class PostingGroupMutationResponse(PostingGroupResponse):
    data_revalidation: DataRevalidationImpactSummary


class WeekendExceptionResponse(BaseModel):
    id: UUID
    programme_code: str | None
    posting_code: str | None
    day_type: str
    start_time_min: time | None
    end_time_max: time | None
    session_type_id: UUID | None
    session_type_name: str | None = None
    session_name_pattern: str | None
    mutates_to_session_type_id: UUID | None
    mutates_to_session_type_name: str | None = None
    adjusted_duration_hours: Decimal | None
    created_at: datetime
    updated_at: datetime


class WeekendExceptionMutationResponse(WeekendExceptionResponse):
    data_revalidation: DataRevalidationImpactSummary


class GlobalSessionTypeResponse(BaseModel):
    id: UUID
    name: str
    duration_hours: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime


class GlobalSessionTypeMutationResponse(GlobalSessionTypeResponse):
    data_revalidation: DataRevalidationImpactSummary


class ConfigMutationDeleteResponse(BaseModel):
    entity_type: str
    entity_id: str
    deleted: bool = True
    data_revalidation: DataRevalidationImpactSummary


class UploadLogListItem(BaseModel):
    id: UUID
    upload_type: str
    uploaded_at: datetime
    uploaded_by: UUID | None = None
    uploaded_by_name: str | None = None
    status: str
    reporting_period_id: UUID | None = None
    reporting_period_label: str | None = None
    programme_code: str | None = None
    warning_count: int
    error_count: int
    summary_counts: dict[str, int]


class UploadLogListResponse(BaseModel):
    items: list[UploadLogListItem]
    total: int
    limit: int
    offset: int


class UploadLogDetailResponse(UploadLogListItem):
    summary: Any
    original_filename: str | None = None


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


class UploadWarningResponse(BaseModel):
    issue_id: str | None = None
    warning_issue_id: str | None = None
    status: str | None = None
    warning_id: str
    upload_warning_id: str | None = None
    dedupe_key: str
    upload_log_id: str
    upload_type: str
    uploaded_at: datetime
    uploaded_by: str | None = None
    reporting_period_id: str | None = None
    programme_code: str | None = None
    warning_type: str
    severity: str
    message: str
    resident_name: str | None = None
    mcr: str | None = None
    month_label: str | None = None
    sheet_name: str | None = None
    row_number: int | None = None
    cell_ref: str | None = None
    posting_codes: list[str] = Field(default_factory=list)
    session_type: str | None = None
    count: int | None = None
    source_label: str | None = None
    raw_payload: Any = None
    suggested_action: str | None = None
    seen_count: int = 1
    first_seen_at: datetime
    last_seen_at: datetime
    upload_log_ids: list[str] = Field(default_factory=list)
    first_seen_upload_log_id: str | None = None
    last_seen_upload_log_id: str | None = None
    latest_upload_warning_id: str | None = None
    latest_source_trace: dict[str, Any] | None = None
    reappeared: bool = False


class UploadWarningOccurrenceResponse(BaseModel):
    id: str
    issue_id: str
    source_trace: dict[str, Any] | None = None
    upload_log_id: str
    upload_type: str | None = None
    uploaded_at: datetime | None = None
    warning_type: str
    severity: str
    reporting_period_id: str | None = None
    programme_code: str | None = None
    resident_id: str | None = None
    mcr: str | None = None
    resident_name: str | None = None
    month_label: str | None = None
    sheet_name: str | None = None
    row_number: int | None = None
    cell_ref: str | None = None
    source_table: str | None = None
    source_record_id: str | None = None
    source_payload: Any = Field(default_factory=dict)
    message: str
    suggested_action: str | None = None
    fingerprint: str
    created_at: datetime


class UploadWarningIssueDetailResponse(BaseModel):
    issue_id: str
    warning_issue_id: str
    fingerprint: str
    warning_type: str
    severity: str
    status: str
    reappeared: bool = False
    first_seen_upload_log_id: str | None = None
    last_seen_upload_log_id: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    latest_upload_warning_id: str | None = None
    latest_source_trace: dict[str, Any] | None = None
    latest_source_payload: Any = Field(default_factory=dict)
    message: str | None = None
    suggested_action: str | None = None
    resident_name: str | None = None
    reporting_period_id: str | None = None
    programme_code: str | None = None
    resident_id: str | None = None
    mcr: str | None = None
    month_label: str | None = None
    resolution_note: str | None = None
    resolution_source_type: str | None = None
    resolution_source_id: str | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    occurrences: list[UploadWarningOccurrenceResponse] = Field(default_factory=list)


class UploadWarningActionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class UploadWarningIssueActionResponse(BaseModel):
    issue_id: str
    status: str
    previous_status: str
    new_status: str
    resolution_note: str | None = None
    note: str | None = None
    resolved_by: str | None = None
    actor_user_id: str | None = None
    resolved_at: datetime | None = None
    updated_at: datetime | None = None


class RDBSourceCellWarningPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replacement_raw_cell_value: Any = None
    upload_warning_id: UUID | None = None
    expected_latest_upload_warning_id: UUID | None = None
    expected_fingerprint: str | None = None


class RDBSourceCellWarningApplyRequest(RDBSourceCellWarningPreviewRequest):
    correction_reason: str = Field(min_length=1, max_length=500)

    @field_validator("correction_reason")
    @classmethod
    def _trim_reason(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("correction_reason is required")
        return trimmed


class RDBSourceCellWarningPreviewResponse(BaseModel):
    warning_issue_id: str
    upload_warning_id: str | None = None
    latest_upload_warning_id: str | None = None
    fingerprint: str
    source_trace: dict[str, Any]
    source_payload: Any = Field(default_factory=dict)
    original_warning_type: str
    original_warning_status: str
    replacement_raw_cell_value: Any = None
    normalized_cell_value: str
    parsed_candidate_rows: list[dict[str, Any]]
    parser_warnings: list[Any] = Field(default_factory=list)
    parser_errors: list[Any] = Field(default_factory=list)
    apply_allowed: bool
    data_revalidation: DataRevalidationImpactSummary | None = None
    suggested_next_action: str
    next_actions: list[str] = Field(default_factory=list)


class RDBSourceCellWarningApplyResponse(BaseModel):
    warning_issue_id: str
    upload_warning_id: str | None = None
    latest_upload_warning_id: str | None = None
    fingerprint: str
    source_trace: dict[str, Any]
    source_payload: Any = Field(default_factory=dict)
    original_warning_type: str
    warning_issue_status: str
    replacement_raw_cell_value: Any = None
    normalized_cell_value: str
    before_rows: list[dict[str, Any]]
    after_rows: list[dict[str, Any]]
    replacement_summary: dict[str, int] = Field(default_factory=dict)
    parser_warnings: list[Any] = Field(default_factory=list)
    parser_errors: list[Any] = Field(default_factory=list)
    audit_log_id: UUID
    entity_type: str
    entity_id: UUID | None = None
    updated_fields: list[str]
    data_revalidation: DataRevalidationImpactSummary | None = None
    suggested_next_action: str
    next_actions: list[str] = Field(default_factory=list)


class ParsedResidentRow(BaseModel):
    id: UUID
    employee_code: str | None = None
    name: str
    mcr: str
    programme_code: str | None = None
    r_year: str | None = None
    classification: str | None = None
    reg_type: str | None = None
    base_institution: str | None = None
    email: str | None = None
    phone: str | None = None
    employer_tag: str | None = None
    status: str | None = None
    updated_at: datetime | None = None


class ParsedResidentListResponse(BaseModel):
    items: list[ParsedResidentRow]
    total: int
    limit: int
    offset: int


class ParsedResidentPostingRow(BaseModel):
    id: UUID
    resident_id: UUID
    resident_name: str | None = None
    mcr: str | None = None
    programme_code: str | None = None
    posting_code: str | None = None
    reporting_period_id: UUID
    reporting_period_label: str | None = None
    start_date: date
    end_date: date
    day_part: str | None = None
    month_label: str | None = None
    r_year: str
    status: str
    loa_type: str | None = None
    loa_start_date: date | None = None
    loa_end_date: date | None = None
    refresher_training_type: str | None = None
    refresher_training_start: date | None = None
    refresher_training_end: date | None = None
    active_months_weight: Decimal | None = None
    working_days_in_month: int | None = None
    updated_at: datetime | None = None


class ParsedResidentPostingListResponse(BaseModel):
    items: list[ParsedResidentPostingRow]
    total: int
    limit: int
    offset: int


class ParsedTeachingTargetRow(BaseModel):
    id: UUID
    reporting_period_id: UUID
    reporting_period_label: str | None = None
    programme_code: str
    r_year: str
    posting_code: str
    session_type_id: UUID
    session_type_name: str | None = None
    duration_hours: Decimal | None = None
    monthly_target: int
    is_tracked: bool
    is_reallocatable: bool
    tag: str | None = None
    details_of_training: str | None = None
    updated_at: datetime | None = None


class ParsedTeachingTargetListResponse(BaseModel):
    items: list[ParsedTeachingTargetRow]
    total: int
    limit: int
    offset: int


class ParsedTeachingNameCatalogueRow(BaseModel):
    id: UUID
    keyword: str
    programme_code: str
    posting_code: str
    r_year: str
    reporting_period_id: UUID
    reporting_period_label: str | None = None
    session_type_id: UUID
    session_type_name: str | None = None
    duration_hours: Decimal
    is_tracked: bool


class ParsedTeachingNameCatalogueListResponse(BaseModel):
    items: list[ParsedTeachingNameCatalogueRow]
    total: int
    limit: int
    offset: int


class ParsedFormF1RecordRow(BaseModel):
    id: UUID
    reporting_period_id: UUID
    reporting_period_label: str | None = None
    mcr: str
    resident_name: str | None = None
    programme_code: str | None = None
    month_label: str
    status_raw: str
    is_active: bool
    promotion_date: date | None = None
    upload_id: UUID | None = None
    updated_at: datetime | None = None


class ParsedFormF1RecordListResponse(BaseModel):
    items: list[ParsedFormF1RecordRow]
    total: int
    limit: int
    offset: int


class ParsedPublicHolidayRow(BaseModel):
    id: UUID
    holiday_date: date
    name: str | None = None
    day_of_week: str | None = None
    year: int | None = None


class ParsedPublicHolidayListResponse(BaseModel):
    items: list[ParsedPublicHolidayRow]
    total: int
    limit: int
    offset: int


class ParsedAcademicMonthBoundaryRow(BaseModel):
    id: UUID
    academic_year_label: str
    ay_date_category: Literal["im_subspec", "non_im_subspec"]
    month_label: str
    start_date: date
    end_date: date
    upload_id: UUID | None = None
    updated_at: datetime | None = None


class ParsedDataCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: dict[str, Any]
    correction_reason: str = Field(min_length=1, max_length=500)
    last_seen_updated_at: datetime | None = None

    @field_validator("correction_reason")
    @classmethod
    def _trim_reason(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("correction_reason is required")
        return trimmed

    @field_validator("changes")
    @classmethod
    def _require_changes(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("changes must include at least one field")
        return value


class ParsedDataCorrectionResponse(BaseModel):
    item: dict[str, Any]
    audit_log_id: UUID
    entity_type: str
    entity_id: UUID | None = None
    updated_fields: list[str]
    data_revalidation: DataRevalidationImpactSummary | None = None


class ResidentPostingReplacementRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resident_id: UUID
    posting_code: str | None = None
    reporting_period_id: UUID
    start_date: date
    end_date: date
    day_part: Literal["AM", "PM"] | None = None
    month_label: str | None = None
    r_year: str
    status: str
    loa_type: str | None = None
    loa_start_date: date | None = None
    loa_end_date: date | None = None
    refresher_training_type: str | None = None
    refresher_training_start: date | None = None
    refresher_training_end: date | None = None
    active_months_weight: Decimal = Decimal("1.0")
    working_days_in_month: int | None = None

    @model_validator(mode="after")
    def _validate_dates(self) -> "ResidentPostingReplacementRow":
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class ParsedDataLastSeenRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    updated_at: datetime


class ParsedDataSourceCellMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_log_id: UUID | None = None
    sheet_name: str | None = None
    row_number: int | None = Field(default=None, ge=1)
    cell_ref: str | None = None
    source_column_header: str | None = None
    source_cell_text: str | None = None


class ResidentPostingSourceCellReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    affected_resident_posting_ids: list[UUID]
    replacement_rows: list[ResidentPostingReplacementRow]
    correction_reason: str = Field(min_length=1, max_length=500)
    source: ParsedDataSourceCellMetadata = Field(default_factory=ParsedDataSourceCellMetadata)
    last_seen_rows: list[ParsedDataLastSeenRow]

    @field_validator("correction_reason")
    @classmethod
    def _trim_reason(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("correction_reason is required")
        return trimmed

    @field_validator("affected_resident_posting_ids", "replacement_rows")
    @classmethod
    def _require_non_empty_list(cls, value):
        if not value:
            raise ValueError("must include at least one item")
        return value

    @model_validator(mode="after")
    def _require_token_for_each_affected_row(self) -> "ResidentPostingSourceCellReplaceRequest":
        affected = [str(row_id) for row_id in self.affected_resident_posting_ids]
        tokens = [str(row.id) for row in self.last_seen_rows]
        if len(set(affected)) != len(affected):
            raise ValueError("affected_resident_posting_ids must not contain duplicates")
        if len(set(tokens)) != len(tokens):
            raise ValueError("last_seen_rows must not contain duplicate ids")
        if set(affected) != set(tokens):
            raise ValueError("last_seen_rows must include one token for every affected resident posting")
        return self


class ParsedDataSourceCellReplaceResponse(BaseModel):
    before_rows: list[dict[str, Any]]
    after_rows: list[dict[str, Any]]
    audit_log_id: UUID
    entity_type: str
    entity_id: UUID | None = None
    updated_fields: list[str]
    data_revalidation: DataRevalidationImpactSummary | None = None


class ParsedDataCorrectionHistoryRow(BaseModel):
    id: UUID
    created_at: datetime
    actor_user_id: UUID | None = None
    actor_role: str
    actor_name: str
    action: str
    entity_type: str
    entity_id: UUID | None = None
    correction_reason: str | None = None
    before_json: Any = None
    after_json: Any = None
    metadata_json: Any = None


class ParsedDataCorrectionHistoryListResponse(BaseModel):
    items: list[ParsedDataCorrectionHistoryRow]
    total: int
    limit: int
    offset: int


class ParsedAcademicMonthBoundaryListResponse(BaseModel):
    items: list[ParsedAcademicMonthBoundaryRow]
    total: int
    limit: int
    offset: int


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
    status: str | None = None
    activate_on: date | None = None
    deactivate_on: date | None = None

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
        if (
            self.activate_on is not None
            and self.deactivate_on is not None
            and self.activate_on > self.deactivate_on
        ):
            raise ValueError("activate_on must be on or before deactivate_on")
        return self

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalise_reporting_period_status(value)


class ReportingPeriodUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=30)
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None
    activate_on: date | None = None
    deactivate_on: date | None = None

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
        return normalise_reporting_period_status(value)

    @model_validator(mode="after")
    def _validate_transition_order(self) -> "ReportingPeriodUpdateRequest":
        if (
            self.activate_on is not None
            and self.deactivate_on is not None
            and self.activate_on > self.deactivate_on
        ):
            raise ValueError("activate_on must be on or before deactivate_on")
        return self


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

    @field_validator("code")
    @classmethod
    def _trim_code(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Code is required")
        return trimmed

    @field_validator("description")
    @classmethod
    def _trim_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class LoaTypeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=100)

    @field_validator("code")
    @classmethod
    def _trim_code(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Code is required")
        return trimmed

    @field_validator("description")
    @classmethod
    def _trim_description(cls, value: str | None) -> str | None:
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
    day_type: str = Field(min_length=1, max_length=4)
    start_time_min: time | None = None
    end_time_max: time | None = None
    session_type_id: UUID | None = None
    session_name_pattern: str | None = Field(default=None, max_length=100)
    mutates_to_session_type_id: UUID | None = None
    adjusted_duration_hours: Decimal | None = Field(default=None, gt=0)

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
        if lowered not in {"sat", "sun", "both"}:
            raise ValueError("day_type must be one of: sat, sun, both")
        return lowered

    @model_validator(mode="after")
    def _validate_exception_shape(self) -> "WeekendExceptionMutationRequest":
        if self.start_time_min is not None and self.end_time_max is not None:
            if self.start_time_min > self.end_time_max:
                raise ValueError("start_time_min must be before or equal to end_time_max")
        if self.adjusted_duration_hours is not None and self.mutates_to_session_type_id is None:
            raise ValueError("mutates_to_session_type_id is required when adjusted_duration_hours is set")
        return self


class GlobalSessionTypeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    duration_hours: Decimal = Field(gt=0)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name cannot be blank")
        return trimmed


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
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name cannot be blank")
        return trimmed
