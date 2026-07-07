"""Parse and normalize tool-call JSONL artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._constants import KNOWN_STATUSES, SUPPORTED_SCHEMA_VERSIONS
from ._entry import ToolCallEntry


def derive_tool_call_status(record: Mapping[str, Any]) -> str:
    """Derive a known display status from a normalized artifact record."""
    raw_status = record.get("status")
    if isinstance(raw_status, str):
        normalized_status = raw_status.lower()
        if normalized_status in KNOWN_STATUSES:
            return normalized_status
        if normalized_status in {"failed", "error"}:
            return "failure"
        if normalized_status in {"cancelled", "canceled"}:
            return "interrupted"
        if normalized_status in {"in_progress", "running"}:
            return "pending"

    if record.get("is_interrupt") is True:
        return "interrupted"

    event = record.get("event")
    if event == "PostToolUseFailure":
        return "failure"
    if event in {"SubagentStart", "SubagentStop"}:
        return "subagent"
    if event == "ToolUse":
        return "pending"

    response = record.get("tool_response_summary")
    if isinstance(response, Mapping):
        if response.get("interrupted") is True:
            return "interrupted"
        if (
            response.get("success") is False
            or response.get("is_error") is True
            or response.get("error")
        ):
            return "failure"

    return "success"


def prefer_hook_records(entries: list[ToolCallEntry]) -> list[ToolCallEntry]:
    """Drop stream rows when an old hook row exists for the same call.

    New artifacts should not mix Claude stream and hook collection. This rule
    is retained for historical runs created while Claude hook collection was
    enabled, where both sources could describe one logical ``tool_use_id``.
    """
    hook_ids = {
        (entry.runtime, entry.tool_use_id)
        for entry in entries
        if entry.source == "hook" and entry.tool_use_id
    }
    if not hook_ids:
        return entries
    return [
        entry
        for entry in entries
        if (entry.runtime, entry.tool_use_id) not in hook_ids or entry.source == "hook"
    ]


def collapse_tool_use_pairs(
    entries: list[ToolCallEntry],
) -> list[ToolCallEntry]:
    """Merge ``ToolUse`` + ``ToolResult`` pairs with matching ``tool_use_id``.

    Orphan ``ToolUse`` rows (no result yet) are kept with status ``pending``.
    Other event types (``PostToolUse``, ``SubagentStart``, etc.) pass through
    unchanged. Schema-v1 records are returned as-is for back-compat.
    """
    starts_by_id: dict[tuple[str, str, str], int] = {}
    merged: list[ToolCallEntry | None] = list(entries)

    for index, entry in enumerate(entries):
        if entry.event == "ToolUse" and entry.tool_use_id:
            starts_by_id[_tool_pair_key(entry)] = index
            continue
        if entry.event == "ToolResult" and entry.tool_use_id:
            start_index = starts_by_id.pop(_tool_pair_key(entry), None)
            if start_index is None:
                continue
            start_entry = merged[start_index]
            if start_entry is None:
                continue
            merged[start_index] = _merge_use_and_result(start_entry, entry)
            merged[index] = None

    return _reconcile_incomplete_tool_uses(
        [entry for entry in merged if entry is not None]
    )


def _reconcile_incomplete_tool_uses(
    entries: list[ToolCallEntry],
) -> list[ToolCallEntry]:
    """Bound orphaned pending starts superseded by a later assistant message."""
    pending_by_stream: dict[tuple[str, str, str], list[int]] = {}
    reconciled: list[ToolCallEntry] = list(entries)

    for index, entry in enumerate(entries):
        if entry.event != "ToolUse":
            continue
        stream_key = _tool_stream_key(entry)
        if stream_key is None:
            continue

        pending_indexes = pending_by_stream.get(stream_key, [])
        still_pending: list[int] = []
        for pending_index in pending_indexes:
            pending_entry = reconciled[pending_index]
            if (
                pending_entry.status == "pending"
                and pending_entry.message_id
                and pending_entry.message_id != entry.message_id
                and entry.recorded_at
            ):
                reconciled[pending_index] = replace(
                    pending_entry,
                    status="incomplete",
                    completed_at=entry.recorded_at,
                )
            else:
                still_pending.append(pending_index)
        pending_by_stream[stream_key] = still_pending

        if entry.status == "pending":
            pending_by_stream[stream_key].append(index)

    return reconciled


def read_tool_call_file(
    path: Path,
    artifact_dir: Path,
    file_order: int,
) -> list[ToolCallEntry]:
    entries: list[ToolCallEntry] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                entry = _parse_tool_call_line(
                    line,
                    artifact_dir=artifact_dir,
                    source_path=path,
                    line_number=line_number,
                    file_order=file_order,
                )
                if entry is not None:
                    entries.append(entry)
    except OSError:
        return []
    return entries


def _parse_tool_call_line(
    line: str,
    *,
    artifact_dir: Path,
    source_path: Path,
    line_number: int,
    file_order: int,
) -> ToolCallEntry | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None

    if not isinstance(record, Mapping):
        return None
    if record.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        return None

    input_summary = _mapping_or_empty(record.get("tool_input_summary"))
    response_summary = _mapping_or_empty(record.get("tool_response_summary"))
    recorded_at = _str_or_empty(record.get("recorded_at"))
    return ToolCallEntry(
        recorded_at=recorded_at,
        runtime=_str_or_default(record.get("runtime"), "unknown"),
        event=_str_or_default(record.get("event"), "unknown"),
        status=derive_tool_call_status(record),
        tool_name=_str_or_none(record.get("tool_name")),
        tool_use_id=_str_or_none(record.get("tool_use_id")),
        duration_ms=_int_or_none(record.get("duration_ms")),
        completed_at=_str_or_none(record.get("completed_at")),
        tool_input_summary=input_summary,
        tool_response_summary=response_summary,
        session_id=_str_or_none(record.get("session_id")),
        transcript_path=_str_or_none(record.get("transcript_path")),
        cwd=_str_or_none(record.get("cwd")),
        permission_mode=_str_or_none(record.get("permission_mode")),
        agent_id=_str_or_none(record.get("agent_id")),
        agent_type=_str_or_none(record.get("agent_type")),
        parent_tool_use_id=_str_or_none(record.get("parent_tool_use_id")),
        message_id=_str_or_none(record.get("message_id")),
        error=_str_or_none(record.get("error")),
        is_interrupt=record.get("is_interrupt") is True,
        source=_str_or_none(record.get("source")),
        artifact_dir=str(artifact_dir),
        source_path=str(source_path),
        line_number=line_number,
        _recorded_at_sort=_parse_recorded_at(recorded_at),
        _file_order=file_order,
    )


def _tool_pair_key(entry: ToolCallEntry) -> tuple[str, str, str]:
    """Return the scope in which a provider tool-use id is unique."""
    scope = entry.session_id or entry.artifact_dir or ""
    return entry.runtime, entry.tool_use_id or "", scope


def _tool_stream_key(entry: ToolCallEntry) -> tuple[str, str, str] | None:
    """Return the logical stream scope for assistant-message ordering."""
    if not entry.session_id or not entry.message_id:
        return None
    return entry.runtime, entry.session_id, entry.parent_tool_use_id or ""


def _merge_use_and_result(start: ToolCallEntry, end: ToolCallEntry) -> ToolCallEntry:
    """Combine a ``ToolUse`` start entry with its matching ``ToolResult`` end."""
    response_summary: Mapping[str, Any] = end.tool_response_summary
    return ToolCallEntry(
        recorded_at=start.recorded_at,
        runtime=start.runtime,
        event="ToolUse",
        status=end.status if end.status in KNOWN_STATUSES else start.status,
        tool_name=start.tool_name or end.tool_name,
        tool_use_id=start.tool_use_id,
        duration_ms=start.duration_ms or end.duration_ms,
        completed_at=start.completed_at or end.completed_at or end.recorded_at,
        tool_input_summary=start.tool_input_summary or end.tool_input_summary,
        tool_response_summary=response_summary,
        session_id=start.session_id or end.session_id,
        transcript_path=start.transcript_path or end.transcript_path,
        cwd=start.cwd or end.cwd,
        permission_mode=start.permission_mode or end.permission_mode,
        agent_id=start.agent_id or end.agent_id,
        agent_type=start.agent_type or end.agent_type,
        parent_tool_use_id=start.parent_tool_use_id or end.parent_tool_use_id,
        message_id=start.message_id or end.message_id,
        error=start.error or end.error,
        is_interrupt=start.is_interrupt or end.is_interrupt,
        source=start.source or end.source,
        artifact_dir=start.artifact_dir,
        source_path=start.source_path,
        line_number=start.line_number,
        _recorded_at_sort=start._recorded_at_sort,
        _file_order=start._file_order,
    )


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _parse_recorded_at(value: str) -> datetime:
    if not value:
        return datetime.max.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.max.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _str_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _str_or_default(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
