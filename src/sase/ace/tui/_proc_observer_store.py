"""Durable-store reads behind the proc observer.

Everything here runs on the observer daemon thread: session attribution, the
adapter from a stored :class:`~sase.procs.Proc` to an observed row, log tails,
and typed-result decoding for watched operations.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from sase.core.time import local_now, to_local
from sase.ops import OperationIOError, read_operation_result
from sase.procs import Proc, read_proc_log_tail
from sase.procs.runtime import proc_operation_result_path

from ._proc_observer_models import ObservedProc, ProcCompletionRecord

DETAIL_LOG_LINES = 400


@dataclass(frozen=True)
class ProcWatch:
    """One durable operation the observer decodes once its proc goes terminal."""

    operation: str
    result_path: str
    placeholder_id: str | None = None


@dataclass(frozen=True)
class ObserverContext:
    """This process's session attribution, resolved on the observer thread."""

    session_id: str | None
    session_label: str | None
    project: str | None
    workspace_num: int | None
    cwd: str


def store_proc_row(
    proc: Proc,
    *,
    live_session_ids: frozenset[str] = frozenset(),
    with_output: bool = False,
) -> ObservedProc:
    """Adapt one durable proc row into an observed row."""
    started_at = _local_datetime(proc.started_at or proc.created_at) or local_now()
    output = _read_log_tail(proc.proc_id, proc.log_path) if with_output else ""
    return ObservedProc(
        proc_id=proc.proc_id,
        proc_type=proc.kind,
        cl_name=proc.cl_name or "",
        project_file="",
        status=proc.status,
        message=proc.message or "",
        started_at=started_at,
        display_name=proc.label,
        finished_at=_local_datetime(proc.finished_at),
        output=output,
        error=proc.message if proc.status in {"error", "killed"} else None,
        command=list(proc.command) or None,
        phase=proc.phase,
        exit_code=proc.exit_code,
        durable_proc_id=proc.proc_id,
        store_backed=True,
        session_id=proc.session_id,
        session_label=proc.session_label,
        session_live=bool(proc.session_id and proc.session_id in live_session_ids),
        exclusive_scopes=frozenset(proc.concurrency_keys),
        origin=proc.origin,
        log_path=proc.log_path,
        shell_name=proc.shell_name,
        lifecycle=proc.lifecycle,
        project=proc.project,
        workspace_num=proc.workspace_num,
        cwd=proc.cwd,
        shell_kind=proc.shell_kind,
        request_fingerprint=proc.request_fingerprint,
        reserved_at=_local_datetime(proc.reserved_at),
        supervisor_id=proc.supervisor_id,
        stop_requested_by=proc.stop_requested_by,
        stop_requested_at=_local_datetime(proc.stop_requested_at),
        stop_reason=proc.stop_reason,
        timeout_seconds=proc.timeout_seconds,
        idle_timeout_seconds=proc.idle_timeout_seconds,
        settling_started_at=_local_datetime(proc.settling_started_at),
        settled_by=proc.settled_by,
        settled_at=_local_datetime(proc.settled_at),
        xprompt_proc=proc.xprompt_proc,
    )


def decode_completion(proc: Proc, watch: ProcWatch) -> ProcCompletionRecord:
    """Read the typed result envelope a terminal watched proc left behind."""
    raw_result_path = watch.result_path
    if not raw_result_path and isinstance(proc.result, Mapping):
        value = proc.result.get("result_path")
        raw_result_path = value if isinstance(value, str) else ""
    if not raw_result_path:
        raw_result_path = str(proc_operation_result_path(proc.proc_id))
    try:
        result = read_operation_result(
            raw_result_path,
            expected_operation=watch.operation,
            expected_proc_id=proc.proc_id,
        )
    except OperationIOError as exc:
        return ProcCompletionRecord(
            proc_id=proc.proc_id,
            operation=watch.operation,
            result=None,
            error=str(exc),
        )
    return ProcCompletionRecord(
        proc_id=proc.proc_id,
        operation=watch.operation,
        result=result,
    )


def proc_is_relevant(
    proc: Proc,
    *,
    context: ObserverContext,
    watched: Mapping[str, ProcWatch],
) -> bool:
    """Return whether a stored proc belongs in this observer's projection."""
    if proc.proc_id in watched:
        return True
    if proc.session_id is None:
        return True
    if context.session_id is not None and proc.session_id == context.session_id:
        return True
    if proc.origin == "ace":
        return True
    if context.project is not None and proc.project == context.project:
        return True
    if "ace" in proc.tags:
        return True
    return False


def load_observer_context() -> ObserverContext:
    """Resolve this process's session attribution on the observer thread."""
    from sase.sessions import current_session_id, live_sessions, session_display_label

    try:
        session_id: str | None = current_session_id()
    except Exception:
        session_id = None
    identity = None
    if session_id is not None:
        try:
            identity = next(
                (item for item in live_sessions() if item.session_id == session_id),
                None,
            )
        except Exception:
            identity = None
    if identity is None:
        return ObserverContext(
            session_id=session_id,
            session_label=None,
            project=None,
            workspace_num=None,
            cwd=os.getcwd(),
        )
    return ObserverContext(
        session_id=identity.session_id,
        session_label=session_display_label(identity),
        project=identity.project,
        workspace_num=identity.workspace_num,
        cwd=identity.cwd or os.getcwd(),
    )


def live_session_ids() -> frozenset[str]:
    """Return the session ids that currently have a live owner."""
    try:
        from sase.sessions import live_sessions

        return frozenset(identity.session_id for identity in live_sessions())
    except Exception:
        return frozenset()


def _read_log_tail(proc_id: str, log_path: str = "") -> str:
    try:
        return read_proc_log_tail(proc_id, DETAIL_LOG_LINES, log_path=log_path or None)
    except (OSError, ValueError):
        return ""


def _local_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return to_local(parsed)


__all__ = [
    "DETAIL_LOG_LINES",
    "ObserverContext",
    "ProcWatch",
    "decode_completion",
    "live_session_ids",
    "load_observer_context",
    "proc_is_relevant",
    "store_proc_row",
]
