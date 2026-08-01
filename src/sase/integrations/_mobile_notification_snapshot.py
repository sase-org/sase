"""Snapshot projection for mobile notification gateway surfaces."""

from __future__ import annotations

from pathlib import Path

from sase.integrations._mobile_notification_models import (
    MobileNotificationBridgeCounts,
    MobileNotificationBridgeRow,
    MobileNotificationBridgeSnapshot,
)
from sase.integrations._mobile_notification_paths import normalize_home_path
from sase.notifications.models import (
    Notification,
    encode_notification_activity_cursor,
    notification_activity_sort_key,
    notification_is_newer_than_activity_cursor,
)
from sase.notifications.priority import is_error, is_priority
from sase.notifications.store import read_current_notification_snapshot


def read_mobile_notification_snapshot(
    *,
    unread_only: bool = False,
    include_dismissed: bool = False,
    include_silent: bool = False,
    limit: int | None = None,
    newer_than: str | None = None,
) -> MobileNotificationBridgeSnapshot:
    """Return the gateway's read-only host notification projection."""
    snapshot = read_current_notification_snapshot(include_dismissed=include_dismissed)
    rows = sorted(
        snapshot.notifications,
        key=notification_activity_sort_key,
        reverse=True,
    )
    if unread_only:
        rows = [row for row in rows if not row.read]
    if not include_silent:
        rows = [row for row in rows if not row.silent]
    if newer_than is not None:
        rows = [
            row
            for row in rows
            if notification_is_newer_than_activity_cursor(row, newer_than)
        ]
    if limit is not None:
        rows = rows[: max(0, limit)]

    return MobileNotificationBridgeSnapshot(
        rows=[_bridge_row(row) for row in rows],
        counts=MobileNotificationBridgeCounts(
            priority=int(snapshot.counts.priority),
            errors=int(snapshot.counts.errors),
            rest=int(snapshot.counts.rest),
            muted=int(snapshot.counts.muted),
        ),
        expired_ids=list(snapshot.expired_ids),
        next_high_water=(
            encode_notification_activity_cursor(rows[0]) if rows else None
        ),
    )


def resolve_mobile_notification_detail(
    notification_id: str,
) -> MobileNotificationBridgeRow | None:
    """Return one notification by exact id, including dismissed/silent rows."""
    snapshot = read_mobile_notification_snapshot(
        include_dismissed=True,
        include_silent=True,
    )
    return next((row for row in snapshot.rows if row.id == notification_id), None)


def _bridge_row(notification: Notification) -> MobileNotificationBridgeRow:
    from sase.notifications.pending_actions import action_state_for_notification

    return MobileNotificationBridgeRow(
        id=notification.id,
        timestamp=notification.timestamp,
        resurfaced_at=notification.resurfaced_at,
        sender=notification.sender,
        priority=is_priority(notification) or is_error(notification),
        icon=notification.icon,
        notes=list(notification.notes),
        display_files=[normalize_home_path(path) for path in notification.files],
        host_files=[str(Path(path).expanduser()) for path in notification.files],
        action=notification.action,
        action_state=action_state_for_notification(notification),
        display_action_data={
            key: normalize_home_path(value)
            for key, value in notification.action_data.items()
        },
        host_action_data={
            key: str(Path(value).expanduser())
            for key, value in notification.action_data.items()
        },
        read=notification.read,
        dismissed=notification.dismissed,
        silent=notification.silent,
        muted=notification.muted,
        snooze_until=notification.snooze_until,
    )
