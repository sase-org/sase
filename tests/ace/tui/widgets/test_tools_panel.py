from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.tools import ToolCallEntry, read_tool_calls_for_agent
from sase.ace.tui.tools.reader import TOOL_CALLS_FILENAME
from sase.ace.tui.widgets import tools_panel as tools_panel_mod
from sase.ace.tui.widgets.tools_panel import (
    AgentToolsPanel,
    _build_tools_timeline_markdown,
    _build_tools_timeline_text,
    _ToolsCacheEntry,
    get_cache_key,
)
from sase.llm_provider._tool_calls import append_claude_tool_call_event


def _entry(**overrides: object) -> ToolCallEntry:
    kwargs = {
        "recorded_at": "2026-05-14T14:00:00+00:00",
        "runtime": "claude",
        "event": "PostToolUse",
        "status": "success",
        "tool_name": "Bash",
        "tool_use_id": "toolu_1",
        "duration_ms": 1234,
        "tool_input_summary": {"command": "pytest tests/ace/tui/tools"},
        "tool_response_summary": {"exit_code": 0, "stdout_preview": "ok"},
    }
    kwargs.update(overrides)
    return ToolCallEntry(**kwargs)  # type: ignore[arg-type]


def test_tools_timeline_distinguishes_missing_empty_and_present() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    missing = _build_tools_timeline_text(None, fetch_time).plain
    empty = _build_tools_timeline_text([], fetch_time).plain
    present = _build_tools_timeline_text([_entry()], fetch_time).plain

    assert "No tools artifact available" in missing
    assert "No tool calls recorded" in empty
    assert "TOOLS" in present
    assert "Bash" in present
    assert "pytest tests/ace/tui/tools" in present
    assert "1.2s" in present


def test_tools_timeline_markdown_is_exportable() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_markdown(
        [
            _entry(
                status="failure",
                tool_response_summary={"exit_code": 1, "stderr_preview": "boom"},
            )
        ],
        fetch_time,
    )

    assert rendered is not None
    assert rendered.startswith("TOOLS")
    assert "fail | Bash" in rendered
    assert "boom" in rendered


def test_tools_timeline_markdown_exports_codex_compact_targets() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_markdown(
        [
            _entry(
                runtime="codex",
                event="FunctionCall",
                tool_name="Read",
                tool_use_id="call_1",
                duration_ms=None,
                source="stream",
                tool_input_summary={"file_path": "src/sase/foo.py"},
                tool_response_summary={},
            )
        ],
        fetch_time,
    )

    assert rendered is not None
    assert "ok | Read | src/sase/foo.py" in rendered


def test_tools_timeline_shows_pending_state() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_text(
        [
            _entry(
                status="pending",
                duration_ms=None,
                tool_response_summary={},
            )
        ],
        fetch_time,
    ).plain

    assert "wait" in rendered
    assert "Bash" in rendered


def test_tools_timeline_truncates_long_command() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)
    long_command = "echo " + "x" * 200

    rendered = _build_tools_timeline_text(
        [_entry(tool_input_summary={"command": long_command})],
        fetch_time,
    ).plain

    assert long_command not in rendered
    assert "..." in rendered


def test_tools_timeline_renders_failure_with_error_detail() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_text(
        [
            _entry(
                status="failure",
                tool_response_summary={
                    "exit_code": 2,
                    "stderr_preview": "ENOENT: missing file",
                },
            )
        ],
        fetch_time,
    ).plain

    assert "fail" in rendered
    assert "exit 2" in rendered
    assert "ENOENT: missing file" in rendered


def test_tools_timeline_renders_interrupted_state() -> None:
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_text(
        [
            _entry(
                status="interrupted",
                duration_ms=None,
                tool_response_summary={"interrupted": True},
            )
        ],
        fetch_time,
    ).plain

    assert "stop" in rendered


def test_tools_timeline_renders_rich_response_detail() -> None:
    """A successful row should surface a stdout/content preview line."""
    fetch_time = datetime(2026, 5, 14, 10, 30, 0)

    rendered = _build_tools_timeline_text(
        [
            _entry(
                tool_name="Read",
                tool_input_summary={"file_path": "src/sase/foo.py"},
                tool_response_summary={"content_preview": "class Foo:\n    pass"},
                duration_ms=12,
            )
        ],
        fetch_time,
    ).plain

    assert "Read" in rendered
    assert "src/sase/foo.py" in rendered
    assert "class Foo:" in rendered
    assert "12ms" in rendered


def test_tools_panel_renders_tool_call_from_stream_events(tmp_path: Path) -> None:
    """End-to-end: writer captures assistant+user events, panel renders the row."""
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    artifacts_dir.mkdir(parents=True)

    with patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": str(artifacts_dir)}):
        append_claude_tool_call_event(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_1",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_bash_1",
                            "name": "Bash",
                            "input": {
                                "command": "ls /tmp",
                                "description": "list /tmp",
                            },
                        }
                    ],
                },
                "session_id": "session-1",
                "uuid": "uuid-1",
            }
        )
        append_claude_tool_call_event(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "tool_use_id": "toolu_bash_1",
                            "type": "tool_result",
                            "content": "alpha\nbeta\n",
                            "is_error": False,
                        }
                    ],
                },
                "session_id": "session-1",
                "uuid": "uuid-2",
                "tool_use_result": {
                    "stdout": "alpha\nbeta\n",
                    "stderr": "",
                    "interrupted": False,
                },
            }
        )

    assert (artifacts_dir / TOOL_CALLS_FILENAME).is_file()

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="DONE",
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        artifacts_dir=str(artifacts_dir),
        raw_suffix=artifacts_dir.name,
    )
    entries = read_tool_calls_for_agent(agent)
    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.tool_name == "Bash"
    assert entry.tool_use_id == "toolu_bash_1"
    assert entry.status == "success"

    fetch_time = datetime(2026, 5, 14, 10, 30, 0)
    rendered = _build_tools_timeline_text(entries, fetch_time).plain
    assert "Bash" in rendered
    assert "ls /tmp" in rendered or "list /tmp" in rendered
    assert "alpha" in rendered


def test_tools_panel_cache_invalidates_for_live_codex_appends(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    artifacts_dir.mkdir(parents=True)
    tool_calls_path = artifacts_dir / TOOL_CALLS_FILENAME
    started = {
        "schema_version": 2,
        "recorded_at": "2026-05-14T14:00:00+00:00",
        "runtime": "codex",
        "source": "stream",
        "event": "ToolUse",
        "status": "pending",
        "tool_name": "Bash",
        "tool_use_id": "item_0",
        "tool_input_summary": {"command": "pwd"},
        "tool_response_summary": {},
    }
    completed = {
        "schema_version": 2,
        "recorded_at": "2026-05-14T14:00:01+00:00",
        "runtime": "codex",
        "source": "stream",
        "event": "ToolResult",
        "status": "success",
        "tool_name": "Bash",
        "tool_use_id": "item_0",
        "duration_ms": 4,
        "tool_input_summary": {"command": "pwd"},
        "tool_response_summary": {"exit_code": 0, "output_preview": "/tmp\n"},
    }
    tool_calls_path.write_text(json.dumps(started) + "\n", encoding="utf-8")

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        artifacts_dir=str(artifacts_dir),
        raw_suffix=artifacts_dir.name,
    )
    cache_key = get_cache_key(agent)
    initial_mtime = tool_calls_path.stat().st_mtime_ns
    tools_panel_mod._tools_cache[cache_key] = _ToolsCacheEntry(
        entries=[
            _entry(
                runtime="codex",
                source="stream",
                status="pending",
                duration_ms=None,
                tool_input_summary={"command": "pwd"},
                tool_response_summary={},
            )
        ],
        fetch_time=datetime.now(),
        artifact_mtime_ns=initial_mtime,
        discovered_dirs=[artifacts_dir],
        parent_mtime_ns=artifacts_dir.parent.stat().st_mtime_ns,
        last_worker_monotonic=time.monotonic(),
    )

    try:
        with tool_calls_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(completed) + "\n")
        os.utime(
            tool_calls_path,
            ns=(initial_mtime + 1_000_000_000, initial_mtime + 1_000_000_000),
        )

        panel = _build_panel()
        entries = panel._fetch_tools_in_background(agent)
    finally:
        tools_panel_mod._tools_cache.pop(cache_key, None)

    assert entries is not None
    assert len(entries) == 1
    assert entries[0].status == "success"
    assert entries[0].duration_ms == 4
    assert entries[0].detail == "exit 0 | /tmp"


def _build_panel() -> AgentToolsPanel:
    panel = AgentToolsPanel.__new__(AgentToolsPanel)
    panel._current_agent = None
    panel._current_worker = None
    panel._has_displayed_content = True
    panel._last_entries = None
    panel._last_fetch_time = None
    panel._is_background_refreshing = False
    panel.update = MagicMock()  # type: ignore[method-assign]
    panel.post_message = MagicMock()  # type: ignore[method-assign]
    panel.run_worker = MagicMock(  # type: ignore[method-assign]
        return_value=MagicMock(is_running=False)
    )
    return panel


def test_warm_cache_update_display_does_not_walk_artifacts_on_event_loop(
    tmp_path: Path,
) -> None:
    """Regression for the j/k slowdown: a warm-cache update_display must not
    invoke ``discover_related_tool_artifact_dirs`` (or any sibling-walking
    helper) on the Textual event loop. Throttling keeps repeated keystrokes
    cheap by suppressing worker spawns inside the minimum re-read interval.
    """
    from sase.ace.tui.models.agent import Agent, AgentType

    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    artifacts_dir.mkdir(parents=True)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        artifacts_dir=str(artifacts_dir),
        raw_suffix=artifacts_dir.name,
    )

    cache_key = get_cache_key(agent)
    tools_panel_mod._tools_cache[cache_key] = _ToolsCacheEntry(
        entries=[],
        fetch_time=datetime.now(),
        artifact_mtime_ns=1234,
        discovered_dirs=[artifacts_dir],
        parent_mtime_ns=5678,
        last_worker_monotonic=time.monotonic(),
    )

    with (
        patch(
            "sase.ace.tui.tools.reader.discover_related_tool_artifact_dirs"
        ) as discover_mock,
        patch(
            "sase.ace.tui.tools.reader.discover_related_tool_artifact_dirs_cached"
        ) as discover_cached_mock,
    ):
        try:
            panel = _build_panel()
            for _ in range(10):
                panel.update_display(agent)
        finally:
            tools_panel_mod._tools_cache.pop(cache_key, None)

    run_worker = panel.run_worker
    update = panel.update
    assert isinstance(run_worker, MagicMock)
    assert isinstance(update, MagicMock)
    assert discover_mock.call_count == 0
    assert discover_cached_mock.call_count == 0
    assert run_worker.call_count == 0
    assert update.called


def test_cold_update_display_defers_missing_artifact_reads_to_worker(
    tmp_path: Path,
) -> None:
    """Cold panel refresh must not stat or read tool artifacts on the event loop."""
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    artifacts_dir.mkdir(parents=True)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        artifacts_dir=str(artifacts_dir),
        raw_suffix=artifacts_dir.name,
    )

    cache_key = get_cache_key(agent)
    tools_panel_mod._tools_cache.pop(cache_key, None)

    with (
        patch(
            "sase.ace.tui.widgets.tools_panel.read_tool_calls_for_agent"
        ) as read_mock,
        patch("sase.ace.tui.widgets.tools_panel._max_mtime_ns_for_paths") as mtime_mock,
        patch(
            "sase.ace.tui.tools.reader.discover_related_tool_artifact_dirs"
        ) as discover_mock,
        patch(
            "sase.ace.tui.tools.reader.discover_related_tool_artifact_dirs_cached"
        ) as discover_cached_mock,
    ):
        panel = _build_panel()
        panel.update_display(agent)

    run_worker = panel.run_worker
    assert isinstance(run_worker, MagicMock)
    assert run_worker.call_count == 1
    assert run_worker.call_args.kwargs["thread"] is True
    assert read_mock.call_count == 0
    assert mtime_mock.call_count == 0
    assert discover_mock.call_count == 0
    assert discover_cached_mock.call_count == 0


def test_refresh_tools_defers_forced_codex_reread_to_worker(
    tmp_path: Path,
) -> None:
    """A forced refresh invalidates cache state but still schedules threaded IO."""
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    artifacts_dir.mkdir(parents=True)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        artifacts_dir=str(artifacts_dir),
        raw_suffix=artifacts_dir.name,
    )
    cache_key = get_cache_key(agent)
    tools_panel_mod._tools_cache[cache_key] = _ToolsCacheEntry(
        entries=[
            _entry(
                runtime="codex",
                source="stream",
                status="pending",
                duration_ms=None,
                tool_input_summary={"command": "pwd"},
                tool_response_summary={},
            )
        ],
        fetch_time=datetime.now(),
        artifact_mtime_ns=1234,
        discovered_dirs=[artifacts_dir],
        parent_mtime_ns=artifacts_dir.parent.stat().st_mtime_ns,
        last_worker_monotonic=time.monotonic(),
    )

    with (
        patch(
            "sase.ace.tui.widgets.tools_panel.read_tool_calls_for_agent"
        ) as read_mock,
        patch("sase.ace.tui.widgets.tools_panel._max_mtime_ns_for_paths") as mtime_mock,
    ):
        try:
            panel = _build_panel()
            panel.refresh_tools(agent)
        finally:
            tools_panel_mod._tools_cache.pop(cache_key, None)

    run_worker = panel.run_worker
    assert isinstance(run_worker, MagicMock)
    assert run_worker.call_count == 1
    assert run_worker.call_args.kwargs["thread"] is True
    assert read_mock.call_count == 0
    assert mtime_mock.call_count == 0
