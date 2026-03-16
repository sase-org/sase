"""Tests for Codex NDJSON parser and _format_codex_action."""

import json
import subprocess
import sys

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
