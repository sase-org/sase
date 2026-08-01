"""Notification data model."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Notification:
    """A single notification entry."""

    id: str  # UUID4
    timestamp: str  # ISO-8601
    sender: str  # "crs", "fix-hook", etc.
    icon: str | None = None  # Optional single display glyph
    notes: list[str] = field(default_factory=list)  # Human-readable lines
    files: list[str] = field(default_factory=list)  # File paths
    tags: list[str] = field(default_factory=list)  # Display/filter labels
    action: str | None = None  # "HITL" | "JumpToChangeSpec" | "Tmux" | None
    action_data: dict[str, str] = field(default_factory=dict)
    read: bool = False
    dismissed: bool = False
    silent: bool = False
    muted: bool = False
    snooze_until: str | None = None  # ISO-8601 with timezone, or None
    resurfaced_at: str | None = None  # Durable activity time after snooze expiry


def notification_activity_at(notification: Notification) -> str:
    """Return the durable effective activity timestamp for ordering."""
    return notification.resurfaced_at or notification.timestamp


def notification_activity_cursor(notification: Notification) -> tuple[str, str]:
    """Return the stable activity cursor, including the required ID tie-breaker."""
    return (notification_activity_at(notification), notification.id)


def notification_activity_sort_key(
    notification: Notification,
) -> tuple[int, datetime, str, str]:
    """Return a timezone-normalized activity key with a stable ID tie-breaker."""
    activity_at = notification_activity_at(notification)
    try:
        parsed = datetime.fromisoformat(activity_at)
    except ValueError:
        return (0, datetime.min.replace(tzinfo=UTC), activity_at, notification.id)
    if parsed.tzinfo is None:
        return (0, datetime.min.replace(tzinfo=UTC), activity_at, notification.id)
    return (1, parsed.astimezone(UTC), "", notification.id)


def encode_notification_activity_cursor(notification: Notification) -> str:
    """Encode the mobile-compatible ``(activity_at, id)`` cursor."""
    activity_at, notification_id = notification_activity_cursor(notification)
    return f"{activity_at}|{notification_id}"


def notification_is_newer_than_activity_cursor(
    notification: Notification,
    cursor: str,
) -> bool:
    """Compare against a new activity cursor or a legacy timestamp cursor."""
    cursor_timestamp, separator, cursor_id = cursor.rpartition("|")
    if not separator:
        cursor_timestamp = cursor
        cursor_id = ""

    candidate = notification_activity_at(notification)
    try:
        candidate_time = datetime.fromisoformat(candidate)
        cursor_time = datetime.fromisoformat(cursor_timestamp)
    except ValueError:
        if candidate != cursor_timestamp:
            return candidate > cursor_timestamp
    else:
        if candidate_time.tzinfo is not None and cursor_time.tzinfo is not None:
            candidate_utc = candidate_time.astimezone(UTC)
            cursor_utc = cursor_time.astimezone(UTC)
            if candidate_utc != cursor_utc:
                return candidate_utc > cursor_utc
        elif candidate != cursor_timestamp:
            return candidate > cursor_timestamp

    # A timestamp-only rollout cursor preserves its prior strict comparison.
    return bool(separator) and notification.id > cursor_id


def normalize_notification_tags(tags: Iterable[str] | None) -> list[str]:
    """Normalize sender-provided notification tags."""
    if tags is None:
        return []

    tag_values = (tags,) if isinstance(tags, str) else tags

    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tag_values:
        value = tag.strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def format_relative_time(iso_timestamp: str) -> str:
    """Format an ISO-8601 timestamp as a relative time string.

    Returns strings like "2m ago", "1h ago", "3d ago".
    Handles both tz-aware and naive timestamps.
    """
    from sase.core.time import get_timezone

    try:
        ts = datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return iso_timestamp

    now = datetime.now(get_timezone())

    # Make both tz-aware for comparison
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=get_timezone())

    delta = now - ts
    total_seconds = int(delta.total_seconds())

    if total_seconds < 0:
        return "just now"
    if total_seconds < 60:
        return f"{total_seconds}s ago"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def format_absolute_time(iso_timestamp: str, now: datetime | None = None) -> str:
    """Format an ISO-8601 timestamp as an absolute wall-clock string.

    Rendered in the configured timezone, in four tiers:

    - same calendar day: ``"today 13:18:42"``
    - previous calendar day: ``"yesterday 21:04"``
    - same year: ``"Jul 12 09:31"``
    - other year: ``"Jul 12 '25 09:31"``

    Unparsable input is returned unchanged, matching
    :func:`format_relative_time`.
    """
    from sase.core.time import get_timezone

    try:
        ts = datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return iso_timestamp

    tz = get_timezone()

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=tz)
    local = ts.astimezone(tz)

    if now is None:
        reference = datetime.now(tz)
    elif now.tzinfo is None:
        reference = now.replace(tzinfo=tz)
    else:
        reference = now.astimezone(tz)

    days = (reference.date() - local.date()).days
    if days == 0:
        return local.strftime("today %H:%M:%S")
    if days == 1:
        return local.strftime("yesterday %H:%M")
    if local.year == reference.year:
        return local.strftime("%b %-d %H:%M")
    return local.strftime("%b %-d '%y %H:%M")


def format_relative_until(iso_timestamp: str) -> str:
    """Format an ISO-8601 future timestamp as a remaining-time string.

    Returns strings like "< 1m", "14m", "2h", "1d". A timestamp at or
    before now renders as "expiring…".
    """
    from sase.core.time import get_timezone

    try:
        ts = datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return iso_timestamp

    now = datetime.now(get_timezone())

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=get_timezone())

    delta = ts - now
    total_seconds = int(delta.total_seconds())

    if total_seconds <= 0:
        return "expiring…"
    if total_seconds < 60:
        return "< 1m"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    return f"{days}d"
