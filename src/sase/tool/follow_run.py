"""Shared bounded follow helper for ``show -F`` and ``wait``.

This module owns the poll, stream, and stage-line loop extracted from
``handle_follow``: the output-of-record streaming, the stage ingestor ticks,
and the unretained-owner notice. ``show -F`` renders its terminal summary on
top of it; ``wait`` follows with streaming switched off. ``wait_for_settlement``
stays the single poll-and-reconcile primitive underneath.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Callable

from sase.tool._query_shared import write_bytes
from sase.tool.control import (
    UnknownRunError,
    output_paths_for_run,
    wait_for_settlement,
)
from sase.tool.owner import owner_retention

#: Slice length for one ``wait_for_settlement`` call inside the bounded loop.
#: Short slices let a deadline or a stop event end the follow promptly.
_FOLLOW_SLICE_SECONDS = 0.5


@dataclass(frozen=True)
class FollowOutcome:
    """Outcome of :func:`follow_run`."""

    kind: str  # "settled" | "deadline" | "stopped"
    envelope: dict[str, Any] | None = None


def follow_run(
    run_id: str,
    *,
    deadline_s: float | None = None,
    stream_output: bool = True,
    compact: bool = False,
    on_stage_line: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> FollowOutcome:
    """Follow *run_id* until it settles, the deadline passes, or a stop lands.

    With ``stream_output`` the output of record streams to stdout and stage
    lines go to *on_stage_line* (stderr by default), exactly as ``show -F``
    does. With it off and ``compact`` off, the run is only polled. With it
    off and ``compact`` on, the output of record stays silent but compact
    stage-progress lines still go to *on_stage_line*, matching the inline
    compact executor. Returns a settled outcome carrying the final envelope,
    a deadline outcome carrying the last-seen envelope (possibly ``None``),
    or a stopped outcome for ``KeyboardInterrupt`` and a set *stop_event*.
    Raises :class:`UnknownRunError` for an unknown id.
    """

    if deadline_s is not None and deadline_s <= 0:
        return FollowOutcome(kind="deadline", envelope=_last_envelope(run_id))

    deadline = None if deadline_s is None else time.monotonic() + deadline_s
    offsets: dict[str, int] = {}
    notified: list[bool] = []
    state: dict[str, Any] = {"ingestor": None}
    emit = on_stage_line or (lambda line: print(line, file=sys.stderr))

    ingest_stages = stream_output or compact

    def _on_poll(envelope: dict[str, Any]) -> None:
        if not stream_output and not compact:
            return
        run = envelope.get("run")
        if not isinstance(run, dict):
            return
        if stream_output:
            _stream_output_paths(run, offsets)
        fresh = _follow_ingestor(run, compact=compact)
        if fresh is not None and (
            state["ingestor"] is None or fresh.path != state["ingestor"].path
        ):
            state["ingestor"] = fresh
        if state["ingestor"] is not None:
            for line in state["ingestor"].tick():
                emit(line)

    if ingest_stages:
        try:
            from sase.core.tool_run import tool_run_show

            first = tool_run_show(run_id)
        except Exception:  # noqa: BLE001 - the poll loop reports unknown runs.
            first = None
        if isinstance(first, dict) and isinstance(first.get("run"), dict):
            if stream_output:
                _stream_output_paths(first["run"], offsets)
                _notice_unretained_output(first["run"], notified)
            fresh = _follow_ingestor(first["run"], compact=compact)
            if fresh is not None:
                state["ingestor"] = fresh
                for line in fresh.tick():
                    emit(line)

    from sase.tool._control_shared import is_settled

    last: dict[str, Any] | None = None
    while True:
        if stop_event is not None and stop_event.is_set():
            return FollowOutcome(kind="stopped", envelope=last)
        remaining: float | None = None
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if last is None:
                    last = _last_envelope(run_id)
                return FollowOutcome(kind="deadline", envelope=last)
        slice_s = (
            min(_FOLLOW_SLICE_SECONDS, remaining)
            if remaining is not None
            else _FOLLOW_SLICE_SECONDS
        )
        try:
            envelope = wait_for_settlement(run_id, timeout_s=slice_s, on_poll=_on_poll)
        except UnknownRunError:
            raise
        except KeyboardInterrupt:
            return FollowOutcome(kind="stopped", envelope=last)
        if envelope is not None:
            last = envelope
            run = envelope.get("run")
            if isinstance(run, dict) and is_settled(run):
                if stream_output:
                    _stream_output_paths(run, offsets)
                    ingestor = state["ingestor"]
                    if ingestor is not None:
                        for line in ingestor.tick():
                            emit(line)
                    _notice_unretained_output(run, notified)
                return FollowOutcome(kind="settled", envelope=envelope)
        if deadline is not None and time.monotonic() >= deadline:
            if last is None:
                last = _last_envelope(run_id)
            return FollowOutcome(kind="deadline", envelope=last)


def _last_envelope(run_id: str) -> dict[str, Any] | None:
    """Return the current show envelope for *run_id*, or ``None``."""

    try:
        from sase.core.tool_run import tool_run_show

        envelope = tool_run_show(run_id)
    except Exception:  # noqa: BLE001 - a transient read is no envelope.
        return None
    return envelope if isinstance(envelope, dict) else None


def _follow_ingestor(run: object, *, compact: bool = False):  # type: ignore[no-untyped-def]
    if not isinstance(run, dict):
        return None
    logs = run.get("logs")
    raw = logs.get("events_path") if isinstance(logs, dict) else None
    if not raw:
        return None
    path = Path(str(raw))
    if not path.is_file():
        return None
    from sase.tool.stage_protocol import StageIngestor

    return StageIngestor(
        path=path, run_id=str(run.get("run_id") or ""), compact=compact
    )


def _stream_output_paths(run: object, offsets: dict[str, int]) -> None:
    """Print bytes appended to the output of record since the last poll."""

    if not isinstance(run, dict):
        return
    for path in output_paths_for_run(run):
        key = str(path)
        start = offsets.get(key, 0)
        try:
            if not path.is_file():
                continue
            size = path.stat().st_size
        except OSError:
            continue
        if size < start:
            start = 0
        if size == start:
            continue
        try:
            with open(path, "rb") as handle:
                handle.seek(start)
                chunk = handle.read()
        except OSError:
            continue
        offsets[key] = size
        if chunk:
            write_bytes(sys.stdout, chunk)


def _notice_unretained_output(run: dict[str, Any], notified: list[bool]) -> None:
    """Say once that an owner-bound run has no output of record to stream."""

    if notified:
        return
    retention = owner_retention(run)
    if retention["owner"] == "none" or retention["log"] == "retained":
        return
    settled = str(run.get("state") or "") not in {"created", "running"}
    if not (settled or retention["owner"] == "pruned"):
        return
    notified.append(True)
    print(_unretained_message(run, retention), file=sys.stderr)


def _unretained_message(run: dict[str, Any], retention: dict[str, Any]) -> str:
    kind = str(run.get("owner_kind") or "owner")
    owner_id = str(run.get("owner_id") or "")
    path = retention.get("log_path")
    if retention["owner"] == "pruned":
        detail = (
            f"; its log {path} is missing" if path else "; its log was not recorded"
        )
        return f"sase: {kind} owner {owner_id} is no longer retained (pruned){detail}"
    if path:
        return f"sase: {kind} owner {owner_id} log {path} is missing or expired"
    return f"sase: {kind} owner {owner_id} did not record an output log"


__all__ = [
    "FollowOutcome",
    "follow_run",
]
