"""Read-only host bridge for mobile notification gateway surfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sase.core.time import get_timezone
from sase.notifications.models import Notification
from sase.notifications.priority import is_priority
from sase.notifications.store import read_notification_snapshot


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class MobileNotificationBridgeCounts:
    priority: int = 0
    rest: int = 0
    muted: int = 0


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class MobileNotificationBridgeRow:
    id: str
    timestamp: str
    sender: str
    priority: bool
    notes: list[str] = field(default_factory=list)
    display_files: list[str] = field(default_factory=list)
    host_files: list[str] = field(default_factory=list)
    action: str | None = None
    display_action_data: dict[str, str] = field(default_factory=dict)
    host_action_data: dict[str, str] = field(default_factory=dict)
    read: bool = False
    dismissed: bool = False
    silent: bool = False
    muted: bool = False
    snooze_until: str | None = None


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class MobileNotificationBridgeSnapshot:
    rows: list[MobileNotificationBridgeRow] = field(default_factory=list)
    counts: MobileNotificationBridgeCounts = field(
        default_factory=MobileNotificationBridgeCounts
    )
    expired_ids: list[str] = field(default_factory=list)


# pyvision: public_api_methods.txt
def read_mobile_notification_snapshot(
    *,
    unread_only: bool = False,
    include_dismissed: bool = False,
    include_silent: bool = False,
    limit: int | None = None,
    newer_than: str | None = None,
) -> MobileNotificationBridgeSnapshot:
    """Return the gateway's read-only host notification projection."""
    snapshot = read_notification_snapshot(
        include_dismissed=include_dismissed,
        expire_due_snoozes=True,
    )
    rows = sorted(snapshot.notifications, key=_timestamp_sort_key, reverse=True)
    if unread_only:
        rows = [row for row in rows if not row.read]
    if not include_silent:
        rows = [row for row in rows if not row.silent]
    if newer_than is not None:
        rows = [
            row
            for row in rows
            if _timestamp_sort_key(row) > _parse_timestamp_sort_key(newer_than)
        ]
    if limit is not None:
        rows = rows[: max(0, limit)]

    return MobileNotificationBridgeSnapshot(
        rows=[_bridge_row(row) for row in rows],
        counts=MobileNotificationBridgeCounts(
            priority=int(snapshot.counts.priority),
            rest=int(snapshot.counts.rest),
            muted=int(snapshot.counts.muted),
        ),
        expired_ids=list(snapshot.expired_ids),
    )


# pyvision: public_api_methods.txt
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
    return MobileNotificationBridgeRow(
        id=notification.id,
        timestamp=notification.timestamp,
        sender=notification.sender,
        priority=is_priority(notification),
        notes=list(notification.notes),
        display_files=[_normalize_home_path(path) for path in notification.files],
        host_files=[str(Path(path).expanduser()) for path in notification.files],
        action=notification.action,
        display_action_data={
            key: _normalize_home_path(value)
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


def _normalize_home_path(value: str) -> str:
    expanded = str(Path(value).expanduser())
    home = str(Path.home())
    if expanded == home:
        return "~"
    if expanded.startswith(f"{home}/"):
        return f"~/{expanded[len(home) + 1 :]}"
    return value


def _timestamp_sort_key(notification: Notification) -> datetime:
    return _parse_timestamp_sort_key(notification.timestamp)


def _parse_timestamp_sort_key(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=get_timezone())
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=get_timezone())
    return timestamp


__all__ = [
    "MobileNotificationBridgeCounts",
    "MobileNotificationBridgeRow",
    "MobileNotificationBridgeSnapshot",
    "read_mobile_notification_snapshot",
    "resolve_mobile_notification_detail",
]
