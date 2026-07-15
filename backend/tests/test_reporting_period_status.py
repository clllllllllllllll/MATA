from __future__ import annotations

from datetime import date

import pytest

from app.errors import ApiError
from app.services.reporting_period_status import (
    get_effective_reporting_period_status,
    resolve_reporting_period_for_date,
)


def test_effective_status_uses_stored_status_when_no_transition_is_due() -> None:
    assert (
        get_effective_reporting_period_status(
            {"status": "active", "activate_on": None, "deactivate_on": None},
            as_of_date=date(2026, 6, 17),
        )
        == "active"
    )
    assert (
        get_effective_reporting_period_status(
            {"status": "inactive", "activate_on": None, "deactivate_on": None},
            as_of_date=date(2026, 6, 17),
        )
        == "inactive"
    )


def test_due_activate_on_makes_period_effectively_active() -> None:
    assert (
        get_effective_reporting_period_status(
            {
                "status": "inactive",
                "activate_on": date(2026, 6, 1),
                "deactivate_on": None,
            },
            as_of_date=date(2026, 6, 17),
        )
        == "active"
    )


def test_due_deactivate_on_makes_period_effectively_inactive() -> None:
    assert (
        get_effective_reporting_period_status(
            {
                "status": "active",
                "activate_on": None,
                "deactivate_on": date(2026, 6, 1),
            },
            as_of_date=date(2026, 6, 17),
        )
        == "inactive"
    )


def test_latest_due_transition_wins_when_both_are_due() -> None:
    assert (
        get_effective_reporting_period_status(
            {
                "status": "inactive",
                "activate_on": date(2026, 6, 1),
                "deactivate_on": date(2026, 6, 10),
            },
            as_of_date=date(2026, 6, 17),
        )
        == "inactive"
    )


def test_same_day_deactivation_wins_when_both_transitions_are_due() -> None:
    assert (
        get_effective_reporting_period_status(
            {
                "status": "active",
                "activate_on": date(2026, 6, 17),
                "deactivate_on": date(2026, 6, 17),
            },
            as_of_date=date(2026, 6, 17),
        )
        == "inactive"
    )


def _period(
    period_id: str,
    start_date: date,
    end_date: date,
    *,
    status: str = "active",
    activate_on: date | None = None,
    deactivate_on: date | None = None,
) -> dict[str, object]:
    return {
        "id": period_id,
        "label": period_id,
        "start_date": start_date,
        "end_date": end_date,
        "status": status,
        "activate_on": activate_on,
        "deactivate_on": deactivate_on,
    }


def test_current_date_ignores_reopened_past_and_future_active_periods() -> None:
    periods = [
        _period("reopened-past", date(2025, 7, 1), date(2025, 12, 31)),
        _period("current", date(2026, 7, 1), date(2026, 12, 31)),
        _period("uat-2099", date(2099, 1, 1), date(2099, 6, 30)),
    ]

    result = resolve_reporting_period_for_date(
        periods,
        relevant_date=date(2026, 7, 15),
        status_as_of_date=date(2026, 7, 15),
    )

    assert result is not None
    assert result["id"] == "current"


def test_event_date_resolves_to_reopened_past_period() -> None:
    periods = [
        _period("reopened-past", date(2025, 7, 1), date(2025, 12, 31)),
        _period("current", date(2026, 7, 1), date(2026, 12, 31)),
    ]

    result = resolve_reporting_period_for_date(
        periods,
        relevant_date=date(2025, 10, 1),
        status_as_of_date=date(2026, 7, 15),
    )

    assert result is not None
    assert result["id"] == "reopened-past"


def test_overlapping_effectively_active_periods_fail_closed() -> None:
    periods = [
        _period("one", date(2026, 7, 1), date(2026, 12, 31)),
        _period("two", date(2026, 7, 15), date(2026, 12, 31)),
    ]

    with pytest.raises(ApiError) as exc_info:
        resolve_reporting_period_for_date(
            periods,
            relevant_date=date(2026, 7, 15),
            status_as_of_date=date(2026, 7, 15),
        )

    assert exc_info.value.status_code == 409
