"""Visible pending plan-approval candidates shared by plan CLI commands."""

from __future__ import annotations

import time
from collections.abc import Sequence
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


def _available_plan_notifications() -> list[Notification]:
    """Return available, non-dismissed PlanApproval notifications newest-first."""
    store = read_pending_action_store(include_legacy=True)
    now = time.time()
    notifications = [
        notification
        for notification in load_notifications(include_dismissed=False)
        if notification.action in PLAN_APPROVAL_ACTIONS
        and action_state_for_notification(notification, now=now, store=store)
        == "available"
    ]
    notifications.sort(key=timestamp_sort_key, reverse=True)
    return notifications


def visible_pending_plan_notifications(
    *, agents: Sequence[Any] | None = None
) -> list[Notification]:
    """Return pending plan approvals represented by a live Agents-tab row."""
    notifications = _available_plan_notifications()
    if not notifications:
        return []
    if agents is not None:
        return _notifications_matching_agents(notifications, tuple(agents))

    exact_agents = _load_live_plan_agents_for_notifications(notifications)
    visible = _notifications_matching_agents(notifications, exact_agents)
    if len(visible) == len(notifications):
        return visible

    unmatched = [
        notification for notification in notifications if notification not in visible
    ]
    if all(
        _notification_has_agent_timestamp(notification) for notification in unmatched
    ):
        return visible

    broad_agents = _load_live_plan_agents()
    if not broad_agents:
        return visible
    return _notifications_matching_agents(notifications, (*exact_agents, *broad_agents))


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
