"""Shared date subgroup labels and sort keys for TUI grouping models."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import re

NO_TIMESTAMP_LABEL = "(no timestamp)"


def one_hour_window_label(anchor: datetime) -> str:
    """Return the zero-padded hour label containing *anchor*."""
    return f"{anchor.hour:02d}:00"


def one_hour_window_sort_key(label: str) -> tuple[int, int]:
    """Sort real one-hour labels newest-first, with unknown labels last."""
    if re.fullmatch(r"\d{2}:00", label):
        hour = int(label[:2])
        if 0 <= hour <= 23:
            return (0, -hour)
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
