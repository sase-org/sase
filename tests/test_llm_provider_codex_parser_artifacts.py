"""Tests for Codex live-reply, thinking, and tool-call artifact writing."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from sase.llm_provider._subprocess import (
    _process_codex_json_line,
    stream_and_parse_codex_json_output,
)

from tests._llm_provider_codex_parser_helpers import _start_fixture_codex_process


def test_codex_live_reply_artifacts_append_across_parser_cycles(
    tmp_path: Path,
) -> None:
    """Commit fallback parser cycles preserve earlier live-reply artifacts."""

    def run_cycle(message: str, reasoning: str) -> None:
        ndjson_lines = [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "reasoning",
                        "summary": [{"type": "summary_text", "text": reasoning}],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": message},
                }
            ),
        ]
        script = "import sys; " + "; ".join(f"print({line!r})" for line in ndjson_lines)
        process = subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        text, _stderr, rc = stream_and_parse_codex_json_output(
            process, suppress_output=True
        )

        assert rc == 0
        assert text == message

    with patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": str(tmp_path)}):
        run_cycle("first turn reply", "first thought")
        run_cycle("commit fallback reply", "fallback thought")

    reply_path = tmp_path / "live_reply.md"
    timestamps_path = tmp_path / "live_reply_timestamps.jsonl"
    thinking_path = tmp_path / "codex_thinking.jsonl"

    assert reply_path.read_text(encoding="utf-8") == (
        "first turn reply\n\ncommit fallback reply"
    )

    timestamp_entries = [
        json.loads(line)
        for line in timestamps_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [entry["byte_offset"] for entry in timestamp_entries] == [
        0,
        len("first turn reply"),
    ]

    thinking_entries = [
        json.loads(line)
        for line in thinking_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [entry["text"] for entry in thinking_entries] == [
        "first thought",
        "fallback thought",
    ]


def test_codex_fixture_subprocess_writes_tools_reply_and_thinking(
    tmp_path: Path,
) -> None:
    """Fixture subprocess smoke: Codex artifacts append without clobbering."""
    events = [
        {
            "type": "item.completed",
            "item": {
                "id": "rs_1",
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "Inspect workspace"}],
            },
        },
        {
            "type": "item.started",
            "item": {
                "id": "cmd_1",
                "type": "command_execution",
                "command": "/bin/zsh -lc pwd",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "cmd_1",
                "type": "command_execution",
                "command": "/bin/zsh -lc pwd",
                "aggregated_output": "/tmp/sase-codex-smoke\n",
                "exit_code": 0,
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "rs_2",
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "Patch file"}],
            },
        },
        {
            "type": "item.started",
            "item": {
                "id": "edit_1",
                "type": "file_change",
                "changes": [{"path": "sample.txt", "kind": "update"}],
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "edit_1",
                "type": "file_change",
                "changes": [{"path": "sample.txt", "kind": "update"}],
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "msg_1",
                "type": "agent_message",
                "text": "Smoke complete",
            },
        },
    ]
    process = _start_fixture_codex_process(events)

    with patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": str(tmp_path)}):
        text, stderr, rc = stream_and_parse_codex_json_output(
            process, suppress_output=True
        )

    assert (text, stderr, rc) == ("Smoke complete", "", 0)
    assert (tmp_path / "live_reply.md").read_text(encoding="utf-8") == (
        "Smoke complete"
    )

    tool_records = [
        json.loads(line)
        for line in (tmp_path / "tool_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [record["event"] for record in tool_records] == [
        "ToolUse",
        "ToolResult",
        "ToolUse",
        "ToolResult",
    ]
    assert [record["tool_name"] for record in tool_records] == [
        "Bash",
        "Bash",
        "Edit",
        "Edit",
    ]
    assert tool_records[1]["tool_response_summary"]["output_preview"] == (
        "/tmp/sase-codex-smoke\n"
    )

    thinking_records = [
        json.loads(line)
        for line in (tmp_path / "codex_thinking.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [record["text"] for record in thinking_records] == [
        "Inspect workspace",
        "Patch file",
    ]

    timestamp_records = [
        json.loads(line)
        for line in (tmp_path / "live_reply_timestamps.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [record["byte_offset"] for record in timestamp_records] == [0]


def test_codex_json_parser_writes_function_call_artifact(
    tmp_path: Path,
) -> None:
    """Tool-call capture does not disturb Codex text, errors, or thinking."""
    assistant_texts: list[str] = []
    error_events: list[str] = []
    pending_reasoning: list[dict[str, object]] = []
    thinking_path = tmp_path / "codex_thinking.jsonl"

    with thinking_path.open("w", encoding="utf-8") as thinking_file:
        with patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": str(tmp_path)}):
            _process_codex_json_line(
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "rs_1",
                            "type": "reasoning",
                            "summary": [
                                {"type": "summary_text", "text": "Need to inspect"}
                            ],
                        },
                    }
                ),
                assistant_texts,
                True,
                error_events,
                thinking_file=thinking_file,
                pending_reasoning=pending_reasoning,
            )
            _process_codex_json_line(
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "fc_1",
                            "call_id": "call_1",
                            "type": "function_call",
                            "name": "read_file",
                            "arguments": '{"path": "src/app.py"}',
                        },
                    }
                ),
                assistant_texts,
                True,
                error_events,
                thinking_file=thinking_file,
                pending_reasoning=pending_reasoning,
            )
            _process_codex_json_line(
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "msg_1",
                            "type": "agent_message",
                            "text": "Done",
                        },
                    }
                ),
                assistant_texts,
                True,
                error_events,
                thinking_file=thinking_file,
                pending_reasoning=pending_reasoning,
            )
            _process_codex_json_line(
                json.dumps({"type": "error", "message": "minor warning"}),
                assistant_texts,
                True,
                error_events,
            )

    tool_calls_path = tmp_path / "tool_calls.jsonl"
    records = [
        json.loads(line)
        for line in tool_calls_path.read_text(encoding="utf-8").splitlines()
    ]
    thinking_records = [
        json.loads(line)
        for line in thinking_path.read_text(encoding="utf-8").splitlines()
    ]

    assert assistant_texts == ["Done"]
    assert error_events == ["[error] minor warning"]
    assert len(records) == 1
    assert records[0]["runtime"] == "codex"
    assert records[0]["tool_name"] == "Read"
    assert records[0]["tool_use_id"] == "call_1"
    assert records[0]["tool_input_summary"]["file_path"] == "src/app.py"
    assert thinking_records[0]["following_action"] == "Read app.py"
