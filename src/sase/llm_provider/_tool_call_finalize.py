"""Best-effort reconciliation of interrupted tool-call artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._tool_call_common import base_stream_tool_call_record
from ._tool_call_io import append_jsonl, append_tool_call_collector_diagnostic

_SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2, 3})


def finalize_pending_tool_calls(
    artifacts_dir: str | Path | None,
    *,
    completed_at: float | datetime | None,
) -> None:
    """Append interrupted results for unmatched normalized ``ToolUse`` rows.

    Runner teardown must not fail because tool-call telemetry is missing or
    malformed, so every read/write failure is reduced to a collector
    diagnostic.
    """
    if not artifacts_dir:
        return

    artifacts_path = Path(artifacts_dir)
    tool_calls_path = artifacts_path / "tool_calls.jsonl"
    if not tool_calls_path.is_file():
        return

    try:
        records = _read_tool_call_records(tool_calls_path)
        orphaned = _orphaned_tool_uses(records)
        completed_at_text = _completed_at_text(completed_at)
        for orphan in orphaned:
            record = base_stream_tool_call_record(
                str(orphan["runtime"]),
                "ToolResult",
                "interrupted",
                tool_name=_optional_string(orphan.get("tool_name")),
                tool_use_id=str(orphan["tool_use_id"]),
                session_id=_optional_string(orphan.get("session_id")),
            )
            record.update(
                {
                    "recorded_at": completed_at_text,
                    "completed_at": completed_at_text,
                    "is_interrupt": True,
                    "tool_input_summary": {},
                    "tool_response_summary": {"interrupted": True},
                }
            )
            append_jsonl(tool_calls_path, record)
    except Exception as exc:
        append_tool_call_collector_diagnostic(
            str(artifacts_path),
            reason="finalize_pending_tool_calls_failed",
            raw_preview=str(exc),
        )


def _read_tool_call_records(path: Path) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, Mapping):
                continue
            if record.get("schema_version") not in _SUPPORTED_SCHEMA_VERSIONS:
                continue
            records.append(record)
    return records


def _orphaned_tool_uses(
    records: list[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    terminal_keys = {
        key
        for record in records
        if record.get("event") == "ToolResult"
        if (key := _tool_call_key(record)) is not None
    }
    orphaned_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in records:
        if record.get("event") != "ToolUse":
            continue
        key = _tool_call_key(record)
        if key is None or key in terminal_keys:
            continue
        orphaned_by_key.setdefault(key, record)
    return list(orphaned_by_key.values())


def _tool_call_key(record: Mapping[str, Any]) -> tuple[str, str] | None:
    runtime = record.get("runtime")
    tool_use_id = record.get("tool_use_id")
    if not isinstance(runtime, str) or not runtime:
        return None
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return None
    return runtime, tool_use_id


def _completed_at_text(value: float | datetime | None) -> str:
    if isinstance(value, int | float):
        completed_at = datetime.fromtimestamp(float(value), tz=UTC)
    elif isinstance(value, datetime):
        completed_at = value
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=UTC)
        completed_at = completed_at.astimezone(UTC)
    else:
        completed_at = datetime.now(tz=UTC)
    return completed_at.isoformat()


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = ["finalize_pending_tool_calls"]
