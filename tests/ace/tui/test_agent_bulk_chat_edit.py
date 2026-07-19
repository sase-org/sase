"""Tests for marked-agent chat editing from the Agents tab."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._panel_detail import AgentPanelDetailMixin
from sase.ace.tui.models.agent import Agent, AgentType


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "DONE",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": "20240101120000",
        "response_path": "/tmp/chat.md",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class _SuspendRecorder:
    def __init__(self) -> None:
        self.entered_count = 0

    def __enter__(self) -> None:
        self.entered_count += 1

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeEditApp(AgentPanelDetailMixin):
    def __init__(self, agents: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self.notifications: list[tuple[str, str]] = []
        self.suspend_recorder = _SuspendRecorder()

    def _get_selected_agent(self) -> Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def suspend(self) -> _SuspendRecorder:
        return self.suspend_recorder


def _run_edit(app: _FakeEditApp, editor: str = "test-editor") -> Any:
    with (
        patch.dict("os.environ", {"EDITOR": editor}, clear=False),
        patch("sase.ace.tui.actions.agents._panel_detail.subprocess.run") as mock_run,
    ):
        app.action_edit_spec()
    return mock_run


def test_marked_edit_opens_three_chat_paths_in_one_editor_call() -> None:
    first = _make_agent(
        cl_name="first",
        raw_suffix="20240101120000",
        status="DONE",
        response_path="/tmp/first.md",
    )
    second = _make_agent(
        cl_name="second",
        raw_suffix="20240101130000",
        status="PLAN DONE",
        response_path="/tmp/second.md",
    )
    third = _make_agent(
        cl_name="third",
        raw_suffix="20240101140000",
        status="TALE DONE",
        response_path="/tmp/third.md",
    )
    app = _FakeEditApp([first, second, third])
    app._marked_agents = {first.identity, second.identity, third.identity}

    mock_run = _run_edit(app)

    mock_run.assert_called_once_with(
        ["test-editor", "/tmp/first.md", "/tmp/second.md", "/tmp/third.md"],
        check=False,
    )
    assert app.suspend_recorder.entered_count == 1
    assert app.notifications == []
    assert app._marked_agents == {first.identity, second.identity, third.identity}


def test_marked_edit_order_follows_agents_with_children_not_mark_set() -> None:
    alpha = _make_agent(
        cl_name="alpha",
        raw_suffix="20240101120000",
        response_path="/tmp/alpha.md",
    )
    beta = _make_agent(
        cl_name="beta",
        raw_suffix="20240101130000",
        response_path="/tmp/beta.md",
    )
    gamma = _make_agent(
        cl_name="gamma",
        raw_suffix="20240101140000",
        response_path="/tmp/gamma.md",
    )
    app = _FakeEditApp([beta, alpha, gamma])
    app._marked_agents = {gamma.identity, alpha.identity, beta.identity}

    mock_run = _run_edit(app)

    mock_run.assert_called_once_with(
        ["test-editor", "/tmp/beta.md", "/tmp/alpha.md", "/tmp/gamma.md"],
        check=False,
    )


def test_marked_edit_ignores_stale_marks() -> None:
    live = _make_agent(response_path="/tmp/live.md")
    stale_identity = (AgentType.RUNNING, "ghost", "20240101150000")
    app = _FakeEditApp([live])
    app._marked_agents = {live.identity, stale_identity}

    mock_run = _run_edit(app)

    mock_run.assert_called_once_with(["test-editor", "/tmp/live.md"], check=False)
    assert app.notifications == []
    assert app._marked_agents == {live.identity, stale_identity}


def test_marked_edit_skips_agents_without_editable_transcripts() -> None:
    valid = _make_agent(
        cl_name="valid",
        raw_suffix="20240101120000",
        status="DONE",
        response_path="/tmp/valid.md",
    )
    running = _make_agent(
        cl_name="running",
        raw_suffix="20240101130000",
        status="RUNNING",
        response_path="/tmp/running.md",
    )
    app = _FakeEditApp([running, valid])
    app._marked_agents = {running.identity, valid.identity}

    mock_run = _run_edit(app)

    mock_run.assert_called_once_with(["test-editor", "/tmp/valid.md"], check=False)
    assert app.notifications == [
        ("Skipped 1 marked agent without a chat file", "warning")
    ]


def test_marked_edit_all_stale_warns_and_does_not_launch_editor() -> None:
    stale_identity = (AgentType.RUNNING, "ghost", "20240101150000")
    app = _FakeEditApp([])
    app._marked_agents = {stale_identity}

    mock_run = _run_edit(app)

    mock_run.assert_not_called()
    assert app.notifications == [("No marked agents remain", "warning")]
    assert app.suspend_recorder.entered_count == 0


def test_marked_edit_all_missing_warns_and_does_not_launch_editor() -> None:
    missing = _make_agent(response_path=None)
    running = _make_agent(
        cl_name="running",
        raw_suffix="20240101130000",
        status="RUNNING",
        response_path="/tmp/running.md",
    )
    app = _FakeEditApp([missing, running])
    app._marked_agents = {missing.identity, running.identity}

    mock_run = _run_edit(app)

    mock_run.assert_not_called()
    assert app.notifications == [("No chat files found in marked agents", "warning")]
    assert app.suspend_recorder.entered_count == 0


def test_marked_edit_expands_and_deduplicates_paths(tmp_path: Path) -> None:
    chat_path = tmp_path / "chat.md"
    first = _make_agent(
        cl_name="first",
        raw_suffix="20240101120000",
        response_path="~/chat.md",
    )
    second = _make_agent(
        cl_name="second",
        raw_suffix="20240101130000",
        response_path=str(chat_path),
    )
    app = _FakeEditApp([first, second])
    app._marked_agents = {first.identity, second.identity}

    with patch.dict("os.environ", {"HOME": str(tmp_path)}, clear=False):
        mock_run = _run_edit(app, editor="test-editor")

    mock_run.assert_called_once_with(["test-editor", str(chat_path)], check=False)


def test_no_marks_still_opens_selected_agent_chat() -> None:
    selected = _make_agent(response_path="/tmp/selected.md")
    app = _FakeEditApp([selected])

    mock_run = _run_edit(app)

    mock_run.assert_called_once_with(["test-editor", "/tmp/selected.md"], check=False)
    assert app.notifications == []


def test_edit_records_external_tool_wait_telemetry() -> None:
    import json

    from sase.logs import tui_external_tools_jsonl_path

    selected = _make_agent(response_path="/tmp/selected.md")
    app = _FakeEditApp([selected])

    _run_edit(app, editor="test-editor")

    records = [
        json.loads(line)
        for line in tui_external_tools_jsonl_path().read_text().splitlines()
    ]
    assert len(records) == 1
    record = records[0]
    assert record["event"] == "external_tool_wait"
    assert record["action"] == "edit_spec"
    assert record["tool_kind"] == "editor"
    assert record["command"] == "test-editor"
    assert record["path_count"] == 1
    assert record["current_tab"] == "agents"
    assert "elapsed_seconds" in record
