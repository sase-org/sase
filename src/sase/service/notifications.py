"""Durable service-proc failure notifications for the service host."""

from __future__ import annotations

import sys
from datetime import datetime
from uuid import uuid4

from sase.core.state_write_guard import best_effort_test_state_write_allowed
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import upsert_notification

_SENDER = "service"
_ICON = "!"
_COLOR = "#D14343"
_STATE_WRITE_CATEGORY = "service-notifications"


def _crash_loop_dedup_key(name: str, host_started_at: float, episode: int) -> str:
    """Return the episode-scoped dedup key for one crash-loop episode."""
    return f"service:{name}:crash-loop:{int(host_started_at)}:{int(episode)}"


def _give_up_dedup_key(name: str, host_started_at: float, episode: int) -> str:
    """Return the episode-scoped dedup key for one give-up parking."""
    return f"service:{name}:give-up:{int(host_started_at)}:{int(episode)}"


def _guarded_upsert(notification: Notification, *, plus_one_note: str) -> None:
    try:
        from sase.notifications.store import notifications_file_path

        path = notifications_file_path()
    except Exception as exc:  # noqa: BLE001 - notification must never break the host.
        print(f"sase service host notification error: {exc}", file=sys.stderr)
        return
    if not best_effort_test_state_write_allowed(path, category=_STATE_WRITE_CATEGORY):
        return
    try:
        upsert_notification(
            notification,
            plus_one_note=plus_one_note,
            plus_one_timestamp=notification.timestamp,
        )
    except Exception as exc:  # noqa: BLE001 - notification must never break the host.
        print(f"sase service host notification error: {exc}", file=sys.stderr)


def _timestamp() -> str:
    from sase.core.time import get_timezone

    return datetime.now(get_timezone()).isoformat()


def notify_service_crash_loop(
    *,
    name: str,
    reason: str,
    restarts: int,
    log_path: str | None,
    host_started_at: float,
    episode: int,
) -> None:
    """Upsert one durable row for a crash-loop episode (plus-one within it)."""
    notes = [
        f"Service proc {name!r} is crash-looping: {reason}",
        f"Restarts so far: {restarts}",
    ]
    if log_path:
        notes.append(f"Log: {log_path}")
    notification = Notification(
        id=str(uuid4()),
        timestamp=_timestamp(),
        sender=_SENDER,
        icon=_ICON,
        color=_COLOR,
        notes=notes,
        tags=normalize_notification_tags(["service", "proc", name, "error"]),
        dedup_key=_crash_loop_dedup_key(name, host_started_at, episode),
    )
    _guarded_upsert(notification, plus_one_note="Still crash-looping")


def notify_service_give_up(
    *,
    name: str,
    reason: str,
    restarts: int,
    log_path: str | None,
    host_started_at: float,
    episode: int,
) -> None:
    """Upsert one durable row for a parked given-up proc."""
    notes = [
        f"Service proc {name!r} gave up and stays down: {reason}",
        f"Restarts so far: {restarts}",
        f"Revive with: sase service proc start {name}",
    ]
    if log_path:
        notes.append(f"Log: {log_path}")
    notification = Notification(
        id=str(uuid4()),
        timestamp=_timestamp(),
        sender=_SENDER,
        icon=_ICON,
        color=_COLOR,
        notes=notes,
        tags=normalize_notification_tags(["service", "proc", name, "error"]),
        dedup_key=_give_up_dedup_key(name, host_started_at, episode),
    )
    _guarded_upsert(notification, plus_one_note="Still given up")


__all__ = [
    "notify_service_crash_loop",
    "notify_service_give_up",
]
