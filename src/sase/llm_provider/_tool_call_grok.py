"""Grok Build tool-call artifact normalization."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._tool_call_common import (
    ToolCallDurationTracker,
    base_stream_tool_call_record,
    derive_user_result_status,
    preview_text,
    result_envelope_indicates_error,
    result_envelope_is_interrupted,
    string_or_none,
    summarize_tool_input,
    summarize_tool_response,
)
from ._tool_call_io import append_jsonl, append_writer_diagnostic

_GROK_DURATIONS = ToolCallDurationTracker()
_GROK_TOOL_DISPLAY_NAMES = {
    "run_terminal_command": "Bash",
    "read_file": "Read",
    "write": "Write",
    "search_replace": "Edit",
    "grep": "Grep",
    "list_dir": "Glob",
    "web_fetch": "WebFetch",
    "web_search": "WebSearch",
    "spawn_subagent": "Task",
    "todo_write": "TodoWrite",
}
_GROK_RESULT_DISPLAY_NAMES = {
    "Bash": "Bash",
    "Read": "Read",
    "Write": "Write",
    "SearchReplace": "Edit",
    "Grep": "Grep",
    "Glob": "Glob",
    "WebFetch": "WebFetch",
    "WebSearch": "WebSearch",
    "Task": "Task",
}


@dataclass(frozen=True)
class _GrokToolUse:
    raw_tool_name: str
    tool_name: str
    tool_input: Mapping[str, Any]


# Grok reports a tool_use and its tool_result in two separate stream events, so
# the use has to be carried across them. Entries are popped when their result
# arrives -- same lifecycle as ``ToolCallDurationTracker`` -- leaving only
# genuinely in-flight calls behind; without the pop this module-global would
# retain every tool input for the life of the process.
_GROK_TOOL_USES: dict[str, _GrokToolUse] = {}


def append_grok_tool_call_event(event: Mapping[str, Any]) -> None:
    """Best-effort append of Grok stream tool events to ``tool_calls.jsonl``."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    try:
        records = _normalize_grok_tool_call_event(event)
        if not records:
            return
        path = Path(artifacts_dir) / "tool_calls.jsonl"
        for record in records:
            append_jsonl(path, record)
    except Exception as exc:
        append_writer_diagnostic(artifacts_dir, event, exc)


def _normalize_grok_tool_call_event(
    event: Mapping[str, Any],
) -> list[dict[str, Any]]:
    event_type = event.get("type")
    if event_type == "assistant":
        return _records_from_assistant_event(event)
    if event_type == "user":
        return _records_from_user_event(event)
    return []


def _records_from_assistant_event(
    event: Mapping[str, Any],
) -> list[dict[str, Any]]:
    message = event.get("message")
    if not isinstance(message, Mapping):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []

    session_id = string_or_none(event.get("session_id"))
    cwd = string_or_none(event.get("cwd"))
    parent_tool_use_id = string_or_none(event.get("parent_tool_use_id"))
    message_id = string_or_none(message.get("id"))
    message_uuid = string_or_none(event.get("uuid"))

    records: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "tool_use":
            continue
        raw_tool_name = string_or_none(block.get("name"))
        tool_use_id = string_or_none(block.get("id"))
        if not raw_tool_name or not tool_use_id:
            continue

        tool_name = _grok_display_tool_name(raw_tool_name)
        tool_input = _normalize_grok_tool_input(
            raw_tool_name,
            _mapping_from_possible_json(block.get("input")),
        )
        record = _base_grok_record(
            "ToolUse",
            "pending",
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            session_id=session_id,
            cwd=cwd,
            parent_tool_use_id=parent_tool_use_id,
            message_id=message_id,
            message_uuid=message_uuid,
        )
        record["tool_input_summary"] = summarize_tool_input(tool_name, tool_input)
        record["tool_response_summary"] = {}
        records.append(record)
        _GROK_DURATIONS.remember_start(tool_use_id)
        _GROK_TOOL_USES[tool_use_id] = _GrokToolUse(
            raw_tool_name=raw_tool_name,
            tool_name=tool_name,
            tool_input=tool_input,
        )
    return records


def _records_from_user_event(
    event: Mapping[str, Any],
) -> list[dict[str, Any]]:
    message = event.get("message")
    if not isinstance(message, Mapping):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []

    session_id = string_or_none(event.get("session_id"))
    cwd = string_or_none(event.get("cwd"))
    parent_tool_use_id = string_or_none(event.get("parent_tool_use_id"))
    message_uuid = string_or_none(event.get("uuid"))

    records: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "tool_result":
            continue
        tool_use_id = string_or_none(block.get("tool_use_id"))
        if not tool_use_id:
            continue

        tool_use = _GROK_TOOL_USES.pop(tool_use_id, None)
        decoded = _decode_grok_result_content(block.get("content"))
        tool_name = _tool_name_for_result(tool_use, decoded)
        response = _normalize_grok_tool_response(
            decoded,
            tool_name=tool_name,
            raw_tool_name=tool_use.raw_tool_name if tool_use else None,
        )
        is_error = block.get("is_error") is True or result_envelope_indicates_error(
            response
        )
        interrupted = result_envelope_is_interrupted(response)
        status = derive_user_result_status(is_error=is_error, interrupted=interrupted)
        record = _base_grok_record(
            "ToolResult",
            status,
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            session_id=session_id,
            cwd=cwd,
            parent_tool_use_id=parent_tool_use_id,
            message_uuid=message_uuid,
        )
        tool_input = tool_use.tool_input if tool_use is not None else {}
        record["tool_input_summary"] = summarize_tool_input(tool_name, tool_input)
        record["tool_response_summary"] = summarize_tool_response(
            tool_name=tool_name,
            tool_response=response,
            tool_result_content=block.get("content"),
            is_error=status == "failure",
            interrupted=status == "interrupted",
        )
        if status == "interrupted":
            record["is_interrupt"] = True
        _GROK_DURATIONS.record_duration(record, tool_use_id)
        records.append(record)
    return records


def _base_grok_record(
    event_name: str,
    status: str,
    *,
    tool_name: str | None,
    tool_use_id: str | None,
    session_id: str | None,
    cwd: str | None,
    parent_tool_use_id: str | None = None,
    message_id: str | None = None,
    message_uuid: str | None = None,
) -> dict[str, Any]:
    record = base_stream_tool_call_record(
        "grok",
        event_name,
        status,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        session_id=session_id,
        cwd=cwd,
    )
    if parent_tool_use_id:
        record["parent_tool_use_id"] = preview_text(parent_tool_use_id)
    if message_id:
        record["message_id"] = preview_text(message_id)
    if message_uuid:
        record["message_uuid"] = preview_text(message_uuid)
    return record


def _grok_display_tool_name(tool_name: str) -> str:
    return _GROK_TOOL_DISPLAY_NAMES.get(tool_name, preview_text(tool_name))


def _tool_name_for_result(
    tool_use: _GrokToolUse | None,
    decoded: Mapping[str, Any] | None,
) -> str | None:
    if tool_use is not None:
        return tool_use.tool_name
    if decoded is None:
        return None
    result_type = string_or_none(decoded.get("type"))
    if result_type:
        return _GROK_RESULT_DISPLAY_NAMES.get(result_type, preview_text(result_type))
    return None


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


def _normalize_grok_tool_input(
    raw_tool_name: str,
    tool_input: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(tool_input)
    _alias_first(normalized, "command", ("command", "cmd", "shell_command"))
    _alias_first(
        normalized,
        "file_path",
        ("file_path", "filePath", "filepath", "path", "file", "absolute_path"),
    )
    _alias_first(normalized, "content", ("content", "contents", "text"))
    _alias_first(normalized, "old_string", ("old_string", "old", "oldString"))
    _alias_first(
        normalized,
        "new_string",
        ("new_string", "new", "newString", "replacement"),
    )
    _alias_first(normalized, "replace_all", ("replace_all", "replaceAll"))
    _alias_first(normalized, "pattern", ("pattern", "query", "search_term"))
    _alias_first(normalized, "path", ("path", "directory", "root_dir"))
    _alias_first(
        normalized,
        "subagent_type",
        ("subagent_type", "agent_type", "agentType", "subagent"),
    )
    _alias_first(normalized, "prompt", ("prompt", "instructions"))

    if raw_tool_name == "run_terminal_command" and isinstance(
        normalized.get("command"), list
    ):
        normalized["command"] = " ".join(str(part) for part in normalized["command"])
    return normalized


def _decode_grok_result_content(content: Any) -> Mapping[str, Any] | None:
    if isinstance(content, Mapping):
        return content
    if not isinstance(content, str) or not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _normalize_grok_tool_response(
    decoded: Mapping[str, Any] | None,
    *,
    tool_name: str | None,
    raw_tool_name: str | None,
) -> Mapping[str, Any] | None:
    if decoded is None:
        return None
    if tool_name == "Bash" or decoded.get("type") == "Bash":
        return _normalize_bash_response(decoded)
    if (
        tool_name == "Edit"
        or raw_tool_name == "search_replace"
        or decoded.get("type") == "SearchReplace"
    ):
        return _normalize_edit_response(decoded)
    return _normalize_generic_response(decoded, tool_name=tool_name)


def _normalize_bash_response(decoded: Mapping[str, Any]) -> dict[str, Any]:
    response: dict[str, Any] = {}
    exit_code = _int_or_none(decoded.get("exit_code"))
    if exit_code is not None:
        response["exit_code"] = exit_code
        response["success"] = exit_code == 0
    _copy_bool(decoded, response, "success")
    if decoded.get("timed_out") is True or decoded.get("interrupted") is True:
        response["interrupted"] = True
    _copy_string(decoded, response, "error")
    _copy_string(decoded, response, "stdout")
    _copy_string(decoded, response, "stderr")
    output = _first_string(decoded, ("output_for_prompt", "tool_output_for_prompt"))
    if output:
        response["output"] = output
    elif isinstance(decoded.get("output"), str):
        response["output"] = decoded["output"]
    return response


def _normalize_edit_response(decoded: Mapping[str, Any]) -> dict[str, Any]:
    applied = decoded.get("EditsApplied")
    source = applied if isinstance(applied, Mapping) else decoded
    response: dict[str, Any] = {}
    path = _first_string(
        source,
        ("absolute_path", "file_path", "filePath", "filepath", "path", "file"),
    )
    if path:
        response["file_path"] = path
    output = _first_string(source, ("tool_output_for_prompt", "output_for_prompt"))
    if output:
        response["result"] = output
    if isinstance(source.get("structuredPatch"), str):
        response["structuredPatch"] = source["structuredPatch"]
    elif isinstance(source.get("edits"), Mapping):
        response["structuredPatch"] = source["edits"]
    if decoded.get("error"):
        response["success"] = False
        _copy_string(decoded, response, "error")
    else:
        response["success"] = decoded.get("success", True)
    return response


def _normalize_generic_response(
    decoded: Mapping[str, Any],
    *,
    tool_name: str | None,
) -> dict[str, Any]:
    response: dict[str, Any] = {}
    output = _first_string(decoded, ("output_for_prompt", "tool_output_for_prompt"))
    if output:
        response[_generic_text_key(tool_name)] = output
    elif isinstance(decoded.get("output"), str):
        response["output"] = decoded["output"]
    for source_key, target_key in (
        ("content", "content"),
        ("result", "result"),
        ("stdout", "stdout"),
        ("stderr", "stderr"),
        ("error", "error"),
    ):
        _copy_string(decoded, response, source_key, target_key)
    for key in ("success", "interrupted", "is_error"):
        _copy_bool(decoded, response, key)
    exit_code = _int_or_none(decoded.get("exit_code"))
    if exit_code is not None:
        response["exit_code"] = exit_code
        response.setdefault("success", exit_code == 0)
    if decoded.get("timed_out") is True:
        response["interrupted"] = True
    return response


def _generic_text_key(tool_name: str | None) -> str:
    if tool_name in {"Read", "WebFetch", "WebSearch"}:
        return "content"
    if tool_name in {"Write", "Edit", "MultiEdit"}:
        return "result"
    return "output"


def _alias_first(
    target: dict[str, Any],
    canonical_key: str,
    aliases: Sequence[str],
) -> None:
    if canonical_key in target:
        return
    for alias in aliases:
        value = target.get(alias)
        if value is not None:
            target[canonical_key] = value
            return


def _copy_string(
    source: Mapping[str, Any],
    target: dict[str, Any],
    source_key: str,
    target_key: str | None = None,
) -> None:
    value = source.get(source_key)
    if isinstance(value, str) and value:
        target[target_key or source_key] = value


def _copy_bool(
    source: Mapping[str, Any],
    target: dict[str, Any],
    key: str,
) -> None:
    value = source.get(key)
    if isinstance(value, bool):
        target[key] = value


def _first_string(source: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


normalize_grok_tool_call_event = _normalize_grok_tool_call_event
