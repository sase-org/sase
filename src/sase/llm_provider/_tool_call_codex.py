"""Codex tool-call artifact normalization."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ._tool_call_common import (
    ToolCallDurationTracker,
    base_stream_tool_call_record,
    string_or_none,
    summarize_tool_input,
    summarize_tool_response,
)
from ._tool_call_io import (
    append_jsonl,
    append_tool_call_collector_diagnostic,
    append_writer_diagnostic,
)

_CODEX_DURATIONS = ToolCallDurationTracker()
_CODEX_FILE_WRITE_KINDS = frozenset({"add", "create", "write"})
_CODEX_FILE_EDIT_KINDS = frozenset({"delete", "modify", "remove", "update"})


def append_codex_tool_call_event(event: Mapping[str, Any]) -> None:
    """Best-effort append of a Codex tool event to ``tool_calls.jsonl``."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    try:
        record = _normalize_codex_tool_call_event(event)
        if record is None:
            reason = _codex_malformed_event_reason(event)
            if reason:
                append_tool_call_collector_diagnostic(
                    artifacts_dir,
                    reason=reason,
                    extra={"event": string_or_none(event.get("type")) or ""},
                )
            return
        append_jsonl(Path(artifacts_dir) / "tool_calls.jsonl", record)
    except Exception as exc:
        append_writer_diagnostic(artifacts_dir, event, exc)


def _normalize_codex_tool_call_event(
    event: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Convert a Codex stream item into SASE's tool-call schema."""
    event_type = event.get("type")
    if event_type not in {"item.started", "item.completed"}:
        return None

    item = event.get("item")
    if not isinstance(item, Mapping):
        return None

    item_type = string_or_none(item.get("type"))
    if event_type == "item.completed" and item_type == "function_call":
        return _normalize_legacy_function_call_item(item)
    if item_type == "command_execution":
        return _normalize_command_execution_item(event_type, item)
    if item_type == "file_change":
        return _normalize_file_change_item(event_type, item)
    if _is_named_tool_item(item):
        return _normalize_named_tool_item(event_type, item)
    return None


def _normalize_legacy_function_call_item(item: Mapping[str, Any]) -> dict[str, Any]:
    raw_tool_name = string_or_none(item.get("name"))
    tool_name = _codex_display_tool_name(raw_tool_name)
    tool_input = _normalize_codex_tool_input(
        raw_tool_name,
        _parse_codex_arguments(item.get("arguments")),
    )
    record = _base_codex_record(
        "FunctionCall",
        _derive_codex_status(item),
        tool_name=tool_name,
        tool_use_id=_codex_tool_use_id(item),
    )
    record.update(
        {
            "tool_input_summary": summarize_tool_input(tool_name, tool_input),
            "tool_response_summary": {},
        }
    )
    return record


def _normalize_command_execution_item(
    event_type: object,
    item: Mapping[str, Any],
) -> dict[str, Any]:
    tool_name = "Bash"
    tool_use_id = _codex_tool_use_id(item)
    tool_input = {"command": item.get("command")}
    if event_type == "item.started":
        record = _base_codex_record(
            "ToolUse",
            "pending",
            tool_name=tool_name,
            tool_use_id=tool_use_id,
        )
        record["tool_input_summary"] = summarize_tool_input(tool_name, tool_input)
        record["tool_response_summary"] = {}
        _remember_start_time(tool_use_id)
        return record

    response = {
        "exit_code": item.get("exit_code"),
        "output": item.get("aggregated_output"),
        "success": _derive_codex_status(item) == "success",
    }
    record = _base_codex_result_record(
        item,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        tool_input=tool_input,
        tool_response=response,
    )
    _record_duration(record, tool_use_id)
    return record


def _normalize_file_change_item(
    event_type: object,
    item: Mapping[str, Any],
) -> dict[str, Any]:
    tool_input = _codex_file_change_input(item)
    tool_name = _codex_file_change_tool_name(item)
    tool_use_id = _codex_tool_use_id(item)
    if event_type == "item.started":
        record = _base_codex_record(
            "ToolUse",
            "pending",
            tool_name=tool_name,
            tool_use_id=tool_use_id,
        )
        record["tool_input_summary"] = summarize_tool_input(tool_name, tool_input)
        record["tool_response_summary"] = {}
        _remember_start_time(tool_use_id)
        return record

    response = {
        "file_path": tool_input.get("file_path"),
        "success": _derive_codex_status(item) == "success",
        "structuredPatch": False,
    }
    record = _base_codex_result_record(
        item,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        tool_input=tool_input,
        tool_response=response,
    )
    _record_duration(record, tool_use_id)
    return record


def _normalize_named_tool_item(
    event_type: object,
    item: Mapping[str, Any],
) -> dict[str, Any]:
    raw_tool_name = string_or_none(item.get("name"))
    tool_name = _codex_display_tool_name(raw_tool_name)
    tool_use_id = _codex_tool_use_id(item)
    tool_input = _normalize_codex_tool_input(
        raw_tool_name,
        _parse_codex_arguments(item.get("arguments")),
    )
    if event_type == "item.started":
        record = _base_codex_record(
            "ToolUse",
            "pending",
            tool_name=tool_name,
            tool_use_id=tool_use_id,
        )
        record["tool_input_summary"] = summarize_tool_input(tool_name, tool_input)
        record["tool_response_summary"] = {}
        _remember_start_time(tool_use_id)
        return record

    output = item.get("output")
    record = _base_codex_result_record(
        item,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        tool_input=tool_input,
        tool_response=output if output is not None else {},
    )
    _record_duration(record, tool_use_id)
    return record


def _base_codex_result_record(
    item: Mapping[str, Any],
    *,
    tool_name: str | None,
    tool_use_id: str | None,
    tool_input: Mapping[str, Any],
    tool_response: Any,
) -> dict[str, Any]:
    record = _base_codex_record(
        "ToolResult",
        _derive_codex_status(item),
        tool_name=tool_name,
        tool_use_id=tool_use_id,
    )
    record["tool_input_summary"] = summarize_tool_input(tool_name, tool_input)
    record["tool_response_summary"] = summarize_tool_response(
        tool_name=tool_name,
        tool_response=tool_response,
        is_error=record["status"] == "failure",
        interrupted=record["status"] == "interrupted",
    )
    if record["status"] == "interrupted":
        record["is_interrupt"] = True
    return record


def _base_codex_record(
    event: str,
    status: str,
    *,
    tool_name: str | None,
    tool_use_id: str | None,
) -> dict[str, Any]:
    return base_stream_tool_call_record(
        "codex",
        event,
        status,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
    )


def _codex_tool_use_id(item: Mapping[str, Any]) -> str | None:
    for key in ("call_id", "id"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _codex_display_tool_name(tool_name: str | None) -> str | None:
    if tool_name in {"shell", "container.exec", "command_execution"}:
        return "Bash"
    if tool_name == "read_file":
        return "Read"
    if tool_name == "write_file":
        return "Write"
    if tool_name in {"apply_patch", "apply_diff", "file_change"}:
        return "Edit"
    return tool_name


def _parse_codex_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    if isinstance(arguments, Mapping):
        return dict(arguments)
    return {}


def _normalize_codex_tool_input(
    raw_tool_name: str | None,
    tool_input: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(tool_input)

    if raw_tool_name in {"shell", "container.exec"}:
        command = normalized.get("command")
        if isinstance(command, list):
            normalized["command"] = " ".join(str(part) for part in command)
        return normalized

    if raw_tool_name in {"read_file", "write_file", "apply_patch", "apply_diff"}:
        path = normalized.get("path")
        if isinstance(path, str) and path and "file_path" not in normalized:
            normalized["file_path"] = path

    return normalized


def _derive_codex_status(item: Mapping[str, Any]) -> str:
    raw_status = item.get("status")
    if isinstance(raw_status, str):
        normalized = raw_status.lower()
        if normalized in {"failed", "failure", "error"}:
            return "failure"
        if normalized in {"cancelled", "canceled", "interrupted"}:
            return "interrupted"

    exit_code = item.get("exit_code")
    if (
        isinstance(exit_code, int)
        and not isinstance(exit_code, bool)
        and exit_code != 0
    ):
        return "failure"
    return "success"


def _codex_file_change_input(item: Mapping[str, Any]) -> dict[str, Any]:
    changes = item.get("changes")
    if not isinstance(changes, list):
        return {}

    normalized_changes = [change for change in changes if isinstance(change, Mapping)]
    paths = [
        path
        for change in normalized_changes
        if isinstance((path := change.get("path")), str) and path
    ]
    result: dict[str, Any] = {}
    if paths:
        result["file_path"] = paths[0]
    if len(normalized_changes) > 1:
        result["edits"] = [
            {"old_string": "", "new_string": ""} for _change in normalized_changes
        ]
    return result


def _codex_file_change_tool_name(item: Mapping[str, Any]) -> str:
    changes = item.get("changes")
    if not isinstance(changes, list):
        return "Edit"
    normalized_changes = [change for change in changes if isinstance(change, Mapping)]
    if len(normalized_changes) > 1:
        return "MultiEdit"
    kind = None
    if normalized_changes:
        raw_kind = normalized_changes[0].get("kind")
        kind = raw_kind.lower() if isinstance(raw_kind, str) else None
    if kind in _CODEX_FILE_WRITE_KINDS:
        return "Write"
    if kind in _CODEX_FILE_EDIT_KINDS:
        return "Edit"
    return "Edit"


def _is_named_tool_item(item: Mapping[str, Any]) -> bool:
    return string_or_none(item.get("name")) is not None


def _remember_start_time(tool_use_id: str | None) -> None:
    _CODEX_DURATIONS.remember_start(tool_use_id)


def _record_duration(record: dict[str, Any], tool_use_id: str | None) -> None:
    _CODEX_DURATIONS.record_duration(record, tool_use_id)


def _codex_malformed_event_reason(event: Mapping[str, Any]) -> str | None:
    if event.get("type") not in {"item.started", "item.completed"}:
        return None
    if not isinstance(event.get("item"), Mapping):
        return "codex_item_event_missing_item"
    return None


normalize_codex_tool_call_event = _normalize_codex_tool_call_event
