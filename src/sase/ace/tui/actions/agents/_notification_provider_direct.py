"""Direct fallback ACE notification provider loaders."""

from __future__ import annotations

from typing import Any

from ._notification_provider_metadata import (
    count_value,
    counts_mapping,
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


def notification_snapshot_from_direct(snapshot: Any) -> AceNotificationSnapshot:
    counts = getattr(snapshot, "counts", AceNotificationCounts())
    notifications = list(getattr(snapshot, "notifications", []))
    expired_ids = list(getattr(snapshot, "expired_ids", []))
    next_snooze_deadline = getattr(snapshot, "next_snooze_deadline", None)
    normalized = AceNotificationSnapshot(
        notifications=notifications,
        counts=AceNotificationCounts(
            priority=count_value(counts, "priority"),
            errors=count_value(counts, "errors"),
            rest=count_value(counts, "rest"),
            muted=count_value(counts, "muted"),
        ),
        expired_ids=expired_ids,
        next_snooze_deadline=next_snooze_deadline,
    )
    return notification_snapshot_with_shared_metadata(
        normalized,
        provider_source="direct",
        prefers_daemon=False,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=None,
        page_count=1,
    )


def direct_notification_count_snapshot() -> AceNotificationCountSnapshot:
    from sase.notifications import read_notification_snapshot

    snapshot = notification_snapshot_from_direct(read_notification_snapshot())
    return notification_count_snapshot_from_counts(
        counts_mapping(snapshot.counts),
        provider_source="direct",
        prefers_daemon=False,
        fallback_reason=None,
        fallback_message=None,
    )


def direct_unread_notification_page(
    *,
    include_dismissed: bool,
    limit: int,
) -> AceNotificationPage:
    from sase.notifications import read_notification_snapshot
    from sase.notifications.gate_reconcile import (
        reconcile_terminal_gate_notifications,
    )

    snapshot = notification_snapshot_from_direct(
        read_notification_snapshot(include_dismissed=include_dismissed)
    )
    if reconcile_terminal_gate_notifications(snapshot.notifications):
        snapshot = notification_snapshot_from_direct(
            read_notification_snapshot(include_dismissed=include_dismissed)
        )
    unread = [
        n
        for n in snapshot.notifications
        if not n.read and not n.silent and (include_dismissed or not n.dismissed)
    ][: max(0, limit)]
    page = AceNotificationPage(
        notifications=unread,
        counts=AceNotificationCounts(
            priority=snapshot.counts.priority,
            errors=snapshot.counts.errors,
            rest=snapshot.counts.rest,
            muted=snapshot.counts.muted,
        ),
    )
    return notification_page_with_shared_metadata(
        page,
        provider_source="direct",
        prefers_daemon=False,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=None,
        page_count=1,
    )


def direct_notification_detail(notification_id: str) -> AceNotificationDetail:
    from sase.notifications import load_notifications

    notification = next(
        (
            notification
            for notification in load_notifications(include_dismissed=True)
            if notification.id == notification_id
        ),
        None,
    )
    detail = AceNotificationDetail(notification=notification)
    return notification_detail_with_shared_metadata(
        detail,
        provider_source="direct",
        prefers_daemon=False,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=None,
    )


def direct_pending_actions() -> AceNotificationPendingActions:
    from sase.notifications import pending_actions

    store = pending_actions.read_pending_action_store(include_legacy=True)
    actions = [
        dict(action)
        for action in store.get("actions", {}).values()
        if isinstance(action, dict)
    ]
    actions.sort(key=lambda action: str(action.get("prefix", "")))
    return pending_actions_with_shared_metadata(
        AceNotificationPendingActions(store=store, actions=actions),
        provider_source="direct",
        prefers_daemon=False,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=None,
    )


__all__ = [
    "direct_notification_count_snapshot",
    "direct_notification_detail",
    "direct_pending_actions",
    "direct_unread_notification_page",
    "notification_snapshot_from_direct",
]
