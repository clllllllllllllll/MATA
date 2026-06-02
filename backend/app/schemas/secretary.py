from __future__ import annotations

from datetime import date, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SecretaryTeachingEventCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    teaching_name: str = Field(min_length=1, max_length=200)
    event_date: date
    start_time: time
    cme_points_awarded: bool = False
    smc_event_code: str | None = Field(default=None, max_length=50)

    @field_validator("teaching_name", "smc_event_code")
    @classmethod
    def _trim_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class SecretaryTeachingEventUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    teaching_name: str = Field(min_length=1, max_length=200)
    event_date: date
    start_time: time
    cme_points_awarded: bool = False
    smc_event_code: str | None = Field(default=None, max_length=50)

    @field_validator("teaching_name", "smc_event_code")
    @classmethod
    def _trim_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class SecretaryTeachingEventDuplicateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_event_id: UUID
    event_date: date
    start_time: time | None = None
    teaching_name: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("teaching_name")
    @classmethod
    def _trim_teaching_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class SecretaryTeachingEventSeriesCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    teaching_name: str = Field(min_length=1, max_length=200)
    start_date: date
    start_time: time
    cme_points_awarded: bool = False
    smc_event_code: str | None = Field(default=None, max_length=50)
    recurrence_pattern: str = Field(min_length=1, max_length=20)
    recurrence_interval: int = Field(default=1, ge=1)
    days_of_week: list[str] | None = None
    end_type: str = Field(min_length=1, max_length=10)
    end_date: date | None = None
    end_after_count: int | None = Field(default=None, ge=1)

    @field_validator("teaching_name", "smc_event_code")
    @classmethod
    def _trim_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @field_validator("recurrence_pattern")
    @classmethod
    def _validate_recurrence_pattern(cls, value: str) -> str:
        lowered = value.strip().lower()
        if lowered not in {"daily", "weekly", "monthly"}:
            raise ValueError("recurrence_pattern must be one of: daily, weekly, monthly")
        return lowered

    @field_validator("days_of_week")
    @classmethod
    def _normalise_days_of_week(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalised = [day.strip().lower() for day in value if day.strip()]
        invalid = [day for day in normalised if day not in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}]
        if invalid:
            raise ValueError("days_of_week contains unsupported day names")
        return normalised

    @field_validator("end_type")
    @classmethod
    def _validate_end_type(cls, value: str) -> str:
        lowered = value.strip().lower()
        if lowered not in {"by_date", "by_count"}:
            raise ValueError("end_type must be one of: by_date, by_count")
        return lowered

    @model_validator(mode="after")
    def _validate_end_fields(self) -> "SecretaryTeachingEventSeriesCreateRequest":
        if self.end_type == "by_date" and self.end_date is None:
            raise ValueError("end_date is required when end_type is by_date")
        if self.end_type == "by_count" and self.end_after_count is None:
            raise ValueError("end_after_count is required when end_type is by_count")
        if self.recurrence_pattern == "weekly" and not self.days_of_week:
            raise ValueError("days_of_week is required for weekly recurrence")
        return self
