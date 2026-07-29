from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def acquire_teaching_event_locks(
    db: AsyncSession,
    *,
    event_ids: Sequence[UUID | str],
) -> None:
    """Serialize attendance and staff mutations for the same events."""

    for event_id in sorted({str(value) for value in event_ids}):
        await db.execute(
            text(
                """
                /* teaching_event_mutation_lock */
                SELECT pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended(:lock_scope, 0)
                )
                """
            ),
            {"lock_scope": f"teaching-event:{event_id}"},
        )
