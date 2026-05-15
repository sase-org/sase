from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.ace.tui.models.agent import Agent, AgentType


def _agent(artifacts_dir: Path, **kwargs: Any) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="DONE",
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        artifacts_dir=str(artifacts_dir),
        raw_suffix=artifacts_dir.name,
        **kwargs,
    )


def _record(**overrides: Any) -> dict[str, Any]:
    """Build a legacy v1 hook-event record (still readable for back-compat)."""
    data: dict[str, Any] = {
        "schema_version": 1,
        "recorded_at": "2026-05-14T14:00:00+00:00",
        "runtime": "claude",
        "event": "PostToolUse",
        "status": "success",
        "tool_name": "Bash",
        "tool_use_id": "toolu_default",
        "tool_input_summary": {"command": "pytest tests/foo.py"},
        "tool_response_summary": {"exit_code": 0, "stdout_preview": "ok\n"},
    }
    data.update(overrides)
    return data


def _tool_use_record(
    *,
    tool_use_id: str,
    tool_name: str = "Bash",
    runtime: str = "claude",
    source: str | None = None,
    session_id: str | None = None,
    recorded_at: str = "2026-05-14T14:00:00+00:00",
    tool_input_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": 2,
        "recorded_at": recorded_at,
        "runtime": runtime,
        "event": "ToolUse",
        "status": "pending",
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "tool_input_summary": tool_input_summary or {"command": "pytest tests/foo.py"},
        "tool_response_summary": {},
    }
    if source is not None:
        record["source"] = source
    if session_id is not None:
        record["session_id"] = session_id
    return record


def _tool_result_record(
    *,
    tool_use_id: str,
    tool_name: str | None = None,
    runtime: str = "claude",
    source: str | None = None,
    session_id: str | None = None,
    status: str = "success",
    recorded_at: str = "2026-05-14T14:00:01+00:00",
    duration_ms: int | None = None,
    tool_input_summary: dict[str, Any] | None = None,
    tool_response_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": 2,
        "recorded_at": recorded_at,
        "runtime": runtime,
        "event": "ToolResult",
        "status": status,
        "tool_use_id": tool_use_id,
        "tool_input_summary": tool_input_summary or {},
        "tool_response_summary": tool_response_summary
        or {"stdout_preview": "ok\n", "exit_code": 0},
    }
    if tool_name is not None:
        record["tool_name"] = tool_name
    if source is not None:
        record["source"] = source
    if session_id is not None:
        record["session_id"] = session_id
    if duration_ms is not None:
        record["duration_ms"] = duration_ms
    return record


def _hook_pre_record(
    *,
    tool_use_id: str,
    tool_name: str = "Bash",
    recorded_at: str = "2026-05-14T14:00:00+00:00",
    tool_input_summary: dict[str, Any] | None = None,
    cwd: str = "/workspace",
    transcript_path: str = "/tmp/transcript.jsonl",
) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "recorded_at": recorded_at,
        "runtime": "claude",
        "source": "hook",
        "hook_event": "PreToolUse",
        "event": "ToolUse",
        "status": "pending",
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "session_id": "session-1",
        "transcript_path": transcript_path,
        "cwd": cwd,
        "tool_input_summary": tool_input_summary or {"command": "echo hi"},
        "tool_response_summary": {},
    }


def _hook_post_record(
    *,
    tool_use_id: str,
    tool_name: str = "Bash",
    status: str = "success",
    recorded_at: str = "2026-05-14T14:00:01+00:00",
    tool_input_summary: dict[str, Any] | None = None,
    tool_response_summary: dict[str, Any] | None = None,
    duration_ms: int | None = 42,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": 3,
        "recorded_at": recorded_at,
        "runtime": "claude",
        "source": "hook",
        "hook_event": "PostToolUse",
        "event": "ToolResult",
        "status": status,
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "session_id": "session-1",
        "tool_input_summary": tool_input_summary or {"command": "echo hi"},
        "tool_response_summary": tool_response_summary
        or {"exit_code": 0, "stdout_preview": "hi\n"},
    }
    if duration_ms is not None:
        record["duration_ms"] = duration_ms
    return record


def _write_jsonl(path: Path, records: list[dict[str, Any] | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            if isinstance(record, str):
                f.write(record + "\n")
            else:
                json.dump(record, f, sort_keys=True)
                f.write("\n")
