"""Normalize, match, and parse reset hints from usage-limit error text."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone, tzinfo as TzInfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .usage_limit_config_types import ProviderUsageLimitConfig

# Grace buffer added to any parsed reset hint so sase never re-enables a
# provider a moment before the provider's own reset actually happens.
_RESET_GRACE_SECONDS = 60

# U+2019 RIGHT SINGLE QUOTATION MARK, U+2018 LEFT SINGLE QUOTATION MARK,
# U+02BC MODIFIER LETTER APOSTROPHE, U+00B4 ACUTE ACCENT, and the backtick all
# get typed as "an apostrophe" by one provider or another; normalize them all
# to ASCII ' so pattern matching doesn't silently half-work.
_APOSTROPHE_TRANSLATION = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "ʼ": "'",
        "´": "'",
        "`": "'",
    }
)

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_preserve_case(text: str) -> str:
    # Apostrophe translation must run before NFKC: NFKC's compatibility
    # decomposition of U+00B4 (ACUTE ACCENT) turns it into a bare combining
    # accent, which would no longer match this translation table.
    normalized = text.translate(_APOSTROPHE_TRANSLATION)
    normalized = unicodedata.normalize("NFKC", normalized)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def normalize_for_match(text: str) -> str:
    """Normalize text for case/apostrophe/whitespace-insensitive matching."""
    return _normalize_preserve_case(text).casefold()


def find_matching_pattern(text: str, config: ProviderUsageLimitConfig) -> str | None:
    """Return the first configured pattern matching ``text``, or None.

    Exclusions are checked against the whole text, not per-pattern: if any
    exclude_patterns entry matches anywhere, no pattern is considered a match.
    """
    if not config.patterns:
        return None
    normalized_text = normalize_for_match(text)
    for exclude in config.exclude_patterns:
        normalized_exclude = normalize_for_match(exclude)
        if normalized_exclude and normalized_exclude in normalized_text:
            return None
    for pattern in config.patterns:
        normalized_pattern = normalize_for_match(pattern)
        if normalized_pattern and normalized_pattern in normalized_text:
            return pattern
    return None


def is_usage_limit_error(text: str, config: ProviderUsageLimitConfig) -> bool:
    """Check whether ``text`` matches this provider's usage-limit patterns."""
    return find_matching_pattern(text, config) is not None


# --- Reset-hint parsing ---

# A broadened anchor shared by every absolute/clock-time form below. Accepts
# both "resets"/"reset" and "try again" as the keyword, and an optional
# "at "/"on " before the payload, so "Try again at <X>" and "resets at <X>"
# both match. The numeric/month payload is required immediately after, so
# incidental prose ("connection reset by peer", "try again later:") cannot
# match.
_RESET_ANCHOR = r"(?:resets?|try\s+again)\s+(?:at\s+|on\s+)?"

# Shared zone-name fragment: an IANA "Area/City" name, or the bare "UTC" that
# has no slash (Claude's billing-error body emits "resets ... UTC" and can
# also emit a parenthesized "(UTC)").
_ZONE_NAME_RE = r"[A-Za-z_]+(?:/[A-Za-z_]+)+|UTC"

# Shared ISO-ish timestamp payload (year-month-day and clock), used by both
# the keyword-anchored form and the unanchored fallback.
_ISO_DATETIME_PAYLOAD = (
    r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?"
    r"(?:\s*(Z|UTC|[+-]\d{2}:\d{2}))?"
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

# Month-name date + 12h clock. Claude Code 2.1.235 ``fW(epoch, withZone)``
# strips the space before the meridiem via
# ``.replace(/ ([AP]M)/i, (full, mer) => mer.toLowerCase())``, which returns
# only the lowercased ``am``/``pm``. Keep ``\s*`` so compact ``8pm`` /
# ``6:38am`` parse; do not tighten to ``\s+``.
_MONTH_NAME_DATETIME_PAYLOAD = (
    r"([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+"
    r"(?:(\d{4}),?\s+)?"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
    r"(?:\s*\((" + _ZONE_NAME_RE + r")\))?"
)

_RESET_ISO_RE = re.compile(_RESET_ANCHOR + _ISO_DATETIME_PAYLOAD, re.IGNORECASE)
_RESET_MONTH_DATE_RE = re.compile(
    _RESET_ANCHOR + _MONTH_NAME_DATETIME_PAYLOAD, re.IGNORECASE
)
_UNANCHORED_ISO_RE = re.compile(_ISO_DATETIME_PAYLOAD, re.IGNORECASE)
_UNANCHORED_MONTH_DATE_RE = re.compile(_MONTH_NAME_DATETIME_PAYLOAD, re.IGNORECASE)
_RESET_TIME_WITH_ZONE_RE = re.compile(
    _RESET_ANCHOR + r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*\((" + _ZONE_NAME_RE + r")\)",
    re.IGNORECASE,
)
_RESET_TIME_RE = re.compile(
    _RESET_ANCHOR + r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
    re.IGNORECASE,
)
_RESET_DURATION_RE = re.compile(
    r"(?:resets?\s+in|try\s+again\s+in)\s+"
    r"((?:\d+\s*(?:hours?|hrs?|h|minutes?|mins?|m)\s*)+)",
    re.IGNORECASE,
)
_DURATION_TOKEN_RE = re.compile(
    r"(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m)", re.IGNORECASE
)
_DURATION_UNIT_SECONDS = {
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
}


def _resolve_clock_time(
    hour_str: str,
    minute_str: str | None,
    meridiem: str,
    tz: TzInfo,
    now: float,
) -> float | None:
    try:
        hour = int(hour_str)
        minute = int(minute_str) if minute_str else 0
    except ValueError:
        return None
    if not (1 <= hour <= 12) or not (0 <= minute <= 59):
        return None
    hour24 = hour % 12
    if meridiem.lower() == "pm":
        hour24 += 12
    now_dt = datetime.fromtimestamp(now, tz=tz)
    candidate = now_dt.replace(hour=hour24, minute=minute, second=0, microsecond=0)
    if candidate < now_dt:
        candidate += timedelta(days=1)
    return candidate.timestamp()


def _resolve_iso_datetime(
    year_str: str,
    month_str: str,
    day_str: str,
    hour_str: str,
    minute_str: str,
    second_str: str | None,
    zone_str: str | None,
) -> float | None:
    try:
        year = int(year_str)
        month = int(month_str)
        day = int(day_str)
        hour = int(hour_str)
        minute = int(minute_str)
        second = int(second_str) if second_str else 0
    except ValueError:
        return None
    if not (0 <= hour <= 23) or not (0 <= minute <= 59) or not (0 <= second <= 59):
        return None

    if zone_str is None:
        from sase.core.time import get_timezone

        tz: TzInfo = get_timezone()
    elif zone_str.upper() in ("Z", "UTC"):
        tz = ZoneInfo("UTC")
    else:
        sign = 1 if zone_str[0] == "+" else -1
        offset_hours_str, offset_minutes_str = zone_str[1:].split(":")
        tz = timezone(
            sign
            * timedelta(hours=int(offset_hours_str), minutes=int(offset_minutes_str))
        )

    try:
        candidate = datetime(year, month, day, hour, minute, second, tzinfo=tz)
    except ValueError:
        return None
    return candidate.timestamp()


def _resolve_month_name_datetime(
    month_str: str,
    day_str: str,
    year_str: str | None,
    hour_str: str,
    minute_str: str | None,
    meridiem: str,
    tz: TzInfo,
    now: float,
) -> float | None:
    month = _MONTH_ABBR_TO_NUM.get(month_str[:3].lower())
    if month is None:
        return None
    try:
        day = int(day_str)
        hour = int(hour_str)
        minute = int(minute_str) if minute_str else 0
    except ValueError:
        return None
    if not (1 <= hour <= 12) or not (0 <= minute <= 59):
        return None
    hour24 = hour % 12
    if meridiem.lower() == "pm":
        hour24 += 12

    if year_str is not None:
        try:
            year = int(year_str)
            candidate = datetime(year, month, day, hour24, minute, tzinfo=tz)
        except ValueError:
            return None
        return candidate.timestamp()

    # Claude omits the year in the common case. Pick whichever of last/this/
    # next year lands closest to ``now`` so a date that just slipped a few
    # minutes into the past resolves as a few minutes ago (clamped up to
    # ``min_disable_seconds`` by the caller) rather than rolling a full year
    # forward and clamping to the 7-day maximum instead.
    now_dt = datetime.fromtimestamp(now, tz=tz)
    best: datetime | None = None
    for year in (now_dt.year - 1, now_dt.year, now_dt.year + 1):
        try:
            candidate = datetime(year, month, day, hour24, minute, tzinfo=tz)
        except ValueError:
            continue
        if best is None or abs(candidate - now_dt) < abs(best - now_dt):
            best = candidate
    if best is None:
        return None
    return best.timestamp()


def _hint_from_iso_match(
    match: re.Match[str], normalized: str
) -> tuple[float | None, str | None]:
    year_str, month_str, day_str, hour_str, minute_str, second_str, zone_str = (
        match.groups()
    )
    expires_at = _resolve_iso_datetime(
        year_str, month_str, day_str, hour_str, minute_str, second_str, zone_str
    )
    if expires_at is None:
        return None, None
    hint = normalized[match.start(1) : match.end()]
    return expires_at + _RESET_GRACE_SECONDS, hint


def _hint_from_month_date_match(
    match: re.Match[str], normalized: str, now: float
) -> tuple[float | None, str | None]:
    month_str, day_str, year_str, hour_str, minute_str, meridiem, zone_str = (
        match.groups()
    )
    if zone_str is not None:
        try:
            tz: TzInfo = ZoneInfo(zone_str)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            return None, None
    else:
        from sase.core.time import get_timezone

        tz = get_timezone()
    expires_at = _resolve_month_name_datetime(
        month_str, day_str, year_str, hour_str, minute_str, meridiem, tz, now
    )
    if expires_at is None:
        return None, None
    hint = normalized[match.start(1) : match.end()]
    return expires_at + _RESET_GRACE_SECONDS, hint


def parse_reset_hint(
    text: str, *, now: float, allow_unanchored: bool = False
) -> tuple[float | None, str | None]:
    """Parse a provider-reported reset time or duration from ``text``.

    Returns ``(expires_at_epoch, display_hint)``. Tries each form in
    priority order (ISO-ish absolute timestamp, month-name absolute date,
    zoned clock time, local clock time, then a relative duration) and
    commits to the first one whose keyword matches: it does not fall through
    to a lower-priority form on failure, since e.g. an unrecognized IANA zone
    name is a failed parse of an explicit zone, not license to silently
    substitute the local timezone. Any parse failure or ambiguity returns
    ``(None, None)`` so the caller can fall back to a flat duration; parsing
    is an optimization and must never block a disable.

    Absolute timestamps with no zone marker (Codex renders local wall time
    with none) resolve via ``sase.core.time.get_timezone()`` — a sase
    ``timezone:`` config deliberately set to something other than the host
    zone will skew these parses, matching what the pre-existing bare
    clock-time form already assumed.

    When ``allow_unanchored`` is true — used by :func:`detect_usage_limit`
    after a usage-limit pattern has already matched — and no keyword form
    matched at all, a month-name or ISO-ish timestamp is accepted without
    ``resets`` / ``try again``. A keyword form that matched and then failed
    to resolve still returns ``(None, None)`` without running that fallback.
    """
    normalized = _normalize_preserve_case(text)

    match = _RESET_ISO_RE.search(normalized)
    if match:
        return _hint_from_iso_match(match, normalized)

    match = _RESET_MONTH_DATE_RE.search(normalized)
    if match:
        return _hint_from_month_date_match(match, normalized, now)

    match = _RESET_TIME_WITH_ZONE_RE.search(normalized)
    if match:
        hour_str, minute_str, meridiem, zone_name = match.groups()
        try:
            tz = ZoneInfo(zone_name)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            return None, None
        expires_at = _resolve_clock_time(hour_str, minute_str, meridiem, tz, now)
        if expires_at is None:
            return None, None
        minute_part = f":{minute_str}" if minute_str else ""
        hint = f"{hour_str}{minute_part}{meridiem.lower()} ({zone_name})"
        return expires_at + _RESET_GRACE_SECONDS, hint

    match = _RESET_TIME_RE.search(normalized)
    if match:
        hour_str, minute_str, meridiem = match.groups()
        from sase.core.time import get_timezone

        expires_at = _resolve_clock_time(
            hour_str, minute_str, meridiem, get_timezone(), now
        )
        if expires_at is None:
            return None, None
        minute_part = f":{minute_str}" if minute_str else ""
        hint = f"{hour_str}{minute_part}{meridiem.lower()}"
        return expires_at + _RESET_GRACE_SECONDS, hint

    match = _RESET_DURATION_RE.search(normalized)
    if match:
        total_seconds = sum(
            int(amount) * _DURATION_UNIT_SECONDS[unit.lower()]
            for amount, unit in _DURATION_TOKEN_RE.findall(match.group(1))
        )
        if total_seconds > 0:
            return now + total_seconds + _RESET_GRACE_SECONDS, match.group(1).strip()
        return None, None

    if allow_unanchored:
        match = _UNANCHORED_ISO_RE.search(normalized)
        if match:
            return _hint_from_iso_match(match, normalized)
        match = _UNANCHORED_MONTH_DATE_RE.search(normalized)
        if match:
            return _hint_from_month_date_match(match, normalized, now)

    return None, None
