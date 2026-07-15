"""Shared helpers for runtime-neutral tool-call artifact records."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

_SCHEMA_VERSION = 2
_HOOK_SCHEMA_VERSION = 3
_PREVIEW_LIMIT = 512
_COMMAND_OUTPUT_PREVIEW_LIMIT = _PREVIEW_LIMIT
_COMMAND_OUTPUT_MIN_TAIL_LINES = 50
_SUBAGENT_OUTPUT_LIMIT = 64 * 1024
_MAX_KEYS = 20
_SUBAGENT_TOOL_STATS_FIELDS = (
    ("readCount", "read_count"),
    ("read_count", "read_count"),
    ("searchCount", "search_count"),
    ("search_count", "search_count"),
    ("bashCount", "bash_count"),
    ("bash_count", "bash_count"),
    ("editFileCount", "edit_count"),
    ("edit_file_count", "edit_count"),
    ("editCount", "edit_count"),
    ("edit_count", "edit_count"),
    ("linesAdded", "lines_added"),
    ("lines_added", "lines_added"),
    ("linesRemoved", "lines_removed"),
    ("lines_removed", "lines_removed"),
)
_TOOL_CALL_RECORD_REQUIRED_FIELDS = (
    "schema_version",
    "recorded_at",
    "runtime",
    "source",
    "event",
    "status",
)
_TOOL_CALL_RECORD_OPTIONAL_FIELDS = (
    "tool_name",
    "tool_use_id",
    "tool_input_summary",
    "tool_response_summary",
    "duration_ms",
    "session_id",
    "cwd",
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?P<prefix>(?:^|[\s;])(?:export\s+)?)"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"=(?P<quote>['\"]?)(?P<value>[^\s;'\"&|]+)(?P=quote)",
    re.IGNORECASE,
)
_SECRET_NAME_PARTS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "PASS", "AUTH")
_TAIL_TRUNCATION_MARKER_RE = re.compile(
    r"^\.\.\.\[truncated \d+ chars(?: and \d+ lines)? from the beginning\]\n"
)


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
                summary[f"{key}_preview"] = _tail_command_output(value)
        if "output" in tool_response:
            summary["output_preview"] = _tail_command_output(
                tool_response.get("output")
            )
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
    subagent_summary = _summarize_subagent_response(tool_response)
    if subagent_summary:
        return subagent_summary

    # Default, including user-event records where the ToolResult row does not
    # carry a tool name: surface common shape fields plus text previews.
    summary = {"response_keys": _sorted_limited_keys(tool_response)}
    for key in ("success", "error", "interrupted", "exit_code", "isImage"):
        if key in tool_response:
            summary[key] = _bounded_value(tool_response[key])
    for key in ("stdout", "stderr", "output", "content", "result"):
        value = tool_response.get(key)
        text = _text_content(value) if key in {"content", "result"} else value
        if isinstance(text, str) and text:
            summary[f"{key}_preview"] = (
                _tail_command_output(text)
                if key in {"stdout", "stderr", "output"}
                else _preview_text(text)
            )
            if key == "content" and isinstance(value, list):
                summary["content_full"] = _preview_text(
                    text,
                    _SUBAGENT_OUTPUT_LIMIT,
                )
    return summary


def _summarize_tool_result_content(content: Any) -> dict[str, Any]:
    if isinstance(content, str):
        return {"content_preview": _preview_text(content)}
    text = _text_content(content)
    if isinstance(text, str) and text:
        return {
            "content_preview": _preview_text(text),
            "content_full": _preview_text(text, _SUBAGENT_OUTPUT_LIMIT),
        }
    return {}


def _summarize_subagent_response(tool_response: Mapping[str, Any]) -> dict[str, Any]:
    content = _text_content(tool_response.get("content"))
    identity = _first_string_field(
        tool_response,
        ("agentType", "agent_type", "agentId", "agent_id"),
    )
    if not identity or not content:
        return {}

    summary: dict[str, Any] = {
        "response_keys": _sorted_limited_keys(tool_response),
        "content_preview": _preview_text(content),
        "content_full": _preview_text(content, _SUBAGENT_OUTPUT_LIMIT),
    }

    for output_key, input_keys in (
        ("agent_type", ("agentType", "agent_type")),
        ("agent_status", ("status", "agentStatus", "agent_status")),
        ("resolved_model", ("resolvedModel", "resolved_model")),
    ):
        value = _first_string_field(tool_response, input_keys)
        if value:
            summary[output_key] = _preview_text(value)

    for output_key, input_keys in (
        ("total_duration_ms", ("totalDurationMs", "total_duration_ms")),
        ("total_tokens", ("totalTokens", "total_tokens")),
        ("total_tool_use_count", ("totalToolUseCount", "total_tool_use_count")),
    ):
        int_value = _first_int_field(tool_response, input_keys)
        if int_value is not None:
            summary[output_key] = int_value

    tool_stats = _summarize_subagent_tool_stats(
        tool_response.get("toolStats", tool_response.get("tool_stats"))
    )
    if tool_stats:
        summary["tool_stats"] = tool_stats
    return summary


def _summarize_subagent_tool_stats(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    stats: dict[str, int] = {}
    for source_key, output_key in _SUBAGENT_TOOL_STATS_FIELDS:
        if output_key in stats:
            continue
        stat_value = _int_value(value.get(source_key))
        if stat_value is not None:
            stats[output_key] = stat_value
    return stats


def _text_content(value: Any) -> str | None:
    if isinstance(value, str):
        return value if value else None
    if not isinstance(value, list):
        return None

    parts: list[str] = []
    for block in value:
        if isinstance(block, str) and block:
            parts.append(block)
        elif isinstance(block, Mapping):
            text = block.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
    if not parts:
        return None
    return "\n".join(parts)


def _first_string_field(
    mapping: Mapping[str, Any], keys: tuple[str, ...]
) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _first_int_field(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = _int_value(mapping.get(key))
        if value is not None:
            return value
    return None


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


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


def _tail_command_output(
    value: Any,
    limit: int = _COMMAND_OUTPUT_PREVIEW_LIMIT,
    min_lines: int = _COMMAND_OUTPUT_MIN_TAIL_LINES,
) -> str:
    """Return normalized command output with a bounded, line-safe suffix.

    ``limit`` is a soft character budget. When its boundary falls inside the
    final ``min_lines`` logical lines, the retained suffix expands to the start
    of the earliest required line. Consequently, unusually wide trailing lines
    may make the result larger than the nominal budget.
    """
    text = value if isinstance(value, str) else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) <= limit or _TAIL_TRUNCATION_MARKER_RE.match(text):
        return text

    retain_from = _command_output_tail_start(text, limit, min_lines)
    if retain_from <= 0:
        return text

    omitted_lines = (
        text[:retain_from].count("\n")
        if text[retain_from - 1 : retain_from] == "\n"
        else None
    )
    marker = _command_output_omission_marker(retain_from, omitted_lines)
    return f"{marker}\n{text[retain_from:]}"


def _command_output_tail_start(text: str, limit: int, min_lines: int) -> int:
    """Return the prefix length that can be omitted from normalized output."""
    if len(text) <= limit:
        return 0

    character_boundary = len(text) - limit
    lines = text.splitlines(keepends=True)
    if len(lines) <= min_lines:
        line_boundary = 0
    else:
        line_boundary = sum(len(line) for line in lines[:-min_lines])
    return min(character_boundary, line_boundary)


def _command_output_omission_marker(
    omitted_chars: int,
    omitted_lines: int | None = None,
) -> str:
    """Format a fence-safe, directional command-output omission marker."""
    if omitted_lines is None:
        line_detail = ""
    else:
        unit = "line" if omitted_lines == 1 else "lines"
        line_detail = f" and {omitted_lines} {unit}"
    return f"...[truncated {omitted_chars} chars{line_detail} from the beginning]"


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


def _base_stream_tool_call_record(
    runtime: str,
    event: str,
    status: str,
    *,
    source: str = "stream",
    tool_name: str | None = None,
    tool_use_id: str | None = None,
    session_id: str | None = None,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Build the shared stream-backed tool-call artifact envelope.

    Codex and Qwen stream writers should emit this same required field set so
    the TUI reader can stay provider-neutral. Tool input/response summaries and
    optional duration are added by provider normalizers after this envelope is
    created.
    """
    record: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "runtime": runtime,
        "source": source,
        "event": event,
        "status": status,
    }
    if tool_name:
        record["tool_name"] = _preview_text(tool_name)
    if tool_use_id:
        record["tool_use_id"] = _preview_text(tool_use_id)
    if session_id:
        record["session_id"] = _preview_text(session_id)
    if cwd:
        record["cwd"] = _preview_text(cwd)
    return record


class ToolCallDurationTracker:
    """Track best-effort durations for stream ``ToolUse``/``ToolResult`` pairs."""

    def __init__(self) -> None:
        self._started_at: dict[str, float] = {}

    def remember_start(self, tool_use_id: str | None) -> None:
        if tool_use_id:
            self._started_at[tool_use_id] = perf_counter()

    def record_duration(self, record: dict[str, Any], tool_use_id: str | None) -> None:
        if not tool_use_id:
            return
        started_at = self._started_at.pop(tool_use_id, None)
        if started_at is None:
            return
        duration_ms = int((perf_counter() - started_at) * 1000)
        record["duration_ms"] = max(duration_ms, 0)


SCHEMA_VERSION = _SCHEMA_VERSION
HOOK_SCHEMA_VERSION = _HOOK_SCHEMA_VERSION
PREVIEW_LIMIT = _PREVIEW_LIMIT
COMMAND_OUTPUT_MIN_TAIL_LINES = _COMMAND_OUTPUT_MIN_TAIL_LINES
COMMAND_OUTPUT_PREVIEW_LIMIT = _COMMAND_OUTPUT_PREVIEW_LIMIT
TOOL_CALL_RECORD_OPTIONAL_FIELDS = _TOOL_CALL_RECORD_OPTIONAL_FIELDS
TOOL_CALL_RECORD_REQUIRED_FIELDS = _TOOL_CALL_RECORD_REQUIRED_FIELDS
base_stream_tool_call_record = _base_stream_tool_call_record
command_output_omission_marker = _command_output_omission_marker
command_output_tail_start = _command_output_tail_start
derive_user_result_status = _derive_user_result_status
preview_text = _preview_text
result_envelope_indicates_error = _result_envelope_indicates_error
result_envelope_is_interrupted = _result_envelope_is_interrupted
string_or_none = _string_or_none
summarize_tool_input = _summarize_tool_input
summarize_tool_response = _summarize_tool_response
tail_command_output = _tail_command_output
