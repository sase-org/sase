"""Muse Code (``muse exec --json``) JSONL subprocess parsing.

Every ``muse exec --json`` stdout line is a self-describing envelope::

    {"schema_version": 1, "sequence": 45, "record_type": "event",
     "durability": "durable", "payload_type": "run.output.delta",
     "payload_schema_version": 1, "payload": {...}}

Human diagnostics go to stderr, so stdout is pure JSONL. The parser rules,
in priority order:

1. ``run.terminal.*`` carries the authoritative reply in ``payload.text``;
   ``payload.terminal`` is the outcome and ``payload.reason`` the detail.
2. ``run.output.delta`` is ``ephemeral`` and repeats the same text the
   terminal event later returns. It streams into ``live_reply.md`` for live
   display only and is never appended to the returned content.
3. A failed, rejected, or cancelled *task* is not a failed *run*. Muse emits
   ``task.lifecycle.rejected``/``cancelled`` on runs that exit ``0``, so
   task-level failures are recorded as diagnostics that only reach stderr
   when the process itself failed.
4. Unrecognized payload types and higher schema versions never raise; they
   are recorded as bounded artifact diagnostics instead.
5. Exit code ``2`` is a CLI usage error, not a model failure, and says so.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import IO

from ._muse_session_usage import read_muse_session_usage
from ._subprocess_artifacts import (
    append_stream_text,
    initial_usage_totals,
    open_live_reply_file,
    open_live_reply_timestamps_file,
    write_run_metadata_artifact,
    write_usage_artifact,
)
from ._subprocess_diagnostics import record_stdout_json_decode_diagnostic
from ._subprocess_stream import append_error_events, stream_json_lines
from ._tool_call_io import append_tool_call_collector_diagnostic
from ._tool_call_muse import (
    MUSE_TOOL_CALL_PAYLOAD_TYPES,
    MuseToolCallTracker,
    append_muse_tool_call_events,
)

# --- Muse event-stream vocabulary -------------------------------------
# Every payload-type and envelope-field string Muse's stream parser depends
# on lives here so a beta rename is a one-line fix rather than a grep.

MUSE_RUNTIME_NAME = "muse"

ENVELOPE_SCHEMA_VERSION_FIELD = "schema_version"
ENVELOPE_PAYLOAD_SCHEMA_VERSION_FIELD = "payload_schema_version"
ENVELOPE_PAYLOAD_TYPE_FIELD = "payload_type"
ENVELOPE_PAYLOAD_FIELD = "payload"

SUPPORTED_SCHEMA_VERSION = 1
SUPPORTED_PAYLOAD_SCHEMA_VERSION = 1

PAYLOAD_RUN_OUTPUT_DELTA = "run.output.delta"
PAYLOAD_RUN_TERMINAL_PREFIX = "run.terminal."
PAYLOAD_RUN_MODEL_CONFIGURED = "run.model.configured"
PAYLOAD_TASK_REJECTED = "task.lifecycle.rejected"
PAYLOAD_TASK_CANCELLED = "task.lifecycle.cancelled"
PAYLOAD_TASK_FAILED = "task.lifecycle.failed"

# Terminal outcomes: ``payload.terminal`` values that mean the run produced a
# real answer. Anything else is surfaced as a diagnostic.
TERMINAL_OUTCOME_COMPLETED = "completed"

# ``muse exec`` exits 2 for an invalid command line. Saying so keeps a bad
# SASE-built flag from reading as a model failure.
MUSE_USAGE_ERROR_EXIT_CODE = 2
MUSE_USAGE_ERROR_NOTE = (
    "[muse] exit code 2 is a `muse exec` usage error (invalid command line), "
    "not a model or run failure. Check the SASE-built argv above."
)

_MAX_SCHEMA_DIAGNOSTICS = 5
_schema_diagnostic_counts: dict[tuple[str, str], int] = {}


@dataclass
class _MuseStreamState:
    """Mutable accumulator threaded through the per-line Muse parser."""

    suppress_output: bool
    live_reply_file: IO[str] | None = None
    timestamps_file: IO[str] | None = None
    terminal_texts: list[str] = field(default_factory=list)
    streamed_texts: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    # Captured from ``run.model.configured``: the model Muse actually
    # configured, which closes the gap where a run with no SASE-resolved model
    # or effort shows blank while Muse quietly used its own defaults.
    model_id: str | None = None
    provider_id: str | None = None
    tool_calls: MuseToolCallTracker = field(default_factory=MuseToolCallTracker)


def stream_and_parse_muse_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
    *,
    session_id: str | None = None,
) -> tuple[str, str, int, dict[str, int]]:
    """Stream ``muse exec --json`` events and extract the authoritative reply.

    Returns ``(content, stderr_content, return_code, usage_totals)``. Muse's
    stdout stream carries no token usage at all, so ``usage_totals`` is
    recovered after the process exits from the on-disk session log SASE named
    via ``--session-id``. Without a *session_id* the totals stay zeroed.
    """
    state = _MuseStreamState(
        suppress_output=suppress_output,
        live_reply_file=open_live_reply_file(),
        timestamps_file=open_live_reply_timestamps_file(),
    )

    try:
        stderr_content, return_code = stream_json_lines(
            process,
            lambda line: _process_muse_json_line(line, state),
            suppress_output,
        )
    finally:
        if state.live_reply_file:
            state.live_reply_file.close()
        if state.timestamps_file:
            state.timestamps_file.close()

    content = _resolve_muse_content(state)
    # The session log is only complete once Muse has exited, so usage is read
    # here rather than streamed.
    usage_totals = (
        read_muse_session_usage(session_id) if session_id else initial_usage_totals()
    )
    write_usage_artifact(usage_totals)
    _write_muse_run_metadata(state, session_id)

    stderr_content = append_error_events(stderr_content, return_code, state.diagnostics)
    if return_code == MUSE_USAGE_ERROR_EXIT_CODE:
        stderr_content = (
            f"{stderr_content}\n{MUSE_USAGE_ERROR_NOTE}"
            if stderr_content
            else MUSE_USAGE_ERROR_NOTE
        )

    return content, stderr_content, return_code, usage_totals


def _process_muse_json_line(line: str, state: _MuseStreamState) -> None:
    """Parse one ``muse exec --json`` JSONL envelope into *state*."""
    line = line.strip()
    if not line:
        return

    try:
        envelope = json.loads(line)
    except json.JSONDecodeError as exc:
        record_stdout_json_decode_diagnostic(MUSE_RUNTIME_NAME, line, exc)
        _record_schema_diagnostic(
            reason="muse_stdout_envelope_unparsed",
            raw_preview=line,
            extra={"error": exc.msg},
        )
        return

    if not isinstance(envelope, Mapping):
        return

    _note_unknown_schema_version(envelope, line)

    payload_type = envelope.get(ENVELOPE_PAYLOAD_TYPE_FIELD)
    payload = envelope.get(ENVELOPE_PAYLOAD_FIELD)
    if not isinstance(payload_type, str) or not isinstance(payload, Mapping):
        return

    if payload_type == PAYLOAD_RUN_OUTPUT_DELTA:
        _stream_output_delta(payload, state)
    elif payload_type.startswith(PAYLOAD_RUN_TERMINAL_PREFIX):
        _capture_run_terminal(payload, state)
    elif payload_type == PAYLOAD_RUN_MODEL_CONFIGURED:
        _capture_model_identity(payload, state)
    elif payload_type in (
        PAYLOAD_TASK_REJECTED,
        PAYLOAD_TASK_CANCELLED,
        PAYLOAD_TASK_FAILED,
    ):
        _capture_task_diagnostic(payload_type, payload, state)
    # Any other payload type — including ones this release has never seen —
    # is deliberately ignored rather than treated as an error.

    if payload_type in MUSE_TOOL_CALL_PAYLOAD_TYPES:
        append_muse_tool_call_events(state.tool_calls, payload_type, payload)


def _capture_model_identity(
    payload: Mapping[str, object], state: _MuseStreamState
) -> None:
    """Record the model and provider Muse configured for this run."""
    model_id = payload.get("model_id")
    if isinstance(model_id, str) and model_id:
        state.model_id = model_id
    provider_id = payload.get("provider_id")
    if isinstance(provider_id, str) and provider_id:
        state.provider_id = provider_id


def _write_muse_run_metadata(state: _MuseStreamState, session_id: str | None) -> None:
    """Persist the model Muse actually configured, plus the session handle."""
    fields: dict[str, object] = {}
    if state.model_id:
        fields["model_id"] = state.model_id
    if state.provider_id:
        fields["provider_id"] = state.provider_id
    if session_id:
        fields["muse_session_id"] = session_id
    if fields:
        fields["runtime"] = MUSE_RUNTIME_NAME
        write_run_metadata_artifact(fields)


def _stream_output_delta(
    payload: Mapping[str, object], state: _MuseStreamState
) -> None:
    """Stream an ephemeral output delta into the live-reply artifacts only."""
    text = payload.get("text")
    if not isinstance(text, str) or not text:
        return
    # ``state.streamed_texts`` is display-only bookkeeping: it drives the
    # blank-line separator in ``live_reply.md`` and is never returned as the
    # reply, because the terminal event repeats the same text verbatim.
    append_stream_text(
        text,
        state.streamed_texts,
        state.suppress_output,
        state.live_reply_file,
        state.timestamps_file,
    )


def _capture_run_terminal(
    payload: Mapping[str, object],
    state: _MuseStreamState,
) -> None:
    """Record the authoritative reply text and the run's terminal outcome."""
    outcome = payload.get("terminal")
    if isinstance(outcome, str) and outcome and outcome != TERMINAL_OUTCOME_COMPLETED:
        reason = payload.get("reason")
        detail = f": {reason}" if isinstance(reason, str) and reason else ""
        state.diagnostics.append(f"[muse] run terminal {outcome}{detail}")

    text = payload.get("text")
    if isinstance(text, str) and text:
        state.terminal_texts.append(text)


def _capture_task_diagnostic(
    payload_type: str,
    payload: Mapping[str, object],
    state: _MuseStreamState,
) -> None:
    """Record a task-level failure as a diagnostic, never as a run failure."""
    event = payload.get("event")
    reason = event.get("reason") if isinstance(event, Mapping) else None
    kind = payload_type.rsplit(".", 1)[-1]
    detail = f": {reason}" if isinstance(reason, str) and reason else ""
    state.diagnostics.append(f"[muse] task {kind}{detail}")


def _resolve_muse_content(state: _MuseStreamState) -> str:
    """Return the reply text, preferring the authoritative terminal events."""
    if state.terminal_texts:
        return "\n\n".join(state.terminal_texts)

    # No terminal event arrived. Returning an empty success here would hide a
    # schema drift behind a blank reply, so record it and fall back to the
    # streamed deltas rather than losing the answer.
    _record_schema_diagnostic(
        reason="muse_missing_run_terminal_event",
        extra={"streamed_chunks": len(state.streamed_texts)},
    )
    return "\n\n".join(state.streamed_texts)


def _note_unknown_schema_version(envelope: Mapping[str, object], line: str) -> None:
    """Record a bounded diagnostic for envelope/payload versions from the future."""
    schema_version = envelope.get(ENVELOPE_SCHEMA_VERSION_FIELD)
    payload_version = envelope.get(ENVELOPE_PAYLOAD_SCHEMA_VERSION_FIELD)
    newer_schema = (
        isinstance(schema_version, int) and schema_version > SUPPORTED_SCHEMA_VERSION
    )
    newer_payload = (
        isinstance(payload_version, int)
        and payload_version > SUPPORTED_PAYLOAD_SCHEMA_VERSION
    )
    if not newer_schema and not newer_payload:
        return

    _record_schema_diagnostic(
        reason="muse_stdout_schema_version_ahead",
        raw_preview=line,
        extra={
            "payload_type": envelope.get(ENVELOPE_PAYLOAD_TYPE_FIELD),
            "schema_version": schema_version,
            "payload_schema_version": payload_version,
            "supported_schema_version": SUPPORTED_SCHEMA_VERSION,
            "supported_payload_schema_version": SUPPORTED_PAYLOAD_SCHEMA_VERSION,
        },
    )


def _record_schema_diagnostic(
    *,
    reason: str,
    raw_preview: str = "",
    extra: Mapping[str, object] | None = None,
) -> None:
    """Append a bounded Muse schema diagnostic to the artifacts directory."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    key = (artifacts_dir, reason)
    count = _schema_diagnostic_counts.get(key, 0)
    if count >= _MAX_SCHEMA_DIAGNOSTICS:
        return
    _schema_diagnostic_counts[key] = count + 1

    append_tool_call_collector_diagnostic(
        artifacts_dir,
        reason=reason,
        raw_preview=raw_preview,
        extra=dict(extra) if extra else None,
    )


__all__ = [
    "MUSE_RUNTIME_NAME",
    "MUSE_USAGE_ERROR_EXIT_CODE",
    "MUSE_USAGE_ERROR_NOTE",
    "stream_and_parse_muse_json_output",
]
