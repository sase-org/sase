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


class _TmuxApp(AgentPanelTmuxMixin):
    def __init__(self, agent: Agent) -> None:
        self.current_tab = "agents"
        self._agent = agent
        self.notifications: list[tuple[str, str]] = []

    def _get_selected_agent(self) -> Agent | None:
        return self._agent

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))


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
