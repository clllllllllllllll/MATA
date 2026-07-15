from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, ErrorCode


REPORTING_PERIOD_ACTIVE = "active"
REPORTING_PERIOD_INACTIVE = "inactive"
REPORTING_PERIOD_STATUSES = {REPORTING_PERIOD_ACTIVE, REPORTING_PERIOD_INACTIVE}


def _period_value(period: Mapping[str, Any] | Any, key: str) -> Any:
    if isinstance(period, Mapping):
        return period.get(key)
    return getattr(period, key, None)


def _coerce_date(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    return None


def normalise_reporting_period_status(value: str) -> str:
    status = value.strip().lower()
    if status not in REPORTING_PERIOD_STATUSES:
        raise ValueError("status must be one of: active, inactive")
    return status


def get_effective_reporting_period_status(
    period: Mapping[str, Any] | Any,
    *,
    as_of_date: date | None = None,
) -> str:
    today = as_of_date or date.today()
    status = normalise_reporting_period_status(str(_period_value(period, "status")))
    activate_on = _coerce_date(_period_value(period, "activate_on"))
    deactivate_on = _coerce_date(_period_value(period, "deactivate_on"))

    due_transitions: list[tuple[date, int, str]] = []
    if activate_on is not None and today >= activate_on:
        due_transitions.append((activate_on, 0, REPORTING_PERIOD_ACTIVE))
    if deactivate_on is not None and today >= deactivate_on:
        due_transitions.append((deactivate_on, 1, REPORTING_PERIOD_INACTIVE))

    if not due_transitions:
        return status
    return max(due_transitions)[2]


def is_reporting_period_effectively_active(
    period: Mapping[str, Any] | Any,
    *,
    as_of_date: date | None = None,
) -> bool:
    return (
        get_effective_reporting_period_status(period, as_of_date=as_of_date)
        == REPORTING_PERIOD_ACTIVE
    )


REPORTING_PERIOD_SELECT = """
    SELECT
        id,
        label,
        start_date,
        end_date,
        status,
        activate_on,
        deactivate_on
    FROM reporting_periods
"""


def _period_contains_date(period: Mapping[str, Any], relevant_date: date) -> bool:
    return period["start_date"] <= relevant_date <= period["end_date"]


def resolve_reporting_period_for_date(
    periods: list[Mapping[str, Any]],
    *,
    relevant_date: date,
    status_as_of_date: date | None = None,
) -> dict[str, Any] | None:
    """Resolve one administratively open period applicable to ``relevant_date``.

    Multiple non-overlapping active periods are valid. Overlap at the relevant date is
    a configuration conflict and must never be resolved by row order.
    """

    matches = [
        dict(period)
        for period in periods
        if _period_contains_date(period, relevant_date)
        and is_reporting_period_effectively_active(
            period,
            as_of_date=status_as_of_date,
        )
    ]
    if len(matches) > 1:
        raise ApiError(
            status_code=409,
            detail="Reporting period configuration is ambiguous for the selected date",
            error_code=ErrorCode.CONFLICT.value,
        )
    return matches[0] if matches else None


async def list_reporting_periods_for_resolution(
    db: AsyncSession,
) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            f"""
            /* reporting_period_resolution:list */
            {REPORTING_PERIOD_SELECT}
            ORDER BY start_date ASC, id ASC
            """
        )
    )
    return [dict(row) for row in result.mappings().all()]


async def resolve_active_reporting_period_for_date(
    db: AsyncSession,
    *,
    relevant_date: date,
    status_as_of_date: date | None = None,
) -> dict[str, Any] | None:
    periods = await list_reporting_periods_for_resolution(db)
    return resolve_reporting_period_for_date(
        periods,
        relevant_date=relevant_date,
        status_as_of_date=status_as_of_date,
    )


async def resolve_explicit_reporting_period(
    db: AsyncSession,
    *,
    reporting_period_id: UUID | str,
    require_effectively_active: bool = False,
    status_as_of_date: date | None = None,
    relevant_date: date | None = None,
) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            f"""
            /* reporting_period_resolution:explicit */
            {REPORTING_PERIOD_SELECT}
            WHERE id = :reporting_period_id
            """
        ),
        {"reporting_period_id": str(reporting_period_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        return None
    period = dict(row)
    if require_effectively_active and not is_reporting_period_effectively_active(
        period,
        as_of_date=status_as_of_date,
    ):
        return None
    if relevant_date is not None and not _period_contains_date(period, relevant_date):
        raise ApiError(
            status_code=422,
            detail="The selected reporting period does not contain the relevant date",
            error_code=ErrorCode.VALIDATION_FAILED.value,
        )
    return period
