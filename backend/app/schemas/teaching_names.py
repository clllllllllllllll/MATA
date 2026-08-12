from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.data_revalidation import DataRevalidationImpactSummary


class TeachingNameProgrammeResponse(BaseModel):
    programme_code: str


class TeachingNameProgrammeListResponse(BaseModel):
    items: list[TeachingNameProgrammeResponse]


class TeachingNameResponse(BaseModel):
    id: UUID
    reporting_period_id: UUID
    programme_code: str
    teaching_name: str
    created_by_role: str
    visibility_scope: str
    origin_posting_code: str | None = None
    admission_reason: str
    can_manage_name: bool
    is_active: bool
    revision: int
    created_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None = None


class TeachingNameListResponse(BaseModel):
    items: list[TeachingNameResponse]
    total: int
    limit: int
    offset: int


class TeachingNameCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_period_id: UUID
    programme_code: str = Field(min_length=1, max_length=20)
    teaching_name: str = Field(min_length=1, max_length=200)


class TeachingNameUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    teaching_name: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=1)


class TeachingNameRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class TeachingNameDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    force_delete: bool = False
    reason: str | None = Field(default=None, max_length=1000)
    confirmation: str | None = Field(default=None, max_length=20)


class TeachingNameMutationResponse(TeachingNameResponse):
    data_revalidation: DataRevalidationImpactSummary


class TeachingNameDeleteResponse(BaseModel):
    teaching_name_id: UUID
    deleted: bool = True
    used_name: bool
    event_reference_count: int
    native_attendance_count: int
    non_nhg_attendance_count: int
    data_revalidation: DataRevalidationImpactSummary
