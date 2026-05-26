"""Tests for Agents-tab wait/fork actions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.base import BaseActionsMixin
from sase.ace.tui.actions.agents._wait_resume import (
    AgentWaitResumeMixin,
    _parse_wait_dependency_names,
)
from sase.ace.tui.actions.hints._hooks import HookEditingMixin
from sase.ace.tui.models.agent import Agent, AgentType


def _make_waiting_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "WAITING",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": "20240101120000",
        "waiting_for": ["old_dep"],
        "wait_duration": 300.0,
        "wait_until": "2026-05-01T12:00:00",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class _FakeWaitResumeApp(AgentWaitResumeMixin):
    """Minimal app implementing what _apply_wait touches."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.refresh_calls = 0

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        del list_changed, defer_detail
        self.refresh_calls += 1


class _FakeResumeActionApp(AgentWaitResumeMixin):
    """Minimal app implementing what action_fork_agent touches."""

    def __init__(self, agents: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self.notifications: list[tuple[str, str]] = []
        self.prompt_bar_calls: list[dict[str, str | None]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _get_selected_agent(self) -> Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def _show_prompt_input_bar_for_home(
        self,
        *,
        initial_text: str = "",
        display_name: str | None = None,
        history_sort_key: str | None = None,
    ) -> None:
        self.prompt_bar_calls.append(
            {
                "initial_text": initial_text,
                "display_name": display_name,
                "history_sort_key": history_sort_key,
            }
        )


def test_parse_wait_dependency_names_splits_commas() -> None:
    assert _parse_wait_dependency_names("alice, bob,, ") == ["alice", "bob"]


def test_apply_wait_overwrites_wait_conditions(tmp_path: Path) -> None:
    waiting_path = tmp_path / "waiting.json"
    waiting_path.write_text(
        json.dumps(
            {
                "waiting_for": ["old_dep"],
                "wait_duration": 300.0,
                "wait_until": "2026-05-01T12:00:00",
                "cl_name": "test_cl",
                "timestamp": "20240101120000",
            }
        ),
        encoding="utf-8",
    )
    agent = _make_waiting_agent()
    app = _FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._wait_resume."
        "update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        app._apply_wait(str(tmp_path), agent, "alice, bob,, ")

    data = json.loads(waiting_path.read_text(encoding="utf-8"))
    assert data == {
        "cl_name": "test_cl",
        "timestamp": "20240101120000",
        "waiting_for": ["alice", "bob"],
    }
    assert agent.waiting_for == ["alice", "bob"]
    assert agent.wait_duration is None
    assert agent.wait_until is None
    assert app.notifications == [("Now waiting for: alice, bob", "information")]
    assert app.refresh_calls == 1
    update_index.assert_called_once_with(str(tmp_path))


def test_apply_wait_empty_submission_keeps_run_now_behavior(tmp_path: Path) -> None:
    agent = _make_waiting_agent(waiting_for=["old_dep"], wait_duration=None)
    app = _FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._wait_resume."
        "update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        app._apply_wait(str(tmp_path), agent, "")

    ready_path = tmp_path / "ready.json"
    assert json.loads(ready_path.read_text(encoding="utf-8")) == {
        "resolved_deps": ["old_dep"],
        "unwait": True,
    }
    assert agent.waiting_for == ["old_dep"]
    assert app.notifications == [("Wait: test_cl", "information")]
    update_index.assert_not_called()


class _FakeAgentForkDispatchApp(BaseActionsMixin, HookEditingMixin):
    """Minimal app for Agents-tab key dispatch assertions."""

    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.changespecs = [object()]
        self.fork_calls = 0
        self.retry_edit_calls = 0

    def action_fork_agent(self) -> None:
        self.fork_calls += 1

    def _retry_edit_agent(self) -> None:
        self.retry_edit_calls += 1


def test_fork_agent_tale_done_family_root_uses_family_name() -> None:
    agent = _make_waiting_agent(
        status="TALE DONE",
        agent_name="aww-plan",
        agent_family="aww",
        agent_family_role="root",
        plan_chain_root=True,
    )
    app = _FakeResumeActionApp([agent])

    app.action_fork_agent()

    assert app.notifications == []
    assert app.prompt_bar_calls == [
        {
            "initial_text": "#fork:aww ",
            "display_name": "fork(aww)",
            "history_sort_key": "test_cl",
        }
    ]


def test_fork_agent_plan_done_family_root_uses_family_name() -> None:
    agent = _make_waiting_agent(
        status="PLAN DONE",
        agent_name="planner-plan",
        agent_family="planner",
        agent_family_role="root",
        plan_chain_root=True,
    )
    app = _FakeResumeActionApp([agent])

    app.action_fork_agent()

    assert app.notifications == []
    assert app.prompt_bar_calls[0]["initial_text"] == "#fork:planner "


def test_run_workflow_on_agents_dispatches_retry_edit_and_does_not_fork() -> None:
    app = _FakeAgentForkDispatchApp()

    BaseActionsMixin.action_run_workflow(app)

    assert app.retry_edit_calls == 1
    assert app.fork_calls == 0


def test_edit_hooks_on_agents_dispatches_to_fork() -> None:
    app = _FakeAgentForkDispatchApp()

    HookEditingMixin.action_edit_hooks(app)

    assert app.fork_calls == 1
