from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.reporting_period_status import resolve_active_reporting_period_for_date


# The resident alias is deliberately fixed to ``r``. Keeping this fragment shared
# prevents admin/read surfaces from drifting from the display-only /auth/me
# current-posting contract.
NATIVE_CURRENT_POSTING_JOIN_SQL = """
LEFT JOIN LATERAL (
    SELECT rp.posting_code
    FROM resident_postings rp
    WHERE rp.resident_id = r.id
      AND rp.status IN ('active', 'loa_working')
      AND rp.reporting_period_id = :reporting_period_id
    ORDER BY
      CASE
        WHEN rp.start_date <= CURRENT_DATE
         AND (rp.end_date IS NULL OR rp.end_date >= CURRENT_DATE)
          THEN 0
        WHEN rp.start_date > CURRENT_DATE
          THEN 1
        ELSE 2
      END,
      CASE
        WHEN rp.start_date > CURRENT_DATE
          THEN rp.start_date - CURRENT_DATE
        ELSE CURRENT_DATE - COALESCE(rp.end_date, rp.start_date)
      END,
      rp.start_date DESC,
      rp.posting_code
    LIMIT 1
) current_posting ON true
LEFT JOIN posting_codes pc
  ON pc.code = current_posting.posting_code
"""


async def current_reporting_period_params(db: AsyncSession) -> dict[str, Any]:
    """Return the one period that may supply a display-only current posting."""

    period = await resolve_active_reporting_period_for_date(
        db,
        relevant_date=date.today(),
    )
    if period is None:
        # Keep bound date types concrete while making the external-period overlap
        # predicate impossible. Native posting rows are constrained by the null id.
        return {
            "has_reporting_period": False,
            "reporting_period_id": None,
            "reporting_period_start": date.max,
            "reporting_period_end": date.min,
        }
    return {
        "has_reporting_period": True,
        "reporting_period_id": str(period["id"]),
        "reporting_period_start": period["start_date"],
        "reporting_period_end": period["end_date"],
    }
