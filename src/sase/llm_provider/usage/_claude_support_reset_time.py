"""Parsing for Claude usage-window reset-time expressions."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone, tzinfo as TzInfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sase.core.time import get_timezone
from sase.llm_provider.usage._claude_support_text import normalize_text

_ZONE_NAME_RE = r"[A-Za-z_]+(?:/[A-Za-z_]+)+|UTC"
_ISO_RESET_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?"
    r"(?:\s*(Z|UTC|[+-]\d{2}:\d{2}))?$",
    re.IGNORECASE,
)
_MONTH_RESET_RE = re.compile(
    r"^([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+"
    r"(?:(\d{4}),?\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
    r"(?:\s*\((" + _ZONE_NAME_RE + r")\))?$",
    re.IGNORECASE,
)
_TIME_RESET_RE = re.compile(
    r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
    r"(?:\s*\((" + _ZONE_NAME_RE + r")\))?$",
    re.IGNORECASE,
)
_MONTH_ABBR_TO_NUM = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def parse_claude_reset_timestamp(text: str, *, observed_at: float) -> float | None:
    """Parse a Claude usage-window reset expression into epoch seconds."""
    normalized = normalize_text(text)
    if not normalized:
        return None
    match = _ISO_RESET_RE.match(normalized)
    if match:
        return _resolve_iso_datetime(match.groups())
    match = _MONTH_RESET_RE.match(normalized)
    if match:
        return _resolve_month_datetime(match.groups(), observed_at=observed_at)
    match = _TIME_RESET_RE.match(normalized)
    if match:
        return _resolve_time_only(match.groups(), observed_at=observed_at)
    return None


def _resolve_iso_datetime(groups: tuple[str | None, ...]) -> float | None:
    year_str, month_str, day_str, hour_str, minute_str, second_str, zone_str = groups
    try:
        year = int(year_str or "")
        month = int(month_str or "")
        day = int(day_str or "")
        hour = int(hour_str or "")
        minute = int(minute_str or "")
        second = int(second_str) if second_str else 0
    except ValueError:
        return None
    tz = _resolve_zone(zone_str)
    if tz is None:
        return None
    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=tz).timestamp()
    except ValueError:
        return None


def _resolve_month_datetime(
    groups: tuple[str | None, ...],
    *,
    observed_at: float,
) -> float | None:
    month_str, day_str, year_str, hour_str, minute_str, meridiem, zone_str = groups
    month = _MONTH_ABBR_TO_NUM.get(str(month_str or "")[:3].casefold())
    if month is None:
        return None
    try:
        day = int(day_str or "")
        hour = _hour_24(hour_str, meridiem)
        minute = int(minute_str) if minute_str else 0
    except ValueError:
        return None
    if hour is None or not (0 <= minute <= 59):
        return None
    tz = _resolve_zone(zone_str)
    if tz is None:
        return None
    if year_str is not None:
        try:
            candidate = datetime(
                int(year_str),
                month,
                day,
                hour,
                minute,
                tzinfo=tz,
            )
            return candidate.timestamp()
        except ValueError:
            return None
    now_dt = datetime.fromtimestamp(observed_at, tz=tz)
    candidates: list[datetime] = []
    for year in (now_dt.year - 1, now_dt.year, now_dt.year + 1):
        try:
            candidates.append(datetime(year, month, day, hour, minute, tzinfo=tz))
        except ValueError:
            continue
    if not candidates:
        return None
    closest = min(candidates, key=lambda candidate: abs(candidate - now_dt))
    return closest.timestamp()


def _resolve_time_only(
    groups: tuple[str | None, ...],
    *,
    observed_at: float,
) -> float | None:
    hour_str, minute_str, meridiem, zone_str = groups
    try:
        hour = _hour_24(hour_str, meridiem)
        minute = int(minute_str) if minute_str else 0
    except ValueError:
        return None
    if hour is None or not (0 <= minute <= 59):
        return None
    tz = _resolve_zone(zone_str)
    if tz is None:
        return None
    now_dt = datetime.fromtimestamp(observed_at, tz=tz)
    candidate = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate.timestamp() < observed_at - 300.0:
        candidate += timedelta(days=1)
    return candidate.timestamp()


def _hour_24(hour_str: str | None, meridiem: str | None) -> int | None:
    try:
        hour = int(hour_str or "")
    except ValueError:
        return None
    if not (1 <= hour <= 12):
        return None
    hour %= 12
    if str(meridiem or "").casefold() == "pm":
        hour += 12
    return hour


def _resolve_zone(zone_str: str | None) -> TzInfo | None:
    if zone_str is None:
        return get_timezone()
    if zone_str.upper() in {"Z", "UTC"}:
        return ZoneInfo("UTC")
    if zone_str.startswith(("+", "-")):
        try:
            hours, minutes = zone_str[1:].split(":", 1)
            offset = timedelta(hours=int(hours), minutes=int(minutes))
        except ValueError:
            return None
        if zone_str.startswith("-"):
            offset = -offset
        return timezone(offset)
    try:
        return ZoneInfo(zone_str)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None
