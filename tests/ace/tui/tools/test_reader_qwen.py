from __future__ import annotations

from pathlib import Path

from sase.ace.tui.tools import read_tool_calls_for_agent

from ._reader_helpers import (
    _agent,
    _tool_result_record,
    _tool_use_record,
    _write_jsonl,
)


def test_read_tool_calls_for_agent_collapses_qwen_stream_records(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _tool_use_record(
                tool_use_id="call_qwen",
                tool_name="Bash",
                runtime="qwen",
                source="stream",
                session_id="session-qwen",
                tool_input_summary={
                    "command": "printf qwen_tool_fixture",
                    "description": "Print fixture",
                },
            ),
            _tool_result_record(
                tool_use_id="call_qwen",
                tool_name="Bash",
                runtime="qwen",
                source="stream",
                session_id="session-qwen",
                status="success",
                duration_ms=17,
                tool_response_summary={"content_preview": "qwen_tool_fixture"},
            ),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.runtime == "qwen"
    assert entry.event == "ToolUse"
    assert entry.status == "success"
    assert entry.display_tool_name == "Bash"
    assert entry.compact_target == "Print fixture"
    assert entry.detail == "qwen_tool_fixture"
    assert entry.duration_ms == 17
