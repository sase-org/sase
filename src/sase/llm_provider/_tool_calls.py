"""Runtime-neutral tool-call artifact writer for LLM provider streams."""

from __future__ import annotations

import fcntl
import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SUPPORTED_CLAUDE_HOOK_EVENTS = frozenset(
    {"PostToolUse", "PostToolUseFailure", "SubagentStart", "SubagentStop"}
)

_SCHEMA_VERSION = 1
_PREVIEW_LIMIT = 512
_MAX_KEYS = 20
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?P<prefix>(?:^|[\s;])(?:export\s+)?)"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"=(?P<quote>['\"]?)(?P<value>[^\s;'\"&|]+)(?P=quote)",
    re.IGNORECASE,
)
_SECRET_NAME_PARTS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "PASS", "AUTH")


def append_claude_tool_call_event(event: Mapping[str, Any]) -> None:
    """Best-effort append of a Claude hook event to ``tool_calls.jsonl``."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    try:
        record = _normalize_claude_tool_call_event(event)
        if record is None:
            return
        _append_jsonl(Path(artifacts_dir) / "tool_calls.jsonl", record)
    except Exception as exc:
        _append_writer_diagnostic(artifacts_dir, event, exc)


def _normalize_claude_tool_call_event(
    event: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Convert a Claude hook lifecycle event into SASE's tool-call schema."""
    event_name = event.get("hook_event_name")
    if (
        not isinstance(event_name, str)
        or event_name not in SUPPORTED_CLAUDE_HOOK_EVENTS
    ):
        return None

    status = _status_for_event(event_name, event)
    tool_name = _string_or_none(event.get("tool_name"))
    record: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "runtime": "claude",
        "event": event_name,
        "status": status,
        "tool_input_summary": _summarize_tool_input(tool_name, event.get("tool_input")),
        "tool_response_summary": _summarize_tool_response(
            tool_name,
            event.get("tool_response"),
            error=event.get("error"),
        ),
    }

    for key in (
        "session_id",
        "transcript_path",
        "cwd",
        "permission_mode",
        "agent_id",
        "agent_type",
        "tool_use_id",
        "tool_name",
        "error",
    ):
        value = event.get(key)
        if isinstance(value, str) and value:
            record[key] = _preview_text(value)

    for key in ("duration_ms",):
        value = event.get(key)
        if isinstance(value, int):
            record[key] = value
        elif isinstance(value, float):
            record[key] = int(value)

    is_interrupt = event.get("is_interrupt")
    if isinstance(is_interrupt, bool):
        record["is_interrupt"] = is_interrupt

    return record


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
) -> dict[str, Any]:
    """Return a bounded summary of a Claude structured tool response."""
    if os.environ.get("SASE_TOOL_LOG_FULL") == "1":
        summary = {"raw": _json_safe_value(tool_response)}
    elif isinstance(tool_response, Mapping):
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
        elif tool_name in {"Read", "WebFetch", "WebSearch"}:
            summary = _pick_fields(tool_response, ("success", "isImage"))
            if "content" in tool_response:
                summary["content_preview"] = _preview_text(tool_response.get("content"))
            if "result" in tool_response:
                summary["result_preview"] = _preview_text(tool_response.get("result"))
        elif tool_name in {"Write", "Edit", "MultiEdit"}:
            summary = _pick_fields(
                tool_response,
                ("filePath", "file_path", "success", "structuredPatch"),
            )
        else:
            summary = {
                "response_keys": _sorted_limited_keys(tool_response),
            }
            for key in ("success", "error", "interrupted"):
                if key in tool_response:
                    summary[key] = _bounded_value(tool_response[key])
    elif tool_response is None:
        summary = {}
    else:
        summary = {"preview": _preview_text(tool_response)}

    if isinstance(error, str) and error:
        summary["error"] = _preview_text(error)
    return summary


def _status_for_event(event_name: str, event: Mapping[str, Any]) -> str:
    if event.get("is_interrupt") is True:
        return "interrupted"
    if event_name == "PostToolUseFailure":
        return "failure"
    if event_name in {"SubagentStart", "SubagentStop"}:
        return "subagent"
    response = event.get("tool_response")
    if isinstance(response, Mapping) and response.get("success") is False:
        return "failure"
    return "success"


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


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with open(lock_path, "a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            with open(path, "a", encoding="utf-8") as output_file:
                json.dump(record, output_file, sort_keys=True)
                output_file.write("\n")
                output_file.flush()
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _append_writer_diagnostic(
    artifacts_dir: str,
    event: Mapping[str, Any],
    exc: Exception,
) -> None:
    try:
        diagnostic = {
            "recorded_at": datetime.now(tz=UTC).isoformat(),
            "error": _preview_text(str(exc), 240),
            "event": _preview_text(event.get("hook_event_name", ""), 80),
        }
        _append_jsonl(
            Path(artifacts_dir) / "tool_calls_writer_errors.jsonl", diagnostic
        )
    except Exception:
        pass
