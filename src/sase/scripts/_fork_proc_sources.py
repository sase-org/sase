"""Proc and monitor shell projections for the ``#fork`` source resolver.

Builds the typed execution-record metadata for a stand-alone proc shell or a
monitor family member from the durable proc store / monitor markers, kept
separate from :mod:`sase.scripts.agent_chat_from_name` so that module stays
focused on source *resolution* rather than proc/monitor field mapping.
"""

from __future__ import annotations

from dataclasses import dataclass

from sase.monitor.models import MonitorRecord
from sase.monitor_state import monitor_state_is_terminal
from sase.procs import Proc, read_proc_log_tail
from sase.procs.text_bounding import bound_and_redact_text

_LOG_TAIL_LINES = 400
_LOG_TAIL_MAX_CHARS = 12000

#: Standalone proc statuses that mean the command has stopped running.
_TERMINAL_PROC_STATUSES = frozenset({"success", "error", "killed"})

#: Standalone proc statuses that mean the command did not succeed.
_FAILED_PROC_STATUSES = frozenset({"error", "killed"})


@dataclass(frozen=True)
class ForkProcInfo:
    """Typed execution metadata for one proc or monitor fork shell."""

    proc_id: str
    is_monitor: bool
    terminal: bool
    failed: bool
    shell_name: str | None
    command: str | None
    cwd: str | None
    project: str | None
    started_at: str | None
    finished_at: str | None
    status: str
    exit_code: int | None
    timeout_seconds: float | None
    elapsed_seconds: float | None
    log_path: str | None
    log_tail: str | None
    log_truncated: bool
    monitor_lane: str | None = None
    monitor_reason: str | None = None
    monitor_followup_outcome: str | None = None
    monitor_followup_error: str | None = None

    def to_json_data(self) -> dict[str, object]:
        data: dict[str, object] = {
            "proc_id": self.proc_id,
            "is_monitor": self.is_monitor,
            "terminal": self.terminal,
            "failed": self.failed,
            "shell_name": self.shell_name,
            "command": self.command,
            "cwd": self.cwd,
            "project": self.project,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "exit_code": self.exit_code,
            "timeout_seconds": self.timeout_seconds,
            "elapsed_seconds": self.elapsed_seconds,
            "log_path": self.log_path,
            "log_tail": self.log_tail,
            "log_truncated": self.log_truncated,
        }
        if self.is_monitor:
            data["monitor_lane"] = self.monitor_lane
            data["monitor_reason"] = self.monitor_reason
            data["monitor_followup_outcome"] = self.monitor_followup_outcome
            data["monitor_followup_error"] = self.monitor_followup_error
        return data


def _log_tail(proc_id: str, log_path: str | None) -> tuple[str | None, bool]:
    if not log_path:
        return None, False
    try:
        raw = read_proc_log_tail(proc_id, _LOG_TAIL_LINES, log_path=log_path)
    except OSError:
        return None, False
    bounded = bound_and_redact_text(raw, _LOG_TAIL_MAX_CHARS)
    truncated = bool(raw) and (
        bounded is None or len(bounded) < len(raw) or raw.count("\n") >= _LOG_TAIL_LINES
    )
    return bounded, truncated


def proc_info_from_proc(proc: Proc) -> ForkProcInfo:
    """Project a stand-alone proc-store row into typed fork execution metadata."""
    log_tail, truncated = _log_tail(proc.proc_id, proc.log_path)
    return ForkProcInfo(
        proc_id=proc.proc_id,
        is_monitor=False,
        terminal=proc.status in _TERMINAL_PROC_STATUSES,
        failed=proc.status in _FAILED_PROC_STATUSES,
        shell_name=proc.shell_name,
        command=" ".join(proc.command) if proc.command else None,
        cwd=proc.cwd or None,
        project=proc.project,
        started_at=proc.started_at,
        finished_at=proc.finished_at,
        status=proc.status,
        exit_code=proc.exit_code,
        timeout_seconds=(
            float(proc.timeout_seconds) if proc.timeout_seconds is not None else None
        ),
        elapsed_seconds=None,
        log_path=proc.log_path or None,
        log_tail=log_tail,
        log_truncated=truncated,
    )


def proc_info_from_monitor(record: MonitorRecord) -> ForkProcInfo:
    """Project a joined :class:`MonitorRecord` into typed fork execution metadata."""
    terminal = monitor_state_is_terminal(record.monitor_state)
    log_tail, truncated = _log_tail(record.monitor_id, record.output_path)
    return ForkProcInfo(
        proc_id=record.monitor_id,
        is_monitor=True,
        terminal=terminal,
        failed=terminal and record.monitor_state != "completed",
        shell_name=record.label or record.lane or None,
        command=record.command or None,
        cwd=record.cwd or None,
        project=record.project_name or None,
        started_at=record.timestamp or None,
        finished_at=None,
        status=record.monitor_state,
        exit_code=record.exit_code,
        timeout_seconds=record.timeout_seconds or None,
        elapsed_seconds=record.elapsed_seconds,
        log_path=record.output_path,
        log_tail=log_tail,
        log_truncated=truncated or record.output_truncated,
        monitor_lane=record.lane or None,
        monitor_reason=record.reason or None,
        monitor_followup_outcome=record.followup_outcome,
        monitor_followup_error=record.followup_error,
    )


__all__ = ["ForkProcInfo", "proc_info_from_monitor", "proc_info_from_proc"]
