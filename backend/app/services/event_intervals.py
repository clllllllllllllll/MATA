from __future__ import annotations

from datetime import date, datetime, time, timedelta


def event_interval(
    *,
    event_date: date,
    start_time: time,
    end_time: time | None,
) -> tuple[datetime, datetime]:
    """Return the persisted event interval, preserving overnight events."""

    starts_at = datetime.combine(event_date, start_time)
    if end_time is None:
        return starts_at, starts_at
    ends_at = datetime.combine(event_date, end_time)
    if end_time <= start_time:
        ends_at += timedelta(days=1)
    return starts_at, ends_at


def intervals_overlap(
    *,
    left_date: date,
    left_start: time,
    left_end: time | None,
    right_date: date,
    right_start: time,
    right_end: time | None,
) -> bool:
    left_starts_at, left_ends_at = event_interval(
        event_date=left_date,
        start_time=left_start,
        end_time=left_end,
    )
    right_starts_at, right_ends_at = event_interval(
        event_date=right_date,
        start_time=right_start,
        end_time=right_end,
    )
    return left_starts_at < right_ends_at and right_starts_at < left_ends_at


def spanned_dates(
    *,
    event_date: date,
    start_time: time,
    end_time: time | None,
) -> set[date]:
    starts_at, ends_at = event_interval(
        event_date=event_date,
        start_time=start_time,
        end_time=end_time,
    )
    dates: set[date] = set()
    current = starts_at.date()
    while current <= ends_at.date():
        dates.add(current)
        current += timedelta(days=1)
    return dates


def overlap_candidate_dates(
    *,
    event_date: date,
    start_time: time,
    end_time: time | None,
) -> set[date]:
    """Dates on which a less-than-24-hour persisted event can start and overlap."""

    _, ends_at = event_interval(
        event_date=event_date,
        start_time=start_time,
        end_time=end_time,
    )
    return {event_date - timedelta(days=1), event_date, ends_at.date()}
