"""Muse Code tool-call artifact normalization.

Muse's ``muse exec --json`` stream never carries tool *arguments*. What it
carries is a four-event state machine, verified against the release-keyed
captures in ``tests/llm_provider/fixtures/``:

- ``task.lifecycle.proposed`` — ``task_kind: "tool.<name>"`` opens a call.
- ``task.lifecycle.scheduled`` and ``task.lifecycle.side_effect_intent`` —
  ``idempotency_key: "tool:<call_id>"`` binds the task id to its call id.
- ``task.lifecycle.output`` — streamed tool output chunks.
- ``tool.result`` — ``call_id``, ``correlation_facts.{tool_name,outcome}``,
  an optional ``edit_facts.{path,added}``, and the result ``text``.

Only ``task_kind`` values under the ``tool.`` prefix become tool records:
``model.meta.response`` and ``reminder.agent.plugin:*`` tasks share the same
lifecycle events and must never be reported as tool calls.

Because arguments are absent, the record's target is derived honestly and in
one fixed order: ``edit_facts.path`` when present, then the ``command`` /
``description`` fields of a ``bash`` result's JSON body, and otherwise a
bounded preview of the result text.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._tool_call_common import (
    ToolCallDurationTracker,
    base_stream_tool_call_record,
    preview_text,
    string_or_none,
    summarize_tool_input,
    summarize_tool_response,
)
from ._tool_call_io import append_jsonl, append_writer_diagnostic

MUSE_TOOL_TASK_KIND_PREFIX = "tool."
MUSE_TOOL_IDEMPOTENCY_PREFIX = "tool:"

PAYLOAD_TASK_PROPOSED = "task.lifecycle.proposed"
PAYLOAD_TASK_SCHEDULED = "task.lifecycle.scheduled"
PAYLOAD_TASK_SIDE_EFFECT_INTENT = "task.lifecycle.side_effect_intent"
PAYLOAD_TASK_OUTPUT = "task.lifecycle.output"
PAYLOAD_TOOL_RESULT = "tool.result"

MUSE_TOOL_CALL_PAYLOAD_TYPES = frozenset(
    {
        PAYLOAD_TASK_PROPOSED,
        PAYLOAD_TASK_SCHEDULED,
        PAYLOAD_TASK_SIDE_EFFECT_INTENT,
        PAYLOAD_TASK_OUTPUT,
        PAYLOAD_TOOL_RESULT,
    }
)

# ``correlation_facts.outcome`` values that are not a plain success.
_FAILURE_OUTCOMES = frozenset({"error", "failed", "failure", "rejected"})
_INTERRUPTED_OUTCOMES = frozenset({"cancelled", "canceled", "interrupted"})

_MUSE_DISPLAY_TOOL_NAMES = {
    "bash": "Bash",
    "edit_file": "Edit",
    "glob": "Glob",
    "grep": "Grep",
    "list_directory": "Glob",
    "read_file": "Read",
    "web_fetch": "WebFetch",
    "web_search": "WebSearch",
    "write_file": "Write",
}

# Result-body fields a ``bash`` tool result carries in place of the arguments
# the stream never emits.
_BASH_RESULT_INPUT_FIELDS = ("command", "description")


@dataclass
class _PendingMuseToolCall:
    """A ``tool.<name>`` task observed but not yet closed by ``tool.result``."""

    tool_name: str
    call_id: str | None = None
    emitted_use: bool = False
    output_chunks: list[str] = field(default_factory=list)


@dataclass
class MuseToolCallTracker:
    """Per-run state binding Muse task ids to tool call ids.

    Muse announces a tool task and its call id in two separate events, and the
    result arrives keyed by call id only, so the binding has to be carried
    across the stream rather than derived from any single event.
    """

    pending_by_task: dict[str, _PendingMuseToolCall] = field(default_factory=dict)
    pending_by_call: dict[str, _PendingMuseToolCall] = field(default_factory=dict)
    durations: ToolCallDurationTracker = field(default_factory=ToolCallDurationTracker)


def append_muse_tool_call_events(
    tracker: MuseToolCallTracker,
    payload_type: str,
    payload: Mapping[str, Any],
    *,
    artifacts_dir: str | None = None,
) -> None:
    """Best-effort append of Muse tool events to ``tool_calls.jsonl``.

    Telemetry must never fail a run, so every normalization or write failure is
    reduced to a writer diagnostic.
    """
    artifacts_dir = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    try:
        records = normalize_muse_tool_call_event(tracker, payload_type, payload)
        for record in records:
            append_jsonl(Path(artifacts_dir) / "tool_calls.jsonl", record)
    except Exception as exc:
        append_writer_diagnostic(artifacts_dir, {"type": payload_type}, exc)


def normalize_muse_tool_call_event(
    tracker: MuseToolCallTracker,
    payload_type: str,
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Advance *tracker* with one event and return the records it produced."""
    if payload_type == PAYLOAD_TASK_PROPOSED:
        _open_pending_call(tracker, payload)
        return []
    if payload_type in (PAYLOAD_TASK_SCHEDULED, PAYLOAD_TASK_SIDE_EFFECT_INTENT):
        record = _bind_call_id(tracker, payload)
        return [record] if record is not None else []
    if payload_type == PAYLOAD_TASK_OUTPUT:
        _record_output_chunk(tracker, payload)
        return []
    if payload_type == PAYLOAD_TOOL_RESULT:
        record = _close_tool_call(tracker, payload)
        return [record] if record is not None else []
    return []


def _open_pending_call(
    tracker: MuseToolCallTracker, payload: Mapping[str, Any]
) -> None:
    """Open a pending call for a ``tool.<name>`` task, ignoring other kinds."""
    event = payload.get("event")
    if not isinstance(event, Mapping):
        return
    task_id = string_or_none(event.get("task_id"))
    task_kind = string_or_none(event.get("task_kind"))
    if not task_id or not task_kind:
        return
    if not task_kind.startswith(MUSE_TOOL_TASK_KIND_PREFIX):
        return

    tool_name = task_kind[len(MUSE_TOOL_TASK_KIND_PREFIX) :]
    if not tool_name:
        return
    tracker.pending_by_task[task_id] = _PendingMuseToolCall(tool_name=tool_name)


def _bind_call_id(
    tracker: MuseToolCallTracker, payload: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Bind ``task_id`` to its ``call_id`` and emit the pending ``ToolUse``."""
    event = payload.get("event")
    if not isinstance(event, Mapping):
        return None
    task_id = string_or_none(event.get("task_id"))
    if not task_id:
        return None
    pending = tracker.pending_by_task.get(task_id)
    if pending is None:
        return None

    call_id = _tool_call_id(event)
    if not call_id:
        return None

    # A tool task emits both ``scheduled`` and ``side_effect_intent`` with the
    # same idempotency key; only the first one opens the record.
    pending.call_id = call_id
    tracker.pending_by_call[call_id] = pending
    if pending.emitted_use:
        return None
    pending.emitted_use = True

    tool_name = _display_tool_name(pending.tool_name)
    record = _base_muse_record("ToolUse", "pending", tool_name, call_id)
    record["tool_input_summary"] = {}
    record["tool_response_summary"] = {}
    tracker.durations.remember_start(call_id)
    return record


def _tool_call_id(event: Mapping[str, Any]) -> str | None:
    """Return the ``call_id`` a scheduled/intent event carries, if any."""
    idempotency_key = string_or_none(event.get("idempotency_key"))
    if idempotency_key and idempotency_key.startswith(MUSE_TOOL_IDEMPOTENCY_PREFIX):
        return idempotency_key[len(MUSE_TOOL_IDEMPOTENCY_PREFIX) :] or None
    return None


def _record_output_chunk(
    tracker: MuseToolCallTracker, payload: Mapping[str, Any]
) -> None:
    """Accumulate streamed tool output for a pending call."""
    event = payload.get("event")
    if not isinstance(event, Mapping):
        return
    task_id = string_or_none(event.get("task_id"))
    chunk = event.get("chunk")
    if not task_id or not isinstance(chunk, str) or not chunk:
        return
    pending = tracker.pending_by_task.get(task_id)
    if pending is None:
        return
    pending.output_chunks.append(chunk)


def _close_tool_call(
    tracker: MuseToolCallTracker, payload: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Close a call with its outcome, derived target, and result summary."""
    call_id = string_or_none(payload.get("call_id"))
    correlation_facts = payload.get("correlation_facts")
    facts = correlation_facts if isinstance(correlation_facts, Mapping) else {}

    pending = tracker.pending_by_call.pop(call_id, None) if call_id else None
    raw_tool_name = string_or_none(facts.get("tool_name")) or (
        pending.tool_name if pending else None
    )
    if not call_id and not raw_tool_name:
        return None

    if pending is not None:
        tracker.pending_by_task = {
            task_id: value
            for task_id, value in tracker.pending_by_task.items()
            if value is not pending
        }

    tool_name = _display_tool_name(raw_tool_name)
    status = _result_status(facts.get("outcome"))
    text = payload.get("text")
    result_body = _parse_result_body(text)

    record = _base_muse_record("ToolResult", status, tool_name, call_id)
    record["tool_input_summary"] = _derive_tool_input_summary(
        tool_name,
        raw_tool_name,
        payload.get("edit_facts"),
        result_body,
        text,
    )
    record["tool_response_summary"] = summarize_tool_response(
        tool_name=tool_name,
        tool_response=_derive_tool_response(result_body, text),
        is_error=status == "failure",
        interrupted=status == "interrupted",
    )
    if status == "interrupted":
        record["is_interrupt"] = True
    tracker.durations.record_duration(record, call_id)
    return record


def _derive_tool_input_summary(
    tool_name: str | None,
    raw_tool_name: str | None,
    edit_facts: Any,
    result_body: Mapping[str, Any] | None,
    text: Any,
) -> dict[str, Any]:
    """Reconstruct a best-effort tool input from what the stream does carry.

    The derivation order is fixed and deliberately conservative, because Muse
    never emits the arguments themselves: ``edit_facts.path``, then a ``bash``
    result's own ``command``/``description``, then a bounded preview of the
    result text. Nothing is inferred beyond those three.
    """
    if isinstance(edit_facts, Mapping):
        path = string_or_none(edit_facts.get("path"))
        if path:
            derived: dict[str, Any] = {"file_path": preview_text(path)}
            added = edit_facts.get("added")
            if isinstance(added, int) and not isinstance(added, bool):
                derived["lines_added"] = added
            return derived

    if raw_tool_name == "bash" and result_body is not None:
        command_input = {
            key: result_body[key]
            for key in _BASH_RESULT_INPUT_FIELDS
            if isinstance(result_body.get(key), str)
        }
        if command_input:
            # Routed through the shared summarizer so secret-looking shell
            # assignments are redacted the same way they are for every other
            # provider.
            return summarize_tool_input(tool_name, command_input)

    if isinstance(text, str) and text:
        return {"result_preview": preview_text(text)}
    return {}


def _derive_tool_response(
    result_body: Mapping[str, Any] | None, text: Any
) -> Mapping[str, Any] | str | None:
    """Return the richest result envelope available for summarization."""
    if result_body is not None:
        return result_body
    if isinstance(text, str) and text:
        return {"output": text}
    return None


def _parse_result_body(text: Any) -> dict[str, Any] | None:
    """Return a ``tool.result`` text body parsed as JSON, when it is JSON."""
    if not isinstance(text, str) or not text:
        return None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return dict(parsed) if isinstance(parsed, Mapping) else None


def _result_status(outcome: Any) -> str:
    normalized = outcome.lower() if isinstance(outcome, str) else ""
    if normalized in _FAILURE_OUTCOMES:
        return "failure"
    if normalized in _INTERRUPTED_OUTCOMES:
        return "interrupted"
    return "success"


def _display_tool_name(tool_name: str | None) -> str | None:
    if not tool_name:
        return None
    return _MUSE_DISPLAY_TOOL_NAMES.get(tool_name, preview_text(tool_name))


def _base_muse_record(
    event: str,
    status: str,
    tool_name: str | None,
    tool_use_id: str | None,
) -> dict[str, Any]:
    return base_stream_tool_call_record(
        "muse",
        event,
        status,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
    )


__all__ = [
    "MUSE_TOOL_CALL_PAYLOAD_TYPES",
    "MuseToolCallTracker",
    "append_muse_tool_call_events",
    "normalize_muse_tool_call_event",
]
