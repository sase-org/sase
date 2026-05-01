"""Python facade for the Rust notification-store bindings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.core.notification_store_wire import (
    NotificationStateUpdateWire,
    NotificationStoreSnapshotWire,
    NotificationUpdateOutcomeWire,
    notification_snapshot_from_dict,
    notification_store_wire_to_json_dict,
    notification_update_outcome_from_dict,
)
from sase.core.rust import require_rust_binding
from sase.notifications.models import Notification


# pyvision: tests/test_core_facade/test_notification_store.py
def read_notifications_snapshot(
    path: Path | str,
    include_dismissed: bool = False,
    expire_due_snoozes: bool = False,
) -> NotificationStoreSnapshotWire:
    """Read notification rows through ``sase_core_rs`` and rehydrate wires."""
    binding = require_rust_binding("read_notifications_snapshot")
    payload: dict[str, Any] = binding(str(path), include_dismissed, expire_due_snoozes)
    return notification_snapshot_from_dict(payload)


# pyvision: tests/test_core_facade/test_notification_store.py
def apply_notification_state_update(
    path: Path | str,
    update: NotificationStateUpdateWire | dict[str, Any],
) -> NotificationUpdateOutcomeWire:
    """Apply one state update through Rust and return the typed outcome."""
    binding = require_rust_binding("apply_notification_state_update")
    payload: dict[str, Any] = binding(
        str(path), notification_store_wire_to_json_dict(update)
    )
    return notification_update_outcome_from_dict(payload)


def append_notification(
    path: Path | str,
    notification: Notification | dict[str, Any],
) -> NotificationUpdateOutcomeWire:
    """Append one notification through Rust and return the typed outcome."""
    binding = require_rust_binding("append_notification")
    payload: dict[str, Any] = binding(
        str(path), notification_store_wire_to_json_dict(notification)
    )
    return notification_update_outcome_from_dict(payload)


def rewrite_notifications(
    path: Path | str,
    notifications: list[Notification] | tuple[Notification, ...] | list[dict[str, Any]],
) -> NotificationUpdateOutcomeWire:
    """Rewrite the store through Rust's lock/tempfile/rename path."""
    binding = require_rust_binding("rewrite_notifications")
    payload: dict[str, Any] = binding(
        str(path), notification_store_wire_to_json_dict(notifications)
    )
    return notification_update_outcome_from_dict(payload)


__all__ = [
    "NotificationStateUpdateWire",
    "NotificationStoreSnapshotWire",
    "NotificationUpdateOutcomeWire",
    "append_notification",
    "apply_notification_state_update",
    "read_notifications_snapshot",
    "rewrite_notifications",
]
