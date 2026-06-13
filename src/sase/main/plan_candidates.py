"""Visible pending plan-approval candidates shared by plan CLI commands."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sase.agent.status_buckets import status_bucket_for_values
from sase.notifications.agent_matching import notification_matches_any_agent
from sase.notifications.models import Notification
from sase.notifications.pending_actions import action_state_for_notification
from sase.notifications.sort import timestamp_sort_key
from sase.notifications.store import load_notifications

_LIVE_PLAN_AGENT_BUCKETS = frozenset({"Stopped", "Starting", "Running", "Waiting"})


def _available_plan_notifications() -> list[Notification]:
    """Return available, non-dismissed PlanApproval notifications newest-first."""
    notifications = [
        notification
        for notification in load_notifications(include_dismissed=False)
        if notification.action == "PlanApproval"
        and action_state_for_notification(notification) == "available"
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
    live_agents = tuple(agents) if agents is not None else _load_live_plan_agents()
    if not live_agents:
        return []
    return [
        notification
        for notification in notifications
        if notification_matches_any_agent(notification, live_agents)
    ]


def _load_live_plan_agents() -> tuple[Any, ...]:
    from sase.ace.tui.models.agent_loader import load_all_agents

    return tuple(
        agent for agent in load_all_agents() if _agent_is_live_plan_candidate(agent)
    )


def _agent_is_live_plan_candidate(agent: Any) -> bool:
    bucket = status_bucket_for_values(
        getattr(agent, "status", None),
        getattr(agent, "retried_as_timestamp", None),
    )
    return bucket in _LIVE_PLAN_AGENT_BUCKETS
