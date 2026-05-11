"""Shared timestamp sort key for notifications."""

from __future__ import annotations

from datetime import datetime

from sase.core.time import get_timezone
from sase.notifications.models import Notification


def timestamp_sort_key(notification: Notification) -> datetime:
    """Return a tz-aware datetime for sorting; malformed timestamps sink to the floor."""
    try:
        timestamp = datetime.fromisoformat(notification.timestamp)
    except ValueError:
        return datetime.min.replace(tzinfo=get_timezone())
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=get_timezone())
    return timestamp


__all__ = ["timestamp_sort_key"]
