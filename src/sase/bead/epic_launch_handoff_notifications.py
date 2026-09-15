"""Notification identity helpers for epic launch completion handoffs."""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from sase.bead.epic_launch_handoff_model import (
    CompletionNotificationPayload,
    DeferredCompletion,
)


def completion_notification_id(
    deferred: DeferredCompletion,
    *,
    kind: str,
) -> str:
    return deferred.notification_id or stable_notification_id(
        deferred.key,
        deferred.payload,
        kind=kind,
    )


def stable_notification_id(
    key: str,
    payload: CompletionNotificationPayload,
    *,
    kind: str,
) -> str:
    identity = {
        "kind": f"epic-completion-{kind}",
        "key": key,
        "payload": payload.to_dict(),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return str(uuid5(NAMESPACE_URL, f"sase:{encoded}"))


def notification_is_durable(notification_id: str) -> bool:
    try:
        from sase.notifications.store import load_notifications

        return any(
            notification.id == notification_id
            for notification in load_notifications(include_dismissed=True)
        )
    except Exception:
        return False
