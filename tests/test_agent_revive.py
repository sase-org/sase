"""Tests for agent revive behavior."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import find_named_agent
from sase.ace.tui.actions.agents._revive import AgentRevivalMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup, panel_key_per_agent


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
        self.current_attempt_number: int | None = None
        self._current_group_key: tuple[str, ...] | None = None
        self._agent_panels_grouped = False
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._revived_agent_raw_suffixes: set[str] = set()
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self.loaded_agents: list[Agent] | None = None
        self.notifications: list[tuple[str, str]] = []
        self.restored: list[tuple[tuple[AgentType, str, str | None], str | None]] = []
        self.load_count = 0
        self.refresh_count = 0

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _load_agents(self) -> None:
        self.load_count += 1
        if self.loaded_agents is not None:
            self._agents = self.loaded_agents

    def _refresh_agents_display(self, *, list_changed: bool) -> None:
        if list_changed:
            self.refresh_count += 1

    def _panel_keys_per_agent(self) -> list[str | None]:
        return panel_key_per_agent(
            self._agents,
            merge_tag_panels=getattr(self, "_agent_panels_grouped", False),
        )

    def _restore_agent_artifacts(
        self,
        agent: Agent,
        *,
        parent_artifacts_dir: str | None = None,
    ) -> None:
        self.restored.append((agent.identity, parent_artifacts_dir))


class RealArtifactReviveApp(FakeReviveApp):
    """Revive fake that uses the real artifact restoration helpers."""

    _restore_agent_artifacts = AgentRevivalMixin._restore_agent_artifacts


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


def test_do_revive_agent_selects_revived_agent_panel_after_reload() -> None:
    """Single revive moves focus to the revived agent's rendered tag panel."""
    app = FakeReviveApp()
    active = _make_agent(cl_name="active", raw_suffix="active_suffix", tag="alpha")
    dismissed = _make_agent(cl_name="revived", raw_suffix="revived_suffix", tag="beta")
    reloaded = _make_agent(
        cl_name="revived",
        raw_suffix="revived_suffix",
        tag="beta",
        status="RUNNING",
    )
    app._agents = [active]
    app.loaded_agents = [active, reloaded]
    app._panel_group = AgentPanelGroup.from_agents(app._agents, focused_key="alpha")
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}
    app.current_idx = 0
    app.current_attempt_number = 7

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agent(dismissed)

    assert app.current_idx == 1
    assert app._agents[app.current_idx].raw_suffix == "revived_suffix"
    assert app._panel_group.focused_key == "beta"
    assert app._current_group_key is None
    assert app.current_attempt_number is None
    assert app.refresh_count == 1


def test_do_revive_agent_clears_stale_banner_focus() -> None:
    """Reviving an agent selects its row, not a stale collapsed group banner."""
    app = FakeReviveApp()
    dismissed = _make_agent(cl_name="revived", raw_suffix="revived_suffix")
    reloaded = _make_agent(cl_name="revived", raw_suffix="revived_suffix")
    app.loaded_agents = [reloaded]
    app._panel_group = AgentPanelGroup.from_agents([reloaded])
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}
    app._current_group_key = ("stale",)

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agent(dismissed)

    assert app.current_idx == 0
    assert app._current_group_key is None
    assert app.refresh_count == 1


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


def test_do_revive_agents_batch_selects_first_selected_parent() -> None:
    """Batch revive selects the first selected parent, not an implicit child."""
    app = FakeReviveApp()
    active = _make_agent(cl_name="active", raw_suffix="active_suffix", tag="alpha")
    parent_one = _make_agent(
        cl_name="feature1",
        raw_suffix="parent_one_suffix",
        tag="beta",
    )
    parent_two = _make_agent(
        cl_name="feature2",
        raw_suffix="parent_two_suffix",
        workflow="wf_two",
        tag="gamma",
    )
    child_one = _make_agent(
        cl_name="child1",
        raw_suffix="child_one_suffix",
        parent_workflow="wf",
        parent_timestamp="parent_one_suffix",
        tag="beta",
    )
    app._agents = [active]
    app.loaded_agents = [active, child_one, parent_one, parent_two]
    app._panel_group = AgentPanelGroup.from_agents(app._agents, focused_key="alpha")
    app._dismissed_agent_objects = [parent_one, parent_two, child_one]
    app._dismissed_agents = {
        parent_one.identity,
        parent_two.identity,
        child_one.identity,
    }

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agents([parent_one, parent_two])

    assert app.current_idx == 2
    assert app._agents[app.current_idx].raw_suffix == "parent_one_suffix"
    assert app._panel_group.focused_key == "beta"
    assert app._current_group_key is None
    assert app.current_attempt_number is None
    assert app.refresh_count == 1


@pytest.mark.parametrize(
    ("display_status", "canonical"),
    [
        ("DONE", "completed"),
        ("PLAN DONE", "completed"),
        ("PLAN COMMITTED", "completed"),
        ("EPIC APPROVED", "completed"),
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
        ("EPIC CREATED", "completed"),
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
    epic_time = datetime(2024, 1, 1, 12, 30, 0)
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
        epic_time=epic_time,
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
    assert data["epic_started_at"] == epic_time.isoformat()
    assert data["feedback_submitted_at"] == feedback_times[0].isoformat()
    assert data["questions_submitted_at"] == questions_times[0].isoformat()
    assert data["retry_started_at"] == [t.isoformat() for t in retry_times]
    assert data["plan"] is True
    assert data["plan_approved"] is True
    assert data["plan_action"] == "commit"


def test_restore_agent_meta_merges_existing_metadata(tmp_path: Path) -> None:
    agent = _make_agent(
        agent_type=AgentType.RUNNING,
        raw_suffix="20260504224829",
        agent_name="abb_3",
        model="claude-sonnet",
        workspace_dir="/tmp/workspace",
    )
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"legacy_field": "preserve", "model": "old-model"})
    )

    AgentRevivalMixin._restore_agent_meta(agent, tmp_path)
    data = json.loads((tmp_path / "agent_meta.json").read_text())

    assert data["legacy_field"] == "preserve"
    assert data["model"] == "claude-sonnet"
    assert data["name"] == "abb_3"
    assert data["workspace_dir"] == "/tmp/workspace"


def test_revive_existing_meta_without_name_preserves_stored_lookup(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / ".sase" / "projects" / "proj" / "proj.gp"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("")
    artifact_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260504224829"
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(json.dumps({"model": "old-model"}))

    app = RealArtifactReviveApp()
    agent = _make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature_a",
        project_file=str(project_file),
        raw_suffix="20260504224829",
        agent_name="260504.abb_3",
        workflow="ace-run",
        artifacts_dir=str(artifact_dir),
    )
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}

    with (
        _patch_home(tmp_path),
        patch.dict(os.environ, {"HOME": str(tmp_path)}),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agent(agent)
        resolved = find_named_agent("260504.abb_3")

    data = json.loads((artifact_dir / "agent_meta.json").read_text())
    assert data["model"] == "old-model"
    assert data["name"] == "260504.abb_3"
    assert resolved is not None
    assert resolved.is_done
    assert resolved.artifacts_dir == str(artifact_dir)


# ---------------------------------------------------------------------------
# Phase 4: revive preserves stored names
# ---------------------------------------------------------------------------


def _patch_home(tmp_path: Path) -> patch:  # type: ignore[type-arg]
    """Point ``Path.home()`` at *tmp_path* for the duration of a test."""

    def _path_home() -> Path:
        return tmp_path

    return patch.object(Path, "home", _path_home)


def test_revive_preserves_dismissal_prefixed_name(tmp_path: Path) -> None:
    """Reviving ``260428.foo`` does not rename it in memory."""
    app = FakeReviveApp()
    agent = _make_agent(
        cl_name="feature_a",
        raw_suffix="20260428100000",
        agent_name="260428.foo",
    )
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}

    with (
        _patch_home(tmp_path),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agent(agent)

    assert agent.agent_name == "260428.foo"


def test_revive_preserves_active_agent_waiting_for(tmp_path: Path) -> None:
    """Revive does not rewrite active wait references."""
    app = FakeReviveApp()
    revived = _make_agent(
        cl_name="feature_a",
        raw_suffix="20260428100000",
        agent_name="260428.foo",
    )
    dependent = _make_agent(
        cl_name="feature_b",
        raw_suffix="20260428110000",
        status="WAITING",
        waiting_for=["260428.foo"],
    )
    app._dismissed_agent_objects = [revived]
    app._dismissed_agents = {revived.identity}
    app._agents_with_children = [dependent]

    with (
        _patch_home(tmp_path),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agent(revived)

    assert dependent.waiting_for == ["260428.foo"]


def test_revive_preserves_artifact_wait_for_on_disk(tmp_path: Path) -> None:
    """Revive leaves dependent ``agent_meta.json`` wait_for untouched."""
    artifact_dir = (
        tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / "20260428"
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"wait_for": ["260428.foo"]})
    )
    (artifact_dir / "raw_xprompt.md").write_text("%w:260428.foo run it")

    app = FakeReviveApp()
    revived = _make_agent(
        cl_name="feature_a",
        raw_suffix="20260428100000",
        agent_name="260428.foo",
    )
    app._dismissed_agent_objects = [revived]
    app._dismissed_agents = {revived.identity}

    with (
        _patch_home(tmp_path),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agent(revived)

    assert json.loads((artifact_dir / "agent_meta.json").read_text())["wait_for"] == [
        "260428.foo"
    ]
    assert (artifact_dir / "raw_xprompt.md").read_text() == "%w:260428.foo run it"


def test_revive_legacy_bundle_without_prefix_keeps_name(tmp_path: Path) -> None:
    """Pre-prefix bundles (no ``YYmmdd.``) revive under their current name."""
    app = FakeReviveApp()
    agent = _make_agent(
        cl_name="feature_a",
        raw_suffix="20260428100000",
        agent_name="foo",
    )
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}

    with (
        _patch_home(tmp_path),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agent(agent)

    assert agent.agent_name == "foo"
    # No fallback-name notification was emitted.
    assert not any(sev == "warning" for _, sev in app.notifications)


def test_revive_with_taken_name_keeps_stored_name(tmp_path: Path) -> None:
    """Revive does not dedup or rename when a stripped base is taken."""
    # Plant an active agent named "foo" so the revival sees the slot taken.
    active_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260501090000"
    )
    active_dir.mkdir(parents=True)
    (active_dir / "agent_meta.json").write_text(
        json.dumps({"name": "foo", "pid": 123456789})
    )
    (active_dir / "done.json").write_text(json.dumps({"outcome": "completed"}))

    app = FakeReviveApp()
    agent = _make_agent(
        cl_name="feature_a",
        raw_suffix="20260428100000",
        agent_name="260428.foo",
    )
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}

    with (
        _patch_home(tmp_path),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agent(agent)

    assert agent.agent_name == "260428.foo"
    assert not any(sev == "warning" for _, sev in app.notifications)


def test_revive_workflow_parent_preserves_children_prefix(tmp_path: Path) -> None:
    """A workflow parent + children keep their stored names together."""
    app = FakeReviveApp()
    parent = _make_agent(
        cl_name="feature",
        raw_suffix="20260428100000",
        agent_name="260428.a",
    )
    child = _make_agent(
        cl_name="child_step",
        raw_suffix="child_suffix_1",
        parent_workflow="wf",
        parent_timestamp="20260428100000",
        agent_name="260428.a.1",
    )
    app._dismissed_agent_objects = [parent, child]
    app._dismissed_agents = {parent.identity, child.identity}

    with (
        _patch_home(tmp_path),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agent(parent)

    assert parent.agent_name == "260428.a"
    assert child.agent_name == "260428.a.1"


def test_batch_revive_preserves_names_for_all_agents(tmp_path: Path) -> None:
    """Batch revive does not rename any revival_group member."""
    app = FakeReviveApp()
    parent_one = _make_agent(
        cl_name="f1",
        raw_suffix="20260428100000",
        agent_name="260428.foo",
    )
    parent_two = _make_agent(
        cl_name="f2",
        raw_suffix="20260428110000",
        workflow="wf_two",
        agent_name="260428.bar",
    )
    app._dismissed_agent_objects = [parent_one, parent_two]
    app._dismissed_agents = {parent_one.identity, parent_two.identity}

    with (
        _patch_home(tmp_path),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agents([parent_one, parent_two])

    assert parent_one.agent_name == "260428.foo"
    assert parent_two.agent_name == "260428.bar"
