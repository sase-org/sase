"""Tests for Codex reasoning/thinking capture and following_action support."""

import json
import os
import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from sase.llm_provider._subprocess import (
    _flush_codex_reasoning,
    _process_codex_json_line,
    _write_codex_thinking,
    stream_and_parse_codex_json_output,
)


def test_codex_reasoning_captured_to_thinking_file(tmp_path: Path) -> None:
    """Test that reasoning items from Codex NDJSON are written to codex_thinking.jsonl."""
    thinking_path = tmp_path / "codex_thinking.jsonl"

    ndjson_lines = [
        json.dumps({"type": "thread.started", "thread_id": "t1"}),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "reasoning",
                    "id": "rs_001",
                    "summary": [
                        {"type": "summary_text", "text": "Let me think about this..."},
                    ],
                },
            }
        ),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": "Here is my answer",
                },
            }
        ),
    ]

    with patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": str(tmp_path)}):
        script = "import sys; " + "; ".join(f"print({line!r})" for line in ndjson_lines)
        process = subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        text, stderr, rc = stream_and_parse_codex_json_output(
            process, suppress_output=True
        )

    assert rc == 0
    assert "Here is my answer" in text

    # Verify thinking file was written
    assert thinking_path.exists()
    entries = [
        json.loads(line) for line in thinking_path.read_text().strip().splitlines()
    ]
    assert len(entries) == 1
    assert entries[0]["text"] == "Let me think about this..."
    assert "timestamp" in entries[0]


def test_write_codex_thinking_extracts_summary_text() -> None:
    """Test that _write_codex_thinking extracts text from summary parts."""
    f = StringIO()
    item = {
        "type": "reasoning",
        "id": "rs_001",
        "summary": [
            {"type": "summary_text", "text": "First thought"},
            {"type": "summary_text", "text": "Second thought"},
        ],
    }
    _write_codex_thinking(item, f)

    entries = [json.loads(line) for line in f.getvalue().strip().splitlines()]
    assert len(entries) == 1
    assert "First thought" in entries[0]["text"]
    assert "Second thought" in entries[0]["text"]


def test_write_codex_thinking_ignores_empty_summary() -> None:
    """Test that _write_codex_thinking skips items with no summary text."""
    f = StringIO()
    _write_codex_thinking({"type": "reasoning", "summary": []}, f)
    assert f.getvalue() == ""

    f2 = StringIO()
    _write_codex_thinking({"type": "reasoning"}, f2)
    assert f2.getvalue() == ""


def test_process_codex_json_line_writes_reasoning_to_thinking_file() -> None:
    """Test that _process_codex_json_line routes reasoning items to thinking_file."""
    assistant_texts: list[str] = []
    error_events: list[str] = []
    thinking_file = StringIO()

    line = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "reasoning",
                "id": "rs_001",
                "summary": [{"type": "summary_text", "text": "deep thoughts"}],
            },
        }
    )
    _process_codex_json_line(
        line, assistant_texts, True, error_events, None, thinking_file
    )

    assert len(assistant_texts) == 0  # Reasoning is not assistant text
    entries = [json.loads(ln) for ln in thinking_file.getvalue().strip().splitlines()]
    assert len(entries) == 1
    assert entries[0]["text"] == "deep thoughts"


def test_codex_reasoning_following_action_from_function_call() -> None:
    """Test that reasoning gets following_action when a function_call follows."""
    assistant_texts: list[str] = []
    thinking_file = StringIO()
    pending: list[dict[str, object]] = []

    # Send reasoning
    reasoning_line = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "thinking..."}],
            },
        }
    )
    _process_codex_json_line(
        reasoning_line, assistant_texts, True, None, None, thinking_file, pending
    )
    # Reasoning should be buffered, not written yet
    assert thinking_file.getvalue() == ""
    assert len(pending) == 1

    # Send function_call
    func_line = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "function_call",
                "name": "read_file",
                "arguments": '{"path": "/home/user/config.py"}',
            },
        }
    )
    _process_codex_json_line(
        func_line, assistant_texts, True, None, None, thinking_file, pending
    )

    # Reasoning should now be written with following_action
    entries = [json.loads(ln) for ln in thinking_file.getvalue().strip().splitlines()]
    assert len(entries) == 1
    assert entries[0]["text"] == "thinking..."
    assert entries[0]["following_action"] == "Read config.py"
    assert len(pending) == 0


def test_codex_reasoning_following_action_from_agent_message() -> None:
    """Test that reasoning gets text following_action when agent_message follows."""
    assistant_texts: list[str] = []
    thinking_file = StringIO()
    pending: list[dict[str, object]] = []

    # Send reasoning
    reasoning_line = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "deep thought"}],
            },
        }
    )
    _process_codex_json_line(
        reasoning_line, assistant_texts, True, None, None, thinking_file, pending
    )

    # Send agent_message
    msg_line = json.dumps(
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "Here is the answer"},
        }
    )
    _process_codex_json_line(
        msg_line, assistant_texts, True, None, None, thinking_file, pending
    )

    entries = [json.loads(ln) for ln in thinking_file.getvalue().strip().splitlines()]
    assert len(entries) == 1
    assert entries[0]["following_action"] == "Here is the answer"


def test_codex_consecutive_reasoning_flushes_previous() -> None:
    """Test that consecutive reasoning items flush the previous without action."""
    assistant_texts: list[str] = []
    thinking_file = StringIO()
    pending: list[dict[str, object]] = []

    # Send first reasoning
    r1 = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "thought 1"}],
            },
        }
    )
    _process_codex_json_line(
        r1, assistant_texts, True, None, None, thinking_file, pending
    )
    assert thinking_file.getvalue() == ""

    # Send second reasoning (should flush first without action)
    r2 = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "thought 2"}],
            },
        }
    )
    _process_codex_json_line(
        r2, assistant_texts, True, None, None, thinking_file, pending
    )

    entries = [json.loads(ln) for ln in thinking_file.getvalue().strip().splitlines()]
    assert len(entries) == 1
    assert entries[0]["text"] == "thought 1"
    assert "following_action" not in entries[0]

    # Flush remaining
    _flush_codex_reasoning(pending, thinking_file, None)
    entries = [json.loads(ln) for ln in thinking_file.getvalue().strip().splitlines()]
    assert len(entries) == 2
    assert entries[1]["text"] == "thought 2"


def test_write_codex_thinking_with_following_action() -> None:
    """Test that _write_codex_thinking includes following_action in JSONL."""
    f = StringIO()
    item = {
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "reasoning text"}],
    }
    _write_codex_thinking(item, f, following_action="Read config.py")

    entries = [json.loads(ln) for ln in f.getvalue().strip().splitlines()]
    assert len(entries) == 1
    assert entries[0]["following_action"] == "Read config.py"


def test_write_codex_thinking_omits_following_action_when_none() -> None:
    """Test that following_action key is absent when None."""
    f = StringIO()
    item = {
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "text"}],
    }
    _write_codex_thinking(item, f)

    entries = [json.loads(ln) for ln in f.getvalue().strip().splitlines()]
    assert "following_action" not in entries[0]
