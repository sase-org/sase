"""Tests for _resolve_agent_cl_name and action_jump_to_agent_changespec."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._core import AgentsMixinCore
from sase.ace.tui.actions.agents._notification_navigation import (
    navigate_to_changespec_tab,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.query_history import QueryHistoryStacks
from test_utils import build_changespec


def _make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for testing."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.gp",
        "status": "RUNNING",
        "start_time": datetime(2024, 1, 1, 14, 23, 45),
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class FakeApp(AgentsMixinCore):
    """Minimal stand-in for AceApp with what jump-to-changespec needs."""

    def __init__(
        self,
        agents: list[Agent] | None = None,
        agents_with_children: list[Agent] | None = None,
    ) -> None:
        self._agents: list[Agent] = agents or []
        self._agents_with_children: list[Agent] = agents_with_children or []
        self.current_tab = "agents"
        self.current_idx: int = 0
        self._notifications: list[tuple[str, str]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:  # type: ignore[override]
        self._notifications.append((message, severity))

    def _get_selected_agent(self) -> Agent | None:
        if self._agents and 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None


class FakeNavigationApp:
    """Minimal stand-in for navigate_to_changespec_tab tests."""

    def __init__(
        self,
        changespecs: list[object],
        *,
        reloaded_changespecs: list[object] | None = None,
    ) -> None:
        self.changespecs = changespecs
        self.reloaded_changespecs = reloaded_changespecs
        self.current_tab = "agents"
        self.current_idx = 0
        self.canonical_query_string = "status:ready"
        self.query_string = "status:READY"
        self.parsed_query = object()
        self._query_history = QueryHistoryStacks(prev=[], next=[])
        self.load_count = 0
        self.save_count = 0
        self.notifications: list[tuple[str, str]] = []

    def _load_changespecs(self) -> None:
        self.load_count += 1
        if self.reloaded_changespecs is not None:
            self.changespecs = self.reloaded_changespecs

    def _save_current_query(self) -> None:
        self.save_count += 1

    def notify(
        self, message: str, *, severity: str = "information", **_: object
    ) -> None:
        self.notifications.append((message, severity))


# ---------------------------------------------------------------------------
# FM1: Workflow child step resolves to parent's cl_name
# ---------------------------------------------------------------------------


class TestWorkflowChildResolution:
    """Workflow child steps should resolve to the parent workflow's cl_name."""

    def test_child_resolves_to_parent_cl_name(self) -> None:
        """Child step's cl_name is the step name; resolution returns parent's."""
        parent = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="real_changespec",
            workflow="my_workflow",
            raw_suffix="20240101142345",
        )
        child = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="run_agent",  # step name, not a real ChangeSpec
            workflow="my_workflow",
            raw_suffix="20240101142345",
            parent_workflow="my_workflow",
            parent_timestamp="20240101142345",
            step_name="run_agent",
        )
        app = FakeApp(agents_with_children=[parent, child])
        assert app._resolve_agent_cl_name(child) == "real_changespec"

    def test_child_falls_back_to_workflow_state_json(self, tmp_path: Path) -> None:
        """When parent is not in the list, read workflow_state.json."""
        child = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="make_changes",
            workflow="deploy",
            raw_suffix="20240101142345",
            parent_workflow="deploy",
            parent_timestamp="20240101142345",
            project_file=str(tmp_path / "projects" / "myproj" / "myproj.gp"),
            step_name="make_changes",
        )

        # Create the workflow_state.json on disk
        wf_dir = (
            tmp_path
            / "projects"
            / "myproj"
            / "artifacts"
            / "workflow-deploy"
            / "20240101142345"
        )
        wf_dir.mkdir(parents=True)
        state_file = wf_dir / "workflow_state.json"
        state_file.write_text(
            json.dumps({"context": {"cl_name": "fallback_cl"}}),
            encoding="utf-8",
        )

        app = FakeApp(agents_with_children=[])  # No parent in list

        # Patch expanduser so ~/.sase/projects/... resolves to tmp_path
        with patch.object(Path, "expanduser", return_value=state_file):
            assert app._resolve_agent_cl_name(child) == "fallback_cl"

    def test_child_returns_none_when_parent_cl_name_is_unknown(self) -> None:
        """Parent with cl_name='unknown' yields None."""
        parent = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="unknown",
            workflow="wf",
            raw_suffix="20240101142345",
        )
        child = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="step1",
            parent_workflow="wf",
            parent_timestamp="20240101142345",
        )
        app = FakeApp(agents_with_children=[parent, child])
        assert app._resolve_agent_cl_name(child) is None


# ---------------------------------------------------------------------------
# FM2: Project agent without meta shows notification
# ---------------------------------------------------------------------------


class TestProjectAgentNoMeta:
    """Project agents without meta output should show a notification."""

    def test_project_agent_no_meta_returns_none(self) -> None:
        """Project agent with no step_output returns None."""
        agent = _make_agent(
            cl_name="myproj",
            project_file="/tmp/projects/myproj/myproj.gp",
        )
        app = FakeApp()
        assert app._resolve_agent_cl_name(agent) is None

    def test_project_agent_with_meta_changespec(self) -> None:
        """Project agent with meta_changespec returns the ChangeSpec name."""
        agent = _make_agent(
            cl_name="myproj",
            project_file="/tmp/projects/myproj/myproj.gp",
            step_output={"meta_changespec": "new_feature"},
        )
        app = FakeApp()
        assert app._resolve_agent_cl_name(agent) == "new_feature"

    def test_action_notifies_on_no_changespec(self) -> None:
        """action_jump_to_agent_changespec shows notification for project agent."""
        agent = _make_agent(
            cl_name="myproj",
            project_file="/tmp/projects/myproj/myproj.gp",
        )
        app = FakeApp(agents=[agent])
        app.action_jump_to_agent_changespec()
        assert any("No ChangeSpec" in msg for msg, _ in app._notifications)


# ---------------------------------------------------------------------------
# FM3: cl_name = "unknown" shows notification
# ---------------------------------------------------------------------------


class TestUnknownClName:
    """Agents with cl_name='unknown' should not navigate."""

    def test_unknown_cl_name_returns_none(self) -> None:
        agent = _make_agent(cl_name="unknown")
        app = FakeApp()
        assert app._resolve_agent_cl_name(agent) is None

    def test_empty_cl_name_returns_none(self) -> None:
        agent = _make_agent(cl_name="")
        app = FakeApp()
        assert app._resolve_agent_cl_name(agent) is None

    def test_action_notifies_on_unknown(self) -> None:
        agent = _make_agent(cl_name="unknown")
        app = FakeApp(agents=[agent])
        app.action_jump_to_agent_changespec()
        assert any("No ChangeSpec" in msg for msg, _ in app._notifications)


# ---------------------------------------------------------------------------
# FM4: Footer hides "go to CL" for agents that can't jump
# ---------------------------------------------------------------------------


class TestFooterVisibility:
    """Footer should only show 'go to CL' when the agent can actually jump."""

    def test_can_jump_true_for_normal_agent(self) -> None:
        agent = _make_agent(cl_name="real_cl")
        app = FakeApp()
        assert app._resolve_agent_cl_name(agent) is not None

    def test_can_jump_false_for_unknown_cl(self) -> None:
        agent = _make_agent(cl_name="unknown")
        app = FakeApp()
        assert app._resolve_agent_cl_name(agent) is None

    def test_can_jump_false_for_project_agent_no_meta(self) -> None:
        agent = _make_agent(
            cl_name="myproj",
            project_file="/tmp/projects/myproj/myproj.gp",
        )
        app = FakeApp()
        assert app._resolve_agent_cl_name(agent) is None

    def test_can_jump_false_for_workflow_child_unknown_parent(self) -> None:
        parent = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="unknown",
            workflow="wf",
            raw_suffix="20240101142345",
        )
        child = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="step1",
            parent_workflow="wf",
            parent_timestamp="20240101142345",
        )
        app = FakeApp(agents_with_children=[parent, child])
        assert app._resolve_agent_cl_name(child) is None

    def test_can_jump_true_for_workflow_child_valid_parent(self) -> None:
        parent = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="valid_cl",
            workflow="wf",
            raw_suffix="20240101142345",
        )
        child = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="step1",
            parent_workflow="wf",
            parent_timestamp="20240101142345",
        )
        app = FakeApp(agents_with_children=[parent, child])
        assert app._resolve_agent_cl_name(child) == "valid_cl"


class TestNavigateToChangespecExactFirst:
    """ChangeSpec tab navigation should prefer exact names over suffix fallback."""

    def test_exact_target_wins_over_earlier_suffixed_sibling(self) -> None:
        app = FakeNavigationApp(
            [
                build_changespec(name="feature_1"),
                build_changespec(name="feature"),
            ]
        )

        assert navigate_to_changespec_tab(app, "feature", "/tmp/projects/proj/proj.gp")
        assert app.current_tab == "changespecs"
        assert app.current_idx == 1
        assert app.load_count == 0

    def test_suffix_fallback_still_matches_when_exact_is_absent(self) -> None:
        app = FakeNavigationApp([build_changespec(name="feature_1")])

        assert navigate_to_changespec_tab(app, "feature", "/tmp/projects/proj/proj.gp")
        assert app.current_idx == 0
        assert app.load_count == 0

    def test_exact_target_wins_after_switching_to_project_query(self) -> None:
        app = FakeNavigationApp(
            [build_changespec(name="unrelated")],
            reloaded_changespecs=[
                build_changespec(name="feature_1"),
                build_changespec(name="feature"),
            ],
        )

        with patch("sase.ace.query_history.save_query_history", return_value=True):
            assert navigate_to_changespec_tab(
                app, "feature", "/tmp/projects/myproj/myproj.gp"
            )

        assert app.current_idx == 1
        assert app.load_count == 1
        assert app.save_count == 1
        assert app.query_string == "project:myproj"
