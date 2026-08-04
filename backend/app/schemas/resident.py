from __future__ import annotations

from datetime import date, time
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class ResidentAttendanceSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_ids: list[UUID] = Field(min_length=1)


class ResidentAdhocTeachingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    teaching_date: date = Field(validation_alias=AliasChoices("teaching_date", "date"))
    start_time: time
    attended_posting_code: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "attended_posting_code",
            "attended_department_posting_code",
        ),
        max_length=50,
    )
    details_of_session: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def _validate_teaching_date_aliases(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        teaching_date = value.get("teaching_date")
        legacy_date = value.get("date")
        if teaching_date is None and legacy_date is None:
            raise ValueError("teaching_date is required")
        if (
            teaching_date is not None
            and legacy_date is not None
            and str(teaching_date) != str(legacy_date)
        ):
            raise ValueError(
                "teaching_date and date must match when both are provided"
            )
        if teaching_date is not None and legacy_date is not None:
            normalized = dict(value)
            normalized.pop("date", None)
            return normalized
        return value

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
