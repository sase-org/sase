"""Shared value types for notification modal state actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sase.core.time import get_timezone


def resolve_snooze_deadline(
    result: timedelta | datetime,
    *,
    now_utc: datetime | None = None,
) -> datetime:
    """Resolve relative durations on UTC and calendar choices in local time."""
    if isinstance(result, datetime):
        if result.tzinfo is None or result.utcoffset() is None:
            return result.replace(tzinfo=get_timezone())
        return result
    return (now_utc or datetime.now(UTC)) + result


@dataclass(frozen=True)
class NotificationTargetSelection:
    """Stable notification IDs targeted by one modal action."""

    ids: tuple[str, ...]
    from_marks: bool


@dataclass(frozen=True)
class NotificationMutationResult:
    """Result of a mute or snooze persistence operation."""

    action: Literal["mute", "snooze", "read"]
    ids: tuple[str, ...]
    success: bool
    message: str
    matched_count: int = 0
    muted: bool | None = None
    snooze_until: str | None = None
    description: str = ""
    cancelled_snoozes: bool = False
