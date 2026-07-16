"""Tests for initiating the single-agent kill flow."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.actions.agents import AgentsMixin
from sase.ace.tui.models.agent import Agent, AgentType

from tests._agent_kill_single_helpers import cleanup_plan


class _ActionApp(AgentsMixin):
    def __init__(self, agent: Agent | list[Agent], *, current_idx: int = 0) -> None:
        agents = list(agent) if isinstance(agent, list) else [agent]
        self.current_tab = "agents"
        self.current_idx = current_idx
        self._agents = agents
        self._agents_with_children = list(agents)
        self._marked_agents = set()
        self._current_group_key = None
        self._notifications: list[tuple[str, str]] = []
        self.pushed: list[tuple[object, object]] = []

    def notify(self, msg: str, severity: str = "information") -> None:
        self._notifications.append((msg, severity))

    def push_screen(self, modal: object, callback: object = None) -> None:
        self.pushed.append((modal, callback))

    def _get_selected_agent(self) -> Agent | None:
        return self._agents[self.current_idx] if self._agents else None


def test_action_kill_single_running_uses_cleanup_planner_before_confirm() -> None:
    from sase.core.agent_cleanup_wire import (
        CLEANUP_MODE_KILL_AND_DISMISS,
        CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
    )

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=12345,
        raw_suffix="run-12345",
    )
    app = _ActionApp(agent)
    plan = cleanup_plan(agent, action="kill")

    with (
        patch(
            "sase.core.agent_cleanup_facade.plan_agent_cleanup", return_value=plan
        ) as mock_plan,
        patch.object(app, "_do_kill_agent") as mock_do_kill,
    ):
        app.action_kill_agent()
        assert app.pushed
        app.pushed[0][1](True)  # type: ignore[index,operator]

    _, request = mock_plan.call_args.args
    assert request.scope == CLEANUP_SCOPE_EXPLICIT_IDENTITIES
    assert request.mode == CLEANUP_MODE_KILL_AND_DISMISS
    assert request.identities[0].raw_suffix == agent.raw_suffix
    assert request.include_pidless_as_dismissable is True
    mock_do_kill.assert_called_once_with(agent, plan)


def test_action_kill_single_done_uses_planner_backed_dismiss() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="done_feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=None,
        workflow=None,
        pid=None,
        raw_suffix="done-12345",
    )
    app = _ActionApp(agent)
    plan = cleanup_plan(agent, action="dismiss")

    with (
        patch("sase.core.agent_cleanup_facade.plan_agent_cleanup", return_value=plan),
        patch.object(app, "_dismiss_planned_agent") as mock_dismiss,
    ):
        app.action_kill_agent()

    mock_dismiss.assert_called_once_with(agent, plan)
    assert app.pushed == []


def test_action_kill_single_pidless_running_is_planned_as_dismissable() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="pidless_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=None,
        raw_suffix="pidless-12345",
    )
    app = _ActionApp(agent)
    plan = cleanup_plan(agent, action="dismiss")

    with (
        patch(
            "sase.core.agent_cleanup_facade.plan_agent_cleanup", return_value=plan
        ) as mock_plan,
        patch.object(app, "_dismiss_planned_agent") as mock_dismiss,
    ):
        app.action_kill_agent()

    _, request = mock_plan.call_args.args
    assert request.include_pidless_as_dismissable is True
    mock_dismiss.assert_called_once_with(agent, plan)


def test_action_kill_running_child_opens_confirmation_for_child() -> None:
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="parent_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=111,
        raw_suffix="parent-12345",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="child_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=222,
        raw_suffix="child-12345",
        parent_timestamp="parent-12345",
    )
    app = _ActionApp([parent, child], current_idx=1)
    plan = cleanup_plan(child, action="kill")

    with (
        patch("sase.core.agent_cleanup_facade.plan_agent_cleanup", return_value=plan),
        patch.object(app, "_do_kill_agent") as mock_do_kill,
    ):
        app.action_kill_agent()
        assert app.pushed
        app.pushed[0][1](True)  # type: ignore[index,operator]

    mock_do_kill.assert_called_once_with(child, plan)


def test_action_kill_completed_child_dismisses_child() -> None:
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="parent_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=111,
        raw_suffix="parent-12345",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="child_feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=None,
        workflow=None,
        pid=None,
        raw_suffix="child-12345",
        parent_timestamp="parent-12345",
    )
    app = _ActionApp([parent, child], current_idx=1)
    plan = cleanup_plan(child, action="dismiss")

    with (
        patch("sase.core.agent_cleanup_facade.plan_agent_cleanup", return_value=plan),
        patch.object(app, "_dismiss_planned_agent") as mock_dismiss,
    ):
        app.action_kill_agent()

    mock_dismiss.assert_called_once_with(child, plan)
    assert app.pushed == []


def test_no_focused_cleanup_action_prefers_focused_skip_reason() -> None:
    from sase.core.agent_cleanup_wire import (
        AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        SKIPPED_NOT_IN_SCOPE,
        SKIPPED_NOT_KILLABLE,
        AgentCleanupIdentityWire,
        AgentCleanupPlanWire,
        AgentCleanupSkippedItemWire,
    )

    other = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="other_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=None,
        raw_suffix="other-12345",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="child_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=None,
        raw_suffix="child-12345",
        parent_timestamp="parent-12345",
    )
    app = _ActionApp([other, child], current_idx=1)
    plan = AgentCleanupPlanWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        skipped_items=(
            AgentCleanupSkippedItemWire(
                identity=AgentCleanupIdentityWire(
                    agent_type=other.agent_type.value,
                    cl_name=other.cl_name,
                    raw_suffix=other.raw_suffix,
                ),
                reason=SKIPPED_NOT_IN_SCOPE,
            ),
            AgentCleanupSkippedItemWire(
                identity=AgentCleanupIdentityWire(
                    agent_type=child.agent_type.value,
                    cl_name=child.cl_name,
                    raw_suffix=child.raw_suffix,
                ),
                reason=SKIPPED_NOT_KILLABLE,
                detail="RUNNING",
            ),
        ),
    )

    app._notify_no_focused_cleanup_action(plan, child)

    assert app._notifications == [
        ("Agent cannot be cleaned up (not_killable: RUNNING)", "warning")
    ]
