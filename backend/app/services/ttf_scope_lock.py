from __future__ import annotations

from hashlib import blake2b
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _lock_keys(lock_key: str) -> tuple[int, int]:
    digest = blake2b(lock_key.encode("utf-8"), digest_size=8).digest()
    signed = int.from_bytes(digest, byteorder="big", signed=True)
    key1 = signed >> 32
    key2 = signed & 0xFFFFFFFF
    if key2 >= 2**31:
        key2 -= 2**32
    return key1, key2


def advisory_lock_keys(
    reporting_period_id: UUID,
    programme_code: str,
) -> tuple[int, int]:
    """Return the deterministic advisory-lock pair for a TTF programme scope."""
    return _lock_keys(f"{reporting_period_id}:{programme_code}")


def programme_advisory_lock_keys(programme_code: str) -> tuple[int, int]:
    """Return a deterministic transaction-lock pair for programme posting groups."""
    return _lock_keys(f"ttf-posting-groups:{programme_code}")


async def acquire_ttf_programme_lock(
    db_session: AsyncSession,
    *,
    programme_code: str,
) -> bool:
    """Try to serialize posting-group writers for one programme only."""
    key1, key2 = programme_advisory_lock_keys(programme_code)
    result = await db_session.execute(
        text("SELECT pg_try_advisory_xact_lock(:key1, :key2) AS acquired"),
        {"key1": key1, "key2": key2},
    )
    return bool(result.scalar())


async def acquire_ttf_scope_lock(
    db_session: AsyncSession,
    *,
    reporting_period_id: UUID,
    programme_code: str,
) -> bool:
    """Try to serialize TTF targets and Teaching Name changes for one scope."""
    key1, key2 = advisory_lock_keys(reporting_period_id, programme_code)
    result = await db_session.execute(
        text("SELECT pg_try_advisory_xact_lock(:key1, :key2) AS acquired"),
        {"key1": key1, "key2": key2},
    )
    return bool(result.scalar())
