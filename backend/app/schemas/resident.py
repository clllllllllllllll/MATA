from __future__ import annotations

from datetime import date, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResidentAttendanceSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_ids: list[UUID] = Field(min_length=1)


class ResidentAdhocTeachingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    start_time: time
    teaching_name: str = Field(min_length=1, max_length=200)

    @field_validator("teaching_name")
    @classmethod
    def _trim_teaching_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("teaching_name is required")
        return trimmed
