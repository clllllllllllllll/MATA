from __future__ import annotations

from datetime import date

from app.services.reporting_period_status import get_effective_reporting_period_status


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
