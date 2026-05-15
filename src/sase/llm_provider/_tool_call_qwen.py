"""Qwen Code tool-call artifact normalization."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ._tool_call_common import (
    ToolCallDurationTracker,
    base_stream_tool_call_record,
    derive_user_result_status,
    preview_text,
    result_envelope_is_interrupted,
    string_or_none,
    summarize_tool_input,
    summarize_tool_response,
)
from ._tool_call_io import (
    append_jsonl,
    append_tool_call_collector_diagnostic,
    append_writer_diagnostic,
)

_QWEN_DURATIONS = ToolCallDurationTracker()
_QWEN_TOOL_USE_EVENT_TYPES = frozenset(
    {"tool_use", "tool_call", "function_call", "function_call_start"}
)
_QWEN_TOOL_RESULT_EVENT_TYPES = frozenset(
    {"tool_result", "tool_response", "function_result", "function_call_result"}
)
_QWEN_EXPLICIT_TOOL_EVENT_TYPES = (
    _QWEN_TOOL_USE_EVENT_TYPES | _QWEN_TOOL_RESULT_EVENT_TYPES
)


def append_qwen_tool_call_event(event: Mapping[str, Any]) -> None:
    """Best-effort append of Qwen stream tool events to ``tool_calls.jsonl``."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    try:
        records, diagnostics = _normalize_qwen_tool_call_event_with_diagnostics(event)
        for diagnostic in diagnostics:
            append_tool_call_collector_diagnostic(
                artifacts_dir,
                reason=diagnostic["reason"],
                extra=diagnostic.get("extra"),
            )
        for record in records:
            append_jsonl(Path(artifacts_dir) / "tool_calls.jsonl", record)
    except Exception as exc:
        append_writer_diagnostic(artifacts_dir, event, exc)


def _normalize_qwen_tool_call_event(
    event: Mapping[str, Any],
) -> list[dict[str, Any]]:
    records, _diagnostics = _normalize_qwen_tool_call_event_with_diagnostics(event)
    return records


def _normalize_qwen_tool_call_event_with_diagnostics(
    event: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert Qwen stream-json events into SASE's tool-call schema.

    Qwen Code 0.15.10 emits Claude-style nested blocks:
    ``assistant.message.content[].type == "tool_use"`` and
    ``user.message.content[].type == "tool_result"``. The normalizer also
    accepts explicit top-level tool event variants seen in related stream-json
    CLIs.
    """
    records: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    for block in _qwen_tool_blocks(event):
        record, reason = _normalize_qwen_tool_block(event, block)
        if record is not None:
            records.append(record)
        elif reason:
            diagnostics.append(
                {
                    "reason": reason,
                    "extra": {
                        "event": string_or_none(event.get("type")) or "",
                        "block_type": string_or_none(block.get("type")) or "",
                    },
                }
            )

    event_type = string_or_none(event.get("type")) or ""
    if not records and not diagnostics and "tool" in event_type:
        diagnostics.append(
            {
                "reason": "qwen_unsupported_tool_event",
                "extra": {"event": event_type},
            }
        )

    return records, diagnostics


def _qwen_tool_blocks(event: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    event_type = string_or_none(event.get("type"))
    if event_type in _QWEN_EXPLICIT_TOOL_EVENT_TYPES:
        return [event]

    blocks: list[Mapping[str, Any]] = []
    message = event.get("message")
    if isinstance(message, Mapping):
        blocks.extend(_content_tool_blocks(message.get("content")))
    blocks.extend(_content_tool_blocks(event.get("content")))
    return blocks


def _content_tool_blocks(content: Any) -> list[Mapping[str, Any]]:
    if isinstance(content, Mapping):
        content_type = string_or_none(content.get("type"))
        return [content] if content_type in _QWEN_EXPLICIT_TOOL_EVENT_TYPES else []
    if not isinstance(content, list):
        return []

    blocks: list[Mapping[str, Any]] = []
    for block in content:
        if not isinstance(block, Mapping):
            continue
        if string_or_none(block.get("type")) in _QWEN_EXPLICIT_TOOL_EVENT_TYPES:
            blocks.append(block)
    return blocks


def _normalize_qwen_tool_block(
    event: Mapping[str, Any],
    block: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    block_type = string_or_none(block.get("type"))
    if block_type in _QWEN_TOOL_USE_EVENT_TYPES:
        record = _normalize_qwen_tool_use(event, block)
        return record, None if record is not None else "qwen_malformed_tool_use"
    if block_type in _QWEN_TOOL_RESULT_EVENT_TYPES:
        record = _normalize_qwen_tool_result(event, block)
        return record, None if record is not None else "qwen_malformed_tool_result"
    return None, "qwen_unsupported_tool_event"


def _normalize_qwen_tool_use(
    event: Mapping[str, Any],
    block: Mapping[str, Any],
) -> dict[str, Any] | None:
    raw_tool_name = _qwen_tool_name(block)
    tool_name = _qwen_display_tool_name(raw_tool_name)
    tool_use_id = _qwen_tool_use_id(block)
    if not raw_tool_name or not tool_use_id:
        return None

    tool_input = _normalize_qwen_tool_input(
        raw_tool_name,
        _qwen_tool_input(block),
    )
    record = _base_qwen_record(
        event,
        "ToolUse",
        "pending",
        tool_name=tool_name,
        tool_use_id=tool_use_id,
    )
    record["tool_input_summary"] = summarize_tool_input(tool_name, tool_input)
    record["tool_response_summary"] = {}
    _QWEN_DURATIONS.remember_start(tool_use_id)
    return record


def _normalize_qwen_tool_result(
    event: Mapping[str, Any],
    block: Mapping[str, Any],
) -> dict[str, Any] | None:
    tool_use_id = _qwen_tool_use_id(block)
    if not tool_use_id:
        return None

    raw_tool_name = _qwen_tool_name(block)
    tool_name = _qwen_display_tool_name(raw_tool_name)
    is_error = block.get("is_error") is True
    response = _qwen_tool_response(block)
    status = derive_user_result_status(
        is_error=is_error or _qwen_response_indicates_error(response),
        interrupted=result_envelope_is_interrupted(response),
    )
    record = _base_qwen_record(
        event,
        "ToolResult",
        status,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
    )
    tool_input = _normalize_qwen_tool_input(raw_tool_name, _qwen_tool_input(block))
    record["tool_input_summary"] = summarize_tool_input(tool_name, tool_input)
    record["tool_response_summary"] = summarize_tool_response(
        tool_name=tool_name,
        tool_response=response,
        is_error=status == "failure",
        interrupted=status == "interrupted",
    )
    if status == "interrupted":
        record["is_interrupt"] = True
    _QWEN_DURATIONS.record_duration(record, tool_use_id)
    return record


def _base_qwen_record(
    event: Mapping[str, Any],
    record_event: str,
    status: str,
    *,
    tool_name: str | None,
    tool_use_id: str | None,
) -> dict[str, Any]:
    return base_stream_tool_call_record(
        "qwen",
        record_event,
        status,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        session_id=string_or_none(event.get("session_id")),
        cwd=string_or_none(event.get("cwd")),
    )


def _qwen_tool_use_id(block: Mapping[str, Any]) -> str | None:
    for key in ("tool_use_id", "id", "call_id", "tool_call_id"):
        value = string_or_none(block.get(key))
        if value:
            return value
    nested = block.get("tool_use")
    if isinstance(nested, Mapping):
        return _qwen_tool_use_id(nested)
    return None


def _qwen_tool_name(block: Mapping[str, Any]) -> str | None:
    for key in ("name", "tool_name", "function_name"):
        value = string_or_none(block.get(key))
        if value:
            return value
    function = block.get("function")
    if isinstance(function, Mapping):
        return string_or_none(function.get("name"))
    nested = block.get("tool_use")
    if isinstance(nested, Mapping):
        return _qwen_tool_name(nested)
    return None


def _qwen_tool_input(block: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("input", "arguments", "args", "parameters"):
        parsed = _mapping_from_possible_json(block.get(key))
        if parsed:
            return parsed
    function = block.get("function")
    if isinstance(function, Mapping):
        parsed = _mapping_from_possible_json(function.get("arguments"))
        if parsed:
            return parsed
    nested = block.get("tool_use")
    if isinstance(nested, Mapping):
        return _qwen_tool_input(nested)
    return {}


def _qwen_tool_response(block: Mapping[str, Any]) -> Mapping[str, Any]:
    response: dict[str, Any] = {}
    for key in ("content", "result", "output", "response"):
        if key in block:
            response[_qwen_response_summary_key(key)] = block.get(key)
            break
    for key in ("is_error", "error", "success", "exit_code", "interrupted"):
        if key in block:
            response[key] = block.get(key)
    return response


def _qwen_response_summary_key(key: str) -> str:
    if key == "output":
        return "output"
    if key == "result":
        return "result"
    return "content"


def _qwen_response_indicates_error(response: Mapping[str, Any]) -> bool:
    if response.get("is_error") is True or response.get("success") is False:
        return True
    error = response.get("error")
    return isinstance(error, str) and bool(error)


def _mapping_from_possible_json(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def _normalize_qwen_tool_input(
    raw_tool_name: str | None,
    tool_input: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(tool_input)
    if raw_tool_name == "run_shell_command":
        return normalized
    if raw_tool_name in {"read_file", "write_file", "edit"}:
        path = normalized.get("path")
        if isinstance(path, str) and path and "file_path" not in normalized:
            normalized["file_path"] = path
    return normalized


def _qwen_display_tool_name(tool_name: str | None) -> str | None:
    if tool_name == "run_shell_command":
        return "Bash"
    if tool_name == "read_file":
        return "Read"
    if tool_name == "write_file":
        return "Write"
    if tool_name == "edit":
        return "Edit"
    if tool_name == "grep_search":
        return "Grep"
    if tool_name == "glob":
        return "Glob"
    if tool_name == "web_fetch":
        return "WebFetch"
    if tool_name == "web_search":
        return "WebSearch"
    if tool_name in {"agent", "task"}:
        return "Task"
    return preview_text(tool_name) if tool_name else None


normalize_qwen_tool_call_event = _normalize_qwen_tool_call_event
