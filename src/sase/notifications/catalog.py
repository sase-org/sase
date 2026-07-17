"""Read-only notification catalog helpers for CLI and skill surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.notifications.models import (
    Notification,
    format_relative_time,
    normalize_notification_tags,
)
from sase.notifications.priority import is_error, is_priority
from sase.notifications.sort import timestamp_sort_key
from sase.notifications.store import load_notifications


@dataclass(frozen=True)
class NotificationInfo:
    """Stable read projection for one notification."""

    id: str
    timestamp: str
    age: str
    sender: str
    icon: str | None
    priority: bool
    notes: list[str]
    files: list[str]
    tags: list[str]
    action: str | None
    action_data: dict[str, str]
    read: bool
    dismissed: bool
    silent: bool
    muted: bool
    snooze_until: str | None


def _normalize_home_path(value: str) -> str:
    home = str(Path.home())
    if value == home:
        return "~"
    if value.startswith(f"{home}/"):
        return f"~/{value[len(home) + 1 :]}"
    return value


def _notification_info(notification: Notification) -> NotificationInfo:
    return NotificationInfo(
        id=notification.id,
        timestamp=notification.timestamp,
        age=format_relative_time(notification.timestamp),
        sender=notification.sender,
        icon=notification.icon,
        priority=is_priority(notification) or is_error(notification),
        notes=list(notification.notes),
        files=[_normalize_home_path(path) for path in notification.files],
        tags=list(notification.tags),
        action=notification.action,
        action_data={
            key: _normalize_home_path(value)
            for key, value in notification.action_data.items()
        },
        read=notification.read,
        dismissed=notification.dismissed,
        silent=notification.silent,
        muted=notification.muted,
        snooze_until=notification.snooze_until,
    )


def _query_values(notification: Notification) -> list[str]:
    values = [
        notification.id,
        notification.sender,
        *(notification.notes or []),
        *(notification.files or []),
        *(notification.tags or []),
    ]
    if notification.icon:
        values.append(notification.icon)
    if notification.action:
        values.append(notification.action)
    values.extend(str(value) for value in notification.action_data.values())
    return values


def _matches_query(notification: Notification, query: str | None) -> bool:
    if not query:
        return True
    needle = query.casefold()
    return any(needle in value.casefold() for value in _query_values(notification))


def list_notification_infos(
    *,
    limit: int | None = None,
    query: str | None = None,
    sender: str | None = None,
    unread: bool = False,
    include_dismissed: bool = False,
    include_silent: bool = True,
    tag: str | None = None,
) -> list[NotificationInfo]:
    """Return filtered notification info rows, newest first."""
    notifications = load_notifications(include_dismissed=include_dismissed)
    rows = sorted(notifications, key=timestamp_sort_key, reverse=True)

    if sender is not None:
        rows = [notification for notification in rows if notification.sender == sender]
    if unread:
        rows = [notification for notification in rows if not notification.read]
    if not include_silent:
        rows = [notification for notification in rows if not notification.silent]
    if tag is not None:
        normalized_tags = normalize_notification_tags(tag)
        if normalized_tags:
            target_tag = normalized_tags[0]
            rows = [
                notification for notification in rows if target_tag in notification.tags
            ]
        else:
            rows = []
    if query:
        rows = [
            notification for notification in rows if _matches_query(notification, query)
        ]
    if limit is not None:
        rows = rows[: max(0, limit)]

    return [_notification_info(notification) for notification in rows]


def resolve_notification_ref(notification_id: str) -> NotificationInfo | None:
    """Return one notification by exact id, including dismissed rows."""
    for notification in load_notifications(include_dismissed=True):
        if notification.id == notification_id:
            return _notification_info(notification)
    return None


def notification_info_to_json(info: NotificationInfo) -> dict[str, object]:
    """Project a notification info row to the stable JSON key order."""
    return {
        "id": info.id,
        "timestamp": info.timestamp,
        "age": info.age,
        "sender": info.sender,
        "icon": info.icon,
        "priority": info.priority,
        "notes": info.notes,
        "files": info.files,
        "tags": info.tags,
        "action": info.action,
        "action_data": info.action_data,
        "read": info.read,
        "dismissed": info.dismissed,
        "silent": info.silent,
        "muted": info.muted,
        "snooze_until": info.snooze_until,
    }


__all__ = [
    "NotificationInfo",
    "list_notification_infos",
    "notification_info_to_json",
    "resolve_notification_ref",
]
