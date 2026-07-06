from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.tools import read_tool_calls_for_agent
from sase.ace.tui.tools.cache import fetch_tool_calls_cached
from sase.ace.tui.tools.reader import TOOL_CALLS_FILENAME
from sase.ace.tui.widgets import tools_panel as tools_panel_mod
from sase.ace.tui.widgets.tools_panel import (
    _build_tools_timeline_text,
    _ToolsCacheEntry,
    get_cache_key,
)
from sase.llm_provider._tool_calls import append_claude_tool_call_event

from ._tools_panel_helpers import _build_panel, _entry


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


def test_tools_panel_worker_reuses_discovered_dirs_for_reread(
    tmp_path: Path,
) -> None:
    root_dir = tmp_path / "ace-run" / "20260514140000"
    retry_dir = tmp_path / "ace-run" / "20260514140500"
    root_dir.mkdir(parents=True)
    retry_dir.mkdir(parents=True)
    (root_dir / TOOL_CALLS_FILENAME).write_text("", encoding="utf-8")
    (retry_dir / TOOL_CALLS_FILENAME).write_text("", encoding="utf-8")
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        artifacts_dir=str(root_dir),
        raw_suffix=root_dir.name,
    )
    cache_key = get_cache_key(agent)
    tools_panel_mod._tools_cache[cache_key] = _ToolsCacheEntry(
        entries=[],
        fetch_time=datetime.now(),
        artifact_mtime_ns=1,
        discovered_dirs=[root_dir, retry_dir],
        parent_mtime_ns=2,
        last_worker_monotonic=time.monotonic(),
    )

    with (
        patch(
            "sase.ace.tui.tools.cache.discover_related_tool_artifact_dirs_cached",
            return_value=([root_dir, retry_dir], 3),
        ),
        patch(
            "sase.ace.tui.tools.cache.read_tool_calls_for_agent",
            return_value=[],
        ) as read_mock,
    ):
        try:
            panel = _build_panel()
            entries = panel._fetch_tools_in_background(agent)
        finally:
            tools_panel_mod._tools_cache.pop(cache_key, None)

    assert entries == ()
    read_mock.assert_called_once_with(agent, artifact_dirs=[root_dir, retry_dir])


def test_tools_panel_and_header_fetch_share_cache_entry(tmp_path: Path) -> None:
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
    expected_entries = [_entry(tool_use_id="shared-cache")]

    with (
        patch(
            "sase.ace.tui.tools.cache.discover_related_tool_artifact_dirs_cached",
            return_value=([artifacts_dir], 123),
        ),
        patch("sase.ace.tui.tools.cache._max_mtime_ns_for_paths", return_value=456),
        patch(
            "sase.ace.tui.tools.cache.read_tool_calls_for_agent",
            return_value=expected_entries,
        ) as read_mock,
    ):
        try:
            header_entries = fetch_tool_calls_cached(agent)
            panel_entries = _build_panel()._fetch_tools_in_background(agent)
        finally:
            tools_panel_mod._tools_cache.pop(cache_key, None)

    assert header_entries == tuple(expected_entries)
    assert panel_entries == tuple(expected_entries)
    read_mock.assert_called_once_with(agent, artifact_dirs=[artifacts_dir])


def test_tools_panel_background_fetch_aggregates_root_child_sources(
    tmp_path: Path,
) -> None:
    root_dir = tmp_path / "ace-run" / "20260514140000"
    code_dir = tmp_path / "ace-run" / "20260514140500"
    root_dir.mkdir(parents=True)
    code_dir.mkdir(parents=True)
    (root_dir / TOOL_CALLS_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "recorded_at": "2026-05-14T14:00:00+00:00",
                "runtime": "claude",
                "event": "PostToolUse",
                "status": "success",
                "tool_name": "Bash",
                "tool_use_id": "plan",
                "duration_ms": 30_000,
                "tool_input_summary": {"command": "plan command"},
                "tool_response_summary": {"exit_code": 0},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (code_dir / TOOL_CALLS_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "recorded_at": "2026-05-14T14:01:00+00:00",
                "runtime": "claude",
                "event": "PostToolUse",
                "status": "success",
                "tool_name": "Bash",
                "tool_use_id": "code",
                "duration_ms": 40_000,
                "tool_input_summary": {"command": "code command"},
                "tool_response_summary": {"exit_code": 0},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="root",
        project_file="/tmp/proj/proj.sase",
        status="DONE",
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        artifacts_dir=str(root_dir),
        raw_suffix="root",
        workflow="wf",
    )
    plan = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="plan",
        project_file="/tmp/proj/proj.sase",
        status="DONE",
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        artifacts_dir=str(root_dir),
        raw_suffix="plan",
        parent_workflow="wf",
        step_type="agent",
        agent_family_role="plan",
        role_suffix="--plan",
    )
    code = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="code",
        project_file="/tmp/proj/proj.sase",
        status="DONE",
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        artifacts_dir=str(code_dir),
        raw_suffix="code",
        parent_timestamp="root",
        agent_family_role="code",
        role_suffix="--code",
    )
    root.runtime_children.extend([plan, code])

    with patch(
        "sase.ace.tui.tools.cache.discover_related_tool_artifact_dirs_cached",
        side_effect=lambda _agent, artifacts_dir, **_kwargs: ([Path(artifacts_dir)], 1),
    ):
        try:
            result = _build_panel()._fetch_tools_result_in_background(root)
        finally:
            tools_panel_mod._tools_cache.pop(get_cache_key(root), None)
            tools_panel_mod._tools_cache.pop(get_cache_key(plan), None)
            tools_panel_mod._tools_cache.pop(get_cache_key(code), None)

    assert [entry.tool_use_id for entry in result.entries or ()] == ["plan", "code"]
    assert [row.source_label for row in result.rows or ()] == ["plan", "code"]
    rendered = _build_tools_timeline_text(
        result.entries,
        result.fetch_time,
        rows=result.rows,
    ).plain
    assert "plan command" in rendered
    assert "code command" in rendered
