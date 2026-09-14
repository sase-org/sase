"""Notification dismissal shared by decision acceptance and execution.

Both the fast decision-acceptance path and the (now redundant, idempotent)
post-execution settlement call this to mark one gate's notification handled
and hide its inbox row. Runs for every terminal transition of every gate
kind, from every client, so no surface has to remember to dismiss the row
itself.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

log = logging.getLogger(__name__)


def settle_gate_notification(
    envelope: Mapping[str, Any],
    response: Mapping[str, Any],
    *,
    source: str,
    action: str | None = None,
) -> None:
    notification_id = envelope.get("notification_id")
    if not isinstance(notification_id, str) or not notification_id:
        return
    from sase.notifications.pending_actions import mark_already_handled

    raw_selected = response.get("selected_option_ids")
    selected = (
        [str(option_id) for option_id in raw_selected]
        if isinstance(raw_selected, list)
        else []
    )
    mark_already_handled(
        notification_id,
        source=source,
        action=action or "+".join(selected) or "resolved",
    )
    _dismiss_gate_notification_best_effort(notification_id)


def _dismiss_gate_notification_best_effort(notification_id: str) -> None:
    """Hide a settled gate row without ever failing a persisted response."""
    try:
        from sase.notifications.store import mark_dismissed

        mark_dismissed(notification_id)
    except Exception:
        log.warning("Failed to dismiss notification for settled gate", exc_info=True)


__all__ = ["settle_gate_notification"]
