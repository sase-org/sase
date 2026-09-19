"""Tests for Agents-tab tmux workspace selection."""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._panel_tmux import AgentPanelTmuxMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals.agent_workspace_tmux_modal import (
    AgentWorkspaceTmuxModal,
    AgentWorkspaceTmuxSelection,
)
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent


class _TmuxApp(AgentPanelTmuxMixin):
    def __init__(self, agent: Agent) -> None:
        self.current_tab = "agents"
        self._agent = agent
        self.notifications: list[tuple[str, str]] = []
        self.pushed: list[tuple[Any, Any]] = []
        self.worker_threads: list[bool] = []

    def _get_selected_agent(self) -> Agent | None:
        return self._agent

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        self.pushed.append((screen, callback))

    def run_worker(self, work: Any, **kwargs: Any) -> None:
        self.worker_threads.append(bool(kwargs.get("thread")))
        if kwargs.get("thread"):
            worker = threading.Thread(target=work)
            worker.start()
            worker.join()
            return
        work()

    def call_from_thread(self, callback: Any, *args: Any, **kwargs: Any) -> None:
        callback(*args, **kwargs)


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


def _fake_tmux(
    calls: list[Sequence[str]],
    *,
    existing: set[str] | None = None,
    fail: set[str] | None = None,
    threads: list[int] | None = None,
) -> Any:
    existing_names = existing or set()
    fail_commands = fail or set()

    def fake_run(
        cmd: Sequence[str], *args: Any, **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        calls.append(cmd)
        if threads is not None:
            threads.append(threading.get_ident())
        if list(cmd[:3]) == ["tmux", "list-windows", "-F"]:
            stdout = "\n".join(sorted(existing_names))
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
        command = cmd[1] if len(cmd) > 1 else ""
        returncode = 1 if command in fail_commands else 0
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr="")

    return fake_run


def _new_window_cwds(calls: list[Sequence[str]]) -> list[str]:
    cwds: list[str] = []
    for cmd in calls:
        if list(cmd[:2]) == ["tmux", "new-window"]:
            cwds.append(cmd[cmd.index("-c") + 1])
    return cwds


def _new_window_cwd(calls: list[Sequence[str]]) -> str:
    cwds = _new_window_cwds(calls)
    if not cwds:
        raise AssertionError("tmux new-window was not called")
    return cwds[0]


def _tmux_mutating_commands(calls: list[Sequence[str]]) -> list[list[str]]:
    return [
        list(cmd)
        for cmd in calls
        if list(cmd[:1]) == ["tmux"] and cmd[1] in {"new-window", "select-window"}
    ]


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
    assert app.worker_threads == [True]


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
        callback(AgentWorkspaceTmuxSelection(indexes=(0,)))

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
        callback(AgentWorkspaceTmuxSelection(indexes=(1,)))

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
        callback(AgentWorkspaceTmuxSelection(indexes=(1,)))

    assert calls == []
    assert any(
        message.startswith("Linked workspace not found") and severity == "warning"
        for message, severity in app.notifications
    )


def test_chooser_cancel_or_empty_selection_launches_nothing(tmp_path: Path) -> None:
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
        callback(None)
        callback(AgentWorkspaceTmuxSelection(indexes=()))

    assert calls == []
    assert app.notifications == []
    assert app.worker_threads == []


def test_chooser_marked_current_and_linked_open_in_display_order(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    explicit = tmp_path / "ad_hoc"
    linked = tmp_path / "sase-core_12"
    extra = tmp_path / "bob_12"
    primary.mkdir()
    explicit.mkdir()
    linked.mkdir()
    extra.mkdir()
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
            OpenedWorkspaceDisplayEvent(
                name="bob",
                workspace_dir=str(extra),
                reason="ctx",
                opened_at="2026-06-14T14:25:08+00:00",
            ),
        ),
    )
    calls: list[Sequence[str]] = []
    ui_thread = threading.get_ident()
    tmux_threads: list[int] = []

    with patch(
        "subprocess.run",
        side_effect=_fake_tmux(calls, existing={"bob_12"}, threads=tmux_threads),
    ):
        app.action_start_tmux_mode()
        _screen, callback = app.pushed[0]
        callback(AgentWorkspaceTmuxSelection(indexes=(0, 1, 2)))

    assert _new_window_cwds(calls) == [str(explicit), str(linked)]
    mutating = _tmux_mutating_commands(calls)
    assert [cmd[1] for cmd in mutating] == ["new-window", "new-window", "select-window"]
    assert mutating[-1][mutating[-1].index("-t") + 1] == ":=bob_12"
    assert app.notifications == [("Opened 2, switched 1", "information")]
    assert app.worker_threads == [True]
    assert tmux_threads
    assert all(thread_id != ui_thread for thread_id in tmux_threads)


def test_chooser_skips_missing_linked_and_still_opens_others(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    explicit = tmp_path / "ad_hoc"
    missing = tmp_path / "sase-core_12"
    extra = tmp_path / "bob_12"
    primary.mkdir()
    explicit.mkdir()
    extra.mkdir()
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
            OpenedWorkspaceDisplayEvent(
                name="bob",
                workspace_dir=str(extra),
                reason="ctx",
                opened_at="2026-06-14T14:25:08+00:00",
            ),
        ),
    )
    calls: list[Sequence[str]] = []

    with patch("subprocess.run", side_effect=_fake_tmux(calls)):
        app.action_start_tmux_mode()
        _screen, callback = app.pushed[0]
        callback(AgentWorkspaceTmuxSelection(indexes=(0, 1, 2)))

    assert _new_window_cwds(calls) == [str(explicit), str(extra)]
    assert app.notifications == [
        ("Opened 2, skipped 1: sase-core", "warning"),
    ]


def test_chooser_tmux_failure_does_not_claim_success_and_continues(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    explicit = tmp_path / "ad_hoc"
    linked = tmp_path / "sase-core_12"
    extra = tmp_path / "bob_12"
    primary.mkdir()
    explicit.mkdir()
    linked.mkdir()
    extra.mkdir()
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
            OpenedWorkspaceDisplayEvent(
                name="bob",
                workspace_dir=str(extra),
                reason="ctx",
                opened_at="2026-06-14T14:25:08+00:00",
            ),
        ),
    )
    calls: list[Sequence[str]] = []

    with patch(
        "subprocess.run",
        side_effect=_fake_tmux(calls, fail={"new-window"}),
    ):
        app.action_start_tmux_mode()
        _screen, callback = app.pushed[0]
        callback(AgentWorkspaceTmuxSelection(indexes=(1, 2)))

    assert len(_new_window_cwds(calls)) == 2
    message, severity = app.notifications[0]
    assert severity == "error"
    assert "Opened" not in message
    assert message.startswith("Failed 2:")
    assert "sase-core_12" in message
    assert "bob_12" in message


def test_tmux_command_not_found_reports_error(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    explicit = tmp_path / "ad_hoc"
    primary.mkdir()
    explicit.mkdir()
    project_file = _project_file(tmp_path, primary)
    app = _TmuxApp(_agent(project_file, workspace_num=0, workspace_dir=explicit))

    with patch("subprocess.run", side_effect=FileNotFoundError):
        app._open_agent_tmux_window(use_primary=False)

    assert ("tmux command not found", "error") in app.notifications


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
