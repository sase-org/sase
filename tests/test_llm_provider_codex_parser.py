"""Tests for Codex NDJSON parser and _format_codex_action."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from sase.llm_provider._subprocess import (
    _format_codex_action,
    _process_codex_json_line,
    stream_and_parse_codex_json_output,
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
