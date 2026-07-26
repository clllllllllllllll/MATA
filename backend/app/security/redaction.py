from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any


REDACTED = "[REDACTED]"
_MAX_DEPTH = 20

_SENSITIVE_EXACT_KEYS = {
    "authorization",
    "proxy_authorization",
    "cookie",
    "set_cookie",
    "x_csrf_token",
    "apikey",
    "api_key",
    "access_token",
    "refresh_token",
    "password",
    "mcr",
    "resident_mcr",
    "database_url",
    "sync_database_url",
    "supabase_service_role_key",
    "mata_resident_session_secret",
    "mata_session_hash_key",
    "rate_limit_hash_secret",
    "session_id",
    "session_identifier",
    "session_token",
    "csrf_token",
}
_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "secret",
    "csrf",
    "access_token",
    "refresh_token",
    "service_role",
    "session_token",
    "session_identifier",
    "token_digest",
)

_CONNECTION_URL_RE = re.compile(
    r"\b(?:postgres(?:ql)?(?:\+asyncpg)?|mysql(?:\+\w+)?|mariadb|mssql|redis)"
    r"://[^\s'\"<>]+",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\bBearer\s+[^\s,;]+", re.IGNORECASE)
_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_IPV4_RE = re.compile(
    r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])"
)
_MCR_VALUE_RE = re.compile(r"\b[A-Z]{1,4}\d{4,8}[A-Z]\b", re.IGNORECASE)
_SUPABASE_SECRET_RE = re.compile(
    r"\bsb_(?:secret|service[_-]?role)_[A-Za-z0-9._-]+\b",
    re.IGNORECASE,
)
_NAMED_SECRET_RE = re.compile(
    r"(?i)\b(authorization|cookie|set-cookie|x-csrf-token|api[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|password|mcr|database[_-]?url|"
    r"service[_-]?role(?:[_-]?key)?|session[_-]?(?:id|token|secret)|"
    r"csrf[_-]?token)\b(\s*[:=]\s*)([^\s,;&]+)"
)


def _normalise_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().casefold()).strip("_")


def is_sensitive_key(key: object) -> bool:
    normalised = _normalise_key(key)
    if normalised in _SENSITIVE_EXACT_KEYS:
        return True
    if (
        normalised in {"email", "ip", "client_ip", "remote_addr", "x_forwarded_for"}
        or normalised.endswith(("_email", "_mcr", "_ip", "_token"))
        or normalised.endswith(("database_url", "db_url"))
    ):
        return True
    return any(fragment in normalised for fragment in _SENSITIVE_KEY_FRAGMENTS)


def redact_text(value: str) -> str:
    redacted = _CONNECTION_URL_RE.sub(REDACTED, value)
    redacted = _BEARER_RE.sub(f"Bearer {REDACTED}", redacted)
    redacted = _JWT_RE.sub(REDACTED, redacted)
    redacted = _EMAIL_RE.sub(REDACTED, redacted)
    redacted = _IPV4_RE.sub(REDACTED, redacted)
    redacted = _MCR_VALUE_RE.sub(REDACTED, redacted)
    redacted = _SUPABASE_SECRET_RE.sub(REDACTED, redacted)
    return _NAMED_SECRET_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}",
        redacted,
    )


def redact_sensitive_data(value: Any) -> Any:
    """Return a recursively redacted, JSON-friendly copy of potentially sensitive data."""

    return _redact(value, depth=0, active_ids=set())


def log_safe_exception(
    logger: logging.Logger,
    event: str,
    exc: BaseException,
    *,
    category: str,
) -> None:
    """Log an operational category without exception text or traceback material."""

    logger.error(
        "%s category=%s exception_class=%s",
        event,
        category,
        exc.__class__.__name__,
    )


def _redact(value: Any, *, depth: int, active_ids: set[int]) -> Any:
    if depth > _MAX_DEPTH:
        return REDACTED
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return REDACTED

    value_id = id(value)
    if value_id in active_ids:
        return REDACTED

    if isinstance(value, Mapping):
        active_ids.add(value_id)
        try:
            return {
                str(key): (
                    REDACTED
                    if is_sensitive_key(key)
                    else _redact(item, depth=depth + 1, active_ids=active_ids)
                )
                for key, item in value.items()
            }
        finally:
            active_ids.remove(value_id)

    if isinstance(value, (list, tuple, set, frozenset)):
        active_ids.add(value_id)
        try:
            return [
                _redact(item, depth=depth + 1, active_ids=active_ids)
                for item in value
            ]
        finally:
            active_ids.remove(value_id)

    # Avoid invoking arbitrary __str__ implementations that could reveal secrets.
    return f"<{value.__class__.__name__}>"
