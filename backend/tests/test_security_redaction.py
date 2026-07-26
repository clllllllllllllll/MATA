from __future__ import annotations

import logging

from app.security.redaction import (
    REDACTED,
    log_safe_exception,
    redact_sensitive_data,
    redact_text,
)


def test_recursive_redaction_covers_headers_credentials_and_identity_secrets() -> None:
    payload = {
        "headers": {
            "Authorization": "Bearer secret-access-token",
            "Cookie": "__Host-mata_session=secret-session",
            "Set-Cookie": "__Host-mata_session=secret-session",
            "X-CSRF-Token": "secret-csrf",
            "apikey": "secret-api-key",
        },
        "body": {
            "access_token": "access",
            "refresh_token": "refresh",
            "password": "password",
            "mcr": "M12345A",
            "email": "resident@example.com",
            "client_ip": "203.0.113.9",
            "database_url": "postgresql://admin:password@database/private",
            "supabase_service_role_key": "service-role-value",
            "mata_resident_session_secret": "resident-session-value",
            "session_identifier": "opaque-session-value",
            "csrf_token": "csrf-value",
        },
        "safe": ["visible", {"count": 1}],
    }

    redacted = redact_sensitive_data(payload)

    assert set(redacted["headers"].values()) == {REDACTED}
    assert set(redacted["body"].values()) == {REDACTED}
    assert redacted["safe"] == ["visible", {"count": 1}]
    rendered = repr(redacted)
    for secret in (
        "M12345A",
        "resident@example.com",
        "203.0.113.9",
        "service-role-value",
        "opaque-session-value",
    ):
        assert secret not in rendered


def test_redact_text_removes_bearer_jwt_database_url_and_named_secrets() -> None:
    text = (
        "Authorization=Bearer abc.def.ghi "
        "database=postgresql+asyncpg://admin:secret@db/mata "
        "resident M12345A resident@example.com from 203.0.113.9 "
        "password=hunter2 sb_secret_do-not-log "
        "token=eyJabcdefghijk.abcdefghijk.abcdefghijk"
    )

    redacted = redact_text(text)

    assert "admin:secret" not in redacted
    assert "M12345A" not in redacted
    assert "resident@example.com" not in redacted
    assert "203.0.113.9" not in redacted
    assert "hunter2" not in redacted
    assert "sb_secret_do-not-log" not in redacted
    assert "eyJabcdefghijk" not in redacted


def test_recursive_redaction_handles_cycles_without_stringifying_objects() -> None:
    payload: dict[str, object] = {"safe": "value"}
    payload["cycle"] = payload

    redacted = redact_sensitive_data(payload)

    assert redacted == {"safe": "value", "cycle": REDACTED}


def test_safe_exception_logging_never_emits_exception_text_or_traceback(caplog) -> None:
    logger = logging.getLogger("tests.safe-redaction")
    error = RuntimeError(
        "postgresql://admin:password@private/db MCR=M12345A C:/private/upload.xlsx"
    )

    with caplog.at_level(logging.ERROR, logger=logger.name):
        log_safe_exception(logger, "upload_failed", error, category="upload_processing")

    assert "upload_failed" in caplog.text
    assert "category=upload_processing" in caplog.text
    assert "exception_class=RuntimeError" in caplog.text
    assert "admin:password" not in caplog.text
    assert "M12345A" not in caplog.text
    assert "private/upload.xlsx" not in caplog.text
    assert "Traceback" not in caplog.text
