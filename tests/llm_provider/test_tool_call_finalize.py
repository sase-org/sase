"""Tests for interrupted tool-call reconciliation at runner teardown."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.ace.tui.tools.reader import read_tool_calls_for_agent
from sase.llm_provider._tool_calls import finalize_pending_tool_calls


class _Agent:
    def __init__(self, artifacts_dir: Path) -> None:
        self._artifacts_dir = artifacts_dir

    def get_artifacts_dir(self) -> str:
        return str(self._artifacts_dir)


def _record(
    event: str,
    status: str,
    tool_use_id: str,
    *,
    runtime: str = "codex",
    tool_name: str = "Bash",
    session_id: str = "session-1",
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "recorded_at": "2026-07-11T12:00:00+00:00",
        "runtime": runtime,
        "source": "stream",
        "event": event,
        "status": status,
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "session_id": session_id,
        "tool_input_summary": {"command": "sase plan propose plan.md"},
        "tool_response_summary": {},
    }


def _write_records(path: Path, records: list[dict[str, Any] | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            if isinstance(record, str):
                stream.write(record + "\n")
            else:
                stream.write(json.dumps(record, sort_keys=True) + "\n")


def _read_records(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip().startswith("{")]


def test_finalize_closes_only_unmatched_tool_uses_and_is_idempotent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tool_calls.jsonl"
    records: list[dict[str, Any] | str] = [
        _record("ToolUse", "pending", "orphan"),
        _record("ToolUse", "pending", "matched"),
        _record("ToolResult", "success", "matched"),
        {
            **_record("SubagentStart", "subagent", "subagent"),
            "event": "SubagentStart",
        },
        "not-json",
        json.dumps({"schema_version": 99, "event": "ToolUse"}),
    ]
    _write_records(path, records)
    completed_at = datetime(2026, 7, 11, 12, 0, 5, tzinfo=UTC)

    finalize_pending_tool_calls(tmp_path, completed_at=completed_at)
    finalized_once = path.read_text(encoding="utf-8")
    finalize_pending_tool_calls(tmp_path, completed_at=completed_at)

    assert path.read_text(encoding="utf-8") == finalized_once
    parsed = _read_records(path)
    synthetic = [record for record in parsed if record.get("status") == "interrupted"]
    assert len(synthetic) == 1
    assert synthetic[0] == {
        "completed_at": completed_at.isoformat(),
        "event": "ToolResult",
        "is_interrupt": True,
        "recorded_at": completed_at.isoformat(),
        "runtime": "codex",
        "schema_version": 2,
        "session_id": "session-1",
        "source": "stream",
        "status": "interrupted",
        "tool_input_summary": {},
        "tool_name": "Bash",
        "tool_response_summary": {"interrupted": True},
        "tool_use_id": "orphan",
    }

    entries = read_tool_calls_for_agent(_Agent(tmp_path), artifact_dirs=[tmp_path])
    assert entries is not None
    orphan = next(entry for entry in entries if entry.tool_use_id == "orphan")
    assert orphan.event == "ToolUse"
    assert orphan.status == "interrupted"
    assert orphan.completed_at == completed_at.isoformat()
    assert orphan.is_interrupt is True


def test_finalize_missing_tool_calls_file_is_noop(tmp_path: Path) -> None:
    finalize_pending_tool_calls(tmp_path, completed_at=None)

    assert list(tmp_path.iterdir()) == []
