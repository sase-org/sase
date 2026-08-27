"""Typed records and state semantics for monitor family members.

A monitor has no dedicated store: its durable record is the monitor member's
own ``agent_meta.json`` (while running) and ``done.json`` (once terminal),
exactly like any other agent family member. :class:`MonitorRecord` is the
Python-side projection of those two markers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sase.monitor_state import monitor_state_bucket
from sase.monitor_status import MonitorStatusPair, monitor_status_pair

from .followup_prompt import DEFAULT_NEXT_OUTPUT

if TYPE_CHECKING:
    from sase.core.agent_scan_wire import (
        AgentArtifactRecordWire,
        AgentMetaWire,
        DoneMarkerWire,
        FamilyShellWire,
    )

MonitorState = Literal["running", "completed", "failed", "timeout", "stopped", "lost"]

MONITOR_STATES: tuple[MonitorState, ...] = (
    "running",
    "completed",
    "failed",
    "timeout",
    "stopped",
    "lost",
)

#: Every state but ``running`` -- the command has stopped producing output.
TERMINAL_MONITOR_STATES: frozenset[str] = frozenset(
    {"completed", "failed", "timeout", "stopped", "lost"}
)

#: ``followup_outcome`` for a ``--next`` action that only launched after
#: falling back to a fresh claim or workspace 0. It carries a
#: ``followup_degraded_reason`` rather than a ``followup_error``, because the
#: follow-up *is* running -- just not necessarily where the command ran.
MONITOR_FOLLOWUP_DEGRADED_OUTCOME = "launched-degraded"


class MonitorError(RuntimeError):
    """Base class for monitor lifecycle failures."""


class MonitorLaneError(MonitorError):
    """A monitor's lane could not be resolved to a family member."""


class MonitorAlreadyRunningError(MonitorError):
    """The lane already has an active monitor."""


class MonitorRefError(ValueError):
    """A monitor reference was empty, unknown, or ambiguous."""


def _monitor_shell(
    source: AgentMetaWire | DoneMarkerWire | None,
) -> FamilyShellWire | None:
    shell = None if source is None else source.family_shell
    return shell if shell is not None and shell.kind == "monitor" else None


def is_monitor_member_record(record: AgentArtifactRecordWire) -> bool:
    """Return whether *record* is a real monitor family member.

    A row that merely claims ``agent_family_role="monitor"`` but has no
    durable ``monitor_id`` is a historical false positive, not a monitor.
    """
    meta = record.agent_meta
    if meta is None or meta.agent_family_role != "monitor":
        return False
    shell = _monitor_shell(meta)
    return shell is not None and bool(shell.id)


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
    idle_timeout_seconds: float = 0.0
    next_action: str | None = None
    next_model: str | None = None
    next_output: str = DEFAULT_NEXT_OUTPUT
    pid: int | None = None
    exit_code: int | None = None
    elapsed_seconds: float | None = None
    output_path: str | None = None
    output_truncated: bool = False
    starter_agent: str | None = None
    followup_agent: str | None = None
    pgid: int | None = None
    supervisor_identity: str | None = None
    settled: bool = False
    request_fingerprint: str | None = None
    followup_outcome: str | None = None
    followup_error: str | None = None
    followup_degraded_reason: str | None = None
    followup_prompt_path: str | None = None

    @property
    def status_bucket(self) -> str:
        """Return this monitor's status bucket for its current state."""
        if not self.is_terminal:
            return "Running"
        return monitor_state_bucket(self.monitor_state)

    @property
    def is_terminal(self) -> bool:
        """Return whether the monitored command has stopped running."""
        return self.monitor_state in TERMINAL_MONITOR_STATES and self.settled

    @property
    def followup_needs_attention(self) -> bool:
        """Return whether this monitor's ``--next`` action needs a human.

        True for both halves of the stalled-lane contract: a follow-up that
        did not launch at all (``followup_error``) and one that launched
        degraded, into a workspace the monitored command may not have run
        in. A degraded launch records no error, so checking
        ``followup_error`` alone silently misses it.
        """
        return bool(
            self.followup_error
            or self.followup_outcome == MONITOR_FOLLOWUP_DEGRADED_OUTCOME
        )

    @classmethod
    def from_record(cls, record: AgentArtifactRecordWire) -> MonitorRecord:
        """Build a record from an agent-artifact-index scan row."""
        meta = record.agent_meta
        meta_shell = _monitor_shell(meta)
        if meta is None or meta_shell is None or not meta_shell.id:
            raise ValueError(
                f"artifact record at {record.artifact_dir!r} is not a monitor member"
            )
        meta_monitor = meta_shell.monitor
        done = record.done
        done_shell = _monitor_shell(done)
        done_monitor = done_shell.monitor if done_shell is not None else None

        monitor_state: MonitorState = "running"
        if done_shell is not None and done_shell.state:
            monitor_state = done_shell.state  # type: ignore[assignment]
        elif meta_shell.state:
            monitor_state = meta_shell.state  # type: ignore[assignment]

        exit_code: int | None = None
        if done_monitor is not None and done_monitor.exit_code is not None:
            exit_code = done_monitor.exit_code
        elif meta_monitor is not None and meta_monitor.exit_code is not None:
            exit_code = meta_monitor.exit_code

        elapsed_seconds: float | None = None
        if done_shell is not None and done_shell.elapsed_seconds is not None:
            elapsed_seconds = done_shell.elapsed_seconds

        settled = bool((meta_monitor is not None and meta_monitor.settled) or done)

        followup_outcome = (
            done_shell.followup_outcome if done_shell is not None else None
        ) or meta_shell.followup_outcome
        followup_error = (
            done_shell.followup_error if done_shell is not None else None
        ) or meta_shell.followup_error
        followup_degraded_reason = (
            done_shell.followup_degraded_reason if done_shell is not None else None
        ) or meta_shell.followup_degraded_reason
        followup_prompt_path = (
            done_shell.followup_prompt_path if done_shell is not None else None
        ) or meta_shell.followup_prompt_path

        status_pair: MonitorStatusPair = monitor_status_pair(
            meta_shell.start_status, meta_shell.stop_status
        )

        command = meta_monitor.command if meta_monitor is not None else None
        return cls(
            monitor_id=meta_shell.id,
            member_agent_name=meta.name or "",
            lane=meta.agent_family or "",
            project_name=record.project_name,
            artifacts_dir=record.artifact_dir,
            timestamp=record.timestamp,
            command=command or "",
            cwd=(meta_monitor.cwd if meta_monitor is not None else None) or "",
            reason=meta_shell.reason or "",
            label=meta_shell.label or command or "",
            start_status=status_pair.start,
            stop_status=status_pair.stop,
            timeout_seconds=meta_shell.timeout_seconds or 0.0,
            tail_lines=(meta_monitor.tail_lines if meta_monitor is not None else None)
            or 200,
            monitor_state=monitor_state,
            idle_timeout_seconds=(
                meta_monitor.idle_timeout_seconds if meta_monitor is not None else None
            )
            or 0.0,
            next_action=meta_shell.next_action or None,
            next_model=meta_shell.next_model or None,
            next_output=meta_shell.next_output or DEFAULT_NEXT_OUTPUT,
            pid=meta.pid,
            exit_code=exit_code,
            elapsed_seconds=elapsed_seconds,
            output_path=meta_shell.output_path,
            output_truncated=meta_shell.output_truncated,
            starter_agent=(
                meta_monitor.starter_agent if meta_monitor is not None else None
            ),
            followup_agent=meta_shell.followup_agent,
            pgid=meta_monitor.pgid if meta_monitor is not None else None,
            supervisor_identity=(
                meta_monitor.supervisor_identity if meta_monitor is not None else None
            ),
            settled=settled,
            request_fingerprint=meta_shell.request_fingerprint,
            followup_outcome=followup_outcome,
            followup_error=followup_error,
            followup_degraded_reason=followup_degraded_reason,
            followup_prompt_path=followup_prompt_path,
        )


__all__ = [
    "MONITOR_FOLLOWUP_DEGRADED_OUTCOME",
    "MONITOR_STATES",
    "TERMINAL_MONITOR_STATES",
    "MonitorAlreadyRunningError",
    "MonitorError",
    "MonitorLaneError",
    "MonitorRecord",
    "MonitorRefError",
    "MonitorState",
    "is_monitor_member_record",
    "monitor_state_bucket",
]
