"""Tests for the Claude tool-call writer that consumes stream-json events."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.llm_provider._tool_calls import (
    _normalize_claude_stream_event,
    append_claude_tool_call_event,
)


@pytest.fixture
def artifacts_dir() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": tmpdir}):
            yield Path(tmpdir)


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _assistant_event(
    tool_use_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    session_id: str = "session-1",
    parent_tool_use_id: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "id": "msg_1",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": tool_name,
                    "input": tool_input,
                }
            ],
        },
        "parent_tool_use_id": parent_tool_use_id,
        "session_id": session_id,
        "uuid": "uuid-1",
    }


def _user_result_event(
    tool_use_id: str,
    *,
    content: str | list[dict[str, Any]] = "ok",
    is_error: bool = False,
    tool_use_result: dict[str, Any] | None = None,
    parent_tool_use_id: str | None = None,
    session_id: str = "session-1",
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "tool_use_id": tool_use_id,
                    "type": "tool_result",
                    "content": content,
                    "is_error": is_error,
                }
            ],
        },
        "parent_tool_use_id": parent_tool_use_id,
        "session_id": session_id,
        "uuid": "uuid-2",
    }
    if tool_use_result is not None:
        event["tool_use_result"] = tool_use_result
    return event


# ---------------------------------------------------------------------------
# assistant events → ToolUse records
# ---------------------------------------------------------------------------


def test_assistant_event_emits_tool_use_record(artifacts_dir: Path) -> None:
    event = _assistant_event(
        "toolu_bash",
        "Bash",
        {
            "command": "OPENAI_API_KEY=sk-secret echo hi",
            "description": "demo",
        },
    )
    append_claude_tool_call_event(event)

    records = _read_records(artifacts_dir / "tool_calls.jsonl")
    assert len(records) == 1
    record = records[0]
    assert record["schema_version"] == 2
    assert record["runtime"] == "claude"
    assert record["event"] == "ToolUse"
    assert record["status"] == "pending"
    assert record["tool_name"] == "Bash"
    assert record["tool_use_id"] == "toolu_bash"
    assert record["session_id"] == "session-1"
    assert "sk-secret" not in record["tool_input_summary"]["command"]
    assert record["tool_input_summary"]["command"].startswith(
        "OPENAI_API_KEY=[REDACTED]"
    )
    assert record["tool_response_summary"] == {}


def test_assistant_event_with_multiple_tool_uses(artifacts_dir: Path) -> None:
    event = {
        "type": "assistant",
        "message": {
            "id": "msg_2",
            "content": [
                {"type": "text", "text": "thinking..."},
                {
                    "type": "tool_use",
                    "id": "toolu_a",
                    "name": "Read",
                    "input": {"file_path": "src/sase/foo.py"},
                },
                {
                    "type": "tool_use",
                    "id": "toolu_b",
                    "name": "Grep",
                    "input": {"pattern": "TODO", "path": "src/"},
                },
            ],
        },
        "session_id": "session-2",
        "uuid": "uuid-x",
    }
    append_claude_tool_call_event(event)

    records = _read_records(artifacts_dir / "tool_calls.jsonl")
    assert [r["tool_use_id"] for r in records] == ["toolu_a", "toolu_b"]
    assert records[0]["tool_name"] == "Read"
    assert records[1]["tool_name"] == "Grep"
    assert records[0]["tool_input_summary"]["file_path"] == "src/sase/foo.py"
    assert records[1]["tool_input_summary"]["pattern"] == "TODO"


def test_assistant_event_with_parent_tool_use_id(artifacts_dir: Path) -> None:
    event = _assistant_event(
        "toolu_child",
        "Bash",
        {"command": "ls"},
        parent_tool_use_id="toolu_parent_task",
    )
    append_claude_tool_call_event(event)

    records = _read_records(artifacts_dir / "tool_calls.jsonl")
    assert records[0]["parent_tool_use_id"] == "toolu_parent_task"


def test_assistant_event_task_subagent_records_prompt_length(
    artifacts_dir: Path,
) -> None:
    event = _assistant_event(
        "toolu_task",
        "Task",
        {
            "subagent_type": "general-purpose",
            "description": "Find files",
            "prompt": "x" * 200,
        },
    )
    append_claude_tool_call_event(event)

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    assert record["tool_name"] == "Task"
    assert record["tool_input_summary"]["subagent_type"] == "general-purpose"
    assert record["tool_input_summary"]["prompt_length"] == 200


def test_assistant_event_unknown_tool_records_input_keys(
    artifacts_dir: Path,
) -> None:
    event = _assistant_event(
        "toolu_mcp",
        "mcp__memory__create_entities",
        {"entities": [{"name": "secret"}], "dry_run": True},
    )
    append_claude_tool_call_event(event)

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    assert record["tool_name"] == "mcp__memory__create_entities"
    assert record["tool_input_summary"] == {"input_keys": ["dry_run", "entities"]}


# ---------------------------------------------------------------------------
# user events → ToolResult records
# ---------------------------------------------------------------------------


def test_user_event_emits_tool_result_record(artifacts_dir: Path) -> None:
    event = _user_result_event(
        "toolu_bash",
        content="hello\n",
        tool_use_result={
            "stdout": "hello\n",
            "stderr": "",
            "interrupted": False,
            "isImage": False,
        },
    )
    append_claude_tool_call_event(event)

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    assert record["event"] == "ToolResult"
    assert record["status"] == "success"
    assert record["tool_use_id"] == "toolu_bash"
    assert record["tool_response_summary"]["stdout_preview"] == "hello\n"


def test_user_event_is_error_records_failure(artifacts_dir: Path) -> None:
    event = _user_result_event(
        "toolu_x",
        content="boom",
        is_error=True,
        tool_use_result={"stderr": "boom", "interrupted": False},
    )
    append_claude_tool_call_event(event)

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    assert record["status"] == "failure"


def test_user_event_interrupted_records_interrupted(artifacts_dir: Path) -> None:
    event = _user_result_event(
        "toolu_y",
        content="cancelled",
        tool_use_result={"interrupted": True},
    )
    append_claude_tool_call_event(event)

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    assert record["status"] == "interrupted"
    assert record["is_interrupt"] is True


def test_user_event_without_envelope_falls_back_to_content_preview(
    artifacts_dir: Path,
) -> None:
    event = _user_result_event("toolu_z", content="just text")
    append_claude_tool_call_event(event)

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    assert record["tool_response_summary"]["content_preview"] == "just text"


def test_user_event_list_content_blocks_concatenated(artifacts_dir: Path) -> None:
    event = _user_result_event(
        "toolu_list",
        content=[{"type": "text", "text": "alpha"}, {"type": "text", "text": "beta"}],
    )
    append_claude_tool_call_event(event)

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    assert record["tool_response_summary"]["content_preview"] == "alpha\nbeta"


# ---------------------------------------------------------------------------
# system hook-event enrichment
# ---------------------------------------------------------------------------


def test_system_hook_response_post_tool_use_emits_record(
    artifacts_dir: Path,
) -> None:
    event = {
        "type": "system",
        "subtype": "hook_response",
        "hook_id": "h1",
        "hook_name": "PostToolUse:Bash",
        "hook_event": "PostToolUse",
        "tool_use_id": "toolu_bash",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "tool_response": {"exit_code": 0, "stdout": "ok\n", "success": True},
        "duration_ms": 123,
        "session_id": "session-1",
    }
    append_claude_tool_call_event(event)

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    assert record["event"] == "PostToolUse"
    assert record["status"] == "success"
    assert record["duration_ms"] == 123
    assert record["tool_use_id"] == "toolu_bash"


def test_system_hook_response_post_tool_use_failure(artifacts_dir: Path) -> None:
    event = {
        "type": "system",
        "subtype": "hook_response",
        "hook_event": "PostToolUseFailure",
        "tool_use_id": "toolu_failed",
        "tool_name": "Bash",
        "error": "Command exited with non-zero status code 4",
        "is_interrupt": False,
        "duration_ms": 900,
    }
    append_claude_tool_call_event(event)

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    assert record["event"] == "PostToolUseFailure"
    assert record["status"] == "failure"
    assert (
        record["tool_response_summary"]["error"]
        == "Command exited with non-zero status code 4"
    )
    assert record["is_interrupt"] is False


def test_system_hook_started_for_tool_event_is_ignored(artifacts_dir: Path) -> None:
    event = {
        "type": "system",
        "subtype": "hook_started",
        "hook_event": "PostToolUse",
        "tool_use_id": "toolu_x",
    }
    append_claude_tool_call_event(event)

    assert not (artifacts_dir / "tool_calls.jsonl").exists()


def test_system_hook_started_for_subagent_event_is_captured(
    artifacts_dir: Path,
) -> None:
    event = {
        "type": "system",
        "subtype": "hook_started",
        "hook_event": "SubagentStart",
        "agent_id": "agent-1",
        "agent_type": "Explore",
        "session_id": "session-1",
    }
    append_claude_tool_call_event(event)

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    assert record["event"] == "SubagentStart"
    assert record["status"] == "subagent"
    assert record["agent_id"] == "agent-1"
    assert record["agent_type"] == "Explore"


def test_system_unknown_hook_event_is_ignored(artifacts_dir: Path) -> None:
    event = {
        "type": "system",
        "subtype": "hook_response",
        "hook_event": "SessionStart",
        "hook_name": "SessionStart:startup",
    }
    append_claude_tool_call_event(event)

    assert not (artifacts_dir / "tool_calls.jsonl").exists()


# ---------------------------------------------------------------------------
# graceful handling of irrelevant or malformed events
# ---------------------------------------------------------------------------


def test_irrelevant_events_are_silently_ignored(artifacts_dir: Path) -> None:
    for event in (
        {"type": "result", "usage": {"input_tokens": 1}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
        {"type": "user", "message": {"content": []}},
        {"type": "system", "subtype": "hook_response"},  # missing hook_event
        {},
    ):
        append_claude_tool_call_event(event)

    assert not (artifacts_dir / "tool_calls.jsonl").exists()
    assert not (artifacts_dir / "tool_calls_writer_errors.jsonl").exists()


def test_missing_artifacts_dir_noops() -> None:
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("sase.llm_provider._tool_calls._append_jsonl") as mock_append,
    ):
        append_claude_tool_call_event({"type": "assistant", "message": {"content": []}})

    mock_append.assert_not_called()


# ---------------------------------------------------------------------------
# SASE_TOOL_LOG_FULL raw capture
# ---------------------------------------------------------------------------


def test_sase_tool_log_full_includes_raw_input(artifacts_dir: Path) -> None:
    event = _assistant_event(
        "toolu_full",
        "Bash",
        {"command": "echo hi", "description": "demo"},
    )
    with patch.dict(os.environ, {"SASE_TOOL_LOG_FULL": "1"}):
        append_claude_tool_call_event(event)

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    assert "raw" in record["tool_input_summary"]
    assert record["tool_input_summary"]["raw"]["command"] == "echo hi"


# ---------------------------------------------------------------------------
# _normalize_claude_stream_event direct call (unit-level)
# ---------------------------------------------------------------------------


def test_normalize_claude_stream_event_assistant_then_user() -> None:
    assistant_records = _normalize_claude_stream_event(
        _assistant_event("toolu_1", "Read", {"file_path": "a.py"})
    )
    user_records = _normalize_claude_stream_event(
        _user_result_event(
            "toolu_1",
            content="content",
            tool_use_result={"content": "content"},
        )
    )

    assert [r["event"] for r in assistant_records] == ["ToolUse"]
    assert [r["event"] for r in user_records] == ["ToolResult"]
    assert assistant_records[0]["tool_use_id"] == "toolu_1"
    assert user_records[0]["tool_use_id"] == "toolu_1"
