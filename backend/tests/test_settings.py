from __future__ import annotations

from traceback import format_exception

import pytest

from app.config import Settings, SettingsConfigurationError, get_settings
from app.middleware.request_body_limit import (
    DEFAULT_GLOBAL_BODY_LIMIT_BYTES,
    DEFAULT_UPLOAD_BODY_LIMIT_BYTES,
    MEBIBYTE,
)


def test_cors_origins_accepts_comma_separated_env(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == [
        "http://localhost:5173",
        "http://localhost:3000",
    ]


def test_cors_origins_accepts_json_array_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "CORS_ORIGINS",
        '["http://localhost:5173","http://localhost:3000"]',
    )

    settings = Settings(_env_file=None)

    assert settings.cors_origins == [
        "http://localhost:5173",
        "http://localhost:3000",
    ]


def test_request_body_limit_defaults_agree_with_middleware() -> None:
    settings = Settings(_env_file=None)

    assert settings.max_upload_size_bytes == 3 * MEBIBYTE
    assert (
        settings.max_upload_request_size_bytes
        == DEFAULT_UPLOAD_BODY_LIMIT_BYTES
        == 4 * MEBIBYTE
    )
    assert (
        settings.max_request_body_size_bytes
        == DEFAULT_GLOBAL_BODY_LIMIT_BYTES
        == 4 * MEBIBYTE
    )
    assert settings.max_upload_size_bytes < settings.max_upload_request_size_bytes
    assert (
        settings.max_upload_request_size_bytes
        <= settings.max_request_body_size_bytes
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_request_body_size_mb", 0),
        ("max_upload_request_size_mb", 0),
        ("max_upload_size_mb", 0),
    ],
)
def test_request_body_limits_must_be_positive(field: str, value: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        Settings(_env_file=None, **{field: value})


def test_upload_file_limit_must_leave_multipart_headroom() -> None:
    with pytest.raises(ValueError, match="smaller than the upload request"):
        Settings(
            _env_file=None,
            max_upload_size_mb=3,
            max_upload_request_size_mb=3,
        )


def test_upload_request_limit_cannot_exceed_global_limit() -> None:
    with pytest.raises(ValueError, match="cannot exceed the global"):
        Settings(
            _env_file=None,
            max_upload_request_size_mb=5,
            max_request_body_size_mb=4,
        )


def test_production_rejects_superseded_request_body_limits() -> None:
    with pytest.raises(ValueError, match="approved Vercel contract"):
        Settings(
            _env_file=None,
            environment="production",
            max_request_body_size_mb=12,
            max_upload_request_size_mb=11,
            max_upload_size_mb=10,
        )


def test_get_settings_reports_production_failure_without_rendering_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = (
        "postgresql+asyncpg://runtime:runtime-password-do-not-log"
        "@db.example.invalid:5432/mata"
    )
    auth_database_url = (
        "postgresql+asyncpg://auth:auth-password-do-not-log"
        "@db.example.invalid:5432/mata"
    )
    sync_database_url = (
        "postgresql+psycopg2://migration:migration-password-do-not-log"
        "@db.example.invalid:5432/mata"
    )
    supabase_publishable_key = "sb_publishable_sensitive-input-do-not-log"
    session_hash_key = "session-hash-sensitive-input-do-not-log"
    rate_limit_hash_secret = "rate-limit-sensitive-input-do-not-log"
    sensitive_values = {
        "DATABASE_URL": database_url,
        "MATA_AUTH_DATABASE_URL": auth_database_url,
        "SYNC_DATABASE_URL": sync_database_url,
        "SUPABASE_PUBLISHABLE_KEY": supabase_publishable_key,
        "MATA_SESSION_HASH_KEY": session_hash_key,
        "RATE_LIMIT_HASH_SECRET": rate_limit_hash_secret,
    }
    environment = {
        "ENVIRONMENT": "production",
        "AUTH_MODE": "supabase",
        "AUTH_TRANSPORT": "cookie",
        "MATA_DATABASE_RLS_ENABLED": "false",
        "DATABASE_RLS_ENABLED": "false",
        "RATE_LIMIT_STORE": "postgres",
        "SUPABASE_URL": "https://project.supabase.co",
        "CORS_ORIGINS": "https://mata-aine.vercel.app",
        "MATA_ALLOWED_HOSTS": "mata-backend.vercel.app",
        **sensitive_values,
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    get_settings.cache_clear()
    try:
        with pytest.raises(
            SettingsConfigurationError,
            match="DATABASE_RLS_ENABLED must be true",
        ) as exc_info:
            get_settings()

        rendered_error = "".join(format_exception(exc_info.value))
        for sensitive_value in sensitive_values.values():
            assert sensitive_value not in rendered_error
        assert "input_value" not in rendered_error
    finally:
        get_settings.cache_clear()


def test_get_settings_redacts_unexpected_root_validation_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password = "runtime-password-must-never-appear"
    malformed_netloc = (
        f"runtime:{password}@db.example.invalid／tenant:5432"
    )
    malformed_database_url = (
        f"postgresql+asyncpg://{malformed_netloc}/mata"
    )
    auth_database_url = (
        "postgresql+asyncpg://auth:auth-password-do-not-log"
        "@db.example.invalid:5432/mata"
    )
    sync_database_url = (
        "postgresql+psycopg2://migration:migration-password-do-not-log"
        "@db.example.invalid:5432/mata"
    )
    session_hash_key = "session-hash-input-do-not-log-123456789"
    rate_limit_hash_secret = "rate-limit-input-do-not-log-123456789"
    environment = {
        "ENVIRONMENT": "production",
        "AUTH_MODE": "supabase",
        "AUTH_TRANSPORT": "cookie",
        "MATA_DATABASE_RLS_ENABLED": "true",
        "DATABASE_RLS_ENABLED": "true",
        "MATA_DATABASE_RUNTIME_ROLE": "mata_app_runtime",
        "MATA_DATABASE_AUTH_ROLE": "mata_auth_internal",
        "DATABASE_URL": malformed_database_url,
        "MATA_AUTH_DATABASE_URL": auth_database_url,
        "SYNC_DATABASE_URL": sync_database_url,
        "RATE_LIMIT_STORE": "postgres",
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_input-do-not-log",
        "MATA_SESSION_HASH_KEY": session_hash_key,
        "RATE_LIMIT_HASH_SECRET": rate_limit_hash_secret,
        "CORS_ORIGINS": "https://mata-aine.vercel.app",
        "MATA_ALLOWED_HOSTS": "mata-backend.vercel.app",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    get_settings.cache_clear()
    try:
        with pytest.raises(
            SettingsConfigurationError,
            match=r"configuration \(value_error\)",
        ) as exc_info:
            get_settings()

        error = exc_info.value
        rendered_values = (
            str(error),
            repr(error),
            "".join(format_exception(error)),
        )
        prohibited_fragments = (
            password,
            malformed_netloc,
            "db.example.invalid／tenant",
            malformed_database_url,
            "input_value",
        )
        for rendered_value in rendered_values:
            for prohibited_fragment in prohibited_fragments:
                assert prohibited_fragment not in rendered_value
        assert error.__cause__ is None
        assert error.__context__ is None
    finally:
        get_settings.cache_clear()
