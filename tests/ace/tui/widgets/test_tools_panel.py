from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.tools import ToolCallEntry, read_tool_calls_for_agent
from sase.ace.tui.tools.reader import TOOL_CALLS_FILENAME
from sase.ace.tui.widgets.tools_panel import (
    _build_tools_timeline_markdown,
    _build_tools_timeline_text,
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
    from sase.ace.tui.models.agent import Agent, AgentType

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
