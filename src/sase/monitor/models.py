"""Typed records and state semantics for monitor family members.

A monitor has no dedicated store: its durable record is the monitor member's
own ``agent_meta.json`` (while running) and ``done.json`` (once terminal),
exactly like any other agent family member. :class:`MonitorRecord` is the
Python-side projection of those two markers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sase.core.agent_scan_wire import AgentArtifactRecordWire

MonitorState = Literal["running", "completed", "failed", "timeout", "stopped"]

MONITOR_STATES: tuple[MonitorState, ...] = (
    "running",
    "completed",
    "failed",
    "timeout",
    "stopped",
)

#: Every state but ``running`` -- the command has stopped producing output.
TERMINAL_MONITOR_STATES: frozenset[str] = frozenset(
    {"completed", "failed", "timeout", "stopped"}
)

_MONITOR_STATE_BUCKETS: dict[str, str] = {
    "running": "Running",
    "completed": "Done",
    "failed": "Failed",
    "timeout": "Failed",
    "stopped": "Done",
}


class MonitorError(RuntimeError):
    """Base class for monitor lifecycle failures."""


class MonitorLaneError(MonitorError):
    """A monitor's lane could not be resolved to a family member."""


class MonitorAlreadyRunningError(MonitorError):
    """The lane already has an active monitor."""


def monitor_state_bucket(monitor_state: str | None) -> str:
    """Return the status bucket for a monitor's ``monitor_state``.

    An unrecognized or missing state buckets as ``Running`` so a monitor
    member that has not (yet) reached a terminal state never reads as
    finished.
    """
    return _MONITOR_STATE_BUCKETS.get(monitor_state or "", "Running")


@dataclass(frozen=True)
class MonitorRecord:
    """Projection of one monitor family member's durable record."""

    monitor_id: str
    member_agent_name: str
    lane: str
    project_name: str
    artifacts_dir: str
    timestamp: str
    command: str
    cwd: str
    reason: str
    label: str
    start_status: str
    stop_status: str
    timeout_seconds: float
    tail_lines: int
    monitor_state: MonitorState
    next_action: str | None = None
    pid: int | None = None
    exit_code: int | None = None
    output_path: str | None = None
    output_truncated: bool = False
    starter_agent: str | None = None
    followup_agent: str | None = None

    @property
    def status_bucket(self) -> str:
        """Return this monitor's status bucket for its current state."""
        return monitor_state_bucket(self.monitor_state)

    @property
    def is_terminal(self) -> bool:
        """Return whether the monitored command has stopped running."""
        return self.monitor_state in TERMINAL_MONITOR_STATES

    @classmethod
    def from_record(cls, record: AgentArtifactRecordWire) -> MonitorRecord:
        """Build a record from an agent-artifact-index scan row."""
        meta = record.agent_meta
        if meta is None or not meta.monitor_id:
            raise ValueError(
                f"artifact record at {record.artifact_dir!r} is not a monitor member"
            )
        done = record.done
        monitor_state: MonitorState = "running"
        if done is not None and done.monitor_state:
            monitor_state = done.monitor_state  # type: ignore[assignment]
        elif meta.monitor_state:
            monitor_state = meta.monitor_state  # type: ignore[assignment]

        exit_code: int | None = None
        if done is not None and done.monitor_exit_code is not None:
            exit_code = done.monitor_exit_code
        elif meta.monitor_exit_code is not None:
            exit_code = meta.monitor_exit_code

        return cls(
            monitor_id=meta.monitor_id,
            member_agent_name=meta.name or "",
            lane=meta.agent_family or "",
            project_name=record.project_name,
            artifacts_dir=record.artifact_dir,
            timestamp=record.timestamp,
            command=meta.monitor_command or "",
            cwd=meta.monitor_cwd or "",
            reason=meta.monitor_reason or "",
            label=meta.monitor_label or meta.monitor_command or "",
            start_status=meta.monitor_start_status or "MONITORING",
            stop_status=meta.monitor_stop_status or "MONITORED",
            timeout_seconds=meta.monitor_timeout_seconds or 0.0,
            tail_lines=meta.monitor_tail_lines or 200,
            monitor_state=monitor_state,
            next_action=meta.monitor_next_action or None,
            pid=meta.pid,
            exit_code=exit_code,
            output_path=meta.monitor_output_path,
            output_truncated=meta.monitor_output_truncated,
            starter_agent=meta.monitor_starter_agent,
            followup_agent=meta.monitor_followup_agent,
        )


__all__ = [
    "MONITOR_STATES",
    "TERMINAL_MONITOR_STATES",
    "MonitorAlreadyRunningError",
    "MonitorError",
    "MonitorLaneError",
    "MonitorRecord",
    "MonitorState",
    "monitor_state_bucket",
]
