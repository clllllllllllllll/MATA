from __future__ import annotations

from json import JSONDecodeError, loads
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_name: str = "MATA Backend"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/mata_db",
    )
    sync_database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/mata_db",
    )

    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
    )

    csp_default_src: str = "default-src 'self'"
    referrer_policy: str = "strict-origin-when-cross-origin"

    max_upload_size_mb: int = 10

    rate_limit_auth_per_minute: int = 5
    rate_limit_upload_per_hour: int = 10
    rate_limit_mutation_per_minute: int = 60
    rate_limit_report_per_minute: int = 20
    rate_limit_resident_attendance_per_minute: int = 30
    rate_limit_get_per_minute: int = 300

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return []

            if cleaned.startswith("["):
                try:
                    parsed = loads(cleaned)
                except JSONDecodeError:
                    return [origin.strip() for origin in cleaned.split(",") if origin.strip()]

                if isinstance(parsed, list):
                    return [str(origin).strip() for origin in parsed if str(origin).strip()]

            return [origin.strip() for origin in cleaned.split(",") if origin.strip()]

        if isinstance(value, (tuple, set)):
            return [str(origin).strip() for origin in value if str(origin).strip()]

        return value

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
