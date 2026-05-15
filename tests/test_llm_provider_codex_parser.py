"""Tests for Codex NDJSON parser and _format_codex_action."""

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import patch

from sase.llm_provider._subprocess import (
    _format_codex_action,
    _process_codex_json_line,
    stream_and_parse_codex_json_output,
)
from sase.llm_provider._tool_calls import _TOOL_CALL_RECORD_REQUIRED_FIELDS

CODEX_STREAM_FIXTURES = Path(__file__).parent / "fixtures" / "codex_stream"


def _load_fixture_events(name: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (CODEX_STREAM_FIXTURES / name)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def _start_fixture_codex_process(
    events: list[dict[str, object]],
) -> subprocess.Popen[str]:
    lines = [json.dumps(event) for event in events]
    script = f"import sys\nfor line in {lines!r}:\n    print(line, flush=True)\n"
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


# --- codex NDJSON parser tests ---


def test_codex_json_parser_extracts_text() -> None:
    """Test that the Codex NDJSON parser extracts assistant text correctly."""
    ndjson_lines = [
        json.dumps({"type": "thread.started", "thread_id": "t1"}),
        json.dumps({"type": "turn.started"}),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_0",
                    "type": "agent_message",
                    "text": "Hello world",
                },
            }
        ),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_1",
                    "type": "agent_message",
                    "text": "Second response",
                },
            }
        ),
        json.dumps({"type": "turn.completed"}),
    ]
    script = "import sys; " + "; ".join(f"print({line!r})" for line in ndjson_lines)
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    text, stderr, rc = stream_and_parse_codex_json_output(process, suppress_output=True)

    assert rc == 0
    assert "Hello world" in text
    assert "Second response" in text


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


def test_codex_json_parser_handles_malformed_lines() -> None:
    """Test that the Codex NDJSON parser gracefully handles non-JSON lines."""
    lines = [
        "not json at all",
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_0",
                    "type": "agent_message",
                    "text": "valid text",
                },
            }
        ),
        "{broken json",
    ]
    script = "import sys; " + "; ".join(f"print({line!r})" for line in lines)
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    text, stderr, rc = stream_and_parse_codex_json_output(process, suppress_output=True)

    assert rc == 0
    assert "valid text" in text


def test_codex_json_parser_captures_error_events() -> None:
    """Test that _process_codex_json_line captures error events."""
    assistant_texts: list[str] = []
    error_events: list[str] = []

    line = json.dumps({"type": "error", "message": "something went wrong"})
    _process_codex_json_line(line, assistant_texts, True, error_events)

    assert len(error_events) == 1
    assert "[error] something went wrong" in error_events[0]
    assert len(assistant_texts) == 0


def test_codex_json_parser_captures_turn_failed_events() -> None:
    """Test that _process_codex_json_line captures turn.failed events."""
    assistant_texts: list[str] = []
    error_events: list[str] = []

    line = json.dumps({"type": "turn.failed", "error": {"message": "turn failed"}})
    _process_codex_json_line(line, assistant_texts, True, error_events)

    assert len(error_events) == 1
    assert "[turn.failed] turn failed" in error_events[0]


def test_codex_json_parser_ignores_non_agent_message_items() -> None:
    """Test that item.completed with type != 'agent_message' is ignored."""
    assistant_texts: list[str] = []
    error_events: list[str] = []

    line = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "id": "item_0",
                "type": "error",
                "message": "some error",
            },
        }
    )
    _process_codex_json_line(line, assistant_texts, True, error_events)

    assert len(assistant_texts) == 0


def test_codex_json_parser_error_events_appended_to_stderr_on_failure() -> None:
    """Test that error events are appended to stderr when return_code != 0."""
    ndjson_lines = [
        json.dumps({"type": "error", "message": "API error occurred"}),
    ]
    script = (
        "import sys; "
        + "; ".join(f"print({line!r})" for line in ndjson_lines)
        + "; sys.exit(1)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    text, stderr, rc = stream_and_parse_codex_json_output(process, suppress_output=True)

    assert rc == 1
    assert "[error] API error occurred" in stderr


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


def test_codex_stream_fixture_contract_documents_current_tool_shapes() -> None:
    """codex-cli 0.130.0 emits command/file items, not function_call items."""
    events = _load_fixture_events("codex-cli-0.130.0-tools.jsonl")

    tool_items: list[Mapping[str, object]] = []
    for event in events:
        item = event.get("item")
        if (
            event.get("type") in {"item.started", "item.completed"}
            and isinstance(item, Mapping)
            and item.get("type") in {"command_execution", "file_change"}
        ):
            tool_items.append(item)

    command_items = [
        item for item in tool_items if item.get("type") == "command_execution"
    ]
    file_change_items = [
        item for item in tool_items if item.get("type") == "file_change"
    ]
    completed_commands = [
        item for item in command_items if item.get("status") in {"completed", "failed"}
    ]

    assert [event["type"] for event in events[:2]] == ["thread.started", "turn.started"]
    assert {item["status"] for item in command_items} == {
        "in_progress",
        "completed",
        "failed",
    }
    assert {item["status"] for item in file_change_items} == {
        "in_progress",
        "completed",
    }
    assert [item["exit_code"] for item in completed_commands] == [0, 0, 7, 0]
    assert not any(
        isinstance(event.get("item"), Mapping)
        and event["item"].get("type") == "function_call"
        for event in events
    )


def test_codex_parser_processes_captured_tool_fixture_with_artifacts(
    tmp_path: Path,
) -> None:
    """Parser extracts text and writes normalized Codex tool rows."""
    assistant_texts: list[str] = []
    error_events: list[str] = []

    with patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": str(tmp_path)}):
        for event in _load_fixture_events("codex-cli-0.130.0-tools.jsonl"):
            _process_codex_json_line(
                json.dumps(event),
                assistant_texts,
                True,
                error_events,
            )

    assert assistant_texts == [
        'Final file content:\n\n```text\nbeta\n```\n\n`sh -c "exit 7"` failed with exit code `7`.'
    ]
    assert error_events == []
    with open(tmp_path / "tool_calls.jsonl", encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]

    assert len(records) == 10
    assert [record["event"] for record in records[:2]] == ["ToolUse", "ToolResult"]
    assert records[0]["tool_name"] == "Bash"
    assert records[1]["tool_response_summary"]["output_preview"] == (
        "/tmp/sase-codex-fixture\n"
    )
    assert records[7]["status"] == "failure"
    assert records[7]["tool_response_summary"]["exit_code"] == 7
    assert all(
        field in record
        for record in records
        for field in _TOOL_CALL_RECORD_REQUIRED_FIELDS
    )


def test_codex_parser_processes_captured_error_fixture() -> None:
    """Captured Codex CLI errors are surfaced through both error channels."""
    assistant_texts: list[str] = []
    error_events: list[str] = []

    for event in _load_fixture_events("codex-cli-0.130.0-error.jsonl"):
        _process_codex_json_line(
            json.dumps(event),
            assistant_texts,
            True,
            error_events,
        )

    assert assistant_texts == []
    assert len(error_events) == 2
    assert error_events[0].startswith("[error] ")
    assert error_events[1].startswith("[turn.failed] ")
    assert "codex-mini-latest" in error_events[0]


def test_codex_parser_ignores_synthesized_unknown_item_fixture() -> None:
    """Unknown Codex item shapes are ignored until explicitly normalized."""
    assistant_texts: list[str] = []
    error_events: list[str] = []

    for event in _load_fixture_events("synthesized-unknown-item.jsonl"):
        _process_codex_json_line(
            json.dumps(event),
            assistant_texts,
            True,
            error_events,
        )

    assert assistant_texts == []
    assert error_events == []


# --- _format_codex_action tests ---


def test_format_codex_action_shell() -> None:
    """Test formatting of Codex shell/container.exec function calls."""
    item = {"name": "shell", "arguments": '{"command": "ls -la /tmp"}'}
    assert _format_codex_action(item) == "Bash `ls`"

    item2 = {"name": "container.exec", "arguments": '{"command": ["git", "status"]}'}
    assert _format_codex_action(item2) == "Bash `git`"


def test_format_codex_action_read_write() -> None:
    """Test formatting of Codex read/write function calls."""
    item = {"name": "read_file", "arguments": '{"path": "/home/user/src/main.py"}'}
    assert _format_codex_action(item) == "Read main.py"

    item2 = {
        "name": "write_file",
        "arguments": '{"path": "/home/user/config.yml"}',
    }
    assert _format_codex_action(item2) == "Edit config.yml"


def test_format_codex_action_unknown() -> None:
    """Test that unknown Codex tool names are returned as-is."""
    item = {"name": "web_search", "arguments": "{}"}
    assert _format_codex_action(item) == "web_search"


def test_format_codex_action_empty_name() -> None:
    """Test that empty/missing name returns None."""
    assert _format_codex_action({}) is None
    assert _format_codex_action({"name": ""}) is None
