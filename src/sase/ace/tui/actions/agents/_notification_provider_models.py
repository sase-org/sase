"""ACE notification provider data shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.notifications.models import Notification

from ...provider_contract import AceSnapshot


@dataclass(frozen=True)
class AceNotificationCounts:
    """Notification count shape consumed by ACE indicator code."""

    priority: int = 0
    errors: int = 0
    rest: int = 0
    muted: int = 0


@dataclass(frozen=True)
class AceNotificationSnapshot:
    """Notification snapshot shape consumed by ACE notification code."""

    notifications: list[Notification] = field(default_factory=list)
    counts: AceNotificationCounts = field(default_factory=AceNotificationCounts)
    expired_ids: list[str] = field(default_factory=list)
    next_snooze_deadline: str | None = None
    shared_snapshot: AceSnapshot[Notification] | None = None


@dataclass(frozen=True)
class AceNotificationCountSnapshot:
    """Count-only notification provider result for the persistent indicator."""

    counts: AceNotificationCounts = field(default_factory=AceNotificationCounts)
    shared_snapshot: AceSnapshot[Notification] | None = None


@dataclass(frozen=True)
class AceNotificationPage:
    """One modal/list page from the notification provider."""

    notifications: list[Notification] = field(default_factory=list)
    counts: AceNotificationCounts = field(default_factory=AceNotificationCounts)
    next_cursor: str | None = None
    shared_snapshot: AceSnapshot[Notification] | None = None
    bounded: bool = False
    truncated: bool = False


@dataclass(frozen=True)
class AceNotificationDetail:
    """Selected notification detail payload."""

    notification: Notification | None = None
    shared_snapshot: AceSnapshot[Notification] | None = None
    bounded: bool = False
    truncated: bool = False


@dataclass(frozen=True)
class AceNotificationPendingActions:
    """Pending notification action/detail payload."""

    store: dict[str, Any] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)
    shared_snapshot: AceSnapshot[dict[str, Any]] | None = None
    bounded: bool = False
    truncated: bool = False


__all__ = [
    "AceNotificationCountSnapshot",
    "AceNotificationCounts",
    "AceNotificationDetail",
    "AceNotificationPage",
    "AceNotificationPendingActions",
    "AceNotificationSnapshot",
]
