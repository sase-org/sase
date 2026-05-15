"""Runtime-neutral tool-call artifact writer for LLM provider streams.

For Claude, the canonical source of truth for "every tool call this agent made"
is the in-band ``assistant`` event's ``content[].tool_use`` blocks paired with
the corresponding ``user`` event's ``content[].tool_result`` blocks (plus the
top-level ``tool_use_result`` envelope). Hook lifecycle events emitted via
``--include-hook-events`` only fire for hooks the user has actually registered,
so they cannot serve as the primary tool-call source — but they are still useful
as supplemental signal (durations, subagent lifecycle, permission denials) and
are captured here when present.
"""

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

# Hook events consumed by the SASE tool-call hook collector (stdin payload from
# Claude's PreToolUse/PostToolUse hooks). These produce schema-v3 records.
HOOK_COLLECTOR_EVENTS = frozenset({"PreToolUse", "PostToolUse"})

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


def append_claude_tool_call_event(event: Mapping[str, Any]) -> None:
    """Best-effort append of a Claude stream-json event to ``tool_calls.jsonl``.

    Handles three event shapes:

    - ``type: "assistant"`` with ``message.content[].tool_use`` blocks → emit a
      ``ToolUse`` (start) record per block.
    - ``type: "user"`` with ``message.content[].tool_result`` blocks → emit a
      ``ToolResult`` (end) record per block, drawing structured output from the
      top-level ``tool_use_result`` envelope when present.
    - ``type: "system"`` with ``subtype: "hook_response"`` and a recognized
      ``hook_event`` → emit a hook-event record for enrichment (durations,
      subagent boundaries). ``hook_started`` is ignored for ``PostToolUse*`` to
      avoid double-counting, but used as the boundary marker for ``Subagent*``.
    """
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    try:
        records = _normalize_claude_stream_event(event)
        if not records:
            return
        path = Path(artifacts_dir) / "tool_calls.jsonl"
        for record in records:
            _append_jsonl(path, record)
    except Exception as exc:
        _append_writer_diagnostic(artifacts_dir, event, exc)


def append_codex_tool_call_event(event: Mapping[str, Any]) -> None:
    """Best-effort append of a Codex function-call event to ``tool_calls.jsonl``."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    try:
        record = _normalize_codex_tool_call_event(event)
        if record is None:
            return
        _append_jsonl(Path(artifacts_dir) / "tool_calls.jsonl", record)
    except Exception as exc:
        _append_writer_diagnostic(artifacts_dir, event, exc)


def append_tool_call_collector_diagnostic(
    artifacts_dir: str | None,
    *,
    reason: str,
    raw_preview: str = "",
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Append a single line to ``tool_calls_writer_errors.jsonl``.

    Public entry point used by the SASE tool-call hook collector (and other
    runtime-provider glue) to record best-effort diagnostics without raising
    from the caller. A missing ``artifacts_dir`` is treated as a no-op.
    """
    if not artifacts_dir:
        return
    record: dict[str, Any] = {
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "reason": reason,
    }
    if raw_preview:
        record["raw_preview"] = _preview_text(raw_preview, 240)
    if extra:
        for key, value in extra.items():
            if isinstance(value, str):
                record[key] = _preview_text(value, 240)
            else:
                record[key] = value
    try:
        _append_jsonl(Path(artifacts_dir) / "tool_calls_writer_errors.jsonl", record)
    except Exception:
        pass


def append_claude_hook_tool_call_event(payload: Mapping[str, Any]) -> None:
    """Best-effort append of a Claude hook payload to ``tool_calls.jsonl``.

    Reads a single ``PreToolUse``/``PostToolUse`` hook event (the JSON object
    Claude writes to the collector's stdin) and emits a schema-v3 record.
    Other ``hook_event_name`` values are written to a diagnostic file rather
    than treated as hard failures so the collector can stay non-blocking.
    """
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    try:
        record = _normalize_claude_hook_payload(payload)
        if record is None:
            event_name = payload.get("hook_event_name")
            if isinstance(event_name, str) and event_name not in HOOK_COLLECTOR_EVENTS:
                _append_writer_diagnostic(
                    artifacts_dir,
                    payload,
                    ValueError(f"unsupported hook_event_name: {event_name}"),
                )
            return
        _append_jsonl(Path(artifacts_dir) / "tool_calls.jsonl", record)
    except Exception as exc:
        _append_writer_diagnostic(artifacts_dir, payload, exc)


def _normalize_claude_hook_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Convert a Claude PreToolUse/PostToolUse hook payload into a v3 record."""
    event_name = payload.get("hook_event_name")
    if not isinstance(event_name, str) or event_name not in HOOK_COLLECTOR_EVENTS:
        return None

    tool_name = _string_or_none(payload.get("tool_name"))
    tool_use_id = _string_or_none(payload.get("tool_use_id"))
    session_id = _string_or_none(payload.get("session_id"))
    parent_tool_use_id = _string_or_none(payload.get("parent_tool_use_id"))

    if event_name == "PreToolUse":
        record_event = "ToolUse"
        status = "pending"
    else:
        record_event = "ToolResult"
        status = _derive_hook_post_status(payload)

    record: dict[str, Any] = {
        "schema_version": _HOOK_SCHEMA_VERSION,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "runtime": "claude",
        "source": "hook",
        "hook_event": event_name,
        "event": record_event,
        "status": status,
    }
    if tool_name:
        record["tool_name"] = _preview_text(tool_name)
    if tool_use_id:
        record["tool_use_id"] = _preview_text(tool_use_id)
    if session_id:
        record["session_id"] = _preview_text(session_id)
    if parent_tool_use_id:
        record["parent_tool_use_id"] = _preview_text(parent_tool_use_id)

    for key in ("transcript_path", "cwd", "permission_mode"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            record[key] = _preview_text(value)

    if event_name == "PreToolUse":
        record["tool_input_summary"] = _summarize_tool_input(
            tool_name, payload.get("tool_input")
        )
        record["tool_response_summary"] = {}
    else:
        record["tool_input_summary"] = _summarize_tool_input(
            tool_name, payload.get("tool_input")
        )
        is_error = _hook_post_indicates_error(payload)
        interrupted = _result_envelope_is_interrupted(payload.get("tool_response"))
        record["tool_response_summary"] = _summarize_tool_response(
            tool_name=tool_name,
            tool_response=payload.get("tool_response"),
            error=payload.get("error"),
            is_error=is_error,
            interrupted=interrupted,
        )
        duration = payload.get("duration_ms")
        if isinstance(duration, bool):
            pass
        elif isinstance(duration, int):
            record["duration_ms"] = duration
        elif isinstance(duration, float):
            record["duration_ms"] = int(duration)
        if interrupted:
            record["is_interrupt"] = True

    return record


def _derive_hook_post_status(payload: Mapping[str, Any]) -> str:
    if _result_envelope_is_interrupted(payload.get("tool_response")):
        return "interrupted"
    if _hook_post_indicates_error(payload):
        return "failure"
    return "success"


def _hook_post_indicates_error(payload: Mapping[str, Any]) -> bool:
    if isinstance(payload.get("error"), str) and payload.get("error"):
        return True
    if _result_envelope_indicates_error(payload.get("tool_response")):
        return True
    return False


def _normalize_claude_stream_event(
    event: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Convert a Claude stream-json event into zero or more schema-v2 records."""
    event_type = event.get("type")
    if event_type == "assistant":
        return _records_from_assistant_event(event)
    if event_type == "user":
        return _records_from_user_event(event)
    if event_type == "system":
        record = _record_from_system_hook_event(event)
        return [record] if record is not None else []
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

    session_id = _string_or_none(event.get("session_id"))
    parent_tool_use_id = _string_or_none(event.get("parent_tool_use_id"))
    message_id = _string_or_none(message.get("id"))
    message_uuid = _string_or_none(event.get("uuid"))

    records: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "tool_use":
            continue
        tool_name = _string_or_none(block.get("name"))
        tool_use_id = _string_or_none(block.get("id"))
        record = _base_record(
            "ToolUse",
            "pending",
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            session_id=session_id,
            parent_tool_use_id=parent_tool_use_id,
            message_id=message_id,
            message_uuid=message_uuid,
        )
        record["tool_input_summary"] = _summarize_tool_input(
            tool_name, block.get("input")
        )
        record["tool_response_summary"] = {}
        records.append(record)
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

    session_id = _string_or_none(event.get("session_id"))
    parent_tool_use_id = _string_or_none(event.get("parent_tool_use_id"))
    message_uuid = _string_or_none(event.get("uuid"))
    tool_use_result = event.get("tool_use_result")

    records: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "tool_result":
            continue
        tool_use_id = _string_or_none(block.get("tool_use_id"))
        is_error = bool(block.get("is_error")) or _result_envelope_indicates_error(
            tool_use_result
        )
        interrupted = _result_envelope_is_interrupted(tool_use_result)
        status = _derive_user_result_status(is_error=is_error, interrupted=interrupted)
        record = _base_record(
            "ToolResult",
            status,
            tool_name=None,
            tool_use_id=tool_use_id,
            session_id=session_id,
            parent_tool_use_id=parent_tool_use_id,
            message_uuid=message_uuid,
        )
        record["tool_input_summary"] = {}
        record["tool_response_summary"] = _summarize_tool_response(
            tool_name=None,
            tool_response=tool_use_result,
            tool_result_content=block.get("content"),
            is_error=is_error,
            interrupted=interrupted,
        )
        if interrupted:
            record["is_interrupt"] = True
        records.append(record)
    return records


def _record_from_system_hook_event(
    event: Mapping[str, Any],
) -> dict[str, Any] | None:
    subtype = event.get("subtype")
    hook_event = event.get("hook_event")
    if (
        not isinstance(hook_event, str)
        or hook_event not in SUPPORTED_CLAUDE_HOOK_EVENTS
    ):
        return None

    is_subagent_event = hook_event in {"SubagentStart", "SubagentStop"}
    if is_subagent_event:
        # Use both subtypes for subagent lifecycle; prefer hook_started as the
        # boundary marker, but accept hook_response too so we don't drop signal.
        if subtype not in {"hook_started", "hook_response"}:
            return None
    else:
        # For tool-related hooks, hook_started would double-count: only consume
        # hook_response (which carries the structured outcome).
        if subtype != "hook_response":
            return None

    status = _status_for_hook_event(hook_event, event)
    tool_name = _string_or_none(event.get("tool_name"))
    record = _base_record(
        hook_event,
        status,
        tool_name=tool_name,
        tool_use_id=_string_or_none(event.get("tool_use_id")),
        session_id=_string_or_none(event.get("session_id")),
        parent_tool_use_id=_string_or_none(event.get("parent_tool_use_id")),
    )
    record["tool_input_summary"] = _summarize_tool_input(
        tool_name, event.get("tool_input")
    )
    record["tool_response_summary"] = _summarize_tool_response(
        tool_name=tool_name,
        tool_response=event.get("tool_response"),
        error=event.get("error"),
    )

    for key in (
        "transcript_path",
        "cwd",
        "permission_mode",
        "agent_id",
        "agent_type",
        "error",
    ):
        value = event.get(key)
        if isinstance(value, str) and value:
            record[key] = _preview_text(value)

    duration = event.get("duration_ms")
    if isinstance(duration, bool):
        pass
    elif isinstance(duration, int):
        record["duration_ms"] = duration
    elif isinstance(duration, float):
        record["duration_ms"] = int(duration)

    is_interrupt = event.get("is_interrupt")
    if isinstance(is_interrupt, bool):
        record["is_interrupt"] = is_interrupt

    return record


def _base_record(
    event_name: str,
    status: str,
    *,
    tool_name: str | None,
    tool_use_id: str | None,
    session_id: str | None,
    parent_tool_use_id: str | None,
    message_id: str | None = None,
    message_uuid: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "runtime": "claude",
        "event": event_name,
        "status": status,
    }
    if tool_name:
        record["tool_name"] = _preview_text(tool_name)
    if tool_use_id:
        record["tool_use_id"] = _preview_text(tool_use_id)
    if session_id:
        record["session_id"] = _preview_text(session_id)
    if parent_tool_use_id:
        record["parent_tool_use_id"] = _preview_text(parent_tool_use_id)
    if message_id:
        record["message_id"] = _preview_text(message_id)
    if message_uuid:
        record["message_uuid"] = _preview_text(message_uuid)
    return record


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


def _normalize_codex_tool_call_event(
    event: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Convert a Codex ``function_call`` item into SASE's tool-call schema."""
    if event.get("type") != "item.completed":
        return None

    item = event.get("item")
    if not isinstance(item, Mapping) or item.get("type") != "function_call":
        return None

    raw_tool_name = _string_or_none(item.get("name"))
    tool_name = _codex_display_tool_name(raw_tool_name)
    tool_input = _normalize_codex_tool_input(
        raw_tool_name,
        _parse_codex_arguments(item.get("arguments")),
    )
    record: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "runtime": "codex",
        "event": "FunctionCall",
        "status": "success",
        "tool_input_summary": _summarize_tool_input(tool_name, tool_input),
        "tool_response_summary": {},
    }

    if tool_name:
        record["tool_name"] = tool_name

    for key in ("call_id", "id"):
        value = item.get(key)
        if isinstance(value, str) and value:
            record["tool_use_id"] = _preview_text(value)
            break

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
    # Default — including the case where tool_name is unknown (e.g. user-event
    # records, where we don't carry tool_name on the ToolResult row): surface
    # whatever common shape fields exist plus any text previews.
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


def _status_for_hook_event(event_name: str, event: Mapping[str, Any]) -> str:
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


def _codex_display_tool_name(tool_name: str | None) -> str | None:
    if tool_name in {"shell", "container.exec"}:
        return "Bash"
    if tool_name == "read_file":
        return "Read"
    if tool_name == "write_file":
        return "Write"
    if tool_name in {"apply_patch", "apply_diff"}:
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
        event_label = (
            event.get("type")
            or event.get("hook_event")
            or event.get("hook_event_name")
            or ""
        )
        diagnostic = {
            "recorded_at": datetime.now(tz=UTC).isoformat(),
            "error": _preview_text(str(exc), 240),
            "event": _preview_text(str(event_label), 80),
        }
        _append_jsonl(
            Path(artifacts_dir) / "tool_calls_writer_errors.jsonl", diagnostic
        )
    except Exception:
        pass
