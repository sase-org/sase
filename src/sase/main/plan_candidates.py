"""Visible pending plan-approval candidates shared by plan CLI commands."""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sase.notifications.agent_matching import notification_matches_any_agent
from sase.notifications.models import Notification
from sase.notifications.pending_actions import (
    action_state_for_notification,
    read_pending_action_store,
)
from sase.notifications.sort import timestamp_sort_key
from sase.notifications.store import load_notifications
from sase.plan_approval_actions import PLAN_APPROVAL_ACTIONS


def _available_plan_notifications(*, include_dismissed: bool) -> list[Notification]:
    """Return available PlanApproval notifications newest-first."""
    store = read_pending_action_store(include_legacy=True)
    now = time.time()
    notifications = [
        notification
        for notification in load_notifications(include_dismissed=include_dismissed)
        if notification.action in PLAN_APPROVAL_ACTIONS
        and action_state_for_notification(notification, now=now, store=store)
        == "available"
    ]
    notifications.sort(key=timestamp_sort_key, reverse=True)
    return notifications


def visible_pending_plan_notifications(
    *, agents: Sequence[Any] | None = None
) -> list[Notification]:
    """Return pending plan approvals decided by their gate, not the planner.

    Shell-backed gates (everything since the shell migration) are pending
    exactly when their gate shell is not terminal, even if the inbox row was
    dismissed. Legacy gates without a gate-shell record keep the previous
    non-dismissed, live-planner-row rule.
    """
    notifications = _available_plan_notifications(include_dismissed=True)
    if not notifications:
        return []
    if agents is not None:
        return _notifications_matching_agents(notifications, tuple(agents))
    return [
        notification
        for notification in notifications
        if _notification_is_gate_visible(notification)
    ]


def _notification_is_gate_visible(notification: Notification) -> bool:
    """Return whether one available plan notification still awaits a decision."""
    gate_id = _gate_id_for_notification(notification)
    if gate_id is None:
        return _legacy_notification_visible(notification)
    try:
        from sase.gate_shell.store import find_gate_shell_by_gate_id
    except Exception:
        return _legacy_notification_visible(notification)
    try:
        record = find_gate_shell_by_gate_id(None, gate_id)
    except Exception:
        return _legacy_notification_visible(notification)
    if record is None:
        # No gate-shell record: a legacy gate. Dismissed rows stay hidden
        # and visibility falls back to the live-planner-row rule.
        if notification.dismissed:
            return False
        return _legacy_notification_visible(notification)
    return not record.is_terminal


def _gate_id_for_notification(notification: Notification) -> str | None:
    """Return the gate id owning *notification*, if one is recorded."""
    request_id = notification.action_data.get("request_id")
    if request_id and request_id.strip():
        return request_id.strip()
    for key in ("bundle_path", "response_dir"):
        raw = notification.action_data.get(key)
        if raw and raw.strip():
            return Path(raw.strip()).expanduser().name or None
    return None


def _legacy_notification_visible(notification: Notification) -> bool:
    """Apply the pre-shell-migration live-planner-row rule to one row."""
    if notification.dismissed:
        return False
    exact_agents = _load_live_plan_agents_for_notifications((notification,))
    visible = _notifications_matching_agents((notification,), exact_agents)
    if visible:
        return True
    if _notification_has_agent_timestamp(notification):
        return False
    broad_agents = _load_live_plan_agents()
    if not broad_agents:
        return False
    return bool(_notifications_matching_agents((notification,), broad_agents))


def _load_live_plan_agents() -> tuple[Any, ...]:
    from sase.ace.tui.models.agent_loader import load_live_plan_agents

    return tuple(load_live_plan_agents())


def _load_live_plan_agents_for_notifications(
    notifications: Sequence[Notification],
) -> tuple[Any, ...]:
    timestamps = [
        timestamp
        for notification in notifications
        for timestamp in (
            notification.action_data.get("agent_timestamp"),
            notification.action_data.get("agent_root_timestamp"),
        )
        if timestamp
    ]
    if not timestamps:
        return ()

    from sase.ace.tui.models.agent_loader import load_live_plan_agents_for_timestamps

    return tuple(load_live_plan_agents_for_timestamps(timestamps))


def _notifications_matching_agents(
    notifications: Sequence[Notification],
    agents: tuple[Any, ...],
) -> list[Notification]:
    if not agents:
        return []
    return [
        notification
        for notification in notifications
        if notification_matches_any_agent(notification, agents)
    ]


def _notification_has_agent_timestamp(notification: Notification) -> bool:
    return bool(
        notification.action_data.get("agent_timestamp")
        or notification.action_data.get("agent_root_timestamp")
    )
