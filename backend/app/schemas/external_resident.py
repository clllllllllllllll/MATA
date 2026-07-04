from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExternalResidentPostingScheduleRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    programme_code: str = Field(min_length=1, max_length=20)
    institution: str = Field(min_length=1, max_length=20)
    posting_code: str = Field(min_length=1, max_length=50)

    @field_validator("posting_code")
    @classmethod
    def _trim_non_empty(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("value is required")
        return trimmed

    @field_validator("programme_code", "institution")
    @classmethod
    def _trim_upper_non_empty(cls, value: str) -> str:
        trimmed = value.strip().upper()
        if not trimmed:
            raise ValueError("value is required")
        return trimmed


class ExternalResidentRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    mcr: str = Field(min_length=1, max_length=20)
    home_cluster: str = Field(min_length=1, max_length=20)
    current_nhg_posting_code: str | None = Field(default=None, min_length=1, max_length=50)
    posting_schedule: list[ExternalResidentPostingScheduleRow] | None = Field(
        default=None,
        min_length=1,
    )

    @field_validator("name")
    @classmethod
    def _trim_non_empty(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("value is required")
        return trimmed

    @field_validator("current_nhg_posting_code")
    @classmethod
    def _trim_optional_posting(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("current_nhg_posting_code is required")
        return trimmed

    @field_validator("mcr")
    @classmethod
    def _normalise_mcr(cls, value: str) -> str:
        trimmed = value.strip().upper()
        if not trimmed:
            raise ValueError("mcr is required")
        return trimmed

    @field_validator("home_cluster")
    @classmethod
    def _normalise_home_cluster(cls, value: str) -> str:
        trimmed = value.strip()
        if trimmed.lower() == "nuh":
            return "NUH"
        if trimmed.lower() == "singhealth":
            return "SingHealth"
        return trimmed


class ExternalResidentPostingUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_nhg_posting_code: str = Field(min_length=1, max_length=50)

    @field_validator("current_nhg_posting_code")
    @classmethod
    def _trim_non_empty(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("current_nhg_posting_code is required")
        return trimmed


class ExternalResidentPostingScheduleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    posting_schedule: list[ExternalResidentPostingScheduleRow] = Field(min_length=1)
