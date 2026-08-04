from __future__ import annotations

from datetime import date, datetime, time

from app.services.event_intervals import (
    event_interval,
    intervals_overlap,
    overlap_candidate_dates,
    spanned_dates,
)


def test_midnight_end_is_on_the_next_calendar_date() -> None:
    starts_at, ends_at = event_interval(
        event_date=date(2026, 5, 18),
        start_time=time(23, 0),
        end_time=time(0, 0),
    )

    assert starts_at == datetime(2026, 5, 18, 23, 0)
    assert ends_at == datetime(2026, 5, 19, 0, 0)
    assert spanned_dates(
        event_date=date(2026, 5, 18),
        start_time=time(23, 0),
        end_time=time(0, 0),
    ) == {date(2026, 5, 18), date(2026, 5, 19)}


def test_previous_date_wrapped_event_overlaps_next_date_event() -> None:
    assert intervals_overlap(
        left_date=date(2026, 5, 18),
        left_start=time(23, 30),
        left_end=time(0, 30),
        right_date=date(2026, 5, 19),
        right_start=time(0, 0),
        right_end=time(1, 0),
    )


def test_midnight_touching_boundary_does_not_overlap() -> None:
    assert not intervals_overlap(
        left_date=date(2026, 5, 18),
        left_start=time(23, 0),
        left_end=time(0, 0),
        right_date=date(2026, 5, 19),
        right_start=time(0, 0),
        right_end=time(1, 0),
    )


def test_overlap_search_includes_previous_start_and_end_dates() -> None:
    assert overlap_candidate_dates(
        event_date=date(2026, 5, 19),
        start_time=time(0, 0),
        end_time=time(1, 0),
    ) == {date(2026, 5, 18), date(2026, 5, 19)}
