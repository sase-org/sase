"""Project proc rows onto monitor records and agent-session state."""

from __future__ import annotations

from dataclasses import replace

from sase.procs.models import (
    ACTIVE_PROC_STATUSES,
    TERMINAL_PROC_STATUSES,
    Proc,
    ProcObservedSettlementOutcome,
    ProcStoreSnapshot,
)
from sase.procs.settlement import is_named_proc_row
from sase.procs.store import get_proc

from ._proc_adapter_helpers import elapsed_seconds
from .models import MonitorRecord, MonitorState


def named_proc_owns(
    monitor_id: str, *, snapshot: ProcStoreSnapshot | None = None
) -> bool:
    """Return whether *monitor_id* is a named-proc row the facade must not adopt.

    Pass *snapshot* to answer many ownership checks from one store read.
    """
    proc = get_proc(monitor_id, snapshot=snapshot)
    return proc is not None and is_named_proc_row(proc)


def _termination_reason(proc: Proc) -> str | None:
    outcome = ProcObservedSettlementOutcome.from_dict(proc.settlement_outcome)
    if outcome is not None and outcome.termination_reason:
        return outcome.termination_reason
    result = proc.result
    if isinstance(result, dict):
        reason = result.get("termination_reason")
        if isinstance(reason, str) and reason:
            return reason
    return proc.stop_reason


def _monitor_state_from_proc(
    proc: Proc, *, termination_reason: str | None = None
) -> MonitorState:
    """Project a proc row onto the monitor agent-session-member state labels."""
    reason = termination_reason or _termination_reason(proc)
    if proc.status in ACTIVE_PROC_STATUSES:
        return "running"
    if reason == "stop" or proc.status == "killed":
        return "stopped"
    if reason in {"total-timeout", "idle-timeout"}:
        return "timeout"
    if reason in {"reboot", "supervisor-loss"}:
        return "lost"
    if proc.status == "success" or reason == "success":
        return "completed"
    return "failed"


def overlay_proc_on_monitor(record: MonitorRecord, proc: Proc) -> MonitorRecord:
    """Overlay live proc execution state onto an artifacts projection."""
    pid = proc.pid if proc.pid is not None else record.pid
    pgid = proc.pgid if proc.pgid is not None else record.pgid
    identity = proc.supervisor_id or record.supervisor_identity
    output_path = proc.log_path or record.output_path
    fingerprint = proc.request_fingerprint or record.request_fingerprint
    if record.settled:
        return replace(
            record,
            pid=pid,
            pgid=pgid,
            supervisor_identity=identity,
            output_path=output_path,
            request_fingerprint=fingerprint,
        )
    reason = _termination_reason(proc)
    monitor_state = _monitor_state_from_proc(proc, termination_reason=reason)
    settled = proc.status in TERMINAL_PROC_STATUSES
    elapsed = elapsed_seconds(proc)
    return replace(
        record,
        pid=pid,
        pgid=pgid,
        supervisor_identity=identity,
        output_path=output_path,
        exit_code=proc.exit_code if proc.exit_code is not None else record.exit_code,
        monitor_state=monitor_state,
        settled=settled,
        elapsed_seconds=elapsed if elapsed is not None else record.elapsed_seconds,
        request_fingerprint=fingerprint,
    )
