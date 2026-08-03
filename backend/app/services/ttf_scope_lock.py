from __future__ import annotations

from hashlib import blake2b
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def advisory_lock_keys(
    reporting_period_id: UUID,
    programme_code: str,
) -> tuple[int, int]:
    """Return the deterministic advisory-lock pair for a TTF programme scope."""
    scope_key = f"{reporting_period_id}:{programme_code}".encode("utf-8")
    digest = blake2b(scope_key, digest_size=8).digest()
    signed = int.from_bytes(digest, byteorder="big", signed=True)
    key1 = signed >> 32
    key2 = signed & 0xFFFFFFFF
    if key2 >= 2**31:
        key2 -= 2**32
    return key1, key2


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
