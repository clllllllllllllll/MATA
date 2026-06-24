from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AdminLogType(str, Enum):
    UPLOAD = "upload"
    WARNING = "warning"
    WARNING_ACTION = "warning_action"
    SOURCE_CELL_CORRECTION = "source_cell_correction"
    PARSED_DATA_CORRECTION = "parsed_data_correction"
    CONFIG_MUTATION = "config_mutation"
    DATA_REVALIDATION = "data_revalidation"


class AdminLogActorRole(str, Enum):
    MASTER_ADMIN = "master_admin"
    PROGRAMME_PC = "programme_pc"
    ADMIN = "admin"
    SECRETARY = "secretary"
    RESIDENT = "resident"
    EXTERNAL_RESIDENT = "external_resident"


class AdminLogDeepLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: str
    params: dict[str, Any] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    drawer: str | None = None
    entity_id: str | None = None


class AdminLogSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sheet_name: str | None = None
    row_number: int | None = None
    cell_ref: str | None = None


class AdminLogRelatedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: str
    entity_id: str | None = None
    label: str
    relationship: str
    deep_link: AdminLogDeepLink | None = None


class AdminLogAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    label: str
    method: str = "GET"
    endpoint: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    deep_link: AdminLogDeepLink | None = None


class AdminLogListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    log_type: AdminLogType
    occurred_at: str
    actor_user_id: str | None = None
    actor_name: str | None = None
    actor_role: AdminLogActorRole | None = None
    stored_actor_role: str | None = None
    actor_admin_level: str | None = None
    programme_code: str | None = None
    reporting_period_id: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    upload_log_id: str | None = None
    warning_issue_id: str | None = None
    upload_warning_id: str | None = None
    status: str | None = None
    outcome: str | None = None
    title: str
    summary: str
    source_ref: AdminLogSourceRef | None = None
    deep_link: AdminLogDeepLink | None = None


class AdminLogListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AdminLogListItem]
    total: int
    limit: int
    offset: int


class AdminLogDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    log_type: AdminLogType
    list_item: AdminLogListItem
    immutable_evidence: dict[str, Any] = Field(default_factory=dict)
    workflow_status: dict[str, Any] | None = None
    related_entities: list[AdminLogRelatedEntity] = Field(default_factory=list)
    available_actions: list[AdminLogAction] = Field(default_factory=list)
    source_ref: AdminLogSourceRef | None = None
