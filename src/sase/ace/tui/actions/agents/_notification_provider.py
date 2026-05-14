"""ACE notification read provider helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.daemon.client import LOCAL_DAEMON_DEFAULT_PAGE_LIMIT, LocalDaemonClient
from sase.daemon.read_facade import DaemonReadResult, read_or_fallback
from sase.daemon.read_models import (
    notification_counts_from_dict,
    notification_list_from_dict,
)
from sase.notifications.models import Notification


@dataclass(frozen=True)
class _AceNotificationCounts:
    """Notification count shape consumed by ACE indicator code."""

    priority: int = 0
    errors: int = 0
    rest: int = 0
    muted: int = 0


@dataclass(frozen=True)
class _AceNotificationSnapshot:
    """Notification snapshot shape consumed by ACE notification code."""

    notifications: list[Notification] = field(default_factory=list)
    counts: _AceNotificationCounts = field(default_factory=_AceNotificationCounts)
    expired_ids: list[str] = field(default_factory=list)


def read_notification_snapshot_for_tui(
    *,
    include_dismissed: bool = False,
    expire_due_snoozes: bool = False,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[Any]:
    """Return the ACE notification snapshot through daemon reads when possible."""

    from sase.notifications import read_notification_snapshot

    return read_or_fallback(
        "notification_list",
        args=args,
        client=client,
        daemon_loader=lambda daemon: _daemon_notification_snapshot(
            daemon,
            include_dismissed=include_dismissed,
            expire_due_snoozes=expire_due_snoozes,
        ),
        direct_loader=lambda: read_notification_snapshot(
            include_dismissed,
            expire_due_snoozes,
        ),
    )


def _daemon_notification_snapshot(
    client: LocalDaemonClient,
    *,
    include_dismissed: bool,
    expire_due_snoozes: bool,
) -> _AceNotificationSnapshot:
    notifications = []
    cursor: str | None = None
    while True:
        page = notification_list_from_dict(
            client.notification_list(
                include_dismissed=include_dismissed,
                limit=LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
                cursor=cursor,
            )
        )
        notifications.extend(page.notifications)
        cursor = page.page.next_cursor
        if not cursor:
            break

    counts = notification_counts_from_dict(client.notification_counts()).counts
    expired_ids: list[str] = []
    if expire_due_snoozes:
        from sase.notifications.store import expire_due_snoozes as expire_rows

        expired = expire_rows(notifications)
        expired_ids = [notification.id for notification in expired]
        if expired_ids:
            counts = _counts_from_notifications(notifications)
    return _AceNotificationSnapshot(
        notifications=notifications,
        counts=_AceNotificationCounts(
            priority=int(counts.get("priority", 0)),
            errors=int(counts.get("errors", 0)),
            rest=int(counts.get("rest", 0)),
            muted=int(counts.get("muted", 0)),
        ),
        expired_ids=expired_ids,
    )


def _counts_from_notifications(notifications: list[Any]) -> dict[str, int]:
    from sase.notifications.priority import is_error, is_priority

    counts = {"priority": 0, "errors": 0, "rest": 0, "muted": 0}
    for notification in notifications:
        if notification.read or notification.silent:
            continue
        if notification.muted:
            counts["muted"] += 1
        elif is_error(notification):
            counts["errors"] += 1
        elif is_priority(notification):
            counts["priority"] += 1
        else:
            counts["rest"] += 1
    return counts


__all__ = [
    "read_notification_snapshot_for_tui",
]
