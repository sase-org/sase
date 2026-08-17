"""Preset and custom time ranges for historical statistics.

Range boundaries are integer Unix timestamps with an inclusive start and an
exclusive end, matching the Rust statistics API. Calendar inputs use the
configured SASE timezone; relative inputs represent exact elapsed time.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Literal, NamedTuple

from sase.core.time import get_timezone

PresetKey = Literal["today", "24h", "7d", "30d", "90d", "all"]


@dataclass(frozen=True, slots=True)
class RangePreset:
    """One user-selectable Statistics range preset."""

    key: PresetKey
    label: str


class StatsRange(NamedTuple):
    """Resolved inclusive/exclusive timestamps plus concise and absolute labels."""

    start_ts: int
    end_ts: int
    label: str
    display_label: str


PRESETS: tuple[RangePreset, ...] = (
    RangePreset("today", "Today"),
    RangePreset("24h", "Last 24 hours"),
    RangePreset("7d", "Last 7 days"),
    RangePreset("30d", "Last 30 days"),
    RangePreset("90d", "Last 90 days"),
    RangePreset("all", "All time"),
)
PRESET_ORDER: tuple[PresetKey, ...] = tuple(preset.key for preset in PRESETS)
_PRESET_LABELS: dict[PresetKey, str] = {preset.key: preset.label for preset in PRESETS}
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
        label = _absolute_label(start_ts, end_ts, current.tzinfo)
    elif key == "all":
        start_ts = _ALL_TIME_START_TS
        label = _all_time_label(end_ts, current.tzinfo)
    else:
        seconds = {"24h": 86_400, "7d": 604_800, "30d": 2_592_000, "90d": 7_776_000}[
            key
        ]
        start_ts = end_ts - seconds
        label = _absolute_label(start_ts, end_ts, current.tzinfo)
    return StatsRange(
        start_ts,
        end_ts,
        label,
        _PRESET_LABELS[key],
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
            _relative_display_label(
                count,
                relative.group("unit"),
            ),
        )

    if _MONTH_RE.fullmatch(text):
        start = _parse_calendar(text, "%Y-%m", current.tzinfo)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return _calendar_range(
            start,
            end,
            current,
            range_kind="month",
            closed_end=True,
        )

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
            return _calendar_range(
                start,
                end,
                current,
                range_kind="closed",
                closed_end=True,
            )
        return _calendar_range(
            start,
            current,
            current,
            range_kind="open",
            closed_end=False,
        )

    raise ValueError(f"Invalid custom range: {value!r}")


def bucket_seconds_for(start_ts: int, end_ts: int) -> int:
    """Return the product-specified hour/day bucket size for a range."""
    return 3_600 if end_ts - start_ts <= 48 * 3_600 else 24 * 3_600


def _calendar_range(
    start: datetime,
    requested_end: datetime,
    current: datetime,
    *,
    range_kind: Literal["month", "closed", "open"],
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
        _calendar_display_label(
            start,
            end_ts,
            current.tzinfo,
            range_kind=range_kind,
            capped=requested_end_ts > current_end_ts,
        ),
    )


def _relative_display_label(count: int, unit: str) -> str:
    unit_name = {"h": "hour", "d": "day", "w": "week"}[unit]
    suffix = "" if count == 1 else "s"
    return f"Last {count} {unit_name}{suffix}"


def _calendar_display_label(
    start: datetime,
    end_ts: int,
    timezone: tzinfo | None,
    *,
    range_kind: Literal["month", "closed", "open"],
    capped: bool,
) -> str:
    if range_kind == "open":
        return f"Since {_format_date(start)}"
    if range_kind == "month":
        suffix = " to date" if capped else ""
        return f"{start:%B %Y}{suffix}"

    end = datetime.fromtimestamp(end_ts, timezone)
    final_day = end.date()
    if end == end.replace(hour=0, minute=0, second=0, microsecond=0):
        final_day -= timedelta(days=1)
    suffix = " to date" if capped else ""
    return f"{_format_date_span(start.date(), final_day)}{suffix}"


def _format_date(value: datetime) -> str:
    return f"{value:%b} {value.day}, {value.year}"


def _format_date_span(start: date, end: date) -> str:
    start_month = start.strftime("%b")
    end_month = end.strftime("%b")
    if start == end:
        return f"{start_month} {start.day}, {start.year}"
    if start.year != end.year:
        return (
            f"{start_month} {start.day}, {start.year}–{end_month} {end.day}, {end.year}"
        )
    if start.month != end.month:
        return f"{start_month} {start.day}–{end_month} {end.day}, {start.year}"
    return f"{start_month} {start.day}–{end.day}, {start.year}"


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


def _all_time_label(end_ts: int, timezone: tzinfo | None) -> str:
    end = datetime.fromtimestamp(end_ts, timezone)
    return f"through {end:%Y-%m-%d %H:%M %Z} · start bounded by retained data"


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
