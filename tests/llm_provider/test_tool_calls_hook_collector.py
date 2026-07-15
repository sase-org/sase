"""Tests for legacy Claude PreToolUse/PostToolUse schema-v3 normalization."""

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
    _HOOK_SCHEMA_VERSION,
    _PREVIEW_LIMIT,
    append_claude_hook_tool_call_event,
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


def _pre_payload(
    *,
    tool_name: str = "Bash",
    tool_input: dict[str, Any] | None = None,
    tool_use_id: str = "toolu_pre_1",
    session_id: str = "session-1",
) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": "/workspace",
        "tool_name": tool_name,
        "tool_input": tool_input if tool_input is not None else {"command": "ls"},
        "tool_use_id": tool_use_id,
    }


def _post_payload(
    *,
    tool_name: str = "Bash",
    tool_input: dict[str, Any] | None = None,
    tool_response: Any = None,
    tool_use_id: str = "toolu_pre_1",
    session_id: str = "session-1",
    error: str | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": "/workspace",
        "tool_name": tool_name,
        "tool_input": tool_input if tool_input is not None else {"command": "ls"},
        "tool_response": (
            tool_response
            if tool_response is not None
            else {"exit_code": 0, "stdout": "ok\n", "success": True}
        ),
        "tool_use_id": tool_use_id,
    }
    if error is not None:
        payload["error"] = error
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    return payload


# ---------------------------------------------------------------------------
# direct writer: PreToolUse / PostToolUse normalization
# ---------------------------------------------------------------------------


def test_pre_tool_use_emits_pending_v3_record(artifacts_dir: Path) -> None:
    append_claude_hook_tool_call_event(_pre_payload())

    records = _read_records(artifacts_dir / "tool_calls.jsonl")
    assert len(records) == 1
    record = records[0]
    assert record["schema_version"] == _HOOK_SCHEMA_VERSION
    assert record["source"] == "hook"
    assert record["hook_event"] == "PreToolUse"
    assert record["event"] == "ToolUse"
    assert record["status"] == "pending"
    assert record["tool_name"] == "Bash"
    assert record["tool_use_id"] == "toolu_pre_1"
    assert record["session_id"] == "session-1"
    assert record["transcript_path"] == "/tmp/transcript.jsonl"
    assert record["cwd"] == "/workspace"
    assert record["tool_input_summary"]["command"] == "ls"
    assert record["tool_response_summary"] == {}


def test_post_tool_use_success_record(artifacts_dir: Path) -> None:
    append_claude_hook_tool_call_event(_post_payload(duration_ms=42))

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    assert record["schema_version"] == _HOOK_SCHEMA_VERSION
    assert record["hook_event"] == "PostToolUse"
    assert record["event"] == "ToolResult"
    assert record["status"] == "success"
    assert record["duration_ms"] == 42
    assert record["tool_response_summary"]["exit_code"] == 0
    assert record["tool_response_summary"]["stdout_preview"] == "ok\n"


def test_post_tool_use_failure_via_tool_response(artifacts_dir: Path) -> None:
    append_claude_hook_tool_call_event(
        _post_payload(
            tool_response={"exit_code": 1, "stderr": "boom", "success": False}
        )
    )

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    assert record["status"] == "failure"
    assert record["tool_response_summary"]["stderr_preview"] == "boom"


def test_post_tool_use_failure_via_error_field(artifacts_dir: Path) -> None:
    append_claude_hook_tool_call_event(
        _post_payload(tool_response={}, error="Command exited non-zero")
    )

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    assert record["status"] == "failure"
    assert record["tool_response_summary"]["error"] == "Command exited non-zero"


def test_post_tool_use_interrupted_status(artifacts_dir: Path) -> None:
    append_claude_hook_tool_call_event(
        _post_payload(tool_response={"interrupted": True})
    )

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    assert record["status"] == "interrupted"
    assert record["is_interrupt"] is True


def test_unknown_hook_event_writes_diagnostic(artifacts_dir: Path) -> None:
    append_claude_hook_tool_call_event(
        {"hook_event_name": "SessionStart", "tool_name": "x"}
    )

    assert not (artifacts_dir / "tool_calls.jsonl").exists()
    diagnostics = _read_records(artifacts_dir / "tool_calls_writer_errors.jsonl")
    assert diagnostics
    assert "unsupported hook_event_name" in diagnostics[0]["error"]


def test_pre_tool_use_redacts_secrets_in_bash_command(artifacts_dir: Path) -> None:
    append_claude_hook_tool_call_event(
        _pre_payload(
            tool_name="Bash",
            tool_input={"command": "OPENAI_API_KEY=sk-secret echo hi"},
        )
    )

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    command = record["tool_input_summary"]["command"]
    assert "sk-secret" not in command
    assert command.startswith("OPENAI_API_KEY=[REDACTED]")


def test_pre_tool_use_truncates_large_input(artifacts_dir: Path) -> None:
    huge = "x" * (_PREVIEW_LIMIT + 1024)
    append_claude_hook_tool_call_event(
        _pre_payload(
            tool_name="Bash",
            tool_input={"command": huge},
        )
    )

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    command = record["tool_input_summary"]["command"]
    assert len(command) <= _PREVIEW_LIMIT + 80
    assert "truncated" in command


def test_post_tool_use_truncates_large_stdout(artifacts_dir: Path) -> None:
    huge = "".join(f"stdout-line-{index:03d}-{'y' * 24}\n" for index in range(80))
    append_claude_hook_tool_call_event(
        _post_payload(tool_response={"stdout": huge, "exit_code": 0, "success": True})
    )

    record = _read_records(artifacts_dir / "tool_calls.jsonl")[0]
    stdout_preview = record["tool_response_summary"]["stdout_preview"]
    assert stdout_preview.startswith("...[truncated ")
    assert "from the beginning" in stdout_preview.splitlines()[0]
    assert "stdout-line-000" not in stdout_preview
    assert "stdout-line-079" in stdout_preview
    assert len(stdout_preview.splitlines()[1:]) >= 50


def test_missing_artifacts_dir_noops_writer() -> None:
    with patch.dict(os.environ, {}, clear=True):
        # Must not raise even with a fully-valid payload.
        append_claude_hook_tool_call_event(_pre_payload())


def test_pre_then_post_records_are_independently_appended(
    artifacts_dir: Path,
) -> None:
    append_claude_hook_tool_call_event(_pre_payload(tool_use_id="toolu_xyz"))
    append_claude_hook_tool_call_event(
        _post_payload(
            tool_use_id="toolu_xyz",
            tool_response={"exit_code": 0, "success": True},
        )
    )

    records = _read_records(artifacts_dir / "tool_calls.jsonl")
    assert [r["event"] for r in records] == ["ToolUse", "ToolResult"]
    assert all(r["tool_use_id"] == "toolu_xyz" for r in records)
    assert records[0]["status"] == "pending"
    assert records[1]["status"] == "success"


# ---------------------------------------------------------------------------
# Reader compatibility: schema v3 records are accepted alongside v1/v2.
# ---------------------------------------------------------------------------


def test_reader_accepts_schema_v3() -> None:
    from sase.ace.tui.tools.reader import SUPPORTED_SCHEMA_VERSIONS

    assert 1 in SUPPORTED_SCHEMA_VERSIONS
    assert 2 in SUPPORTED_SCHEMA_VERSIONS
    assert 3 in SUPPORTED_SCHEMA_VERSIONS
