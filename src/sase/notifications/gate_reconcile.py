"""Self-healing dismissal for gate rows whose bundle is already terminal."""

from __future__ import annotations

from collections.abc import Iterable

from sase.notifications.models import Notification


def reconcile_terminal_gate_notifications(
    notifications: Iterable[Notification],
) -> tuple[str, ...]:
    """Dismiss live gate rows whose bundle already reached a terminal state.

    Repairs rows left behind by a client that answered a gate without
    dismissing it (legacy bundles, external response writers, or any row
    created before dismissal moved into the shared executor).
    """
    from sase.notification_gates.registry import PRIVILEGED_GATE_ACTIONS
    from sase.notifications.pending_actions import gate_notification_is_terminal
    from sase.notifications.store import mark_many_dismissed

    stale = tuple(
        notification.id
        for notification in notifications
        if not notification.dismissed
        and notification.action in PRIVILEGED_GATE_ACTIONS
        and gate_notification_is_terminal(notification)
    )
    if stale:
        mark_many_dismissed(stale)
    return stale


__all__ = ["reconcile_terminal_gate_notifications"]
