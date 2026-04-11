"""Tests for agent revive behavior."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._revive import AgentRevivalMixin
from sase.ace.tui.models.agent import Agent, AgentType


def _make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for revive tests."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.WORKFLOW,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.gp",
        "status": "DONE",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "workflow": "wf",
        "raw_suffix": "20240101120000",
        "artifacts_dir": "/tmp/projects/myproj/artifacts/workflow-wf/20240101120000",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class FakeReviveApp(AgentRevivalMixin):
    """Minimal app with only the revive dependencies."""

    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._agents: list[Agent] = []
        self.notifications: list[tuple[str, str]] = []
        self.restored: list[tuple[tuple[AgentType, str, str | None], str | None]] = []
        self.load_count = 0
        self.refresh_count = 0

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _load_agents(self) -> None:
        self.load_count += 1

    def _refresh_agents_display(self, *, list_changed: bool) -> None:
        if list_changed:
            self.refresh_count += 1

    def _restore_agent_artifacts(
        self,
        agent: Agent,
        *,
        parent_artifacts_dir: str | None = None,
    ) -> None:
        self.restored.append((agent.identity, parent_artifacts_dir))


def test_do_revive_agent_removes_suffix_aliases() -> None:
    """Single revive clears all dismissed aliases for revived suffixes."""
    app = FakeReviveApp()
    parent = _make_agent(cl_name="feature", raw_suffix="20260201101010")
    child = _make_agent(
        cl_name="child_step",
        raw_suffix="child_suffix_1",
        parent_workflow="wf",
        parent_timestamp="20260201101010",
    )
    app._agents = [parent]
    app._dismissed_agent_objects = [parent, child]
    app._dismissed_agents = {
        parent.identity,
        child.identity,
        (AgentType.RUNNING, "alias_running", "20260201101010"),
        (AgentType.WORKFLOW, "alias_child", "child_suffix_1"),
        (AgentType.WORKFLOW, "keep_me", "20260202101010"),
    }

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity") as mock_remove,
    ):
        app._do_revive_agent(parent)

    assert app._dismissed_agents == {(AgentType.WORKFLOW, "keep_me", "20260202101010")}
    mock_remove.assert_called_once_with(
        parent.identity,
        child_raw_suffixes={"child_suffix_1"},
    )
    assert app.load_count == 1
    assert len(app.restored) == 2
    assert app.restored[0] == (parent.identity, None)
    assert app.restored[1] == (child.identity, parent.artifacts_dir)


def test_do_revive_agents_batch_removes_suffix_aliases() -> None:
    """Batch revive clears aliases for all revived parent/child suffixes."""
    app = FakeReviveApp()
    parent_one = _make_agent(cl_name="feature1", raw_suffix="20260201101010")
    parent_two = _make_agent(
        cl_name="feature2",
        raw_suffix="20260301101010",
        workflow="wf_two",
    )
    child_one = _make_agent(
        cl_name="child1",
        raw_suffix="child_suffix_1",
        parent_workflow="wf",
        parent_timestamp="20260201101010",
    )
    followup_one = _make_agent(
        cl_name="feature1",
        raw_suffix="followup_suffix_1",
        parent_workflow=None,
        parent_timestamp="20260201101010",
    )
    app._dismissed_agent_objects = [parent_one, parent_two, child_one, followup_one]
    app._dismissed_agents = {
        parent_one.identity,
        parent_two.identity,
        child_one.identity,
        followup_one.identity,
        (AgentType.RUNNING, "alias_one", "20260201101010"),
        (AgentType.WORKFLOW, "alias_child", "child_suffix_1"),
        (AgentType.RUNNING, "alias_followup", "followup_suffix_1"),
        (AgentType.RUNNING, "alias_two", "20260301101010"),
        (AgentType.WORKFLOW, "keep_me", "20260401101010"),
    }

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity") as mock_remove,
    ):
        app._do_revive_agents([parent_one, parent_two])

    assert app._dismissed_agents == {(AgentType.WORKFLOW, "keep_me", "20260401101010")}
    mock_save.assert_called_once()
    assert mock_remove.call_count == 2
    assert mock_remove.call_args_list[0].args == (parent_one.identity,)
    assert mock_remove.call_args_list[0].kwargs == {
        "child_raw_suffixes": {"child_suffix_1", "followup_suffix_1"}
    }
    assert mock_remove.call_args_list[1].args == (parent_two.identity,)
    assert mock_remove.call_args_list[1].kwargs == {"child_raw_suffixes": set()}
    assert app.load_count == 1
    assert len(app.restored) == 4


@pytest.mark.parametrize(
    ("display_status", "canonical"),
    [
        ("DONE", "completed"),
        ("PLAN DONE", "completed"),
        ("PLAN COMMITTED", "completed"),
        ("EPIC CREATED", "completed"),
        ("FAILED", "failed"),
        ("WAITING INPUT", "waiting_hitl"),
        ("RUNNING", "running"),
    ],
)
def test_build_workflow_state_data_canonicalizes_statuses(
    display_status: str, canonical: str
) -> None:
    agent = _make_agent(status=display_status)
    data = AgentRevivalMixin._build_workflow_state_data(agent)
    assert data["status"] == canonical


@pytest.mark.parametrize(
    ("display_status", "canonical"),
    [
        ("DONE", "completed"),
        ("PLAN DONE", "completed"),
        ("PLAN COMMITTED", "completed"),
        ("FAILED", "failed"),
        ("WAITING INPUT", "waiting_hitl"),
        ("RUNNING", "in_progress"),
    ],
)
def test_build_step_marker_data_canonicalizes_statuses(
    display_status: str, canonical: str
) -> None:
    agent = _make_agent(status=display_status)
    data = AgentRevivalMixin._build_step_marker_data(agent)
    assert data["status"] == canonical


def test_restore_agent_meta_writes_loader_relevant_fields(tmp_path: Path) -> None:
    run_start = datetime(2024, 1, 1, 12, 5, 0)
    stop_time = datetime(2024, 1, 1, 12, 35, 0)
    plan_times = [
        datetime(2024, 1, 1, 12, 10, 0),
        datetime(2024, 1, 1, 12, 20, 0),
    ]
    feedback_times = [datetime(2024, 1, 1, 12, 22, 0)]
    questions_times = [datetime(2024, 1, 1, 12, 25, 0)]
    retry_times = [
        datetime(2024, 1, 1, 12, 27, 0),
        datetime(2024, 1, 1, 12, 29, 0),
    ]
    agent = _make_agent(
        status="PLAN COMMITTED",
        model="claude-opus",
        llm_provider="claude",
        vcs_provider="GitHub",
        agent_name="@d.1",
        waiting_for=["@f"],
        approve=True,
        hidden=True,
        role_suffix=".plan",
        parent_timestamp="20240101120000",
        workspace_num=7,
        response_path="~/.sase/chat/foo.md",
        run_start_time=run_start,
        stop_time=stop_time,
        plan_times=plan_times,
        feedback_times=feedback_times,
        questions_times=questions_times,
        retry_times=retry_times,
    )

    AgentRevivalMixin._restore_agent_meta(agent, tmp_path)
    data = json.loads((tmp_path / "agent_meta.json").read_text())

    assert data["model"] == "claude-opus"
    assert data["llm_provider"] == "claude"
    assert data["vcs_provider"] == "GitHub"
    assert data["name"] == "@d.1"
    assert data["wait_for"] == ["@f"]
    assert data["approve"] is True
    assert data["hidden"] is True
    assert data["role_suffix"] == ".plan"
    assert data["parent_timestamp"] == "20240101120000"
    assert data["workspace_num"] == 7
    assert data["chat_path"] == "~/.sase/chat/foo.md"
    assert data["run_started_at"] == run_start.isoformat()
    assert data["stopped_at"] == stop_time.isoformat()
    assert data["plan_submitted_at"] == [t.isoformat() for t in plan_times]
    assert data["feedback_submitted_at"] == feedback_times[0].isoformat()
    assert data["questions_submitted_at"] == questions_times[0].isoformat()
    assert data["retry_started_at"] == [t.isoformat() for t in retry_times]
    assert data["plan"] is True
    assert data["plan_approved"] is True
    assert data["plan_action"] == "commit"
