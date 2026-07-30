"""Tests for ClipboardMixin._copy_agent_name (Agents tab %n)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from sase.ace.tui.actions.clipboard import ClipboardMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.WORKFLOW,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "DONE",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "workflow": "wf",
        "raw_suffix": "20240101120000",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class FakeApp(ClipboardMixin):
    """Minimal stand-in app exposing only what _copy_agent_name needs."""

    def __init__(self, agent: Agent | None) -> None:
        self._agents = [agent] if agent is not None else []
        self.current_idx = 0
        self.notifications: list[tuple[str, str]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _get_selected_agent(self) -> Agent | None:
        if self._agents and 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None


def test_copy_agent_name_uses_agent_name_when_set() -> None:
    agent = _make_agent(agent_name="explicit_name")
    app = FakeApp(agent)

    with patch(
        "sase.ace.tui.actions.clipboard._agents.schedule_copy_delivery"
    ) as schedule:
        app._copy_agent_name()

    schedule.assert_called_once_with(
        app,
        "explicit_name",
        copied_label="agent name (explicit_name)",
        task_name="sase-copy-agent-name",
    )
    assert app.notifications == []


def test_copy_agent_name_family_root_uses_root_name() -> None:
    agent = _make_agent(
        agent_name="explicit_name-plan",
        agent_family="explicit_name",
        agent_family_role="root",
        plan_chain_root=True,
    )
    app = FakeApp(agent)

    with patch(
        "sase.ace.tui.actions.clipboard._agents.schedule_copy_delivery"
    ) as schedule:
        app._copy_agent_name()

    schedule.assert_called_once_with(
        app,
        "explicit_name",
        copied_label="agent name (explicit_name)",
        task_name="sase-copy-agent-name",
    )
    assert app.notifications == []


def test_copy_agent_name_falls_back_to_display_name() -> None:
    # No agent_name; workflow top-level entry → display_name == workflow.
    agent = _make_agent(agent_name=None, workflow="my_workflow")
    app = FakeApp(agent)

    with patch(
        "sase.ace.tui.actions.clipboard._agents.schedule_copy_delivery"
    ) as schedule:
        app._copy_agent_name()

    schedule.assert_called_once_with(
        app,
        "my_workflow",
        copied_label="agent display name (my_workflow)",
        task_name="sase-copy-agent-name",
    )
    assert app.notifications == []


def test_copy_agent_name_no_agent_selected() -> None:
    app = FakeApp(None)

    with patch(
        "sase.ace.tui.actions.clipboard._agents.schedule_copy_delivery"
    ) as schedule:
        app._copy_agent_name()

    schedule.assert_not_called()
    assert app.notifications == [("No agent selected", "warning")]


def test_copy_agent_name_uses_recoverable_delivery_policy() -> None:
    agent = _make_agent(agent_name="explicit_name")
    app = FakeApp(agent)

    with patch(
        "sase.ace.tui.actions.clipboard._agents.schedule_copy_delivery"
    ) as schedule:
        app._copy_agent_name()

    assert schedule.call_args.kwargs.get("on_failure", "modal") == "modal"
    assert app.notifications == []


def test_copy_agent_reference_uses_global_name() -> None:
    agent = _make_agent(
        agent_type=AgentType.RUNNING,
        agent_name="sase-b2.7",
    )
    app = FakeApp(agent)
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity(username="alice", machine_name="athena")
    )

    with (
        patch.object(AgentIdentitySnapshot, "current", return_value=identity),
        patch(
            "sase.ace.tui.actions.clipboard._agents.schedule_copy_delivery"
        ) as schedule,
    ):
        app._copy_agent_reference()

    schedule.assert_called_once_with(
        app,
        "@agent:alice.athena.sase-b2.7",
        copied_label="agent reference (agent:alice.athena.sase-b2.7)",
        task_name="sase-copy-agent-reference",
    )
    assert app.notifications == []


def test_copy_agent_reference_warns_for_clan_row() -> None:
    agent = _make_agent(
        agent_name=None,
        agent_clan="reviewers",
        is_clan_container=True,
    )
    app = FakeApp(agent)

    with patch(
        "sase.ace.tui.actions.clipboard._agents.schedule_copy_delivery"
    ) as schedule:
        app._copy_agent_reference()

    schedule.assert_not_called()
    assert app.notifications == [
        ("The selected clan row has no agent reference", "warning")
    ]


def test_copy_agent_reference_warns_for_family_container() -> None:
    member = _make_agent(
        agent_type=AgentType.RUNNING,
        agent_name="review--code",
    )
    agent = _make_agent(
        agent_type=AgentType.RUNNING,
        agent_name="review--plan",
        agent_family="review",
        agent_family_role="root",
        followup_agents=[member],
    )
    app = FakeApp(agent)

    with patch(
        "sase.ace.tui.actions.clipboard._agents.schedule_copy_delivery"
    ) as schedule:
        app._copy_agent_reference()

    schedule.assert_not_called()
    assert app.notifications == [
        ("The selected family container has no agent reference", "warning")
    ]


def test_copy_agent_reference_warns_for_non_agent_workflow_step() -> None:
    agent = _make_agent(
        agent_name=None,
        parent_workflow="release",
        step_type="python",
    )
    app = FakeApp(agent)

    with patch(
        "sase.ace.tui.actions.clipboard._agents.schedule_copy_delivery"
    ) as schedule:
        app._copy_agent_reference()

    schedule.assert_not_called()
    assert app.notifications == [
        ("The selected workflow step row has no agent reference", "warning")
    ]
