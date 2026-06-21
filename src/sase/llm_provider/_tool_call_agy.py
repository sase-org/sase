"""Antigravity trajectory tool-call normalization.

Antigravity CLI 1.0.10 persists tool trajectory data in a private SQLite
database whose ``steps.step_payload`` column is a protobuf message. This module
keeps the private-format handling pure and best-effort: it walks only varint and
length-delimited protobuf fields, skips unknown shapes, and emits SASE's
provider-neutral tool-call records only for recognized tool-use/result steps.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ._tool_call_common import (
    base_stream_tool_call_record,
    summarize_tool_input,
    summarize_tool_response,
)

_TOOL_USE_STEP_TYPE = 15
_TOOL_RESULT_STEP_TYPES = frozenset({8, 9, 21, 132})
_SUCCESS_STATUS = 3
_PENDING_STATUSES = frozenset({0, 1, 2})
_INTERRUPTED_STATUSES = frozenset({4, 5, 6})
_MAX_PROTO_DEPTH = 5
_MAX_PROTO_FIELDS = 400
_MAX_STRING_BYTES = 128 * 1024

_AGY_TOOL_DISPLAY_NAMES = {
    "run_command": "Bash",
    "view_file": "Read",
    "read_file": "Read",
    "write_file": "Write",
    "edit_file": "Edit",
    "replace_file_content": "Edit",
    "grep": "Grep",
    "search": "Grep",
}
_KNOWN_AGY_TOOL_NAMES = frozenset(
    {
        *_AGY_TOOL_DISPLAY_NAMES,
        "list_dir",
        "list_permissions",
    }
)
_TOOL_NAME_KEYS = frozenset(
    {
        "function_name",
        "name",
        "tool",
        "tool_name",
    }
)
_ARG_KEYS = frozenset(
    {
        "args",
        "arguments",
        "input",
        "parameters",
        "request",
    }
)
_METADATA_INPUT_KEYS = _TOOL_NAME_KEYS | frozenset(
    {
        "call_id",
        "id",
        "tool_call_id",
        "tool_use_id",
    }
)


@dataclass(frozen=True)
class AgyTrajectoryStep:
    """One Antigravity trajectory step row needed by the normalizer."""

    idx: int
    step_type: int | None
    status: int | None
    step_payload: bytes


@dataclass(frozen=True)
class _AgyToolUse:
    tool_use_id: str
    raw_tool_name: str
    tool_name: str
    tool_input: Mapping[str, Any]


def normalize_agy_trajectory_steps(
    steps: Iterable[AgyTrajectoryStep],
    *,
    conversation_id: str,
    cwd: str | None = None,
) -> list[dict[str, Any]]:
    """Convert Antigravity trajectory steps into SASE tool-call records."""
    records: list[dict[str, Any]] = []
    pending: _AgyToolUse | None = None

    for step in sorted(steps, key=lambda item: item.idx):
        if step.step_type == _TOOL_USE_STEP_TYPE:
            tool_use = _decode_tool_use_step(step, conversation_id=conversation_id)
            if tool_use is None:
                pending = None
                continue
            records.append(_tool_use_record(tool_use, conversation_id, cwd))
            pending = tool_use
            continue

        if step.step_type not in _TOOL_RESULT_STEP_TYPES or pending is None:
            continue

        records.append(_tool_result_record(step, pending, conversation_id, cwd))
        pending = None

    return records


def agy_trajectory_step_tool_name(step: AgyTrajectoryStep) -> str | None:
    """Return the raw Antigravity tool name for a tool-use step."""
    if step.step_type != _TOOL_USE_STEP_TYPE:
        return None
    tool_use = _decode_tool_use_step(step, conversation_id="progress")
    return tool_use.raw_tool_name if tool_use else None


def agy_trajectory_step_is_tool_result(step: AgyTrajectoryStep) -> bool:
    """Return True when *step* is an Antigravity tool-result step."""
    return step.step_type in _TOOL_RESULT_STEP_TYPES


def agy_trajectory_status_is_pending(status: int | None) -> bool:
    """Return True when an Antigravity status means pending/running."""
    return status in _PENDING_STATUSES


def _decode_tool_use_step(
    step: AgyTrajectoryStep,
    *,
    conversation_id: str,
) -> _AgyToolUse | None:
    strings = _payload_strings(step.step_payload)
    if not strings:
        return None

    mappings = _json_mappings(strings)
    raw_tool_name = _tool_name_from_mappings(mappings) or _tool_name_from_strings(
        strings
    )
    if not raw_tool_name:
        return None

    tool_name = _agy_display_tool_name(raw_tool_name)
    input_mapping = _tool_input_mapping(mappings, raw_tool_name)
    tool_input = _normalize_agy_tool_input(raw_tool_name, input_mapping, strings)
    return _AgyToolUse(
        tool_use_id=f"{conversation_id}:{step.idx}",
        raw_tool_name=raw_tool_name,
        tool_name=tool_name,
        tool_input=tool_input,
    )


def _tool_use_record(
    tool_use: _AgyToolUse,
    conversation_id: str,
    cwd: str | None,
) -> dict[str, Any]:
    record = base_stream_tool_call_record(
        "agy",
        "ToolUse",
        "pending",
        source="trajectory",
        tool_name=tool_use.tool_name,
        tool_use_id=tool_use.tool_use_id,
        session_id=conversation_id,
        cwd=cwd,
    )
    record["tool_input_summary"] = summarize_tool_input(
        tool_use.tool_name,
        tool_use.tool_input,
    )
    record["tool_response_summary"] = {}
    return record


def _tool_result_record(
    step: AgyTrajectoryStep,
    tool_use: _AgyToolUse,
    conversation_id: str,
    cwd: str | None,
) -> dict[str, Any]:
    status = _agy_status_to_sase(step.status)
    response = _normalize_agy_tool_response(step, tool_use, status=status)
    record = base_stream_tool_call_record(
        "agy",
        "ToolResult",
        status,
        source="trajectory",
        tool_name=tool_use.tool_name,
        tool_use_id=tool_use.tool_use_id,
        session_id=conversation_id,
        cwd=cwd,
    )
    record["tool_input_summary"] = summarize_tool_input(
        tool_use.tool_name,
        tool_use.tool_input,
    )
    record["tool_response_summary"] = summarize_tool_response(
        tool_name=tool_use.tool_name,
        tool_response=response,
        is_error=status == "failure",
        interrupted=status == "interrupted",
    )
    if status == "interrupted":
        record["is_interrupt"] = True
    return record


def _normalize_agy_tool_response(
    step: AgyTrajectoryStep,
    tool_use: _AgyToolUse,
    *,
    status: str,
) -> Mapping[str, Any]:
    strings = _payload_strings(step.step_payload)
    mappings = _json_mappings(strings)
    response = dict(_response_mapping(mappings))

    if not response:
        text = _result_text(strings, tool_use.raw_tool_name)
        if text:
            response[_response_text_key(tool_use.tool_name)] = text

    response = _normalize_response_keys(response)
    if "success" not in response:
        response["success"] = status == "success"
    return response


def _agy_status_to_sase(status: int | None) -> str:
    if status == _SUCCESS_STATUS:
        return "success"
    if status in _PENDING_STATUSES:
        return "pending"
    if status in _INTERRUPTED_STATUSES:
        return "interrupted"
    return "failure"


def _agy_display_tool_name(raw_tool_name: str) -> str:
    return _AGY_TOOL_DISPLAY_NAMES.get(raw_tool_name, raw_tool_name)


def _tool_name_from_strings(strings: Sequence[str]) -> str | None:
    for text in strings:
        normalized = text.strip()
        if normalized in _KNOWN_AGY_TOOL_NAMES:
            return normalized
    return None


def _tool_name_from_mappings(mappings: Sequence[Mapping[str, Any]]) -> str | None:
    for mapping in mappings:
        for key in _TOOL_NAME_KEYS:
            value = mapping.get(key)
            if isinstance(value, str) and _looks_like_tool_name(value):
                return value
        function = mapping.get("function")
        if isinstance(function, Mapping):
            value = function.get("name")
            if isinstance(value, str) and _looks_like_tool_name(value):
                return value
    return None


def _looks_like_tool_name(value: str) -> bool:
    return value in _KNOWN_AGY_TOOL_NAMES or (
        bool(value)
        and value.replace("_", "").replace("-", "").isalnum()
        and ("_" in value or value.endswith("tool"))
    )


def _tool_input_mapping(
    mappings: Sequence[Mapping[str, Any]],
    raw_tool_name: str,
) -> Mapping[str, Any]:
    candidates: list[Mapping[str, Any]] = []
    for mapping in mappings:
        nested = _nested_args_mapping(mapping)
        if nested:
            candidates.append(nested)
        stripped = {
            key: value
            for key, value in mapping.items()
            if isinstance(key, str) and key not in _METADATA_INPUT_KEYS
        }
        if stripped:
            candidates.append(stripped)

    if not candidates:
        return {}
    return max(candidates, key=lambda item: _tool_input_score(item, raw_tool_name))


def _nested_args_mapping(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in _ARG_KEYS:
        value = mapping.get(key)
        if isinstance(value, Mapping):
            return value
        if isinstance(value, str):
            parsed = _json_mapping(value)
            if parsed:
                return parsed
    function = mapping.get("function")
    if isinstance(function, Mapping):
        value = function.get("arguments")
        if isinstance(value, Mapping):
            return value
        if isinstance(value, str):
            return _json_mapping(value)
    return {}


def _tool_input_score(mapping: Mapping[str, Any], raw_tool_name: str) -> int:
    keys = {str(key) for key in mapping.keys()}
    score = len(keys)
    if raw_tool_name == "run_command":
        score += 10 * len(keys & {"cmd", "command", "shell_command"})
    elif raw_tool_name in {"read_file", "view_file", "write_file"}:
        score += 10 * len(keys & {"file_path", "filepath", "path", "filePath"})
    elif raw_tool_name in {"edit_file", "replace_file_content"}:
        score += 10 * len(
            keys
            & {
                "file_path",
                "filepath",
                "new_string",
                "old_string",
                "path",
            }
        )
    elif raw_tool_name in {"grep", "search"}:
        score += 10 * len(keys & {"pattern", "query", "search_term"})
    return score


def _normalize_agy_tool_input(
    raw_tool_name: str,
    mapping: Mapping[str, Any],
    strings: Sequence[str],
) -> Mapping[str, Any]:
    normalized = dict(mapping)
    _alias_first(normalized, "command", ("command", "cmd", "shell_command"))
    _alias_first(
        normalized,
        "file_path",
        ("file_path", "filePath", "filepath", "path", "file", "absolute_path"),
    )
    _alias_first(normalized, "content", ("content", "contents", "text"))
    _alias_first(normalized, "old_string", ("old_string", "old", "oldContent"))
    _alias_first(
        normalized,
        "new_string",
        ("new_string", "new", "newContent", "replacement"),
    )
    _alias_first(normalized, "pattern", ("pattern", "query", "search_term"))
    _alias_first(normalized, "path", ("path", "directory", "root_dir"))

    if isinstance(normalized.get("command"), list):
        normalized["command"] = " ".join(str(part) for part in normalized["command"])

    if raw_tool_name == "run_command" and "command" not in normalized:
        command = _first_payload_text(strings, raw_tool_name)
        if command:
            normalized["command"] = command
    elif (
        raw_tool_name
        in {
            "edit_file",
            "read_file",
            "replace_file_content",
            "view_file",
            "write_file",
        }
        and "file_path" not in normalized
    ):
        path = _first_path_like_text(strings, raw_tool_name)
        if path:
            normalized["file_path"] = path
    elif raw_tool_name in {"grep", "search"} and "pattern" not in normalized:
        pattern = _first_payload_text(strings, raw_tool_name)
        if pattern:
            normalized["pattern"] = pattern

    return normalized


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


def _response_mapping(mappings: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    candidates = [mapping for mapping in mappings if _response_score(mapping) > 0]
    if not candidates:
        return {}
    return max(candidates, key=_response_score)


def _response_score(mapping: Mapping[str, Any]) -> int:
    keys = {str(key) for key in mapping.keys()}
    score = len(
        keys
        & {
            "content",
            "error",
            "exit_code",
            "output",
            "result",
            "stderr",
            "stdout",
            "success",
        }
    )
    for value in mapping.values():
        if isinstance(value, str) and value:
            score += 1
    return score


def _normalize_response_keys(response: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(response)
    _alias_first(normalized, "exit_code", ("exit_code", "exitCode", "code"))
    return normalized


def _response_text_key(tool_name: str) -> str:
    if tool_name == "Read":
        return "content"
    if tool_name in {"Write", "Edit", "MultiEdit"}:
        return "result"
    return "output"


def _result_text(strings: Sequence[str], raw_tool_name: str) -> str:
    useful = [
        text
        for text in strings
        if _is_useful_free_text(text, raw_tool_name) and not _looks_like_json(text)
    ]
    if not useful:
        return ""
    return max(useful, key=len)


def _first_payload_text(strings: Sequence[str], raw_tool_name: str) -> str | None:
    for text in strings:
        if _is_useful_free_text(text, raw_tool_name) and not _looks_like_json(text):
            return text
    return None


def _first_path_like_text(strings: Sequence[str], raw_tool_name: str) -> str | None:
    for text in strings:
        if not _is_useful_free_text(text, raw_tool_name):
            continue
        if "/" in text or "." in text:
            return text
    return None


def _is_useful_free_text(text: str, raw_tool_name: str) -> bool:
    stripped = text.strip()
    return (
        bool(stripped) and stripped != raw_tool_name and stripped not in _TOOL_NAME_KEYS
    )


def _json_mappings(strings: Sequence[str]) -> list[Mapping[str, Any]]:
    mappings: list[Mapping[str, Any]] = []
    for text in strings:
        parsed = _json_mapping(text)
        if parsed:
            mappings.extend(_walk_json_mappings(parsed))
    return mappings


def _json_mapping(text: str) -> Mapping[str, Any]:
    if not _looks_like_json(text):
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def _walk_json_mappings(value: Any) -> list[Mapping[str, Any]]:
    mappings: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        mappings.append(value)
        for nested in value.values():
            mappings.extend(_walk_json_mappings(nested))
    elif isinstance(value, list):
        for nested in value:
            mappings.extend(_walk_json_mappings(nested))
    return mappings


def _looks_like_json(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("{") and stripped.endswith("}")


def _payload_strings(payload: bytes) -> list[str]:
    fields = _decode_wire_fields(payload, depth=0)
    strings: list[str] = []
    _collect_wire_strings(fields, strings)
    return _dedupe_strings(strings)


@dataclass(frozen=True)
class _WireField:
    number: int
    wire_type: int
    value: int | bytes
    children: tuple[_WireField, ...] = ()
    text: str | None = None


def _decode_wire_fields(payload: bytes, *, depth: int) -> tuple[_WireField, ...]:
    if depth > _MAX_PROTO_DEPTH or not payload:
        return ()

    pos = 0
    fields: list[_WireField] = []
    try:
        while pos < len(payload) and len(fields) < _MAX_PROTO_FIELDS:
            key, pos = _read_varint(payload, pos)
            field_number = key >> 3
            wire_type = key & 0x07
            if field_number <= 0:
                return ()

            if wire_type == 0:
                value, pos = _read_varint(payload, pos)
                fields.append(_WireField(field_number, wire_type, value))
            elif wire_type == 1:
                if pos + 8 > len(payload):
                    return ()
                fixed64_value = payload[pos : pos + 8]
                pos += 8
                fields.append(_WireField(field_number, wire_type, fixed64_value))
            elif wire_type == 2:
                length, pos = _read_varint(payload, pos)
                if length < 0 or pos + length > len(payload):
                    return ()
                blob = payload[pos : pos + length]
                pos += length
                text = _decode_printable_text(blob)
                children = _decode_wire_fields(blob, depth=depth + 1)
                fields.append(
                    _WireField(
                        field_number,
                        wire_type,
                        blob,
                        children=children,
                        text=text,
                    )
                )
            elif wire_type == 5:
                if pos + 4 > len(payload):
                    return ()
                fixed32_value = payload[pos : pos + 4]
                pos += 4
                fields.append(_WireField(field_number, wire_type, fixed32_value))
            else:
                return ()
    except ValueError:
        return ()

    return tuple(fields) if pos == len(payload) else ()


def _read_varint(payload: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while pos < len(payload) and shift < 70:
        byte = payload[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
    raise ValueError("malformed protobuf varint")


def _decode_printable_text(blob: bytes) -> str | None:
    if not blob or len(blob) > _MAX_STRING_BYTES or b"\x00" in blob:
        return None
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text:
        return None
    printable = sum(
        1 for char in text if char in "\n\r\t" or (" " <= char and char != "\x7f")
    )
    if printable / len(text) < 0.85:
        return None
    return text


def _collect_wire_strings(fields: Iterable[_WireField], output: list[str]) -> None:
    for field in fields:
        if field.text:
            output.append(field.text)
        if field.children:
            _collect_wire_strings(field.children, output)


def _dedupe_strings(strings: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for text in strings:
        if text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


__all__ = [
    "AgyTrajectoryStep",
    "agy_trajectory_status_is_pending",
    "agy_trajectory_step_is_tool_result",
    "agy_trajectory_step_tool_name",
    "normalize_agy_trajectory_steps",
]
