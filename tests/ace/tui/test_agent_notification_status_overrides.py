"""Tests for Agents-tab notification status routing."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._notification_navigation import (
    find_agent_for_notification,
)
from sase.ace.tui.actions.agents._notifications import AgentNotificationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.notifications import Notification


class _NotificationApp(AgentNotificationMixin):
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}

    def _auto_dismiss_external_plan_response(self, notification: Notification) -> bool:
        return False


def _notification(
    *,
    action: str = "PlanApproval",
    cl_name: str = "oo",
    agent_timestamp: str = "20260512094333",
    agent_root_timestamp: str = "20260512090000",
) -> Notification:
    return Notification(
        id="n1",
        timestamp="2026-05-12T09:43:33",
        sender="plan" if action == "PlanApproval" else "question",
        action=action,
        action_data={
            "agent_cl_name": cl_name,
            "agent_timestamp": agent_timestamp,
            "agent_root_timestamp": agent_root_timestamp,
            "response_dir": "/tmp/response",
            "session_id": "session",
        },
    )


def test_plan_approval_root_timestamp_sets_parent_planning_override() -> None:
    """A follow-up plan notification can target the visible parent row."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="oo",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 12, 9, 0, 0),
        raw_suffix="20260512090000",
        role_suffix=".plan",
    )
    workflow_step = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 12, 9, 43, 33),
        raw_suffix="20260512094333",
        parent_timestamp="20260512090000",
        parent_workflow="oo.plan",
    )
    app = _NotificationApp([parent, workflow_step])

    app._apply_notification_status_overrides([_notification()])

    assert app._agent_status_overrides[parent.identity] == "PLANNING"
    assert workflow_step.identity not in app._agent_status_overrides


def test_find_agent_for_notification_matches_root_timestamp() -> None:
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="oo",
        project_file="/tmp/test.sase",
        status="PLANNING",
        start_time=datetime(2026, 5, 12, 9, 0, 0),
        raw_suffix="20260512090000",
        role_suffix=".plan",
    )
    app = _NotificationApp([parent])

    assert find_agent_for_notification(app, _notification()) is parent


def test_user_question_root_timestamp_sets_parent_question_override() -> None:
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="oo",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 12, 9, 0, 0),
        raw_suffix="20260512090000",
        role_suffix=".plan",
    )
    app = _NotificationApp([parent])

    app._apply_notification_status_overrides(
        [_notification(action="UserQuestion", agent_timestamp="20260512094500")]
    )

    assert app._agent_status_overrides[parent.identity] == "QUESTION"
    assert app._agent_pre_question_status[parent.identity] == "RUNNING"
