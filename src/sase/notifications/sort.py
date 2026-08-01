"""Shared timestamp sort keys for notifications."""

from __future__ import annotations

from datetime import datetime

from sase.core.time import get_timezone
from sase.notifications.models import Notification, notification_activity_at


def _parsed_sort_key(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=get_timezone())
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=get_timezone())
    return timestamp


def timestamp_sort_key(notification: Notification) -> datetime:
    """Return a tz-aware datetime for sorting; malformed timestamps sink to the floor."""
    return _parsed_sort_key(notification.timestamp)


def activity_sort_key(notification: Notification) -> datetime:
    """Return the tz-aware effective activity time (``resurfaced_at ?? timestamp``).

    Display surfaces sort with this key so a resurfaced snooze counts as recent
    activity. It deliberately omits the persisted cursor's ID tie-breaker, which
    would otherwise reorder equal-timestamp rows away from their arrival order.
    """
    return _parsed_sort_key(notification_activity_at(notification))


__all__ = ["activity_sort_key", "timestamp_sort_key"]
