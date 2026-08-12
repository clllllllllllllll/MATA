"""Durable LOA classification for native attendance evidence."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def reclassify_attendance_loa(
    db: AsyncSession,
    *,
    reporting_period_id: UUID | str,
    resident_id: UUID | str | None = None,
) -> dict[str, int]:
    """Synchronize event-date LOA classification after posting changes.

    The protected database helper owns the write because ordinary attendance
    updates are intentionally restricted to the resident submission flow.
    """

    result = await db.execute(
        text(
            """
            SELECT affected_count, during_loa_count, non_loa_count
            FROM mata_rls.reclassify_native_attendance_loa(
                :reporting_period_id,
                :resident_id
            )
            """
        ),
        {
            "reporting_period_id": str(reporting_period_id),
            "resident_id": str(resident_id) if resident_id is not None else None,
        },
    )
    row = result.mappings().one()
    return {
        "affected_count": int(row.get("affected_count") or 0),
        "during_loa_count": int(row.get("during_loa_count") or 0),
        "non_loa_count": int(row.get("non_loa_count") or 0),
    }
