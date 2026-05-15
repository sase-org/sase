"""Gemini stream-json tool-call artifact normalization."""

from __future__ import annotations

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

_GEMINI_DURATIONS = ToolCallDurationTracker()


def append_gemini_tool_call_event(event: Mapping[str, Any]) -> None:
    """Best-effort append of a Gemini tool event to ``tool_calls.jsonl``."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    try:
        record = _normalize_gemini_tool_call_event(event)
        if record is None:
            reason = _gemini_malformed_event_reason(event)
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


def _normalize_gemini_tool_call_event(
    event: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Convert a Gemini stream-json tool event into SASE's tool-call schema."""
    event_type = event.get("type")
    if event_type == "tool_use":
        return _normalize_gemini_tool_use(event)
    if event_type == "tool_result":
        return _normalize_gemini_tool_result(event)
    return None


def _normalize_gemini_tool_use(event: Mapping[str, Any]) -> dict[str, Any] | None:
    tool_use = _tool_payload(event, ("tool_use", "toolCall", "tool_call", "call"))
    raw_tool_name = _gemini_raw_tool_name(event, tool_use)
    tool_name = _gemini_display_tool_name(raw_tool_name)
    tool_use_id = _gemini_tool_use_id(event, tool_use)
    if not tool_name and not tool_use_id:
        return None

    tool_input = _gemini_tool_input(event, tool_use)
    record = _base_gemini_record(
        "ToolUse",
        "pending",
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        event=event,
    )
    record["tool_input_summary"] = summarize_tool_input(tool_name, tool_input)
    record["tool_response_summary"] = {}
    _GEMINI_DURATIONS.remember_start(tool_use_id)
    return record


def _normalize_gemini_tool_result(event: Mapping[str, Any]) -> dict[str, Any] | None:
    tool_result = _tool_payload(
        event, ("tool_result", "toolResult", "tool_response", "result")
    )
    raw_tool_name = _gemini_raw_tool_name(event, tool_result)
    tool_name = _gemini_display_tool_name(raw_tool_name)
    tool_use_id = _gemini_tool_use_id(event, tool_result)
    if not tool_name and not tool_use_id:
        return None

    tool_input = _gemini_tool_input(event, tool_result)
    tool_response = _gemini_tool_response(event, tool_result)
    status = _derive_gemini_result_status(event, tool_result)
    record = _base_gemini_record(
        "ToolResult",
        status,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        event=event,
    )
    record["tool_input_summary"] = summarize_tool_input(tool_name, tool_input)
    record["tool_response_summary"] = summarize_tool_response(
        tool_name=tool_name,
        tool_response=tool_response,
        error=_gemini_error_detail(event, tool_result),
        tool_result_content=event.get("content"),
        is_error=status == "failure",
        interrupted=status == "interrupted",
    )
    if status == "interrupted":
        record["is_interrupt"] = True
    _GEMINI_DURATIONS.record_duration(record, tool_use_id)
    return record


def _base_gemini_record(
    event_name: str,
    status: str,
    *,
    tool_name: str | None,
    tool_use_id: str | None,
    event: Mapping[str, Any],
) -> dict[str, Any]:
    return base_stream_tool_call_record(
        "gemini",
        event_name,
        status,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        session_id=string_or_none(event.get("session_id"))
        or string_or_none(event.get("sessionId")),
        cwd=string_or_none(event.get("cwd")),
    )


def _tool_payload(
    event: Mapping[str, Any],
    keys: tuple[str, ...],
) -> Mapping[str, Any]:
    for key in keys:
        value = event.get(key)
        if isinstance(value, Mapping):
            return value
    return event


def _gemini_raw_tool_name(
    event: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> str | None:
    for source in (payload, event):
        for key in ("name", "tool_name", "toolName", "display_name"):
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    function_call = payload.get("function_call") or payload.get("functionCall")
    if isinstance(function_call, Mapping):
        return string_or_none(function_call.get("name"))
    return None


def _gemini_tool_use_id(
    event: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> str | None:
    for source in (payload, event):
        for key in ("tool_id", "tool_use_id", "toolUseId", "call_id", "id"):
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _gemini_tool_input(
    event: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    for source in (payload, event):
        for key in ("input", "arguments", "args", "parameters"):
            value = source.get(key)
            if isinstance(value, Mapping):
                return dict(value)
    function_call = payload.get("function_call") or payload.get("functionCall")
    if isinstance(function_call, Mapping):
        args = function_call.get("args")
        if isinstance(args, Mapping):
            return dict(args)
    return {}


def _gemini_tool_response(
    event: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> Any:
    for source in (payload, event):
        for key in ("response", "output", "result", "content", "data"):
            if key in source:
                return source[key]
    return {}


def _derive_gemini_result_status(
    event: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> str:
    for source in (payload, event):
        raw_status = source.get("status")
        if isinstance(raw_status, str):
            normalized = raw_status.lower()
            if normalized in {"failed", "failure", "error"}:
                return "failure"
            if normalized in {"cancelled", "canceled", "interrupted"}:
                return "interrupted"
            if normalized in {"success", "succeeded", "ok", "completed"}:
                return "success"
        if source.get("is_error") is True or source.get("success") is False:
            return "failure"
    if _gemini_error_detail(event, payload):
        return "failure"
    return "success"


def _gemini_error_detail(
    event: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> Any:
    for source in (payload, event):
        for key in ("error", "error_message"):
            value = source.get(key)
            if value:
                return value
    return None


def _gemini_display_tool_name(tool_name: str | None) -> str | None:
    if not tool_name:
        return None
    normalized = tool_name.lower()
    if normalized in {
        "bash",
        "shell",
        "run_shell_command",
        "run_shell_command_impl",
        "execute_shell_command",
    }:
        return "Bash"
    if normalized in {"read", "read_file", "readfile"}:
        return "Read"
    if normalized in {"write", "write_file", "writefile"}:
        return "Write"
    if normalized in {"edit", "replace", "replace_file", "apply_patch"}:
        return "Edit"
    if normalized in {"grep", "search_file_content", "search_file_content_impl"}:
        return "Grep"
    if normalized in {"glob", "glob_tool", "glob_tool_impl"}:
        return "Glob"
    if normalized in {"web_fetch", "webfetch", "fetch"}:
        return "WebFetch"
    if normalized in {"web_search", "websearch", "google_web_search"}:
        return "WebSearch"
    return tool_name


def _gemini_malformed_event_reason(event: Mapping[str, Any]) -> str | None:
    if event.get("type") not in {"tool_use", "tool_result"}:
        return None
    payload = _tool_payload(
        event,
        (
            "tool_use",
            "toolCall",
            "tool_call",
            "call",
            "tool_result",
            "toolResult",
            "tool_response",
            "result",
        ),
    )
    if not _gemini_raw_tool_name(event, payload) and not _gemini_tool_use_id(
        event, payload
    ):
        return "gemini_tool_event_missing_tool_identity"
    return None


normalize_gemini_tool_call_event = _normalize_gemini_tool_call_event
