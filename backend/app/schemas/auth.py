from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1, max_length=20)
    email: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, max_length=255)
    mcr: str | None = Field(default=None, max_length=20)

    @field_validator("role", "email", "mcr")
    @classmethod
    def _trim_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @field_validator("role")
    @classmethod
    def _normalise_role(cls, value: str) -> str:
        lowered = value.strip().lower()
        if lowered not in {"staff", "admin", "secretary", "resident", "external_resident"}:
            raise ValueError(
                "role must be one of: staff, admin, secretary, resident, external_resident"
            )
        return lowered

    @model_validator(mode="after")
    def _validate_login_shape(self) -> "LoginRequest":
        if self.role in {"resident", "external_resident"}:
            if not self.mcr:
                raise ValueError("mcr is required for resident login")
            return self
        if not self.email or not self.password:
            raise ValueError("email and password are required for staff login")
        return self


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: dict[str, Any]
    csrf_token: str = Field(min_length=32, max_length=256)
    session_refresh_required: bool = False


class LogoutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool = True
    server_logout_confirmed: bool = False


class StaffActorNameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=120)

    @field_validator("full_name")
    @classmethod
    def _trim_and_require_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("full_name is required")
        return trimmed
