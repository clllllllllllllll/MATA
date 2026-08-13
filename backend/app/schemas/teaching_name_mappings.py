from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.data_revalidation import DataRevalidationImpactSummary


class TeachingNameMappingStatus(str, Enum):
    PENDING = "pending"
    MAPPED = "mapped"


class TeachingNameMappingTargetResponse(BaseModel):
    id: UUID
    session_type_id: UUID
    session_type_name: str
    duration_hours: Decimal
    monthly_target: int
    is_tracked: bool
    is_reallocatable: bool
    tag: str | None = None


class TeachingNameMappingResponse(BaseModel):
    id: UUID
    teaching_name_id: UUID
    teaching_name: str
    teaching_name_is_active: bool
    teaching_name_revision: int
    teaching_name_owner_programme_code: str
    teaching_name_created_by_role: str
    teaching_name_visibility_scope: str
    teaching_name_origin_posting_code: str | None = None
    teaching_name_admission_reason: str
    reporting_period_id: UUID
    programme_code: str
    posting_code: str
    r_year: str
    teaching_target_id: UUID | None
    state: TeachingNameMappingStatus
    revision: int
    created_at: datetime
    updated_at: datetime
    target: TeachingNameMappingTargetResponse | None = None
    available_target_options: list[TeachingNameMappingTargetResponse] = Field(
        default_factory=list
    )


class TeachingNameMappingListResponse(BaseModel):
    items: list[TeachingNameMappingResponse]
    total: int
    limit: int
    offset: int


class TeachingNameMappingImpactCounts(BaseModel):
    affected_event_count: int = 0
    affected_attendance_count: int = 0


class TeachingNameMappingMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A clear is intentional only when the caller sends this field as null.
    teaching_target_id: UUID | None
    expected_revision: int = Field(ge=1)
    confirm_impact: bool = False


class TeachingNameMappingMutationResponse(TeachingNameMappingResponse):
    impact: TeachingNameMappingImpactCounts
    data_revalidation: DataRevalidationImpactSummary


class TeachingNameMappingBulkItemRequest(TeachingNameMappingMutationRequest):
    mapping_id: UUID


class TeachingNameMappingBulkMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TeachingNameMappingBulkItemRequest] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _mapping_ids_are_unique(self) -> TeachingNameMappingBulkMutationRequest:
        if len({item.mapping_id for item in self.items}) != len(self.items):
            raise ValueError("mapping_id values must be unique")
        return self


class TeachingNameMappingBulkMutationResponse(BaseModel):
    requested_count: int
    updated_count: int
    mapped_count: int
    pending_count: int
    affected_event_count: int
    affected_attendance_count: int
