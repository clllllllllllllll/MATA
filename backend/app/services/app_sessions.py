from __future__ import annotations

import base64
import binascii
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal, Mapping
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import Settings
from app.models.session import AppSession
from app.services.database_context import (
    session_uses_auth_boundary,
    session_uses_rls_helpers,
)


SESSION_TOKEN_BYTES = 32
CSRF_TOKEN_BYTES = 32
LOCAL_SESSION_HASH_KEY = "development-only-mata-app-session-hash-key"

_SESSION_DIGEST_DOMAIN = b"mata:app-session:token-digest:v1\x00"
_CSRF_TOKEN_DOMAIN = b"mata:app-session:csrf-token:v1\x00"
_CSRF_DIGEST_DOMAIN = b"mata:app-session:csrf-digest:v1\x00"
_USER_AGENT_DOMAIN = b"mata:app-session:user-agent:v1\x00"

SessionSubjectType = Literal["staff", "resident", "external_resident"]
SessionAuthSource = Literal["supabase_staff", "mata_resident"]
CsrfValidationResult = Literal["valid", "invalid_csrf", "invalid_session"]

_AUTH_SOURCE_BY_SUBJECT: dict[str, str] = {
    "staff": "supabase_staff",
    "resident": "mata_resident",
    "external_resident": "mata_resident",
}

_SUBJECT_LOCK_STATEMENTS = {
    "staff": text(
        """
        SELECT session_generation
        FROM users
        WHERE id = :subject_id
          AND role IN ('admin', 'secretary')
          AND is_active = true
          AND session_issuance_blocked = false
        FOR SHARE
        """
    ),
    "resident": text(
        """
        SELECT session_generation
        FROM residents
        WHERE id = :subject_id
          AND status = 'active'
        FOR SHARE
        """
    ),
    "external_resident": text(
        """
        SELECT session_generation
        FROM external_residents
        WHERE id = :subject_id
          AND status = 'active'
        FOR SHARE
        """
    ),
}

_SUBJECT_REVOCATION_LOCK_STATEMENTS = {
    "staff": text(
        """
        SELECT session_generation
        FROM users
        WHERE id = :subject_id
          AND role IN ('admin', 'secretary')
        FOR SHARE
        """
    ),
    "resident": text(
        """
        SELECT session_generation
        FROM residents
        WHERE id = :subject_id
        FOR SHARE
        """
    ),
    "external_resident": text(
        """
        SELECT session_generation
        FROM external_residents
        WHERE id = :subject_id
        FOR SHARE
        """
    ),
}

_SUBJECT_INVALIDATION_STATEMENTS = {
    "staff": text(
        """
        UPDATE users
        SET
            session_generation = session_generation + 1,
            session_issuance_blocked = CASE
                WHEN :block_session_issuance THEN true
                ELSE session_issuance_blocked
            END
        WHERE id = :subject_id
        RETURNING session_generation
        """
    ),
    "resident": text(
        """
        UPDATE residents
        SET session_generation = session_generation + 1
        WHERE id = :subject_id
        RETURNING session_generation
        """
    ),
    "external_resident": text(
        """
        UPDATE external_residents
        SET session_generation = session_generation + 1
        WHERE id = :subject_id
        RETURNING session_generation
        """
    ),
}


class AppSessionError(RuntimeError):
    """Base class for controlled application-session failures."""


class AppSessionConfigurationError(AppSessionError):
    """Raised when secure session hashing cannot be configured."""


class AppSessionInvalidError(AppSessionError):
    """Raised when a session can no longer be safely used or rotated."""


@dataclass(frozen=True, slots=True)
class CreatedSession:
    session: AppSession | SessionLifecycle
    session_token: str
    csrf_token: str


@dataclass
class SessionLifecycle:
    """Minimum server-side state needed after a restricted helper call.

    ``token_digest`` is derived locally from the presented opaque credential;
    it is never returned by a restricted PostgreSQL helper. Stored expiry
    fields likewise remain private. The HTTP layer issues a non-persistent
    browser-session cookie and relies exclusively on synchronous server-side
    deadline enforcement.
    """

    id: UUID
    token_digest: bytes
    subject_type: SessionSubjectType
    subject_id: UUID
    subject_session_generation: int
    session_family_id: UUID
    auth_source: SessionAuthSource
    rotated_from_session_id: UUID | None = None
    session_refresh_required: bool = False
    revoked_at: datetime | None = None
    revoked_reason: str | None = None
    _mata_authorization_fingerprint: str | None = None
    _mata_identity_context: dict[str, Any] | None = None


SessionState = AppSession | SessionLifecycle


_APP_SESSION_COLUMNS = (
    "id",
    "token_digest",
    "subject_type",
    "subject_id",
    "subject_session_generation",
    "session_family_id",
    "auth_source",
    "csrf_token_digest",
    "created_at",
    "last_seen_at",
    "idle_expires_at",
    "absolute_expires_at",
    "revoked_at",
    "revoked_reason",
    "rotated_from_session_id",
    "user_agent_hash",
)
_AUTHORIZATION_FINGERPRINT_ATTRIBUTE = "_mata_authorization_fingerprint"
_IDENTITY_CONTEXT_ATTRIBUTE = "_mata_identity_context"


def _identity_context_from_mapping(row: Mapping[str, Any]) -> dict[str, Any] | None:
    if "app_role" not in row:
        return None
    raw_scope = row.get("programme_scope")
    scope = (
        [
            str(value).strip().upper()
            for value in raw_scope
            if str(value).strip()
        ]
        if isinstance(raw_scope, (list, tuple))
        else []
    )
    return {
        "app_role": str(row.get("app_role") or "").strip().lower(),
        "admin_level": row.get("admin_level"),
        "programme_scope": sorted(set(scope)),
        "posting_code": row.get("posting_code"),
        "current_staff_actor_name": row.get("current_staff_actor_name"),
    }


def _app_session_from_mapping(row: Mapping[str, Any]) -> AppSession:
    values = {column: row[column] for column in _APP_SESSION_COLUMNS}
    values["token_digest"] = bytes(values["token_digest"])
    values["csrf_token_digest"] = bytes(values["csrf_token_digest"])
    if values["user_agent_hash"] is not None:
        values["user_agent_hash"] = bytes(values["user_agent_hash"])
    session = AppSession(**values)
    fingerprint = row.get("authorization_fingerprint")
    if fingerprint is not None:
        setattr(
            session,
            _AUTHORIZATION_FINGERPRINT_ATTRIBUTE,
            str(fingerprint),
        )
    identity_context = _identity_context_from_mapping(row)
    if identity_context is not None:
        setattr(
            session,
            _IDENTITY_CONTEXT_ATTRIBUTE,
            identity_context,
        )
    return session


def _lifecycle_session_from_mapping(
    row: Mapping[str, Any],
    *,
    token_digest: bytes,
) -> SessionLifecycle:
    fingerprint = row.get("authorization_fingerprint")
    return SessionLifecycle(
        id=UUID(str(row["id"])),
        token_digest=bytes(token_digest),
        subject_type=str(row["subject_type"]),
        subject_id=UUID(str(row["subject_id"])),
        subject_session_generation=int(row["subject_session_generation"]),
        session_family_id=UUID(str(row["session_family_id"])),
        auth_source=str(row["auth_source"]),
        rotated_from_session_id=(
            UUID(str(row["rotated_from_session_id"]))
            if row.get("rotated_from_session_id") is not None
            else None
        ),
        session_refresh_required=bool(
            row.get("session_refresh_required", False)
        ),
        _mata_authorization_fingerprint=(
            str(fingerprint) if fingerprint is not None else None
        ),
        _mata_identity_context=_identity_context_from_mapping(row),
    )


def authorization_fingerprint_for_session(
    session: SessionState,
) -> str | None:
    fingerprint = getattr(
        session,
        _AUTHORIZATION_FINGERPRINT_ATTRIBUTE,
        None,
    )
    return fingerprint if isinstance(fingerprint, str) else None


def identity_context_for_session(
    session: SessionState,
) -> dict[str, Any] | None:
    context = getattr(session, _IDENTITY_CONTEXT_ATTRIBUTE, None)
    return dict(context) if isinstance(context, dict) else None


async def _cleanup_sessions_with_helper(
    db: AsyncSession,
    settings: Settings,
) -> int:
    result = await db.execute(
        text(
            """
            SELECT mata_rls.cleanup_app_sessions(
                CAST(:retention_seconds AS integer),
                CAST(:batch_size AS integer)
            )
            """
        ),
        {
            "retention_seconds": max(
                0,
                int(settings.session_cleanup_retention_seconds),
            ),
            "batch_size": max(1, int(settings.session_cleanup_batch_size)),
        },
    )
    return int(result.scalar_one())


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _session_hash_key(settings: Settings) -> bytes:
    configured = getattr(settings, "mata_session_hash_key", None)
    if hasattr(configured, "get_secret_value"):
        configured = configured.get_secret_value()
    configured_text = str(configured or "").strip()
    if configured_text:
        key = configured_text.encode("utf-8")
        if settings.environment == "production" and len(key) < 32:
            raise AppSessionConfigurationError(
                "MATA_SESSION_HASH_KEY must contain at least 32 bytes"
            )
        return key

    if settings.environment in {"development", "test"}:
        return LOCAL_SESSION_HASH_KEY.encode("utf-8")
    raise AppSessionConfigurationError("MATA_SESSION_HASH_KEY is required")


def _encode_raw_token(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def parse_raw_token(
    raw_token: str | None,
    *,
    expected_bytes: int = SESSION_TOKEN_BYTES,
) -> bytes | None:
    """Parse a canonical, unpadded base64url token without accepting aliases."""

    if not isinstance(raw_token, str) or not raw_token or len(raw_token) > 128:
        return None
    try:
        encoded = raw_token.encode("ascii")
    except UnicodeEncodeError:
        return None

    padding = b"=" * (-len(encoded) % 4)
    try:
        decoded = base64.b64decode(
            encoded + padding,
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError):
        return None

    if len(decoded) != expected_bytes:
        return None
    canonical = _encode_raw_token(decoded)
    if not hmac.compare_digest(canonical, raw_token):
        return None
    return decoded


def parse_session_token(raw_token: str | None) -> bytes | None:
    return parse_raw_token(raw_token, expected_bytes=SESSION_TOKEN_BYTES)


def parse_csrf_token(raw_token: str | None) -> bytes | None:
    return parse_raw_token(raw_token, expected_bytes=CSRF_TOKEN_BYTES)


def _keyed_digest(key: bytes, domain: bytes, raw: bytes) -> bytes:
    return hmac.new(key, domain + raw, sha256).digest()


def _session_digest(session_bytes: bytes, *, key: bytes) -> bytes:
    return _keyed_digest(key, _SESSION_DIGEST_DOMAIN, session_bytes)


def _csrf_bytes_for_session(session_bytes: bytes, *, key: bytes) -> bytes:
    return _keyed_digest(key, _CSRF_TOKEN_DOMAIN, session_bytes)


def _csrf_digest(csrf_bytes: bytes, *, key: bytes) -> bytes:
    return _keyed_digest(key, _CSRF_DIGEST_DOMAIN, csrf_bytes)


def csrf_for_session_token(session_token: str, settings: Settings) -> str:
    """Return the stable CSRF token associated with one valid session token.

    The deterministic, domain-separated derivation lets a safe session
    hydration request recover the synchronizer token without mutating the row.
    """

    session_bytes = parse_session_token(session_token)
    if session_bytes is None:
        raise AppSessionInvalidError("Invalid application session")
    csrf_bytes = _csrf_bytes_for_session(
        session_bytes,
        key=_session_hash_key(settings),
    )
    return _encode_raw_token(csrf_bytes)


def _user_agent_digest(user_agent: str | None, *, key: bytes) -> bytes | None:
    if not user_agent:
        return None
    return _keyed_digest(key, _USER_AGENT_DOMAIN, user_agent.encode("utf-8"))


def _timeouts_for_subject(
    settings: Settings,
    subject_type: SessionSubjectType,
) -> tuple[int, int]:
    if subject_type == "staff":
        idle = int(settings.staff_session_idle_timeout_seconds)
        absolute = int(settings.staff_session_absolute_timeout_seconds)
    else:
        idle = int(settings.resident_session_idle_timeout_seconds)
        absolute = int(settings.resident_session_absolute_timeout_seconds)
    return max(1, idle), max(1, absolute)


def _validate_subject_auth_source(
    subject_type: str,
    auth_source: str,
) -> None:
    expected_source = _AUTH_SOURCE_BY_SUBJECT.get(subject_type)
    if expected_source is None or not hmac.compare_digest(expected_source, auth_source):
        raise ValueError("Invalid application-session subject/auth source")


async def _lock_subject_for_session(
    db: AsyncSession,
    *,
    subject_type: SessionSubjectType,
    subject_id: UUID,
    expected_session_generation: int,
) -> int:
    statement = _SUBJECT_LOCK_STATEMENTS.get(subject_type)
    if statement is None:
        raise ValueError("Invalid application-session subject type")
    result = await db.execute(statement, {"subject_id": subject_id})
    current_generation = result.scalar_one_or_none()
    if current_generation is None:
        raise AppSessionInvalidError("Application-session subject is unavailable")
    current_generation = int(current_generation)
    if current_generation != expected_session_generation:
        raise AppSessionInvalidError("Application-session subject changed")
    return current_generation


async def _lock_subject_for_family_revocation(
    db: AsyncSession,
    *,
    subject_type: SessionSubjectType,
    subject_id: UUID,
) -> int | None:
    statement = _SUBJECT_REVOCATION_LOCK_STATEMENTS.get(subject_type)
    if statement is None:
        raise ValueError("Invalid application-session subject type")
    result = await db.execute(statement, {"subject_id": subject_id})
    generation = result.scalar_one_or_none()
    return int(generation) if generation is not None else None


def _session_family_lock_key(session_family_id: UUID) -> int:
    """Fold a UUID into PostgreSQL's signed 64-bit advisory-lock key space."""

    mask = (1 << 64) - 1
    folded = ((session_family_id.int >> 64) ^ session_family_id.int) & mask
    return folded - (1 << 64) if folded >= (1 << 63) else folded


async def _lock_session_family(
    db: AsyncSession,
    session_family_id: UUID,
) -> None:
    # Transaction-scoped advisory locks are released by PostgreSQL on commit,
    # rollback, cancellation, or connection loss, so pooled connections cannot
    # retain a family lock after the transaction ends.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:family_lock_key)"),
        {"family_lock_key": _session_family_lock_key(session_family_id)},
    )


def _is_active(session: AppSession, *, now: datetime) -> bool:
    current_time = _utc(now)
    return (
        session.revoked_at is None
        and current_time < _utc(session.idle_expires_at)
        and current_time < _utc(session.absolute_expires_at)
    )


def _new_session_material(*, settings: Settings) -> tuple[str, bytes, str, bytes]:
    key = _session_hash_key(settings)
    session_bytes = secrets.token_bytes(SESSION_TOKEN_BYTES)
    csrf_bytes = _csrf_bytes_for_session(session_bytes, key=key)
    return (
        _encode_raw_token(session_bytes),
        _session_digest(session_bytes, key=key),
        _encode_raw_token(csrf_bytes),
        _csrf_digest(csrf_bytes, key=key),
    )


async def create_session(
    db: AsyncSession,
    settings: Settings,
    subject_type: SessionSubjectType,
    subject_id: UUID,
    auth_source: SessionAuthSource,
    *,
    expected_subject_session_generation: int,
    normalized_mcr: str | None = None,
    upstream_subject_id: UUID | None = None,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> CreatedSession:
    _validate_subject_auth_source(subject_type, auth_source)
    if session_uses_rls_helpers(db):
        if now is not None:
            raise ValueError(
                "Database-backed application sessions use PostgreSQL time"
            )
        current_generation = int(expected_subject_session_generation)
        if current_generation < 0:
            raise AppSessionInvalidError("Application-session subject changed")
        idle_seconds, absolute_seconds = _timeouts_for_subject(
            settings,
            subject_type,
        )
        (
            session_token,
            token_digest,
            csrf_token,
            csrf_token_digest,
        ) = _new_session_material(settings=settings)
        key = _session_hash_key(settings)
        session_id = uuid4()
        user_agent_hash = _user_agent_digest(user_agent, key=key)

        if subject_type == "staff":
            if upstream_subject_id is None:
                raise AppSessionInvalidError(
                    "Verified staff authentication binding is missing"
                )
            statement = text(
                """
                SELECT *
                FROM mata_rls.issue_staff_app_session_lifecycle(
                    CAST(:subject_id AS uuid),
                    CAST(:upstream_subject_id AS uuid),
                    CAST(:expected_generation AS bigint),
                    CAST(:session_id AS uuid),
                    CAST(:token_digest AS bytea),
                    CAST(:csrf_token_digest AS bytea),
                    CAST(:idle_timeout_seconds AS integer),
                    CAST(:absolute_timeout_seconds AS integer),
                    CAST(:user_agent_hash AS bytea)
                )
                """
            )
            parameters: dict[str, Any] = {
                "subject_id": subject_id,
                "upstream_subject_id": upstream_subject_id,
            }
        else:
            credential = (normalized_mcr or "").strip().upper()
            if not credential:
                raise AppSessionInvalidError(
                    "Verified Resident authentication binding is missing"
                )
            if subject_type == "resident":
                statement = text(
                    """
                    SELECT *
                    FROM mata_rls.issue_resident_app_session_lifecycle(
                        CAST(:normalized_mcr AS text),
                        CAST(:expected_subject_type AS text),
                        CAST(:subject_id AS uuid),
                        CAST(:expected_generation AS bigint),
                        CAST(:session_id AS uuid),
                        CAST(:token_digest AS bytea),
                        CAST(:csrf_token_digest AS bytea),
                        CAST(:idle_timeout_seconds AS integer),
                        CAST(:absolute_timeout_seconds AS integer),
                        CAST(:user_agent_hash AS bytea)
                    )
                    """
                )
            else:
                statement = text(
                    """
                    SELECT *
                    FROM mata_rls.issue_external_resident_app_session_lifecycle(
                        CAST(:normalized_mcr AS text),
                        CAST(:expected_subject_type AS text),
                        CAST(:subject_id AS uuid),
                        CAST(:expected_generation AS bigint),
                        CAST(:session_id AS uuid),
                        CAST(:token_digest AS bytea),
                        CAST(:csrf_token_digest AS bytea),
                        CAST(:idle_timeout_seconds AS integer),
                        CAST(:absolute_timeout_seconds AS integer),
                        CAST(:user_agent_hash AS bytea)
                    )
                    """
                )
            parameters = {
                "normalized_mcr": credential,
                "expected_subject_type": subject_type,
                "subject_id": subject_id,
            }

        parameters.update(
            {
                "expected_generation": current_generation,
                "session_id": session_id,
                "token_digest": token_digest,
                "csrf_token_digest": csrf_token_digest,
                "idle_timeout_seconds": idle_seconds,
                "absolute_timeout_seconds": absolute_seconds,
                "user_agent_hash": user_agent_hash,
            }
        )
        result = await db.execute(statement, parameters)
        row = result.mappings().one_or_none()
        if row is None:
            raise AppSessionInvalidError(
                "Application-session subject is unavailable"
            )
        session = _lifecycle_session_from_mapping(
            row,
            token_digest=token_digest,
        )
        if (
            session.id != session_id
            or session.subject_type != subject_type
            or session.subject_id != subject_id
            or session.subject_session_generation != current_generation
            or session.session_family_id != session_id
        ):
            raise AppSessionInvalidError(
                "Application-session issuance binding changed"
            )
        await _cleanup_sessions_with_helper(db, settings)
        return CreatedSession(
            session=session,
            session_token=session_token,
            csrf_token=csrf_token,
        )

    subject_session_generation = await _lock_subject_for_session(
        db,
        subject_type=subject_type,
        subject_id=subject_id,
        expected_session_generation=expected_subject_session_generation,
    )
    current_time = _utc(now or datetime.now(UTC))
    idle_seconds, absolute_seconds = _timeouts_for_subject(settings, subject_type)
    absolute_expires_at = current_time + timedelta(seconds=absolute_seconds)
    idle_expires_at = min(
        current_time + timedelta(seconds=idle_seconds),
        absolute_expires_at,
    )
    session_token, token_digest, csrf_token, csrf_token_digest = _new_session_material(
        settings=settings
    )
    key = _session_hash_key(settings)
    session_id = uuid4()
    session = AppSession(
        id=session_id,
        token_digest=token_digest,
        subject_type=subject_type,
        subject_id=subject_id,
        subject_session_generation=subject_session_generation,
        session_family_id=session_id,
        auth_source=auth_source,
        csrf_token_digest=csrf_token_digest,
        created_at=current_time,
        last_seen_at=current_time,
        idle_expires_at=idle_expires_at,
        absolute_expires_at=absolute_expires_at,
        revoked_at=None,
        revoked_reason=None,
        rotated_from_session_id=None,
        user_agent_hash=_user_agent_digest(user_agent, key=key),
    )
    db.add(session)
    await db.flush()
    await cleanup_sessions(db, settings, now=current_time)
    return CreatedSession(
        session=session,
        session_token=session_token,
        csrf_token=csrf_token,
    )


async def resolve_session(
    db: AsyncSession,
    settings: Settings,
    session_token: str | None,
    *,
    now: datetime | None = None,
    touch: bool = False,
) -> SessionState | None:
    session_bytes = parse_session_token(session_token)
    if session_bytes is None:
        return None

    key = _session_hash_key(settings)
    expected_digest = _session_digest(session_bytes, key=key)
    if session_uses_rls_helpers(db):
        if now is not None:
            raise ValueError(
                "Database-backed application sessions use PostgreSQL time"
            )

        result = await db.execute(
            text(
                """
                SELECT *
                FROM mata_rls.resolve_app_session_lifecycle(
                    CAST(:token_digest AS bytea),
                    CAST(:rotation_threshold_seconds AS integer)
                )
                """
            ),
            {
                "token_digest": expected_digest,
                "rotation_threshold_seconds": int(
                    settings.session_rotation_seconds
                ),
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        session = _lifecycle_session_from_mapping(
            row,
            token_digest=expected_digest,
        )
        _validate_subject_auth_source(
            session.subject_type,
            session.auth_source,
        )
        if not touch:
            return session
        if not await touch_session(db, settings, session):
            return None
        return session

    statement = select(AppSession).where(AppSession.token_digest == expected_digest)
    result = await db.execute(statement)
    session = result.scalar_one_or_none()
    if session is None:
        return None
    if not hmac.compare_digest(bytes(session.token_digest), expected_digest):
        return None

    current_time = _utc(now or datetime.now(UTC))
    if not _is_active(session, now=current_time):
        return None

    if touch and not await touch_session(
        db,
        settings,
        session,
        session_token=session_token,
        now=current_time,
    ):
        return None
    return session


async def _lock_session_family_shared(
    db: AsyncSession,
    session_family_id: UUID,
) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock_shared(:family_lock_key)"),
        {"family_lock_key": _session_family_lock_key(session_family_id)},
    )


async def touch_session(
    db: AsyncSession,
    settings: Settings,
    session: SessionState,
    *,
    session_token: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Atomically extend idle expiry when qualifying activity is due.

    The absolute family deadline is immutable.  A false result means the row,
    subject binding, generation, or either deadline is no longer valid.
    """

    idle_seconds, _ = _timeouts_for_subject(settings, session.subject_type)
    touch_interval_seconds = int(settings.session_touch_interval_seconds)
    expected_digest = bytes(session.token_digest)
    if session_token is not None:
        session_bytes = parse_session_token(session_token)
        if session_bytes is None:
            return False
        supplied_digest = _session_digest(
            session_bytes,
            key=_session_hash_key(settings),
        )
        if not hmac.compare_digest(expected_digest, supplied_digest):
            return False
        expected_digest = supplied_digest

    if session_uses_rls_helpers(db):
        if now is not None:
            raise ValueError(
                "Database-backed application sessions use PostgreSQL time"
            )
        result = await db.execute(
            text(
                """
                SELECT mata_rls.touch_app_session_lifecycle(
                    CAST(:token_digest AS bytea),
                    CAST(:expected_session_id AS uuid),
                    CAST(:idle_timeout_seconds AS integer),
                    CAST(:touch_interval_seconds AS integer)
                )
                """
            ),
            {
                "token_digest": expected_digest,
                "expected_session_id": session.id,
                "idle_timeout_seconds": idle_seconds,
                "touch_interval_seconds": touch_interval_seconds,
            },
        )
        return bool(result.scalar_one())

    try:
        await _lock_subject_for_session(
            db,
            subject_type=session.subject_type,
            subject_id=session.subject_id,
            expected_session_generation=int(
                session.subject_session_generation
            ),
        )
    except AppSessionInvalidError:
        return False
    await _lock_session_family_shared(
        db,
        UUID(str(session.session_family_id)),
    )
    locked = await _locked_session_by_id(db, session.id)
    current_time = _utc(now or datetime.now(UTC))
    if locked is None or not _is_active(locked, now=current_time):
        return False
    if (
        locked.subject_type != session.subject_type
        or locked.subject_id != session.subject_id
        or locked.subject_session_generation
        != int(session.subject_session_generation)
        or locked.session_family_id != session.session_family_id
        or not hmac.compare_digest(
            bytes(locked.token_digest),
            expected_digest,
        )
    ):
        return False
    if current_time >= _utc(locked.last_seen_at) + timedelta(
        seconds=touch_interval_seconds
    ):
        locked.last_seen_at = current_time
        locked.idle_expires_at = min(
            current_time + timedelta(seconds=idle_seconds),
            _utc(locked.absolute_expires_at),
        )
        await db.flush()
    return True


def validate_csrf(
    session: AppSession,
    csrf_token: str | None,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> bool:
    csrf_bytes = parse_csrf_token(csrf_token)
    if csrf_bytes is None:
        return False
    current_time = _utc(now or datetime.now(UTC))
    if not _is_active(session, now=current_time):
        return False
    expected_digest = _csrf_digest(csrf_bytes, key=_session_hash_key(settings))
    return hmac.compare_digest(bytes(session.csrf_token_digest), expected_digest)


async def validate_session_csrf(
    db: AsyncSession,
    session: SessionState,
    csrf_token: str | None,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> CsrfValidationResult:
    """Validate both current session state and the submitted CSRF secret."""

    if not session_uses_rls_helpers(db):
        current_time = _utc(now or datetime.now(UTC))
        if not isinstance(session, AppSession) or not _is_active(
            session,
            now=current_time,
        ):
            return "invalid_session"
        return (
            "valid"
            if validate_csrf(
                session,
                csrf_token,
                settings,
                now=current_time,
            )
            else "invalid_csrf"
        )

    if now is not None:
        raise ValueError(
            "Database-backed application sessions use PostgreSQL time"
        )
    csrf_bytes = parse_csrf_token(csrf_token)
    supplied_digest = (
        _csrf_digest(csrf_bytes, key=_session_hash_key(settings))
        if csrf_bytes is not None
        else bytes(CSRF_TOKEN_BYTES)
    )
    result = await db.execute(
        text(
            """
            SELECT mata_rls.validate_app_session_csrf(
                CAST(:token_digest AS bytea),
                CAST(:expected_session_id AS uuid),
                CAST(:csrf_token_digest AS bytea)
            )
            """
        ),
        {
            "token_digest": bytes(session.token_digest),
            "expected_session_id": session.id,
            "csrf_token_digest": supplied_digest,
        },
    )
    valid = result.scalar_one_or_none()
    if valid is None:
        return "invalid_session"
    return "valid" if bool(valid) else "invalid_csrf"


def session_needs_rotation(
    session: SessionState,
    *,
    settings: Settings,
    now: datetime | None = None,
) -> bool:
    if isinstance(session, SessionLifecycle):
        return (
            session.revoked_at is None
            and bool(session.session_refresh_required)
        )
    threshold = max(1, int(settings.session_rotation_seconds))
    current_time = _utc(now or datetime.now(UTC))
    return _is_active(session, now=current_time) and (
        current_time - _utc(session.created_at)
    ).total_seconds() >= threshold


async def _locked_session_by_id(
    db: AsyncSession,
    session_id: UUID,
) -> AppSession | None:
    result = await db.execute(
        select(AppSession)
        .where(AppSession.id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def rotate_session(
    db: AsyncSession,
    settings: Settings,
    session: SessionState,
    *,
    session_token: str | None = None,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> CreatedSession:
    try:
        expected_generation = int(session.subject_session_generation)
        session_family_id = UUID(str(session.session_family_id))
    except (TypeError, ValueError) as exc:
        raise AppSessionInvalidError(
            "Application session has invalid subject state"
        ) from exc
    if session_uses_rls_helpers(db):
        if now is not None:
            raise ValueError(
                "Database-backed application sessions use PostgreSQL time"
            )
        if session_token is None:
            old_digest = bytes(session.token_digest)
        else:
            session_bytes = parse_session_token(session_token)
            if session_bytes is None:
                raise AppSessionInvalidError(
                    "Application session is no longer active"
                )
            old_digest = _session_digest(
                session_bytes,
                key=_session_hash_key(settings),
            )
            if not hmac.compare_digest(
                bytes(session.token_digest),
                old_digest,
            ):
                raise AppSessionInvalidError(
                    "Application session is no longer active"
                )

        (
            new_session_token,
            new_token_digest,
            new_csrf_token,
            new_csrf_token_digest,
        ) = _new_session_material(settings=settings)
        replacement_id = uuid4()
        idle_seconds, _ = _timeouts_for_subject(
            settings,
            session.subject_type,
        )
        new_user_agent_hash = (
            _user_agent_digest(
                user_agent,
                key=_session_hash_key(settings),
            )
            if user_agent is not None
            else None
        )
        result = await db.execute(
            text(
                """
                SELECT *
                FROM mata_rls.rotate_app_session_lifecycle(
                    CAST(:old_token_digest AS bytea),
                    CAST(:expected_parent_id AS uuid),
                    CAST(:new_session_id AS uuid),
                    CAST(:new_token_digest AS bytea),
                    CAST(:new_csrf_token_digest AS bytea),
                    CAST(:idle_timeout_seconds AS integer),
                    CAST(:new_user_agent_hash AS bytea)
                )
                """
            ),
            {
                "old_token_digest": old_digest,
                "expected_parent_id": session.id,
                "new_session_id": replacement_id,
                "new_token_digest": new_token_digest,
                "new_csrf_token_digest": new_csrf_token_digest,
                "idle_timeout_seconds": idle_seconds,
                "new_user_agent_hash": new_user_agent_hash,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise AppSessionInvalidError(
                "Application session is no longer active"
            )
        rotated = _lifecycle_session_from_mapping(
            row,
            token_digest=new_token_digest,
        )
        if (
            rotated.id != replacement_id
            or rotated.rotated_from_session_id != session.id
            or rotated.session_family_id != session_family_id
            or rotated.subject_type != session.subject_type
            or rotated.subject_id != session.subject_id
            or rotated.subject_session_generation != expected_generation
        ):
            raise AppSessionInvalidError(
                "Application-session rotation binding changed"
            )
        session.revoked_at = datetime.now(UTC)
        session.revoked_reason = "rotated"
        await _cleanup_sessions_with_helper(db, settings)
        return CreatedSession(
            session=rotated,
            session_token=new_session_token,
            csrf_token=new_csrf_token,
        )

    await _lock_subject_for_session(
        db,
        subject_type=session.subject_type,
        subject_id=session.subject_id,
        expected_session_generation=expected_generation,
    )
    await _lock_session_family(db, session_family_id)
    locked = await _locked_session_by_id(db, session.id)
    current_time = _utc(now or datetime.now(UTC))
    if locked is None or not _is_active(locked, now=current_time):
        raise AppSessionInvalidError("Application session is no longer active")
    if (
        locked.subject_type != session.subject_type
        or locked.subject_id != session.subject_id
        or locked.subject_session_generation != expected_generation
        or locked.session_family_id != session_family_id
    ):
        raise AppSessionInvalidError("Application session subject changed")

    if session_token is not None:
        session_bytes = parse_session_token(session_token)
        if session_bytes is None:
            raise AppSessionInvalidError("Application session is no longer active")
        supplied_digest = _session_digest(
            session_bytes,
            key=_session_hash_key(settings),
        )
        if not hmac.compare_digest(bytes(locked.token_digest), supplied_digest):
            raise AppSessionInvalidError("Application session is no longer active")

    subject_type = locked.subject_type
    auth_source = locked.auth_source
    _validate_subject_auth_source(subject_type, auth_source)
    idle_seconds, _absolute_seconds = _timeouts_for_subject(settings, subject_type)
    parent_idle_expires_at = _utc(locked.idle_expires_at)
    parent_last_seen_at = _utc(locked.last_seen_at)
    absolute_expires_at = _utc(locked.absolute_expires_at)
    idle_expires_at = min(
        parent_idle_expires_at,
        current_time + timedelta(seconds=idle_seconds),
        absolute_expires_at,
    )
    if idle_expires_at <= current_time:
        raise AppSessionInvalidError("Application session is no longer active")

    session_token_new, token_digest, csrf_token, csrf_token_digest = _new_session_material(
        settings=settings
    )
    key = _session_hash_key(settings)
    rotated = AppSession(
        id=uuid4(),
        token_digest=token_digest,
        subject_type=subject_type,
        subject_id=locked.subject_id,
        subject_session_generation=locked.subject_session_generation,
        session_family_id=locked.session_family_id,
        auth_source=auth_source,
        csrf_token_digest=csrf_token_digest,
        created_at=current_time,
        # Refresh is credential maintenance, not qualifying activity.  Carry
        # the family's last real activity forward so interval gating cannot
        # suppress a mutation that occurs near the inherited idle deadline.
        last_seen_at=parent_last_seen_at,
        idle_expires_at=idle_expires_at,
        absolute_expires_at=absolute_expires_at,
        revoked_at=None,
        revoked_reason=None,
        rotated_from_session_id=locked.id,
        user_agent_hash=(
            _user_agent_digest(user_agent, key=key)
            if user_agent is not None
            else locked.user_agent_hash
        ),
    )
    locked.revoked_at = current_time
    locked.revoked_reason = "rotated"
    db.add(rotated)
    await db.flush()
    await cleanup_sessions(db, settings, now=current_time)
    return CreatedSession(
        session=rotated,
        session_token=session_token_new,
        csrf_token=csrf_token,
    )


async def revoke_session(
    db: AsyncSession,
    session: SessionState,
    *,
    reason: str,
    now: datetime | None = None,
) -> bool:
    if session_uses_rls_helpers(db):
        if now is not None:
            raise ValueError(
                "Database-backed application sessions use PostgreSQL time"
            )
        result = await db.execute(
            text(
                """
                SELECT mata_rls.revoke_app_session(
                    CAST(:token_digest AS bytea),
                    CAST(:session_id AS uuid),
                    CAST(:reason AS text)
                )
                """
            ),
            {
                "token_digest": bytes(session.token_digest),
                "session_id": session.id,
                "reason": reason.strip() or "revoked",
            },
        )
        revoked = bool(result.scalar_one())
        if revoked:
            session.revoked_at = datetime.now(UTC)
            session.revoked_reason = reason.strip() or "revoked"
        return revoked

    locked = await _locked_session_by_id(db, session.id)
    if locked is None or locked.revoked_at is not None:
        return False
    locked.revoked_at = _utc(now or datetime.now(UTC))
    locked.revoked_reason = reason.strip() or "revoked"
    await db.flush()
    return True


async def revoke_session_family(
    db: AsyncSession,
    session: SessionState,
    *,
    reason: str,
    now: datetime | None = None,
) -> int:
    """Revoke the current rotation family without affecting other devices."""

    try:
        subject_type: SessionSubjectType = session.subject_type
        session_family_id = UUID(str(session.session_family_id))
    except (AttributeError, TypeError, ValueError) as exc:
        raise AppSessionInvalidError(
            "Application session has invalid family state"
        ) from exc
    if subject_type not in _SUBJECT_REVOCATION_LOCK_STATEMENTS:
        raise AppSessionInvalidError("Application session has invalid family state")

    if session_uses_rls_helpers(db):
        if now is not None:
            raise ValueError(
                "Database-backed application sessions use PostgreSQL time"
            )
        result = await db.execute(
            text(
                """
                SELECT mata_rls.revoke_app_session_family(
                    CAST(:token_digest AS bytea),
                    CAST(:expected_session_id AS uuid),
                    CAST(:reason AS text)
                )
                """
            ),
            {
                "token_digest": bytes(session.token_digest),
                "expected_session_id": session.id,
                "reason": reason.strip() or "family_revoked",
            },
        )
        revoked_count = int(result.scalar_one())
        if revoked_count:
            session.revoked_at = datetime.now(UTC)
            session.revoked_reason = reason.strip() or "family_revoked"
        return revoked_count

    # Keep the global order subject -> family -> session rows. This serializes
    # logout with refresh and subject-wide invalidation without deadlocks.
    await _lock_subject_for_family_revocation(
        db,
        subject_type=subject_type,
        subject_id=session.subject_id,
    )
    await _lock_session_family(db, session_family_id)
    result = await db.execute(
        update(AppSession)
        .where(
            AppSession.session_family_id == session_family_id,
            AppSession.subject_type == subject_type,
            AppSession.subject_id == session.subject_id,
            AppSession.revoked_at.is_(None),
        )
        .values(
            revoked_at=_utc(now or datetime.now(UTC)),
            revoked_reason=reason.strip() or "family_revoked",
        )
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


async def revoke_session_family_for_logout(
    db: AsyncSession,
    settings: Settings,
    *,
    session_token: str | None,
    csrf_token: str | None,
    reason: str = "logout",
    now: datetime | None = None,
) -> int:
    """Revoke the family proved by a logout credential pair.

    This path deliberately does not require a hydrated active session. A
    concurrent refresh may already have revoked the presented parent before
    logout middleware resolves it. The proof remains termination-only: both
    opaque credential digests normally match a still-valid active row or an
    absolute-unexpired row revoked specifically by rotation. A stale tab may
    instead pair the active child cookie with a rotated ancestor's CSRF value;
    that mixed proof is accepted only when both rows share the same immutable
    subject, generation, family, and auth source. The family is always derived
    server-side.
    """

    session_bytes = parse_session_token(session_token)
    csrf_bytes = parse_csrf_token(csrf_token)
    if session_bytes is None or csrf_bytes is None:
        return 0

    key = _session_hash_key(settings)
    token_digest = _session_digest(session_bytes, key=key)
    csrf_token_digest = _csrf_digest(csrf_bytes, key=key)
    normalized_reason = reason.strip() or "logout"

    if session_uses_rls_helpers(db):
        if now is not None:
            raise ValueError(
                "Database-backed application sessions use PostgreSQL time"
            )
        if not session_uses_auth_boundary(db):
            raise AppSessionConfigurationError(
                "Logout family revocation requires the auth database boundary"
            )
        result = await db.execute(
            text(
                """
                SELECT mata_rls.revoke_app_session_family_for_logout(
                    CAST(:token_digest AS bytea),
                    CAST(:csrf_token_digest AS bytea),
                    CAST(:reason AS text)
                )
                """
            ),
            {
                "token_digest": token_digest,
                "csrf_token_digest": csrf_token_digest,
                "reason": normalized_reason,
            },
        )
        return int(result.scalar_one())

    token_session = aliased(AppSession)
    csrf_session = aliased(AppSession)

    def accepted_same_row_proof(observed_at: datetime) -> Any:
        return and_(
            token_session.id == csrf_session.id,
            observed_at < token_session.absolute_expires_at,
            or_(
                and_(
                    token_session.revoked_at.is_(None),
                    observed_at < token_session.idle_expires_at,
                ),
                and_(
                    token_session.revoked_at.is_not(None),
                    token_session.revoked_reason == "rotated",
                ),
            ),
        )

    def accepted_rotated_ancestor_proof(observed_at: datetime) -> Any:
        return and_(
            token_session.id != csrf_session.id,
            token_session.revoked_at.is_(None),
            observed_at < token_session.idle_expires_at,
            observed_at < token_session.absolute_expires_at,
            csrf_session.revoked_at.is_not(None),
            csrf_session.revoked_reason == "rotated",
            observed_at < csrf_session.absolute_expires_at,
        )

    proof_binding = and_(
        csrf_session.subject_type == token_session.subject_type,
        csrf_session.subject_id == token_session.subject_id,
        csrf_session.subject_session_generation
        == token_session.subject_session_generation,
        csrf_session.session_family_id == token_session.session_family_id,
        csrf_session.auth_source == token_session.auth_source,
    )

    def proof_query(observed_at: datetime) -> Any:
        return (
            select(token_session, csrf_session)
            .select_from(token_session)
            .join(csrf_session, proof_binding)
            .where(
                token_session.token_digest == token_digest,
                csrf_session.csrf_token_digest == csrf_token_digest,
                or_(
                    accepted_same_row_proof(observed_at),
                    accepted_rotated_ancestor_proof(observed_at),
                ),
            )
        )

    current_time = _utc(now or datetime.now(UTC))
    candidate_result = await db.execute(
        proof_query(current_time).execution_options(populate_existing=True)
    )
    candidate_pair = candidate_result.one_or_none()
    if candidate_pair is None:
        return 0
    candidate_token, candidate_csrf = candidate_pair

    current_generation = await _lock_subject_for_family_revocation(
        db,
        subject_type=candidate_token.subject_type,
        subject_id=candidate_token.subject_id,
    )
    if (
        current_generation is None
        or current_generation != candidate_token.subject_session_generation
    ):
        return 0

    await _lock_session_family(db, candidate_token.session_family_id)
    current_time = _utc(now or datetime.now(UTC))
    locked_result = await db.execute(
        proof_query(current_time)
        .where(
            token_session.id == candidate_token.id,
            csrf_session.id == candidate_csrf.id,
            token_session.subject_session_generation == current_generation,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    locked_pair = locked_result.one_or_none()
    if locked_pair is None:
        return 0
    locked_token, locked_csrf = locked_pair

    current_time = _utc(now or datetime.now(UTC))
    same_row_proof_is_valid = (
        locked_token.id == locked_csrf.id
        and current_time < _utc(locked_token.absolute_expires_at)
        and (
            (
                locked_token.revoked_at is None
                and current_time < _utc(locked_token.idle_expires_at)
            )
            or (
                locked_token.revoked_at is not None
                and locked_token.revoked_reason == "rotated"
            )
        )
    )
    rotated_ancestor_proof_is_valid = (
        locked_token.id != locked_csrf.id
        and locked_token.revoked_at is None
        and current_time < _utc(locked_token.idle_expires_at)
        and current_time < _utc(locked_token.absolute_expires_at)
        and locked_csrf.revoked_at is not None
        and locked_csrf.revoked_reason == "rotated"
        and current_time < _utc(locked_csrf.absolute_expires_at)
    )
    if not (
        same_row_proof_is_valid
        or rotated_ancestor_proof_is_valid
    ):
        return 0

    result = await db.execute(
        update(AppSession)
        .where(
            AppSession.session_family_id == locked_token.session_family_id,
            AppSession.subject_type == locked_token.subject_type,
            AppSession.subject_id == locked_token.subject_id,
            AppSession.subject_session_generation
            == locked_token.subject_session_generation,
            AppSession.auth_source == locked_token.auth_source,
            AppSession.revoked_at.is_(None),
        )
        .values(
            revoked_at=current_time,
            revoked_reason=normalized_reason,
        )
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


async def revoke_subject_sessions(
    db: AsyncSession,
    subject_type: SessionSubjectType,
    subject_id: UUID,
    reason: str,
    *,
    block_session_issuance: bool = False,
    now: datetime | None = None,
) -> int:
    invalidation_statement = _SUBJECT_INVALIDATION_STATEMENTS.get(subject_type)
    if invalidation_statement is None:
        raise ValueError("Invalid application-session subject type")
    if block_session_issuance and subject_type != "staff":
        raise ValueError("Only staff session issuance can be blocked")
    if session_uses_rls_helpers(db):
        if now is not None:
            raise ValueError(
                "Database-backed application sessions use PostgreSQL time"
            )
        result = await db.execute(
            text(
                """
                SELECT mata_rls.invalidate_subject_app_sessions(
                    CAST(:subject_type AS text),
                    CAST(:subject_id AS uuid),
                    CAST(:reason AS text),
                    CAST(:block_session_issuance AS boolean)
                )
                """
            ),
            {
                "subject_type": subject_type,
                "subject_id": subject_id,
                "reason": reason.strip() or "subject_revoked",
                "block_session_issuance": block_session_issuance,
            },
        )
        value = result.scalar_one_or_none()
        if value is None:
            raise AppSessionInvalidError(
                "Application-session subject is unavailable"
            )
        return int(value)

    generation_result = await db.execute(
        invalidation_statement,
        {
            "subject_id": subject_id,
            "block_session_issuance": block_session_issuance,
        },
    )
    if generation_result.scalar_one_or_none() is None:
        raise AppSessionInvalidError("Application-session subject is unavailable")
    result = await db.execute(
        update(AppSession)
        .where(
            AppSession.subject_type == subject_type,
            AppSession.subject_id == subject_id,
            AppSession.revoked_at.is_(None),
        )
        .values(
            revoked_at=_utc(now or datetime.now(UTC)),
            revoked_reason=reason.strip() or "subject_revoked",
        )
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


async def cleanup_sessions(
    db: AsyncSession,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> int:
    """Delete at most one configured batch of long-expired session rows."""

    if session_uses_rls_helpers(db):
        if now is not None:
            raise ValueError(
                "Database-backed application sessions use PostgreSQL time"
            )
        return await _cleanup_sessions_with_helper(db, settings)

    current_time = _utc(now or datetime.now(UTC))
    retention_seconds = max(0, int(settings.session_cleanup_retention_seconds))
    batch_size = max(1, int(settings.session_cleanup_batch_size))
    cutoff = current_time - timedelta(seconds=retention_seconds)
    result = await db.execute(
        text(
            """
            WITH cleanup_candidates AS (
                SELECT id
                FROM app_sessions
                WHERE (
                        (
                            revoked_at IS NOT NULL
                            AND revoked_at <= :cutoff
                        )
                        OR idle_expires_at <= :cutoff
                        OR absolute_expires_at <= :cutoff
                      )
                  AND (
                        revoked_at IS NULL
                        OR revoked_reason IS DISTINCT FROM 'rotated'
                        OR absolute_expires_at <= :current_time
                      )
                ORDER BY LEAST(
                    COALESCE(revoked_at, absolute_expires_at),
                    idle_expires_at,
                    absolute_expires_at
                ), id
                LIMIT :batch_size
                FOR UPDATE SKIP LOCKED
            )
            DELETE FROM app_sessions AS sessions
            USING cleanup_candidates AS candidates
            WHERE sessions.id = candidates.id
            """
        ),
        {
            "cutoff": cutoff,
            "current_time": current_time,
            "batch_size": batch_size,
        },
    )
    return int(result.rowcount or 0)


# Backwards-readable alias for callers that describe this as cleanup rather than
# storage maintenance.  Both names remain bounded and leave transaction control
# with the caller.
cleanup = cleanup_sessions
