"""Tests for Agents-tab tmux workspace selection."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._panel_tmux import AgentPanelTmuxMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals.agent_workspace_tmux_modal import AgentWorkspaceTmuxModal
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent


class _TmuxApp(AgentPanelTmuxMixin):
    def __init__(self, agent: Agent) -> None:
        self.current_tab = "agents"
        self._agent = agent
        self.notifications: list[tuple[str, str]] = []
        self.pushed: list[tuple[Any, Any]] = []

    def _get_selected_agent(self) -> Agent | None:
        return self._agent

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        self.pushed.append((screen, callback))


def _project_file(tmp_path: Path, primary_workspace: Path) -> Path:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project_file = project_dir / "project.sase"
    project_file.write_text(
        f"WORKSPACE_DIR: {primary_workspace}\nNAME: project\n",
        encoding="utf-8",
    )
    return project_file


def _agent(
    project_file: Path,
    *,
    workspace_num: int | None,
    workspace_dir: Path | None,
    step_output: dict[str, Any] | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file=str(project_file),
        status="RUNNING",
        start_time=None,
        workspace_num=workspace_num,
        workspace_dir=str(workspace_dir) if workspace_dir is not None else None,
        step_output=step_output,
    )


def _fake_tmux(calls: list[Sequence[str]]) -> Any:
    def fake_run(
        cmd: Sequence[str], *args: Any, **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        calls.append(cmd)
        if list(cmd[:3]) == ["tmux", "list-windows", "-F"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    return fake_run


def _new_window_cwd(calls: list[Sequence[str]]) -> str:
    for cmd in calls:
        if list(cmd[:2]) == ["tmux", "new-window"]:
            return cmd[cmd.index("-c") + 1]
    raise AssertionError("tmux new-window was not called")


def test_agent_tmux_prefers_effective_numbered_workspace_over_stale_dir(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    managed = tmp_path / "sase_10"
    primary.mkdir()
    managed.mkdir()
    project_file = _project_file(tmp_path, primary)
    agent = _agent(
        project_file,
        workspace_num=None,
        workspace_dir=primary,
        step_output={"meta_workspace": "10"},
    )
    app = _TmuxApp(agent)
    calls: list[Sequence[str]] = []

    with (
        patch("subprocess.run", side_effect=_fake_tmux(calls)),
        patch("sase.workspace_provider.detect_workflow_type", return_value="git"),
        patch(
            "sase.workspace_provider.get_workspace_directory", return_value=str(managed)
        ),
    ):
        app._open_agent_tmux_window(use_primary=False)

    assert _new_window_cwd(calls) == str(managed)
    assert ("Opened tmux window: project_10", "information") in app.notifications


@pytest.mark.parametrize("workspace_num", [None, 0])
def test_agent_tmux_directory_mode_uses_explicit_workspace_dir(
    tmp_path: Path,
    workspace_num: int | None,
) -> None:
    primary = tmp_path / "sase"
    explicit = tmp_path / "ad_hoc"
    primary.mkdir()
    explicit.mkdir()
    project_file = _project_file(tmp_path, primary)
    app = _TmuxApp(
        _agent(project_file, workspace_num=workspace_num, workspace_dir=explicit)
    )
    calls: list[Sequence[str]] = []

    with (
        patch("subprocess.run", side_effect=_fake_tmux(calls)),
        patch("sase.workspace_provider.detect_workflow_type") as detect_workflow_type,
    ):
        app._open_agent_tmux_window(use_primary=False)

    assert _new_window_cwd(calls) == str(explicit)
    detect_workflow_type.assert_not_called()


def test_agent_tmux_primary_action_stays_on_primary_workspace(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    managed = tmp_path / "sase_10"
    primary.mkdir()
    managed.mkdir()
    project_file = _project_file(tmp_path, primary)
    agent = _agent(
        project_file,
        workspace_num=None,
        workspace_dir=primary,
        step_output={"meta_workspace": "10"},
    )
    app = _TmuxApp(agent)
    calls: list[Sequence[str]] = []

    with (
        patch("subprocess.run", side_effect=_fake_tmux(calls)),
        patch("sase.workspace_provider.detect_workflow_type", return_value="git"),
        patch(
            "sase.workspace_provider.get_workspace_directory", return_value=str(primary)
        ),
    ):
        app._open_agent_tmux_window(use_primary=True)

    assert _new_window_cwd(calls) == str(primary)
    assert ("Opened tmux window: project", "information") in app.notifications


def test_start_tmux_mode_without_cached_workspaces_opens_directly(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    explicit = tmp_path / "ad_hoc"
    primary.mkdir()
    explicit.mkdir()
    project_file = _project_file(tmp_path, primary)
    app = _TmuxApp(_agent(project_file, workspace_num=0, workspace_dir=explicit))
    calls: list[Sequence[str]] = []

    with patch("subprocess.run", side_effect=_fake_tmux(calls)):
        app.action_start_tmux_mode()

    # No opened-workspace context cached: t opens the agent workspace directly.
    assert app.pushed == []
    assert _new_window_cwd(calls) == str(explicit)


def test_start_tmux_mode_with_cached_workspaces_pushes_chooser(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    explicit = tmp_path / "ad_hoc"
    linked = tmp_path / "sase-core_12"
    primary.mkdir()
    explicit.mkdir()
    linked.mkdir()
    project_file = _project_file(tmp_path, primary)
    agent = _agent(project_file, workspace_num=0, workspace_dir=explicit)
    app = _TmuxApp(agent)
    app.publish_selected_agent_opened_workspaces(
        agent,
        (
            OpenedWorkspaceDisplayEvent(
                name="sase-core",
                workspace_dir=str(linked),
                reason="Need Rust backend context",
                opened_at="2026-06-14T14:24:08+00:00",
            ),
        ),
    )
    calls: list[Sequence[str]] = []

    with patch("subprocess.run", side_effect=_fake_tmux(calls)):
        app.action_start_tmux_mode()

    # Cached context: t opens the chooser instead of launching tmux immediately.
    assert calls == []
    assert len(app.pushed) == 1
    screen, _callback = app.pushed[0]
    assert isinstance(screen, AgentWorkspaceTmuxModal)
    assert app.cached_agent_tmux_choice_count(agent) == 2


def test_chooser_current_selection_opens_current_workspace(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    explicit = tmp_path / "ad_hoc"
    linked = tmp_path / "sase-core_12"
    primary.mkdir()
    explicit.mkdir()
    linked.mkdir()
    project_file = _project_file(tmp_path, primary)
    agent = _agent(project_file, workspace_num=0, workspace_dir=explicit)
    app = _TmuxApp(agent)
    app.publish_selected_agent_opened_workspaces(
        agent,
        (
            OpenedWorkspaceDisplayEvent(
                name="sase-core",
                workspace_dir=str(linked),
                reason="ctx",
                opened_at="2026-06-14T14:24:08+00:00",
            ),
        ),
    )
    calls: list[Sequence[str]] = []

    with patch("subprocess.run", side_effect=_fake_tmux(calls)):
        app.action_start_tmux_mode()
        _screen, callback = app.pushed[0]
        callback(0)

    # CURRENT routes through the existing agent-workspace open path.
    assert _new_window_cwd(calls) == str(explicit)


def test_chooser_linked_selection_opens_recorded_workspace(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    explicit = tmp_path / "ad_hoc"
    linked = tmp_path / "sase-core_12"
    primary.mkdir()
    explicit.mkdir()
    linked.mkdir()
    project_file = _project_file(tmp_path, primary)
    agent = _agent(project_file, workspace_num=0, workspace_dir=explicit)
    app = _TmuxApp(agent)
    app.publish_selected_agent_opened_workspaces(
        agent,
        (
            OpenedWorkspaceDisplayEvent(
                name="sase-core",
                workspace_dir=str(linked),
                reason="ctx",
                opened_at="2026-06-14T14:24:08+00:00",
            ),
        ),
    )
    calls: list[Sequence[str]] = []

    with patch("subprocess.run", side_effect=_fake_tmux(calls)):
        app.action_start_tmux_mode()
        _screen, callback = app.pushed[0]
        callback(1)

    assert _new_window_cwd(calls) == str(linked)
    assert ("Opened tmux window: sase-core_12", "information") in app.notifications


def test_chooser_missing_linked_workspace_warns(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    explicit = tmp_path / "ad_hoc"
    missing = tmp_path / "sase-core_12"  # never created on disk
    primary.mkdir()
    explicit.mkdir()
    project_file = _project_file(tmp_path, primary)
    agent = _agent(project_file, workspace_num=0, workspace_dir=explicit)
    app = _TmuxApp(agent)
    app.publish_selected_agent_opened_workspaces(
        agent,
        (
            OpenedWorkspaceDisplayEvent(
                name="sase-core",
                workspace_dir=str(missing),
                reason="ctx",
                opened_at="2026-06-14T14:24:08+00:00",
            ),
        ),
    )
    calls: list[Sequence[str]] = []

    with patch("subprocess.run", side_effect=_fake_tmux(calls)):
        app.action_start_tmux_mode()
        _screen, callback = app.pushed[0]
        callback(1)

    assert calls == []
    assert any(
        message.startswith("Linked workspace not found") and severity == "warning"
        for message, severity in app.notifications
    )


def test_cached_opened_workspaces_ignored_for_other_agent_identity(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    explicit = tmp_path / "ad_hoc"
    linked = tmp_path / "sase-core_12"
    primary.mkdir()
    explicit.mkdir()
    linked.mkdir()
    project_file = _project_file(tmp_path, primary)
    cached_agent = _agent(project_file, workspace_num=0, workspace_dir=explicit)
    app = _TmuxApp(cached_agent)
    app.publish_selected_agent_opened_workspaces(
        cached_agent,
        (
            OpenedWorkspaceDisplayEvent(
                name="sase-core",
                workspace_dir=str(linked),
                reason="ctx",
                opened_at="2026-06-14T14:24:08+00:00",
            ),
        ),
    )

    # A different selection (distinct cl_name => distinct identity) must not
    # reuse the previous agent's cached events.
    other_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="other",
        project_file=str(project_file),
        status="RUNNING",
        start_time=None,
        workspace_num=0,
        workspace_dir=str(explicit),
    )
    app._agent = other_agent
    calls: list[Sequence[str]] = []

    with patch("subprocess.run", side_effect=_fake_tmux(calls)):
        app.action_start_tmux_mode()

    assert app.pushed == []
    assert _new_window_cwd(calls) == str(explicit)
    assert app.cached_agent_tmux_choice_count(other_agent) == 0
