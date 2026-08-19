"""Usage-limit detection configuration for LLM providers.

Deliberately parallel to ``retry_config.py``: built-in defaults are supplied
per-provider via a pluggy hook, user config merges on top, and list fields are
additive with dedup unless a provider opts into ``replace_patterns``.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo as TzInfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sase.config import load_merged_config


@dataclass
class ProviderUsageLimitConfig:
    """Per-provider usage-limit detection configuration."""

    patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    disable_seconds: int | None = None  # None => fall back to global default
    honor_reset_hint: bool | None = None  # None => fall back to global default


@dataclass
class UsageLimitSettings:
    """Resolved global usage-limit settings."""

    enabled: bool = True
    disable_seconds: int = 86400  # 24h fallback when no reset hint is honored
    min_disable_seconds: int = 60
    max_disable_seconds: int = 604800  # 7d cap on any parsed reset time
    honor_reset_hint: bool = True
    notify: bool = True


@dataclass(frozen=True)
class UsageLimitDetection:
    """Result of matching a provider failure against its usage-limit config."""

    provider: str
    matched_pattern: str
    message: str  # normalized, truncated trigger snippet
    raw_message: str  # untruncated original, for the notification body
    disable_seconds: float
    expires_at: float | None
    reset_hint: str | None  # e.g. "8pm (America/New_York)" when parsed
    used_reset_hint: bool


# Grace buffer added to any parsed reset hint so sase never re-enables a
# provider a moment before the provider's own reset actually happens.
_RESET_GRACE_SECONDS = 60

_MAX_MESSAGE_LEN = 500


def _dedup_ordered(items: list[str]) -> list[str]:
    """Return a list with duplicates removed, preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _clone_config(cfg: ProviderUsageLimitConfig) -> ProviderUsageLimitConfig:
    """Return a defensive copy so callers can't mutate module-level built-ins."""
    return ProviderUsageLimitConfig(
        patterns=list(cfg.patterns),
        exclude_patterns=list(cfg.exclude_patterns),
        disable_seconds=cfg.disable_seconds,
        honor_reset_hint=cfg.honor_reset_hint,
    )


def _built_in_defaults() -> dict[str, ProviderUsageLimitConfig]:
    """Aggregate ``llm_default_usage_limit_config()`` values from plugins."""
    from .registry import iter_plugins

    defaults: dict[str, ProviderUsageLimitConfig] = {}
    for name, plugin in iter_plugins():
        method = getattr(plugin, "llm_default_usage_limit_config", None)
        if method is None:
            continue
        try:
            config = method()
        except Exception:
            continue
        if config is not None:
            defaults[name] = config
    return defaults


def _load_llm_usage_limit_section() -> dict[str, Any]:
    try:
        data = load_merged_config()
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    llm_config = data.get("llm_provider", {}) or {}
    if not isinstance(llm_config, dict):
        return {}
    usage_limit_section = llm_config.get("usage_limit", {}) or {}
    if not isinstance(usage_limit_section, dict):
        return {}
    return usage_limit_section


def _load_user_provider_dict(provider_name: str) -> dict[str, Any] | None:
    """Return the raw user-configured usage-limit dict for a provider, or None."""
    providers_section = _load_llm_usage_limit_section().get("providers", {}) or {}
    if not isinstance(providers_section, dict):
        return None
    provider_dict = providers_section.get(provider_name)
    if not provider_dict or not isinstance(provider_dict, dict):
        return None
    return provider_dict


def _config_from_user_dict(user_dict: dict[str, Any]) -> ProviderUsageLimitConfig:
    return ProviderUsageLimitConfig(
        patterns=list(user_dict.get("patterns", [])),
        exclude_patterns=list(user_dict.get("exclude_patterns", [])),
        disable_seconds=user_dict.get("disable_seconds"),
        honor_reset_hint=user_dict.get("honor_reset_hint"),
    )


def _merge_with_built_in(
    user_dict: dict[str, Any], built_in: ProviderUsageLimitConfig
) -> ProviderUsageLimitConfig:
    # ``replace_patterns: true`` plus a present ``patterns`` key is a literal
    # replacement, including ``patterns: []``. Key absence still keeps the
    # built-ins so a provider can opt into replacement later without wiping
    # detection in the meantime.
    if user_dict.get("replace_patterns", False) and "patterns" in user_dict:
        patterns = list(user_dict.get("patterns") or [])
    elif user_dict.get("replace_patterns", False):
        patterns = list(built_in.patterns)
    else:
        patterns = _dedup_ordered(
            list(built_in.patterns) + list(user_dict.get("patterns", []))
        )

    # exclude_patterns are always additive; there is no replace escape hatch.
    exclude_patterns = _dedup_ordered(
        list(built_in.exclude_patterns) + list(user_dict.get("exclude_patterns", []))
    )

    # disable_seconds and honor_reset_hint use key-presence checks so that an
    # explicit user null/False overrides a built-in non-null value.
    disable_seconds = (
        user_dict["disable_seconds"]
        if "disable_seconds" in user_dict
        else built_in.disable_seconds
    )
    honor_reset_hint = (
        user_dict["honor_reset_hint"]
        if "honor_reset_hint" in user_dict
        else built_in.honor_reset_hint
    )
    return ProviderUsageLimitConfig(
        patterns=patterns,
        exclude_patterns=exclude_patterns,
        disable_seconds=disable_seconds,
        honor_reset_hint=honor_reset_hint,
    )


def get_usage_limit_config(provider_name: str) -> ProviderUsageLimitConfig | None:
    """Load usage-limit config for a specific provider.

    Merges user-configured values (from
    ``llm_provider.usage_limit.providers.<provider>``) on top of module-level
    built-in defaults supplied by each provider plugin. Returns None if
    neither a user config nor a built-in exists for the provider.
    """
    user_dict = _load_user_provider_dict(provider_name)
    built_in = _built_in_defaults().get(provider_name)

    if user_dict is None and built_in is None:
        return None
    if user_dict is None:
        assert built_in is not None
        return _clone_config(built_in)
    if built_in is None:
        return _config_from_user_dict(user_dict)
    return _merge_with_built_in(user_dict, built_in)


def get_usage_limit_settings() -> UsageLimitSettings:
    """Load the resolved global usage-limit settings."""
    section = _load_llm_usage_limit_section()
    defaults = UsageLimitSettings()
    return UsageLimitSettings(
        enabled=bool(section.get("enabled", defaults.enabled)),
        disable_seconds=int(section.get("disable_seconds", defaults.disable_seconds)),
        min_disable_seconds=int(
            section.get("min_disable_seconds", defaults.min_disable_seconds)
        ),
        max_disable_seconds=int(
            section.get("max_disable_seconds", defaults.max_disable_seconds)
        ),
        honor_reset_hint=bool(
            section.get("honor_reset_hint", defaults.honor_reset_hint)
        ),
        notify=bool(section.get("notify", defaults.notify)),
    )


# --- Normalization and matching ---

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


def _truncate(text: str, max_len: int = _MAX_MESSAGE_LEN) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


# --- Detection ---


def detect_usage_limit(
    provider: str, error_text: str, *, now: float | None = None
) -> UsageLimitDetection | None:
    """Detect a usage-limit failure and resolve its disable duration.

    Returns None when usage-limit detection is disabled globally, the
    provider has no resolved config, or ``error_text`` does not match.
    """
    settings = get_usage_limit_settings()
    if not settings.enabled:
        return None

    config = get_usage_limit_config(provider)
    if config is None:
        return None

    matched_pattern = find_matching_pattern(error_text, config)
    if matched_pattern is None:
        return None

    resolved_now = time.time() if now is None else now

    honor_reset_hint = (
        config.honor_reset_hint
        if config.honor_reset_hint is not None
        else settings.honor_reset_hint
    )
    disable_seconds: float = (
        config.disable_seconds
        if config.disable_seconds is not None
        else settings.disable_seconds
    )

    reset_hint: str | None = None
    expires_at: float | None = None
    used_reset_hint = False

    if honor_reset_hint:
        parsed_expires_at, parsed_hint = parse_reset_hint(
            error_text, now=resolved_now, allow_unanchored=True
        )
        if parsed_expires_at is not None:
            duration = parsed_expires_at - resolved_now
            duration = min(
                max(duration, settings.min_disable_seconds),
                settings.max_disable_seconds,
            )
            disable_seconds = duration
            expires_at = resolved_now + duration
            reset_hint = parsed_hint
            used_reset_hint = True

    # min/max_disable_seconds only bound a reset-hint-derived duration, which
    # is untrusted provider input; the flat disable_seconds fallback is an
    # admin-chosen value and is used as configured.

    return UsageLimitDetection(
        provider=provider,
        matched_pattern=matched_pattern,
        message=_truncate(normalize_for_match(error_text)),
        raw_message=error_text,
        disable_seconds=disable_seconds,
        expires_at=expires_at,
        reset_hint=reset_hint,
        used_reset_hint=used_reset_hint,
    )


def _usage_limit_provider_order() -> list[str]:
    """Return provider names to try, user-configured first, then built-ins."""
    providers_section = _load_llm_usage_limit_section().get("providers", {}) or {}
    order: list[str] = []
    if isinstance(providers_section, dict):
        order.extend(providers_section.keys())
    order.extend(_built_in_defaults().keys())
    return order


def find_usage_limit_detection_for_error(
    error_output: str, *, now: float | None = None
) -> UsageLimitDetection | None:
    """Find a usage-limit detection that matches the error from any provider.

    Mirrors ``retry_config.find_retry_config_for_error``: iterates
    user-configured providers first (preserving insertion order), then any
    built-in-only providers, and returns the first provider whose config
    matches. Used when the caller does not know which provider actually
    produced the error (e.g. a multi-step workflow that may have invoked
    more than one LLM provider).
    """
    checked: set[str] = set()
    for provider_name in _usage_limit_provider_order():
        if provider_name in checked:
            continue
        checked.add(provider_name)
        try:
            detection = detect_usage_limit(provider_name, error_output, now=now)
        except Exception:
            continue
        if detection is not None:
            return detection
    return None
