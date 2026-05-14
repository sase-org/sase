"""Daemon-backed ACE notification provider loaders."""

from __future__ import annotations

from sase.daemon.client import LOCAL_DAEMON_DEFAULT_PAGE_LIMIT, LocalDaemonClient
from sase.daemon.read_models import (
    NotificationPendingActionsRead,
    notification_counts_from_dict,
    notification_detail_from_dict,
    notification_list_from_dict,
    notification_pending_actions_from_dict,
)

from ._notification_provider_metadata import (
    counts_from_notifications,
    notification_count_snapshot_from_counts,
    notification_detail_with_shared_metadata,
    notification_page_with_shared_metadata,
    notification_snapshot_with_shared_metadata,
    pending_actions_with_shared_metadata,
)
from ._notification_provider_models import (
    AceNotificationCountSnapshot,
    AceNotificationCounts,
    AceNotificationDetail,
    AceNotificationPage,
    AceNotificationPendingActions,
    AceNotificationSnapshot,
)


def daemon_notification_snapshot(
    client: LocalDaemonClient,
    *,
    include_dismissed: bool,
    expire_due_snoozes: bool,
) -> AceNotificationSnapshot:
    notifications = []
    cursor: str | None = None
    snapshot_id: str | None = None
    page_count = 0
    while True:
        page = notification_list_from_dict(
            client.notification_list(
                include_dismissed=include_dismissed,
                limit=LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
                cursor=cursor,
            )
        )
        page_count += 1
        snapshot_id = snapshot_id or page.snapshot.snapshot_id
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
            counts = counts_from_notifications(notifications)
    snapshot = AceNotificationSnapshot(
        notifications=notifications,
        counts=AceNotificationCounts(
            priority=int(counts.get("priority", 0)),
            errors=int(counts.get("errors", 0)),
            rest=int(counts.get("rest", 0)),
            muted=int(counts.get("muted", 0)),
        ),
        expired_ids=expired_ids,
    )
    return notification_snapshot_with_shared_metadata(
        snapshot,
        provider_source="daemon",
        prefers_daemon=True,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=snapshot_id,
        page_count=page_count,
    )


def daemon_notification_count_snapshot(
    client: LocalDaemonClient,
) -> AceNotificationCountSnapshot:
    return notification_count_snapshot_from_counts(
        notification_counts_from_dict(client.notification_counts()).counts,
        provider_source="daemon",
        prefers_daemon=True,
        fallback_reason=None,
        fallback_message=None,
    )


def daemon_unread_notification_page(
    client: LocalDaemonClient,
    *,
    include_dismissed: bool,
    limit: int,
    cursor: str | None,
) -> AceNotificationPage:
    page = notification_list_from_dict(
        client.notification_list(
            include_dismissed=include_dismissed,
            unread=True,
            limit=max(1, limit),
            cursor=cursor,
        )
    )
    notifications = [n for n in page.notifications if not n.read and not n.silent]
    counts = counts_from_notifications(notifications)
    bounded = page.bounded
    snapshot = AceNotificationPage(
        notifications=notifications,
        counts=AceNotificationCounts(
            priority=int(counts.get("priority", 0)),
            errors=int(counts.get("errors", 0)),
            rest=int(counts.get("rest", 0)),
            muted=int(counts.get("muted", 0)),
        ),
        next_cursor=page.page.next_cursor,
        bounded=bounded is not None,
        truncated=bool(bounded.truncated) if bounded is not None else False,
    )
    return notification_page_with_shared_metadata(
        snapshot,
        provider_source="daemon",
        prefers_daemon=True,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=page.snapshot.snapshot_id,
        page_count=1,
    )


def daemon_notification_detail(
    client: LocalDaemonClient,
    notification_id: str,
) -> AceNotificationDetail:
    detail = notification_detail_from_dict(client.notification_detail(notification_id))
    bounded = detail.bounded
    snapshot = AceNotificationDetail(
        notification=detail.notification,
        bounded=bounded is not None,
        truncated=bool(bounded.truncated) if bounded is not None else False,
    )
    return notification_detail_with_shared_metadata(
        snapshot,
        provider_source="daemon",
        prefers_daemon=True,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=detail.snapshot.snapshot_id,
    )


def daemon_pending_actions(
    client: LocalDaemonClient,
) -> AceNotificationPendingActions:
    return pending_actions_from_daemon(
        notification_pending_actions_from_dict(client.notification_pending_actions())
    )


def pending_actions_from_daemon(
    read: NotificationPendingActionsRead,
) -> AceNotificationPendingActions:
    bounded = read.bounded
    return pending_actions_with_shared_metadata(
        AceNotificationPendingActions(
            store=read.store,
            actions=read.actions,
            bounded=bounded is not None,
            truncated=bool(bounded.truncated) if bounded is not None else False,
        ),
        provider_source="daemon",
        prefers_daemon=True,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=read.snapshot.snapshot_id,
    )


__all__ = [
    "daemon_notification_count_snapshot",
    "daemon_notification_detail",
    "daemon_notification_snapshot",
    "daemon_pending_actions",
    "daemon_unread_notification_page",
    "pending_actions_from_daemon",
]
