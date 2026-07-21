"""Tests for Agents-tab notification status routing."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.tui.actions.agents._notification_navigation import (
    find_agent_for_notification,
)
from sase.ace.tui.actions.agents._notification_status_overrides import (
    AgentNotificationStatusMixin,
)
from sase.ace.tui.actions.agents._notifications import AgentNotificationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.notifications import Notification


class _NotificationApp(AgentNotificationMixin):
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents
        self._agents_with_children = agents
        self.refilter_calls = 0
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}

    def _auto_dismiss_external_plan_response(self, notification: Notification) -> bool:
        return False

    def _refilter_agents(self) -> None:
        self.refilter_calls += 1


class _ExternalPlanResponseApp(AgentNotificationStatusMixin):
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents
        self._agents_with_children = agents
        self.refilter_calls = 0
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}
        self.notification_count_refreshes = 0

    def _refilter_agents(self) -> None:
        self.refilter_calls += 1

    def _refresh_notification_count(self) -> None:
        self.notification_count_refreshes += 1


def _notification(
    *,
    action: str = "PlanApproval",
    cl_name: str = "oo",
    agent_name: str | None = None,
    agent_timestamp: str = "20260512094333",
    agent_root_timestamp: str = "20260512090000",
    response_dir: str = "/tmp/response",
    request_id: str | None = None,
) -> Notification:
    action_data = {
        "agent_cl_name": cl_name,
        "agent_timestamp": agent_timestamp,
        "agent_root_timestamp": agent_root_timestamp,
        "response_dir": response_dir,
        "session_id": "session",
    }
    if agent_name:
        action_data["agent_name"] = agent_name
    if request_id:
        action_data["request_id"] = request_id
    return Notification(
        id="n1",
        timestamp="2026-05-12T09:43:33",
        sender="plan" if action == "PlanApproval" else "question",
        action=action,
        action_data=action_data,
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

    auto_dismissed_ids = app._apply_notification_status_overrides([_notification()])

    assert auto_dismissed_ids == set()
    assert app._agent_status_overrides[parent.identity] == "PLAN"
    assert workflow_step.identity not in app._agent_status_overrides
    assert app.refilter_calls == 1


@pytest.mark.parametrize(
    ("action", "kind", "expected_status"),
    [("PlanApproval", "plan", "TALE"), ("EpicApproval", "epic_plan", "EPIC")],
)
def test_neutral_plan_notification_sets_tiered_status_without_plan_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    kind: str,
    expected_status: str,
) -> None:
    from sase.notification_gates import paths

    request_id = "request-1"
    request_dir = tmp_path / kind / request_id
    request_dir.mkdir(parents=True)
    (request_dir / "request.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(paths, "INTERACTION_REQUESTS_DIR", tmp_path)
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

    auto_dismissed_ids = app._apply_notification_status_overrides(
        [_notification(action=action, request_id=request_id)]
    )

    assert auto_dismissed_ids == set()
    assert app._agent_status_overrides[parent.identity] == expected_status


def test_find_agent_for_notification_matches_root_timestamp() -> None:
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="oo",
        project_file="/tmp/test.sase",
        status="PLAN",
        start_time=datetime(2026, 5, 12, 9, 0, 0),
        raw_suffix="20260512090000",
        role_suffix=".plan",
    )
    app = _NotificationApp([parent])

    assert find_agent_for_notification(app, _notification()) is parent


def test_find_agent_for_notification_matches_agent_name_timestamp() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="different-cl",
        project_file="/tmp/test.sase",
        status="PLAN",
        start_time=datetime(2026, 5, 12, 9, 43, 33),
        raw_suffix="20260512094333",
        agent_name="planner",
    )
    app = _NotificationApp([agent])

    assert (
        find_agent_for_notification(
            app,
            _notification(
                cl_name="oo",
                agent_name="planner",
                agent_root_timestamp="20260512090000",
            ),
        )
        is agent
    )


def test_user_question_sets_question_override_on_root_and_child() -> None:
    """A UserQuestion referencing both timestamps marks the root AND the child.

    This keeps the ask path symmetric with the answer path: both the visible
    root/aggregate row and the child that actually asked receive QUESTION, so
    answering can clear both.
    """
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="oo",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 12, 9, 0, 0),
        raw_suffix="20260512090000",
        role_suffix=".plan",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="oo",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 12, 9, 43, 33),
        raw_suffix="20260512094333",
        parent_timestamp="20260512090000",
        parent_workflow="oo.plan",
    )
    app = _NotificationApp([parent, child])

    auto_dismissed_ids = app._apply_notification_status_overrides(
        [_notification(action="UserQuestion")]
    )

    assert auto_dismissed_ids == set()
    assert app._agent_status_overrides[parent.identity] == "QUESTION"
    assert app._agent_status_overrides[child.identity] == "QUESTION"
    assert app._agent_pre_question_status[parent.identity] == "RUNNING"
    assert app._agent_pre_question_status[child.identity] == "RUNNING"


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

    auto_dismissed_ids = app._apply_notification_status_overrides(
        [_notification(action="UserQuestion", agent_timestamp="20260512094500")]
    )

    assert auto_dismissed_ids == set()
    assert app._agent_status_overrides[parent.identity] == "QUESTION"
    assert app._agent_pre_question_status[parent.identity] == "RUNNING"
    assert app.refilter_calls == 1


@pytest.mark.parametrize(
    ("notification_action", "response", "expected_status", "expected_action"),
    [
        (
            "PlanApproval",
            {"action": "approve", "commit_plan": False, "run_coder": True},
            "PLAN APPROVED",
            "approve",
        ),
        (
            "PlanApproval",
            {"action": "approve", "commit_plan": True, "run_coder": True},
            "TALE APPROVED",
            "tale",
        ),
        (
            "EpicApproval",
            {"action": "epic", "commit_plan": True, "run_coder": True},
            "EPIC APPROVED",
            "epic",
        ),
        (
            "PlanApproval",
            {"action": "approve", "commit_plan": True, "run_coder": False},
            "PLAN COMMITTED",
            "commit",
        ),
    ],
)
def test_external_plan_response_uses_canonical_action_status_and_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    notification_action: str,
    response: dict[str, object],
    expected_status: str,
    expected_action: str,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    (response_dir / "plan_response.json").write_text(
        json.dumps(response), encoding="utf-8"
    )
    dismissed: list[str] = []
    monkeypatch.setattr(
        "sase.notifications.mark_dismissed",
        lambda notification_id: dismissed.append(notification_id),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_plan_persistence."
        "update_agent_artifact_index_for_marker_mutation",
        lambda artifacts_dir: None,
    )

    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="oo",
        project_file="/tmp/test.sase",
        status="PLAN",
        start_time=datetime(2026, 5, 12, 9, 0, 0),
        raw_suffix="20260512090000",
        role_suffix=".plan",
        artifacts_dir=str(artifacts_dir),
    )
    app = _ExternalPlanResponseApp([agent])

    auto_dismissed_ids = app._apply_notification_status_overrides(
        [
            _notification(
                action=notification_action,
                response_dir=str(response_dir),
            )
        ]
    )

    assert auto_dismissed_ids == {"n1"}
    assert dismissed == ["n1"]
    assert app._agent_status_overrides[agent.identity] == expected_status
    assert app.refilter_calls == 1
    assert app.notification_count_refreshes == 1
    assert json.loads((artifacts_dir / "agent_meta.json").read_text()) == {
        "plan_approved": True,
        "plan_action": expected_action,
    }
