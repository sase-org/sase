"""Shared date subgroup labels and sort keys for TUI grouping models."""

from __future__ import annotations

from datetime import date, datetime, timedelta

NO_TIMESTAMP_LABEL = "(no timestamp)"

_TIME_WINDOW_START_BY_LABEL: dict[str, int] = {
    "12AM-4AM": 0,
    "4AM-8AM": 4,
    "8AM-12PM": 8,
    "12PM-4PM": 12,
    "4PM-8PM": 16,
    "8PM-12AM": 20,
}


def _hour_label(hour: int) -> str:
    hour %= 24
    if hour == 0:
        return "12AM"
    if hour < 12:
        return f"{hour}AM"
    if hour == 12:
        return "12PM"
    return f"{hour - 12}PM"


def four_hour_window_label(anchor: datetime) -> str:
    """Return the compact 4-hour window label containing *anchor*."""
    start_hour = (anchor.hour // 4) * 4
    return f"{_hour_label(start_hour)}-{_hour_label(start_hour + 4)}"


def four_hour_window_sort_key(label: str) -> tuple[int, int]:
    """Sort real 4-hour labels newest-first, with unknown labels last."""
    start = _TIME_WINDOW_START_BY_LABEL.get(label)
    if start is not None:
        return (0, -start)
    return (1, 0)


def day_subgroup_label(anchor: datetime) -> str:
    """Return a compact calendar-day label such as ``Fri Apr 24``."""
    return f"{anchor:%a} {anchor:%b} {anchor.day}"


def day_subgroup_sort_key(anchor: datetime) -> tuple[int, int]:
    """Sort calendar days newest-first."""
    return (0, -anchor.date().toordinal())


def _monday_start_week_start(anchor: date) -> date:
    """Return the Monday that starts *anchor*'s calendar week."""
    return anchor - timedelta(days=anchor.weekday())


def week_subgroup_label(anchor: datetime) -> str:
    """Return a compact Monday-start week range label."""
    start = _monday_start_week_start(anchor.date())
    end = start + timedelta(days=6)
    if start.month == end.month and start.year == end.year:
        return f"{start:%b} {start.day}-{end.day}"
    return f"{start:%b} {start.day}-{end:%b} {end.day}"


def week_subgroup_sort_key(anchor: datetime) -> tuple[int, int]:
    """Sort Monday-start calendar weeks newest-first."""
    return (0, -_monday_start_week_start(anchor.date()).toordinal())
