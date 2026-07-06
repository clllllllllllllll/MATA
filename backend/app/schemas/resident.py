from __future__ import annotations

from datetime import date, time
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class ResidentAttendanceSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_ids: list[UUID] = Field(min_length=1)


class ResidentAdhocTeachingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    teaching_date: date = Field(validation_alias=AliasChoices("teaching_date", "date"))
    start_time: time
    teaching_name: str = Field(min_length=1, max_length=200)
    attended_posting_code: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "attended_posting_code",
            "attended_department_posting_code",
        ),
        max_length=50,
    )
    details_of_session: str | None = Field(default=None, max_length=2000)

    @field_validator("teaching_name")
    @classmethod
    def _trim_teaching_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("teaching_name is required")
        return trimmed

    @field_validator("attended_posting_code")
    @classmethod
    def _trim_attended_posting_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @field_validator("details_of_session")
    @classmethod
    def _trim_details_of_session(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None
