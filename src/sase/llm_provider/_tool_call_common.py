"""Shared helpers for runtime-neutral tool-call artifact records."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

_SCHEMA_VERSION = 2
_HOOK_SCHEMA_VERSION = 3
_PREVIEW_LIMIT = 512
_MAX_KEYS = 20
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?P<prefix>(?:^|[\s;])(?:export\s+)?)"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"=(?P<quote>['\"]?)(?P<value>[^\s;'\"&|]+)(?P=quote)",
    re.IGNORECASE,
)
_SECRET_NAME_PARTS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "PASS", "AUTH")


def _summarize_tool_input(tool_name: str | None, tool_input: Any) -> dict[str, Any]:
    """Return a bounded, redacted summary of a tool input object."""
    if os.environ.get("SASE_TOOL_LOG_FULL") == "1":
        return {"raw": _json_safe_value(tool_input)}

    if not isinstance(tool_input, Mapping):
        return {}

    if tool_name == "Bash":
        return _pick_fields(
            tool_input,
            ("command", "description", "timeout", "run_in_background"),
            redact_command=True,
        )
    if tool_name == "Read":
        return _pick_fields(tool_input, ("file_path", "offset", "limit"))
    if tool_name == "Grep":
        return _pick_fields(tool_input, ("pattern", "path", "glob", "output_mode"))
    if tool_name == "Glob":
        return _pick_fields(tool_input, ("pattern", "path"))
    if tool_name == "Write":
        summary = _pick_fields(tool_input, ("file_path",))
        summary["content_length"] = _string_length(tool_input.get("content"))
        return summary
    if tool_name == "Edit":
        summary = _pick_fields(tool_input, ("file_path", "replace_all"))
        summary["old_string_length"] = _string_length(tool_input.get("old_string"))
        summary["new_string_length"] = _string_length(tool_input.get("new_string"))
        return summary
    if tool_name == "MultiEdit":
        summary = _pick_fields(tool_input, ("file_path",))
        edits = tool_input.get("edits")
        if isinstance(edits, list):
            summary["edits_count"] = len(edits)
            summary["old_string_length_total"] = sum(
                _string_length(edit.get("old_string"))
                for edit in edits
                if isinstance(edit, Mapping)
            )
            summary["new_string_length_total"] = sum(
                _string_length(edit.get("new_string"))
                for edit in edits
                if isinstance(edit, Mapping)
            )
        return summary
    if tool_name == "WebFetch":
        return _pick_fields(tool_input, ("url", "prompt"))
    if tool_name == "WebSearch":
        return _pick_fields(tool_input, ("query", "allowed_domains", "blocked_domains"))
    if tool_name in {"Task", "Agent"}:
        summary = _pick_fields(tool_input, ("subagent_type", "description"))
        summary["prompt_length"] = _string_length(tool_input.get("prompt"))
        return summary

    return {"input_keys": _sorted_limited_keys(tool_input)}


def _summarize_tool_response(
    tool_name: str | None,
    tool_response: Any,
    *,
    error: Any = None,
    tool_result_content: Any = None,
    is_error: bool = False,
    interrupted: bool = False,
) -> dict[str, Any]:
    """Return a bounded summary of a Claude structured tool response.

    ``tool_response`` is the structured envelope (Claude calls this
    ``tool_response`` for hook events and ``tool_use_result`` for inline
    user-message events; both share the same shape). ``tool_result_content``
    is the unstructured ``content`` field from a ``tool_result`` block used as
    a fallback when no structured envelope is available.
    """
    if os.environ.get("SASE_TOOL_LOG_FULL") == "1":
        summary: dict[str, Any] = {"raw": _json_safe_value(tool_response)}
        if tool_result_content is not None and "raw" not in summary:
            summary["raw"] = _json_safe_value(tool_result_content)
    elif isinstance(tool_response, Mapping):
        summary = _summarize_structured_response(tool_name, tool_response)
    elif tool_response is None:
        summary = {}
    else:
        summary = {"preview": _preview_text(tool_response)}

    if not summary and tool_result_content is not None:
        summary = _summarize_tool_result_content(tool_result_content)

    if interrupted and "interrupted" not in summary:
        summary["interrupted"] = True
    if is_error and "is_error" not in summary and "error" not in summary:
        summary["is_error"] = True

    if isinstance(error, str) and error:
        summary["error"] = _preview_text(error)
    return summary


def _summarize_structured_response(
    tool_name: str | None, tool_response: Mapping[str, Any]
) -> dict[str, Any]:
    summary: dict[str, Any]
    if tool_name == "Bash":
        summary = _pick_fields(
            tool_response,
            ("exit_code", "success", "interrupted", "isImage"),
        )
        for key in ("stdout", "stderr"):
            value = tool_response.get(key)
            if isinstance(value, str) and value:
                summary[f"{key}_preview"] = _preview_text(value)
        if "output" in tool_response:
            summary["output_preview"] = _preview_text(tool_response.get("output"))
        return summary
    if tool_name in {"Read", "WebFetch", "WebSearch"}:
        summary = _pick_fields(tool_response, ("success", "isImage"))
        if "content" in tool_response:
            summary["content_preview"] = _preview_text(tool_response.get("content"))
        if "result" in tool_response:
            summary["result_preview"] = _preview_text(tool_response.get("result"))
        return summary
    if tool_name in {"Write", "Edit", "MultiEdit"}:
        return _pick_fields(
            tool_response,
            ("filePath", "file_path", "success", "structuredPatch"),
        )
    # Default, including user-event records where the ToolResult row does not
    # carry a tool name: surface common shape fields plus text previews.
    summary = {"response_keys": _sorted_limited_keys(tool_response)}
    for key in ("success", "error", "interrupted", "exit_code", "isImage"):
        if key in tool_response:
            summary[key] = _bounded_value(tool_response[key])
    for key in ("stdout", "stderr", "output", "content", "result"):
        value = tool_response.get(key)
        if isinstance(value, str) and value:
            summary[f"{key}_preview"] = _preview_text(value)
    return summary


def _summarize_tool_result_content(content: Any) -> dict[str, Any]:
    if isinstance(content, str):
        return {"content_preview": _preview_text(content)}
    if isinstance(content, list):
        previews: list[str] = []
        for block in content:
            if isinstance(block, Mapping):
                text = block.get("text")
                if isinstance(text, str) and text:
                    previews.append(text)
        if previews:
            return {"content_preview": _preview_text("\n".join(previews))}
    return {}


def _derive_user_result_status(*, is_error: bool, interrupted: bool) -> str:
    if interrupted:
        return "interrupted"
    if is_error:
        return "failure"
    return "success"


def _result_envelope_indicates_error(envelope: Any) -> bool:
    if not isinstance(envelope, Mapping):
        return False
    if envelope.get("is_error") is True:
        return True
    if envelope.get("success") is False:
        return True
    return False


def _result_envelope_is_interrupted(envelope: Any) -> bool:
    return isinstance(envelope, Mapping) and envelope.get("interrupted") is True


def _pick_fields(
    source: Mapping[str, Any],
    fields: tuple[str, ...],
    *,
    redact_command: bool = False,
) -> dict[str, Any]:
    picked: dict[str, Any] = {}
    for field in fields:
        if field not in source:
            continue
        value = source[field]
        if redact_command and field == "command":
            value = _redact_command(_preview_text(value))
        else:
            value = _bounded_value(value)
        picked[field] = value
    return picked


def _bounded_value(value: Any, *, depth: int = 0) -> Any:
    if isinstance(value, str):
        return _preview_text(value)
    if isinstance(value, bool) or isinstance(value, int) or isinstance(value, float):
        return value
    if value is None:
        return None
    if isinstance(value, list):
        if depth >= 2:
            return {"type": "list", "length": len(value)}
        return [_bounded_value(item, depth=depth + 1) for item in value[:_MAX_KEYS]]
    if isinstance(value, Mapping):
        if depth >= 2:
            return {"type": "object", "keys": _sorted_limited_keys(value)}
        bounded: dict[str, Any] = {}
        for key in _sorted_limited_keys(value):
            if isinstance(key, str):
                bounded[key] = _bounded_value(value.get(key), depth=depth + 1)
        return bounded
    return _preview_text(str(value))


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, str | bool | int | float) or value is None:
        return value
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_safe_value(nested) for key, nested in value.items()}
    return str(value)


def _preview_text(value: Any, limit: int = _PREVIEW_LIMIT) -> str:
    text = value if isinstance(value, str) else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"


def _redact_command(command: str) -> str:
    return _SECRET_ASSIGNMENT_RE.sub(
        _redact_assignment_match,
        command,
    )


def _redact_assignment_match(match: re.Match[str]) -> str:
    name = match.group("name")
    if not any(part in name.upper() for part in _SECRET_NAME_PARTS):
        return match.group(0)
    return f"{match.group('prefix')}{name}=[REDACTED]"


def _string_length(value: Any) -> int:
    return len(value) if isinstance(value, str) else 0


def _sorted_limited_keys(mapping: Mapping[Any, Any]) -> list[str]:
    keys = sorted(str(key) for key in mapping.keys())
    return keys[:_MAX_KEYS]


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


SCHEMA_VERSION = _SCHEMA_VERSION
HOOK_SCHEMA_VERSION = _HOOK_SCHEMA_VERSION
PREVIEW_LIMIT = _PREVIEW_LIMIT
derive_user_result_status = _derive_user_result_status
preview_text = _preview_text
result_envelope_indicates_error = _result_envelope_indicates_error
result_envelope_is_interrupted = _result_envelope_is_interrupted
string_or_none = _string_or_none
summarize_tool_input = _summarize_tool_input
summarize_tool_response = _summarize_tool_response
