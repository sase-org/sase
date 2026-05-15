"""Claude tool-call artifact normalization."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._tool_call_common import (
    HOOK_SCHEMA_VERSION,
    SCHEMA_VERSION,
    derive_user_result_status,
    preview_text,
    result_envelope_indicates_error,
    result_envelope_is_interrupted,
    string_or_none,
    summarize_tool_input,
    summarize_tool_response,
)
from ._tool_call_io import append_jsonl, append_writer_diagnostic

SUPPORTED_CLAUDE_HOOK_EVENTS = frozenset(
    {"PostToolUse", "PostToolUseFailure", "SubagentStart", "SubagentStop"}
)

# Hook events consumed by the SASE tool-call hook collector (stdin payload from
# Claude's PreToolUse/PostToolUse hooks). These produce schema-v3 records.
HOOK_COLLECTOR_EVENTS = frozenset({"PreToolUse", "PostToolUse"})


def append_claude_tool_call_event(event: Mapping[str, Any]) -> None:
    """Best-effort append of a Claude stream-json event to ``tool_calls.jsonl``.

    Handles three event shapes:

    - ``type: "assistant"`` with ``message.content[].tool_use`` blocks emits a
      ``ToolUse`` (start) record per block.
    - ``type: "user"`` with ``message.content[].tool_result`` blocks emits a
      ``ToolResult`` (end) record per block, drawing structured output from the
      top-level ``tool_use_result`` envelope when present.
    - ``type: "system"`` with ``subtype: "hook_response"`` and a recognized
      ``hook_event`` emits a hook-event record for enrichment.
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
            append_jsonl(path, record)
    except Exception as exc:
        append_writer_diagnostic(artifacts_dir, event, exc)


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
                append_writer_diagnostic(
                    artifacts_dir,
                    payload,
                    ValueError(f"unsupported hook_event_name: {event_name}"),
                )
            return
        append_jsonl(Path(artifacts_dir) / "tool_calls.jsonl", record)
    except Exception as exc:
        append_writer_diagnostic(artifacts_dir, payload, exc)


def _normalize_claude_hook_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Convert a Claude PreToolUse/PostToolUse hook payload into a v3 record."""
    event_name = payload.get("hook_event_name")
    if not isinstance(event_name, str) or event_name not in HOOK_COLLECTOR_EVENTS:
        return None

    tool_name = string_or_none(payload.get("tool_name"))
    tool_use_id = string_or_none(payload.get("tool_use_id"))
    session_id = string_or_none(payload.get("session_id"))
    parent_tool_use_id = string_or_none(payload.get("parent_tool_use_id"))

    if event_name == "PreToolUse":
        record_event = "ToolUse"
        status = "pending"
    else:
        record_event = "ToolResult"
        status = _derive_hook_post_status(payload)

    record: dict[str, Any] = {
        "schema_version": HOOK_SCHEMA_VERSION,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "runtime": "claude",
        "source": "hook",
        "hook_event": event_name,
        "event": record_event,
        "status": status,
    }
    if tool_name:
        record["tool_name"] = preview_text(tool_name)
    if tool_use_id:
        record["tool_use_id"] = preview_text(tool_use_id)
    if session_id:
        record["session_id"] = preview_text(session_id)
    if parent_tool_use_id:
        record["parent_tool_use_id"] = preview_text(parent_tool_use_id)

    for key in ("transcript_path", "cwd", "permission_mode"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            record[key] = preview_text(value)

    if event_name == "PreToolUse":
        record["tool_input_summary"] = summarize_tool_input(
            tool_name, payload.get("tool_input")
        )
        record["tool_response_summary"] = {}
    else:
        record["tool_input_summary"] = summarize_tool_input(
            tool_name, payload.get("tool_input")
        )
        is_error = _hook_post_indicates_error(payload)
        interrupted = result_envelope_is_interrupted(payload.get("tool_response"))
        record["tool_response_summary"] = summarize_tool_response(
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
    if result_envelope_is_interrupted(payload.get("tool_response")):
        return "interrupted"
    if _hook_post_indicates_error(payload):
        return "failure"
    return "success"


def _hook_post_indicates_error(payload: Mapping[str, Any]) -> bool:
    if isinstance(payload.get("error"), str) and payload.get("error"):
        return True
    if result_envelope_indicates_error(payload.get("tool_response")):
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

    session_id = string_or_none(event.get("session_id"))
    parent_tool_use_id = string_or_none(event.get("parent_tool_use_id"))
    message_id = string_or_none(message.get("id"))
    message_uuid = string_or_none(event.get("uuid"))

    records: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "tool_use":
            continue
        tool_name = string_or_none(block.get("name"))
        tool_use_id = string_or_none(block.get("id"))
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
        record["tool_input_summary"] = summarize_tool_input(
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

    session_id = string_or_none(event.get("session_id"))
    parent_tool_use_id = string_or_none(event.get("parent_tool_use_id"))
    message_uuid = string_or_none(event.get("uuid"))
    tool_use_result = event.get("tool_use_result")

    records: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "tool_result":
            continue
        tool_use_id = string_or_none(block.get("tool_use_id"))
        is_error = bool(block.get("is_error")) or result_envelope_indicates_error(
            tool_use_result
        )
        interrupted = result_envelope_is_interrupted(tool_use_result)
        status = derive_user_result_status(is_error=is_error, interrupted=interrupted)
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
        record["tool_response_summary"] = summarize_tool_response(
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
    tool_name = string_or_none(event.get("tool_name"))
    record = _base_record(
        hook_event,
        status,
        tool_name=tool_name,
        tool_use_id=string_or_none(event.get("tool_use_id")),
        session_id=string_or_none(event.get("session_id")),
        parent_tool_use_id=string_or_none(event.get("parent_tool_use_id")),
    )
    record["tool_input_summary"] = summarize_tool_input(
        tool_name, event.get("tool_input")
    )
    record["tool_response_summary"] = summarize_tool_response(
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
            record[key] = preview_text(value)

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
        "schema_version": SCHEMA_VERSION,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "runtime": "claude",
        "event": event_name,
        "status": status,
    }
    if tool_name:
        record["tool_name"] = preview_text(tool_name)
    if tool_use_id:
        record["tool_use_id"] = preview_text(tool_use_id)
    if session_id:
        record["session_id"] = preview_text(session_id)
    if parent_tool_use_id:
        record["parent_tool_use_id"] = preview_text(parent_tool_use_id)
    if message_id:
        record["message_id"] = preview_text(message_id)
    if message_uuid:
        record["message_uuid"] = preview_text(message_uuid)
    return record


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


normalize_claude_hook_payload = _normalize_claude_hook_payload
normalize_claude_stream_event = _normalize_claude_stream_event
