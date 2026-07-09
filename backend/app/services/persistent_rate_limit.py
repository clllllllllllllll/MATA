from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings


LOCAL_DEV_HASH_SECRET = "mata-local-dev-rate-limit-hash-secret"


class PersistentRateLimitConfigurationError(RuntimeError):
    """Raised when the limiter cannot safely hash bucket keys."""


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    scope: str
    limit: int
    window_seconds: int
    message: str


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    request_count: int
    limit: int
    retry_after_seconds: int


def _hash_secret(settings: Settings) -> str:
    if settings.rate_limit_hash_secret:
        return settings.rate_limit_hash_secret
    if settings.environment in {"development", "test"}:
        return LOCAL_DEV_HASH_SECRET
    raise PersistentRateLimitConfigurationError("RATE_LIMIT_HASH_SECRET is required")


def normalise_identifier(identifier: str) -> str:
    return identifier.strip().lower() or "unknown"


def hash_rate_limit_key(
    *,
    settings: Settings,
    scope: str,
    identifier: str,
) -> str:
    secret = _hash_secret(settings)
    message = f"{scope}:{normalise_identifier(identifier)}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, sha256).hexdigest()


def fixed_window_start(now: datetime, window_seconds: int) -> datetime:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    epoch_seconds = int(now.timestamp())
    window_epoch = epoch_seconds - (epoch_seconds % window_seconds)
    return datetime.fromtimestamp(window_epoch, tz=UTC)


def _retry_after_seconds(*, now: datetime, expires_at: datetime) -> int:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    remaining = int((expires_at - now).total_seconds())
    return max(1, remaining)


def _cleanup_due(key_hash: str) -> bool:
    return int(key_hash[-2:], 16) == 0


async def cleanup_expired_buckets(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> None:
    current_time = now or datetime.now(UTC)
    cutoff = current_time - timedelta(days=1)
    await db.execute(
        text(
            """
            DELETE FROM rate_limit_buckets
            WHERE expires_at < :cutoff
            """
        ),
        {"cutoff": cutoff},
    )


async def check_rate_limit(
    db: AsyncSession,
    *,
    settings: Settings,
    policy: RateLimitPolicy,
    identifier: str,
    now: datetime | None = None,
) -> RateLimitResult:
    current_time = now or datetime.now(UTC)
    window_start = fixed_window_start(current_time, policy.window_seconds)
    expires_at = window_start + timedelta(seconds=policy.window_seconds)
    key_hash = hash_rate_limit_key(
        settings=settings,
        scope=policy.scope,
        identifier=identifier,
    )

    result = await db.execute(
        text(
            """
            INSERT INTO rate_limit_buckets (
                scope,
                key_hash,
                window_start,
                window_seconds,
                request_count,
                expires_at
            )
            VALUES (
                :scope,
                :key_hash,
                :window_start,
                :window_seconds,
                1,
                :expires_at
            )
            ON CONFLICT (scope, key_hash, window_start, window_seconds)
            DO UPDATE
            SET request_count = rate_limit_buckets.request_count + 1,
                expires_at = EXCLUDED.expires_at,
                updated_at = now()
            RETURNING request_count
            """
        ),
        {
            "scope": policy.scope,
            "key_hash": key_hash,
            "window_start": window_start,
            "window_seconds": policy.window_seconds,
            "expires_at": expires_at,
        },
    )
    row = result.mappings().one()
    request_count = int(row["request_count"])

    if _cleanup_due(key_hash):
        await cleanup_expired_buckets(db, now=current_time)
    await db.commit()

    return RateLimitResult(
        allowed=request_count <= policy.limit,
        request_count=request_count,
        limit=policy.limit,
        retry_after_seconds=_retry_after_seconds(
            now=current_time,
            expires_at=expires_at,
        ),
    )
