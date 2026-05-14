"""Daemon-backed read adapters for notification CLI/catalog surfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.daemon.client import LocalDaemonClient
from sase.daemon.read_facade import DaemonReadResult, read_or_fallback
from sase.daemon.read_models import (
    NotificationCountsRead,
    NotificationPendingActionsRead,
    notification_counts_from_dict,
    notification_detail_from_dict,
    notification_list_from_dict,
    notification_pending_actions_from_dict,
)
from sase.notifications.models import Notification
from sase.notifications.store import load_notifications, read_notification_snapshot


@dataclass(frozen=True)
class NotificationPendingActions:
    """Read projection for notification pending-action state."""

    store: dict[str, Any] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)


def read_notifications(
    *,
    limit: int | None = None,
    query: str | None = None,
    sender: str | None = None,
    unread: bool = False,
    include_dismissed: bool = False,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[list[Notification]]:
    """Read filtered notifications through the daemon with direct fallback."""

    def direct_loader() -> list[Notification]:
        return _filter_direct_notifications(
            limit=limit,
            query=query,
            sender=sender,
            unread=unread,
            include_dismissed=include_dismissed,
        )

    return read_or_fallback(
        "notification_list",
        args=args,
        client=client,
        daemon_loader=lambda daemon: _daemon_notification_list(
            daemon,
            limit=limit,
            query=query,
            sender=sender,
            unread=unread,
            include_dismissed=include_dismissed,
        ),
        direct_loader=direct_loader,
    )


def read_notification_detail(
    notification_id: str,
    *,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[Notification | None]:
    """Read one notification through the daemon with direct fallback."""

    return read_or_fallback(
        "notification_detail",
        args=args,
        client=client,
        daemon_loader=lambda daemon: (
            notification_detail_from_dict(
                daemon.notification_detail(notification_id)
            ).notification
        ),
        direct_loader=lambda: _direct_notification_detail(notification_id),
    )


def read_notification_counts(
    *,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[NotificationCountsRead]:
    """Read notification indicator counts through the daemon with fallback."""

    return read_or_fallback(
        "notification_counts",
        args=args,
        client=client,
        daemon_loader=lambda daemon: notification_counts_from_dict(
            daemon.notification_counts()
        ),
        direct_loader=_direct_notification_counts,
    )


def read_notification_pending_actions(
    *,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[NotificationPendingActions]:
    """Read pending notification actions through the daemon with fallback."""

    return read_or_fallback(
        "notification_pending_actions",
        args=args,
        client=client,
        daemon_loader=lambda daemon: _pending_actions_from_daemon(
            notification_pending_actions_from_dict(
                daemon.notification_pending_actions()
            )
        ),
        direct_loader=_direct_pending_actions,
    )


def _filter_direct_notifications(
    *,
    limit: int | None,
    query: str | None,
    sender: str | None,
    unread: bool,
    include_dismissed: bool,
) -> list[Notification]:
    from sase.notifications.catalog import matches_notification_query
    from sase.notifications.sort import timestamp_sort_key

    rows = sorted(
        load_notifications(include_dismissed=include_dismissed),
        key=timestamp_sort_key,
        reverse=True,
    )
    if sender is not None:
        rows = [notification for notification in rows if notification.sender == sender]
    if unread:
        rows = [notification for notification in rows if not notification.read]
    if query:
        rows = [
            notification
            for notification in rows
            if matches_notification_query(notification, query)
        ]
    if limit is not None:
        rows = rows[: max(0, limit)]
    return rows


def _daemon_notification_list(
    daemon: LocalDaemonClient,
    *,
    limit: int | None,
    query: str | None,
    sender: str | None,
    unread: bool,
    include_dismissed: bool,
) -> list[Notification]:
    if limit is not None and limit <= 0:
        request_limit = 1
    elif limit is None:
        request_limit = 500
    else:
        request_limit = limit

    notifications: list[Notification] = []
    cursor: str | None = None
    while True:
        page = notification_list_from_dict(
            daemon.notification_list(
                include_dismissed=include_dismissed,
                query=query,
                sender=sender,
                unread=True if unread else None,
                limit=request_limit,
                cursor=cursor,
            )
        )
        notifications.extend(page.notifications)
        if limit is not None and len(notifications) >= max(0, limit):
            return notifications[: max(0, limit)]
        cursor = page.page.next_cursor
        if not cursor:
            return notifications


def _direct_notification_detail(notification_id: str) -> Notification | None:
    for notification in load_notifications(include_dismissed=True):
        if notification.id == notification_id:
            return notification
    return None


def _direct_notification_counts() -> NotificationCountsRead:
    counts = read_notification_snapshot().counts
    return NotificationCountsRead(
        counts={
            "priority": int(counts.priority),
            "errors": int(counts.errors),
            "rest": int(counts.rest),
            "muted": int(counts.muted),
        }
    )


def _direct_pending_actions() -> NotificationPendingActions:
    from sase.notifications import pending_actions

    store = pending_actions.read_pending_action_store(include_legacy=True)
    actions = [
        dict(action)
        for action in store.get("actions", {}).values()
        if isinstance(action, dict)
    ]
    actions.sort(key=lambda action: str(action.get("prefix", "")))
    return NotificationPendingActions(store=store, actions=actions)


def _pending_actions_from_daemon(
    read: NotificationPendingActionsRead,
) -> NotificationPendingActions:
    return NotificationPendingActions(store=read.store, actions=read.actions)


__all__ = [
    "NotificationPendingActions",
    "read_notification_counts",
    "read_notification_detail",
    "read_notification_pending_actions",
    "read_notifications",
]
