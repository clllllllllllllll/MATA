from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def hibernate_stale_surplus(
    session: AsyncSession,
    reporting_period_id: UUID | str,
) -> None:
    await session.execute(
        text(
            """
            UPDATE surplus_ledger sl
            SET    is_hibernating = true
            WHERE  sl.reporting_period_id = :period_id
            AND    sl.is_hibernating = false
            AND    NOT EXISTS (
                SELECT 1
                FROM   resident_postings rp
                WHERE  rp.resident_id = sl.resident_id
                AND    rp.posting_code = sl.posting_code
                AND    rp.reporting_period_id = :period_id
                AND    rp.status IN ('active', 'loa_working')
            )
            """
        ),
        {"period_id": str(reporting_period_id)},
    )
