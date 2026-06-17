from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any


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
