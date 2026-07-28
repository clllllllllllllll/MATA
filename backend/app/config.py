from __future__ import annotations

from json import JSONDecodeError, loads
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


MINIMUM_HS256_SECRET_BYTES = 32


def _production_https_url_parts(
    raw_url: str,
    *,
    label: str,
) -> tuple[str, int, str]:
    try:
        parsed = urlsplit(raw_url.strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Production {label} must be an explicit HTTPS URL") from exc

    hostname = (parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise ValueError(
            f"Production {label} must be an explicit HTTPS URL without "
            "credentials, query, fragment, or a non-standard port"
        )
    return hostname, port or 443, parsed.path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    project_name: str = "MATA Backend"
    environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "ENV"),
    )
    api_prefix: str = "/api/v1"
    auth_mode: Literal["stub", "demo", "supabase"] = "stub"
    auth_transport: Literal["cookie", "bearer_compat"] = "cookie"
    enable_production_bearer_rollback: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "MATA_ENABLE_PRODUCTION_BEARER_ROLLBACK",
            "ENABLE_PRODUCTION_BEARER_ROLLBACK",
        ),
    )

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/mata_db",
    )
    sync_database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/mata_db",
    )
    database_rls_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "MATA_DATABASE_RLS_ENABLED",
            "DATABASE_RLS_ENABLED",
        ),
    )
    database_runtime_role: str = Field(
        default="mata_app_runtime",
        validation_alias=AliasChoices(
            "MATA_DATABASE_RUNTIME_ROLE",
            "DATABASE_RUNTIME_ROLE",
        ),
    )
    database_auth_role: str = Field(
        default="mata_auth_internal",
        validation_alias=AliasChoices(
            "MATA_DATABASE_AUTH_ROLE",
            "DATABASE_AUTH_ROLE",
        ),
    )
    auth_database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "MATA_AUTH_DATABASE_URL",
            "AUTH_DATABASE_URL",
        ),
    )

    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
    )
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"],
        validation_alias=AliasChoices("MATA_ALLOWED_HOSTS", "ALLOWED_HOSTS"),
    )

    csp_default_src: str = "default-src 'self'"
    referrer_policy: str = "strict-origin-when-cross-origin"
    supabase_url: str | None = None
    supabase_jwks_url: str | None = None
    supabase_jwt_issuer: str | None = None
    supabase_jwt_audience: str = "authenticated"
    supabase_publishable_key: str | None = None
    supabase_anon_key: str | None = None
    supabase_jwks_cache_ttl_seconds: int = 600
    supabase_service_role_key: str | None = None
    mata_resident_session_secret: str | None = None
    mata_resident_session_issuer: str = "mata-api"
    mata_resident_session_audience: str = "mata-resident-session"
    mata_resident_session_ttl_minutes: int = 60

    mata_session_hash_key: str | None = None
    mata_session_cookie_name: str = "__Host-mata_session"
    mata_local_session_cookie_name: str = "mata_session_local"
    staff_session_idle_timeout_seconds: int = Field(
        default=1800,
        validation_alias=AliasChoices(
            "MATA_STAFF_IDLE_TIMEOUT_SECONDS",
            "STAFF_SESSION_IDLE_TIMEOUT_SECONDS",
        ),
    )
    staff_session_absolute_timeout_seconds: int = Field(
        default=28800,
        validation_alias=AliasChoices(
            "MATA_STAFF_ABSOLUTE_TIMEOUT_SECONDS",
            "STAFF_SESSION_ABSOLUTE_TIMEOUT_SECONDS",
        ),
    )
    resident_session_idle_timeout_seconds: int = Field(
        default=3600,
        validation_alias=AliasChoices(
            "MATA_RESIDENT_IDLE_TIMEOUT_SECONDS",
            "RESIDENT_SESSION_IDLE_TIMEOUT_SECONDS",
        ),
    )
    resident_session_absolute_timeout_seconds: int = Field(
        default=43200,
        validation_alias=AliasChoices(
            "MATA_RESIDENT_ABSOLUTE_TIMEOUT_SECONDS",
            "RESIDENT_SESSION_ABSOLUTE_TIMEOUT_SECONDS",
        ),
    )
    session_rotation_seconds: int = Field(
        default=900,
        validation_alias=AliasChoices(
            "MATA_SESSION_ROTATION_SECONDS",
            "SESSION_ROTATION_SECONDS",
        ),
    )
    session_touch_interval_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices(
            "MATA_SESSION_TOUCH_INTERVAL_SECONDS",
            "SESSION_TOUCH_INTERVAL_SECONDS",
        ),
    )
    session_cleanup_retention_seconds: int = Field(
        default=604800,
        validation_alias=AliasChoices(
            "MATA_SESSION_CLEANUP_RETENTION_SECONDS",
            "SESSION_CLEANUP_RETENTION_SECONDS",
        ),
    )
    session_cleanup_batch_size: int = Field(
        default=500,
        validation_alias=AliasChoices(
            "MATA_SESSION_CLEANUP_BATCH_SIZE",
            "SESSION_CLEANUP_BATCH_SIZE",
        ),
    )
    csrf_header_name: str = Field(
        default="X-CSRF-Token",
        validation_alias=AliasChoices("MATA_CSRF_HEADER_NAME", "CSRF_HEADER_NAME"),
    )

    max_request_body_size_mb: int = 4
    max_upload_request_size_mb: int = 4
    max_upload_size_mb: int = 3
    upload_archive_max_uncompressed_bytes: int = 100 * 1024 * 1024
    upload_archive_max_entries: int = 2048
    upload_archive_max_entry_bytes: int = 20 * 1024 * 1024
    upload_archive_max_compression_ratio: float = 100.0

    rate_limit_auth_per_minute: int = 5
    rate_limit_upload_per_hour: int = 10
    rate_limit_mutation_per_minute: int = 60
    rate_limit_report_per_minute: int = 20
    rate_limit_resident_attendance_per_minute: int = 30
    rate_limit_get_per_minute: int = 300
    rate_limit_hash_secret: str | None = None
    rate_limit_store: Literal["memory", "postgres"] = "memory"
    rate_limit_cleanup_retention_seconds: int = 86400
    rate_limit_cleanup_batch_size: int = 500

    @field_validator("cors_origins", "allowed_hosts", mode="before")
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

    @model_validator(mode="after")
    def _validate_security_configuration(self) -> "Settings":
        positive_values = {
            "staff session idle timeout": self.staff_session_idle_timeout_seconds,
            "staff session absolute timeout": self.staff_session_absolute_timeout_seconds,
            "resident session idle timeout": self.resident_session_idle_timeout_seconds,
            "resident session absolute timeout": self.resident_session_absolute_timeout_seconds,
            "session rotation threshold": self.session_rotation_seconds,
            "session touch interval": self.session_touch_interval_seconds,
            "session cleanup retention": self.session_cleanup_retention_seconds,
            "session cleanup batch size": self.session_cleanup_batch_size,
            "request body size": self.max_request_body_size_mb,
            "upload request size": self.max_upload_request_size_mb,
            "upload file size": self.max_upload_size_mb,
            "upload archive total size": self.upload_archive_max_uncompressed_bytes,
            "upload archive entry count": self.upload_archive_max_entries,
            "upload archive entry size": self.upload_archive_max_entry_bytes,
            "rate-limit cleanup retention": self.rate_limit_cleanup_retention_seconds,
            "rate-limit cleanup batch size": self.rate_limit_cleanup_batch_size,
        }
        invalid = [name for name, value in positive_values.items() if value <= 0]
        if invalid:
            raise ValueError(f"Security settings must be positive: {', '.join(invalid)}")
        if self.upload_archive_max_compression_ratio <= 1:
            raise ValueError("Upload archive compression ratio must be greater than 1")
        if self.max_upload_size_mb >= self.max_upload_request_size_mb:
            raise ValueError(
                "Upload file size must be smaller than the upload request size"
            )
        if self.max_upload_request_size_mb > self.max_request_body_size_mb:
            raise ValueError(
                "Upload request size cannot exceed the global request body size"
            )
        if self.staff_session_idle_timeout_seconds > self.staff_session_absolute_timeout_seconds:
            raise ValueError("Staff idle timeout cannot exceed the absolute timeout")
        if self.resident_session_idle_timeout_seconds > self.resident_session_absolute_timeout_seconds:
            raise ValueError("Resident idle timeout cannot exceed the absolute timeout")
        if self.session_touch_interval_seconds >= min(
            self.staff_session_idle_timeout_seconds,
            self.resident_session_idle_timeout_seconds,
        ):
            raise ValueError(
                "Session touch interval must be shorter than every idle timeout"
            )
        if self.session_rotation_seconds >= min(
            self.staff_session_absolute_timeout_seconds,
            self.resident_session_absolute_timeout_seconds,
        ):
            raise ValueError(
                "Session rotation threshold must be shorter than every absolute timeout"
            )
        helper_upper_bounds = {
            "staff session idle timeout": (
                self.staff_session_idle_timeout_seconds,
                86400,
            ),
            "resident session idle timeout": (
                self.resident_session_idle_timeout_seconds,
                86400,
            ),
            "staff session absolute timeout": (
                self.staff_session_absolute_timeout_seconds,
                604800,
            ),
            "resident session absolute timeout": (
                self.resident_session_absolute_timeout_seconds,
                604800,
            ),
            "session cleanup retention": (
                self.session_cleanup_retention_seconds,
                31536000,
            ),
            "session cleanup batch size": (
                self.session_cleanup_batch_size,
                1000,
            ),
        }
        oversized = [
            name
            for name, (value, maximum) in helper_upper_bounds.items()
            if value > maximum
        ]
        if oversized:
            raise ValueError(
                "Security settings exceed PostgreSQL helper bounds: "
                + ", ".join(oversized)
            )
        if not self.csrf_header_name.strip():
            raise ValueError("CSRF header name cannot be blank")

        if self.database_rls_enabled:
            runtime_role = self.database_runtime_role.strip()
            auth_role = self.database_auth_role.strip()
            if runtime_role != "mata_app_runtime":
                raise ValueError(
                    "DATABASE_RUNTIME_ROLE must be the stable mata_app_runtime group"
                )
            if auth_role != "mata_auth_internal":
                raise ValueError(
                    "DATABASE_AUTH_ROLE must be the stable mata_auth_internal group"
                )
            if runtime_role == auth_role:
                raise ValueError("Runtime and auth database groups must be distinct")
            if self.auth_transport != "cookie":
                raise ValueError(
                    "RLS enforcement requires cookie session transport"
                )
            if not self.auth_database_url:
                raise ValueError(
                    "AUTH_DATABASE_URL is required when RLS enforcement is enabled"
                )
            parsed_runtime_database_url = urlsplit(self.database_url)
            parsed_auth_database_url = urlsplit(self.auth_database_url)
            parsed_migration_database_url = urlsplit(self.sync_database_url)
            rls_database_urls = (
                ("DATABASE_URL", parsed_runtime_database_url),
                ("AUTH_DATABASE_URL", parsed_auth_database_url),
            )
            for label, parsed_url in rls_database_urls:
                try:
                    port = parsed_url.port or 5432
                except ValueError as exc:
                    raise ValueError(f"{label} contains an invalid port") from exc
                if (
                    parsed_url.scheme != "postgresql+asyncpg"
                    or not parsed_url.username
                    or not parsed_url.hostname
                    or not parsed_url.path.lstrip("/")
                    or port <= 0
                ):
                    raise ValueError(
                        f"{label} must be an explicit PostgreSQL asyncpg URL"
                    )
            try:
                migration_port = parsed_migration_database_url.port or 5432
            except ValueError as exc:
                raise ValueError(
                    "SYNC_DATABASE_URL contains an invalid port"
                ) from exc
            if (
                parsed_migration_database_url.scheme
                not in {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
                or not parsed_migration_database_url.username
                or not parsed_migration_database_url.hostname
                or not parsed_migration_database_url.path.lstrip("/")
                or migration_port <= 0
            ):
                raise ValueError(
                    "SYNC_DATABASE_URL must be an explicit PostgreSQL URL"
                )

            runtime_endpoint = (
                (parsed_runtime_database_url.hostname or "").casefold(),
                parsed_runtime_database_url.port or 5432,
                parsed_runtime_database_url.path.lstrip("/"),
            )
            auth_endpoint = (
                (parsed_auth_database_url.hostname or "").casefold(),
                parsed_auth_database_url.port or 5432,
                parsed_auth_database_url.path.lstrip("/"),
            )
            migration_endpoint = (
                (parsed_migration_database_url.hostname or "").casefold(),
                migration_port,
                parsed_migration_database_url.path.lstrip("/"),
            )
            if runtime_endpoint != auth_endpoint:
                raise ValueError(
                    "DATABASE_URL and AUTH_DATABASE_URL must target the same "
                    "PostgreSQL host, port, and database"
                )
            if runtime_endpoint != migration_endpoint:
                raise ValueError(
                    "DATABASE_URL and SYNC_DATABASE_URL must target the same "
                    "PostgreSQL host, port, and database"
                )
            if (
                parsed_runtime_database_url.username
                == parsed_auth_database_url.username
            ):
                raise ValueError(
                    "Runtime and auth database URLs must use distinct credentialed "
                    "login roles"
                )
            if parsed_migration_database_url.username in {
                parsed_runtime_database_url.username,
                parsed_auth_database_url.username,
            }:
                raise ValueError(
                    "Migration, runtime, and auth database URLs must use "
                    "distinct credentialed roles"
                )

        if self.environment != "production":
            return self

        approved_request_limits = (4, 4, 3)
        configured_request_limits = (
            self.max_request_body_size_mb,
            self.max_upload_request_size_mb,
            self.max_upload_size_mb,
        )
        if configured_request_limits != approved_request_limits:
            raise ValueError(
                "Production request-body limits must match the approved "
                "Vercel contract: 4 MiB global, 4 MiB aggregate upload, "
                "and 3 MiB per file"
            )
        if self.auth_mode != "supabase":
            raise ValueError("Production AUTH_MODE must be supabase")
        if not self.database_rls_enabled:
            raise ValueError("Production DATABASE_RLS_ENABLED must be true")
        database_contracts = (
            ("DATABASE_URL", self.database_url, {"postgresql+asyncpg"}),
            (
                "SYNC_DATABASE_URL",
                self.sync_database_url,
                {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"},
            ),
        )
        for label, raw_url, allowed_schemes in database_contracts:
            parsed_database_url = urlsplit(raw_url)
            hostname = (parsed_database_url.hostname or "").casefold()
            database_name = parsed_database_url.path.lstrip("/")
            if (
                parsed_database_url.scheme not in allowed_schemes
                or not parsed_database_url.username
                or not hostname
                or not database_name
                or hostname in {"localhost", "127.0.0.1", "::1"}
                or hostname.endswith(".localhost")
            ):
                raise ValueError(
                    f"Production {label} must be an explicit non-local PostgreSQL URL"
                )
        parsed_auth_database_url = urlsplit(self.auth_database_url)
        auth_hostname = (parsed_auth_database_url.hostname or "").casefold()
        if (
            auth_hostname in {"localhost", "127.0.0.1", "::1"}
            or auth_hostname.endswith(".localhost")
        ):
            raise ValueError(
                "Production AUTH_DATABASE_URL must be an explicit non-local "
                "PostgreSQL URL"
            )
        if not self.supabase_url:
            raise ValueError("Production SUPABASE_URL is required")
        supabase_host, supabase_port, supabase_path = _production_https_url_parts(
            self.supabase_url,
            label="SUPABASE_URL",
        )
        if (
            supabase_path not in {"", "/"}
            or supabase_host == "supabase.co"
            or not supabase_host.endswith(".supabase.co")
        ):
            raise ValueError(
                "Production SUPABASE_URL must be the explicit HTTPS origin "
                "of an approved Supabase project"
            )
        supabase_origin = (supabase_host, supabase_port)

        configured_issuer = (
            self.supabase_jwt_issuer
            or f"{self.supabase_url.rstrip('/')}/auth/v1"
        )
        issuer_host, issuer_port, issuer_path = _production_https_url_parts(
            configured_issuer,
            label="SUPABASE_JWT_ISSUER",
        )
        if (
            (issuer_host, issuer_port) != supabase_origin
            or issuer_path.rstrip("/") != "/auth/v1"
        ):
            raise ValueError(
                "Production SUPABASE_JWT_ISSUER must use the SUPABASE_URL "
                "origin and /auth/v1 path"
            )

        configured_jwks_url = (
            self.supabase_jwks_url
            or f"{configured_issuer.rstrip('/')}/.well-known/jwks.json"
        )
        jwks_host, jwks_port, jwks_path = _production_https_url_parts(
            configured_jwks_url,
            label="SUPABASE_JWKS_URL",
        )
        if (
            (jwks_host, jwks_port) != supabase_origin
            or jwks_path != "/auth/v1/.well-known/jwks.json"
        ):
            raise ValueError(
                "Production SUPABASE_JWKS_URL must use the SUPABASE_URL "
                "origin and /auth/v1/.well-known/jwks.json path"
            )
        if not (self.supabase_publishable_key or self.supabase_anon_key):
            raise ValueError("A backend Supabase publishable key is required in production")
        if self.auth_transport == "bearer_compat":
            if not self.enable_production_bearer_rollback:
                raise ValueError(
                    "AUTH_TRANSPORT=bearer_compat is disabled in production unless the narrowly "
                    "scoped emergency rollback flag is enabled"
                )
            resident_secret = (self.mata_resident_session_secret or "").strip()
            if len(resident_secret.encode("utf-8")) < MINIMUM_HS256_SECRET_BYTES:
                raise ValueError(
                    "Production bearer compatibility requires "
                    "MATA_RESIDENT_SESSION_SECRET with at least 32 bytes"
                )
        if self.auth_transport == "cookie":
            if not self.mata_session_hash_key or len(self.mata_session_hash_key) < 32:
                raise ValueError("MATA_SESSION_HASH_KEY must contain at least 32 characters")
            if self.mata_session_cookie_name != "__Host-mata_session":
                raise ValueError("Production session cookie must be named __Host-mata_session")
        if self.rate_limit_store != "postgres":
            raise ValueError("Production RATE_LIMIT_STORE must be postgres")
        if not self.rate_limit_hash_secret or len(self.rate_limit_hash_secret) < 32:
            raise ValueError("RATE_LIMIT_HASH_SECRET must contain at least 32 characters")
        if not self.cors_origins:
            raise ValueError("Production CORS_ORIGINS cannot be empty")
        for origin in self.cors_origins:
            lowered = origin.strip().lower()
            parsed = urlsplit(lowered)
            if (
                "*" in lowered
                or parsed.scheme != "https"
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or "localhost" in lowered
                or "127.0.0.1" in lowered
            ):
                raise ValueError("Production CORS origins must be explicit HTTPS origins")
        if not self.allowed_hosts:
            raise ValueError("Production ALLOWED_HOSTS cannot be empty")
        for host in self.allowed_hosts:
            lowered = host.strip().lower()
            if (
                "*" in lowered
                or "://" in lowered
                or "/" in lowered
                or lowered in {"localhost", "127.0.0.1", "testserver"}
            ):
                raise ValueError("Production allowed hosts must be explicit deployment hosts")
        return self

    @property
    def max_request_body_size_bytes(self) -> int:
        return self.max_request_body_size_mb * 1024 * 1024

    @property
    def max_upload_request_size_bytes(self) -> int:
        return self.max_upload_request_size_mb * 1024 * 1024

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
