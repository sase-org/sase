"""Preset and custom time ranges for historical statistics.

Range boundaries are integer Unix timestamps with an inclusive start and an
exclusive end, matching the Rust statistics API. Calendar inputs use the
configured SASE timezone; relative inputs represent exact elapsed time.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from typing import Literal, NamedTuple

from sase.core.time import get_timezone

PresetKey = Literal["today", "24h", "7d", "30d", "90d", "all"]


@dataclass(frozen=True, slots=True)
class RangePreset:
    """One user-selectable Statistics range preset."""

    key: PresetKey
    label: str


class StatsRange(NamedTuple):
    """Resolved inclusive/exclusive timestamps plus an absolute label."""

    start_ts: int
    end_ts: int
    label: str


PRESETS: tuple[RangePreset, ...] = (
    RangePreset("today", "Today"),
    RangePreset("24h", "24h"),
    RangePreset("7d", "7d"),
    RangePreset("30d", "30d"),
    RangePreset("90d", "90d"),
    RangePreset("all", "All"),
)
PRESET_ORDER: tuple[PresetKey, ...] = tuple(preset.key for preset in PRESETS)
DEFAULT_PRESET: PresetKey = "7d"

_RELATIVE_RE = re.compile(r"(?P<count>[1-9]\d*)(?P<unit>[hdw])")
_MONTH_RE = re.compile(r"\d{4}-\d{2}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ALL_TIME_START_TS = 0


def resolve_preset(
    key: PresetKey,
    *,
    now: datetime | None = None,
) -> StatsRange:
    """Resolve a preset against *now* in the configured timezone."""
    current = _configured_now(now)
    end_ts = _exclusive_now_ts(current)
    if key == "today":
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ts = int(start.timestamp())
    elif key == "all":
        start_ts = _ALL_TIME_START_TS
    else:
        seconds = {"24h": 86_400, "7d": 604_800, "30d": 2_592_000, "90d": 7_776_000}[
            key
        ]
        start_ts = end_ts - seconds
    return StatsRange(
        start_ts, end_ts, _absolute_label(start_ts, end_ts, current.tzinfo)
    )


def parse_custom_range(
    value: str,
    *,
    now: datetime | None = None,
) -> StatsRange:
    """Parse a custom Statistics range.

    Accepted forms are ``Nh``, ``Nd``, ``Nw``, ``YYYY-MM``,
    ``YYYY-MM-DD..YYYY-MM-DD``, and ``YYYY-MM-DD..``. Closed calendar
    ranges include the entire final date. Ranges are capped at the supplied
    current time because Statistics only describes historical activity.
    """
    text = value.strip()
    if not text:
        raise ValueError("Custom range cannot be empty")

    current = _configured_now(now)
    end_now_ts = _exclusive_now_ts(current)
    relative = _RELATIVE_RE.fullmatch(text)
    if relative is not None:
        count = int(relative.group("count"))
        unit_seconds = {"h": 3_600, "d": 86_400, "w": 604_800}[relative.group("unit")]
        start_ts = end_now_ts - count * unit_seconds
        return StatsRange(
            start_ts,
            end_now_ts,
            _absolute_label(start_ts, end_now_ts, current.tzinfo),
        )

    if _MONTH_RE.fullmatch(text):
        start = _parse_calendar(text, "%Y-%m", current.tzinfo)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return _calendar_range(start, end, current, closed_end=True)

    if text.count("..") == 1:
        start_text, end_text = text.split("..")
        if not _DATE_RE.fullmatch(start_text) or (
            end_text and not _DATE_RE.fullmatch(end_text)
        ):
            raise ValueError(f"Invalid custom range: {value!r}")
        start = _parse_calendar(start_text, "%Y-%m-%d", current.tzinfo)
        if end_text:
            final_day = _parse_calendar(end_text, "%Y-%m-%d", current.tzinfo)
            end = final_day + timedelta(days=1)
            return _calendar_range(start, end, current, closed_end=True)
        return _calendar_range(start, current, current, closed_end=False)

    raise ValueError(f"Invalid custom range: {value!r}")


def bucket_seconds_for(start_ts: int, end_ts: int) -> int:
    """Return the product-specified hour/day bucket size for a range."""
    return 3_600 if end_ts - start_ts <= 48 * 3_600 else 24 * 3_600


def _calendar_range(
    start: datetime,
    requested_end: datetime,
    current: datetime,
    *,
    closed_end: bool,
) -> StatsRange:
    current_end_ts = _exclusive_now_ts(current)
    start_ts = int(start.timestamp())
    if start_ts >= current_end_ts:
        raise ValueError("Custom range starts in the future")

    requested_end_ts = math.ceil(requested_end.timestamp())
    end_ts = min(requested_end_ts, current_end_ts)
    if end_ts <= start_ts:
        raise ValueError("Custom range end must be after its start")

    display_end_ts = end_ts
    if closed_end and requested_end_ts <= current_end_ts:
        display_end_ts = end_ts - 1
    return StatsRange(
        start_ts,
        end_ts,
        _absolute_label(start_ts, display_end_ts, current.tzinfo),
    )


def _configured_now(now: datetime | None) -> datetime:
    timezone = get_timezone()
    if now is None:
        return datetime.now(timezone)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone)
    return now.astimezone(timezone)


def _parse_calendar(value: str, fmt: str, timezone: tzinfo | None) -> datetime:
    try:
        return datetime.strptime(value, fmt).replace(tzinfo=timezone)
    except ValueError as exc:
        raise ValueError(f"Invalid custom range date: {value!r}") from exc


def _exclusive_now_ts(now: datetime) -> int:
    return math.ceil(now.timestamp())


def _absolute_label(start_ts: int, end_ts: int, timezone: tzinfo | None) -> str:
    start = datetime.fromtimestamp(start_ts, timezone)
    end = datetime.fromtimestamp(end_ts, timezone)
    return f"{start:%Y-%m-%d %H:%M %Z} – {end:%Y-%m-%d %H:%M %Z}"


__all__ = [
    "DEFAULT_PRESET",
    "PRESETS",
    "PRESET_ORDER",
    "PresetKey",
    "RangePreset",
    "StatsRange",
    "bucket_seconds_for",
    "parse_custom_range",
    "resolve_preset",
]
