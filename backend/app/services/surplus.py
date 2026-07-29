from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database_context import session_uses_rls


async def hibernate_stale_surplus(
    session: AsyncSession,
    reporting_period_id: UUID | str,
) -> None:
    if session_uses_rls(session):
        result = await session.execute(
            text(
                """
                SELECT mata_rls.hibernate_stale_surplus(
                    CAST(:period_id AS uuid)
                ) AS affected_count
                """
            ),
            {"period_id": str(reporting_period_id)},
        )
        row = result.mappings().one()
        if set(row.keys()) != {"affected_count"}:
            raise RuntimeError("Invalid surplus-hibernation helper result")
        affected_count = row["affected_count"]
        if (
            not isinstance(affected_count, int)
            or isinstance(affected_count, bool)
            or affected_count < 0
        ):
            raise RuntimeError("Invalid surplus-hibernation helper result")
        return

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
