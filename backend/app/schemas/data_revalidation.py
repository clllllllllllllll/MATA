from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DataRevalidationOutcome(str, Enum):
    NO_OP = "no_op"
    WARNING_ONLY = "warning_only"
    TARGETED_REVALIDATION = "targeted_revalidation"
    FUTURE_COMPLIANCE_IMPACT = "future_compliance_impact"
    MANUAL_REVALIDATION_REQUIRED = "manual_revalidation_required"


CANONICAL_DATA_REVALIDATION_OUTCOMES = tuple(item.value for item in DataRevalidationOutcome)


class DataRevalidationTriggerSource(str, Enum):
    UPLOAD = "upload"
    LIVE_DATA_CORRECTION = "live_data_correction"
    ADMIN_CONFIG_CHANGE = "admin_config_change"
    PC_CONFIG_CHANGE = "pc_config_change"
    MANUAL_REVALIDATION = "manual_revalidation"


class DataRevalidationChangedEntity(str, Enum):
    RESIDENT = "resident"
    RESIDENT_POSTING = "resident_posting"
    RESIDENT_POSTING_SOURCE_FRAGMENT = "resident_posting_source_fragment"
    TEACHING_TARGET = "teaching_target"
    FORM_F1_RECORD = "form_f1_record"
    ACADEMIC_MONTH_BOUNDARY = "academic_month_boundary"
    REPORTING_PERIOD = "reporting_period"
    PUBLIC_HOLIDAY = "public_holiday"
    PROGRAMME = "programme"
    LOA_TYPE = "loa_type"
    MULTI_POSTING_RULE = "multi_posting_rule"
    POSTING_GROUP = "posting_group"
    WEEKEND_EXCEPTION = "weekend_exception"
    GLOBAL_SESSION_TYPE = "global_session_type"
    UNKNOWN = "unknown"


class DataRevalidationAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"
    REPLACE = "replace"
    UPLOAD = "upload"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class DataRevalidationScope(str, Enum):
    SINGLE_ROW = "single_row"
    RESIDENT_MONTH = "resident_month"
    RESIDENT_REPORTING_PERIOD = "resident_reporting_period"
    PROGRAMME = "programme"
    POSTING = "posting"
    PROGRAMME_REPORTING_PERIOD = "programme_reporting_period"
    REPORTING_PERIOD = "reporting_period"
    UPLOAD_LOG = "upload_log"
    UNRESOLVED_WARNINGS = "unresolved_warnings"
    GLOBAL = "global"
    UNKNOWN = "unknown"


class DataRevalidationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger_source: DataRevalidationTriggerSource
    changed_entity: DataRevalidationChangedEntity = DataRevalidationChangedEntity.UNKNOWN
    action: DataRevalidationAction = DataRevalidationAction.UNKNOWN
    scope: DataRevalidationScope = DataRevalidationScope.UNKNOWN
    entity_id: str | None = None
    programme_code: str | None = None
    resident_id: str | None = None
    reporting_period_id: str | None = None
    upload_log_id: str | None = None
    changed_fields: list[str] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    actor_user_id: str | None = None
    actor_role: str | None = None
    reason: str | None = None


class DataRevalidationWarningImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warning_id: str | None = None
    warning_type: str
    status: str
    action: str
    message: str
    entity_ref: dict[str, Any] = Field(default_factory=dict)


class DataRevalidationImpactSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: DataRevalidationOutcome
    trigger_source: DataRevalidationTriggerSource
    changed_entity: DataRevalidationChangedEntity
    action: DataRevalidationAction
    scope: DataRevalidationScope
    summary: str
    rows_examined: int = 0
    rows_updated: int = 0
    warnings_created: int = 0
    warnings_updated: int = 0
    warnings_resolved: int = 0
    warnings_remaining: int = 0
    affected_models: list[str] = Field(default_factory=list)
    affected_warning_ids: list[str] = Field(default_factory=list)
    warning_impacts: list[DataRevalidationWarningImpact] = Field(default_factory=list)
    audit_metadata: dict[str, Any] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)
