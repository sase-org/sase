"""Shared helpers for notification modal response files."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


def write_workflow_action_response(
    response_path: Path,
    response_data: dict[str, object],
    *,
    action_kind: str,
    notification_id: str,
    default: Callable[[Any], Any] | None = None,
) -> None:
    with response_path.open("x", encoding="utf-8") as f:
        json.dump(response_data, f, indent=2, default=default)
        f.write("\n")
    _mark_plan_action_handled_best_effort(action_kind, notification_id, response_data)


def _mark_plan_action_handled_best_effort(
    action_kind: str,
    notification_id: str,
    response_data: dict[str, object],
) -> None:
    """Record a TUI-resolved plan approval in the shared pending-action store.

    Lets transports (e.g. Telegram) dismiss any inline keyboard they sent for a
    plan the user approved/rejected from the TUI. Best-effort: a failure must
    never block the latency-sensitive response write that runners watch for.
    """
    if action_kind != "plan_approval":
        return
    try:
        from sase.notifications.pending_actions import mark_already_handled

        action = response_data.get("action")
        mark_already_handled(
            notification_id,
            source="tui",
            action=action if isinstance(action, str) else None,
        )
    except Exception:
        pass
