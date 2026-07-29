from __future__ import annotations

import pytest

from app.config import Settings
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
