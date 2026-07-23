"""Immutable records for the portable AXE status wire contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


AXE_STATUS_WIRE_SCHEMA_VERSION = 1

type AxeDesiredStateValue = Literal["running", "stopped"]
type AxeLumberjackReportedState = Literal["running", "stopped", "error"]
type AxeLifecycleEventKind = Literal["start", "stop", "restart"]
type AxeOrchestratorState = Literal["running", "stopped", "incoherent"]
type AxeOrchestratorCoherence = Literal["coherent", "incoherent"]
type AxeLumberjackState = Literal[
    "running",
    "not_reporting",
    "stale_process",
    "stale_heartbeat",
    "error",
    "orphaned",
]
type AxeStatusState = Literal[
    "running",
    "maintenance",
    "stopped",
    "not_started",
    "down",
    "degraded",
    "error",
]
type AxeStatusHealth = Literal["healthy", "unhealthy", "error"]
type AxeStatusIssueSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class AxeDesiredStateRecord:
    """One validated desired-state marker."""

    state: AxeDesiredStateValue
    source: str
    timestamp: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "source": self.source,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class AxeProcessObservation:
    """One PID source paired with its host-observed liveness."""

    pid: int | None
    live: bool | None

    def to_wire(self) -> dict[str, Any]:
        return {"pid": self.pid, "live": self.live}


@dataclass(frozen=True)
class AxeOrchestratorObservation:
    """Raw lifecycle-lock and PID-file evidence."""

    lifecycle_lock_held: bool
    lock_holder: AxeProcessObservation
    orchestrator_pid_file: AxeProcessObservation
    legacy_pid_file: AxeProcessObservation

    def to_wire(self) -> dict[str, Any]:
        return {
            "lifecycle_lock_held": self.lifecycle_lock_held,
            "lock_holder": self.lock_holder.to_wire(),
            "orchestrator_pid_file": self.orchestrator_pid_file.to_wire(),
            "legacy_pid_file": self.legacy_pid_file.to_wire(),
        }


@dataclass(frozen=True)
class AxeMaintenanceRecord:
    """One structurally valid maintenance marker."""

    reason: str
    owner_pid: int
    started_at: str
    age_seconds: int

    def to_wire(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "owner_pid": self.owner_pid,
            "started_at": self.started_at,
            "age_seconds": self.age_seconds,
        }


@dataclass(frozen=True)
class AxeRunnerOccupancy:
    """Current and configured maximum runner occupancy."""

    current: int
    maximum: int

    def to_wire(self) -> dict[str, Any]:
        return {"current": self.current, "maximum": self.maximum}


@dataclass(frozen=True)
class AxeLumberjackObservation:
    """Raw host observations for one lumberjack."""

    name: str
    configured: bool
    interval_seconds: int | None
    configured_chops: tuple[str, ...]
    recorded_pid: int | None
    reported_state: AxeLumberjackReportedState | None
    process_live: bool | None
    started_at: str | None
    start_age_seconds: int | None
    heartbeat_at: str | None
    heartbeat_age_seconds: int | None
    cycles_run: int
    errors_encountered: int
    uptime_seconds: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "configured_chops", tuple(self.configured_chops))

    def to_wire(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "configured": self.configured,
            "interval_seconds": self.interval_seconds,
            "configured_chops": list(self.configured_chops),
            "recorded_pid": self.recorded_pid,
            "reported_state": self.reported_state,
            "process_live": self.process_live,
            "started_at": self.started_at,
            "start_age_seconds": self.start_age_seconds,
            "heartbeat_at": self.heartbeat_at,
            "heartbeat_age_seconds": self.heartbeat_age_seconds,
            "cycles_run": self.cycles_run,
            "errors_encountered": self.errors_encountered,
            "uptime_seconds": self.uptime_seconds,
        }


@dataclass(frozen=True)
class AxeLifecycleEvent:
    """Most recent valid lifecycle-journal event."""

    event: AxeLifecycleEventKind
    timestamp: str
    source: str
    outcome: str
    success: bool
    reason: str | None
    orchestrator_pid: int | None
    age_seconds: int | None

    def to_wire(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "timestamp": self.timestamp,
            "source": self.source,
            "outcome": self.outcome,
            "success": self.success,
            "reason": self.reason,
            "orchestrator_pid": self.orchestrator_pid,
            "age_seconds": self.age_seconds,
        }


@dataclass(frozen=True)
class AxeStatusCollectionError:
    """One required host-collection failure."""

    code: str
    message: str

    def to_wire(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class AxeStatusRequest:
    """Complete typed input for the pure Rust classifier."""

    schema_version: int
    generated_at: str
    desired_state: AxeDesiredStateRecord | None
    orchestrator: AxeOrchestratorObservation
    maintenance: AxeMaintenanceRecord | None
    hook_runners: AxeRunnerOccupancy
    agent_runners: AxeRunnerOccupancy
    lumberjacks: tuple[AxeLumberjackObservation, ...]
    latest_lifecycle_event: AxeLifecycleEvent | None
    collection_error: AxeStatusCollectionError | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "lumberjacks", tuple(self.lumberjacks))

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "desired_state": (
                self.desired_state.to_wire() if self.desired_state is not None else None
            ),
            "orchestrator": self.orchestrator.to_wire(),
            "maintenance": (
                self.maintenance.to_wire() if self.maintenance is not None else None
            ),
            "hook_runners": self.hook_runners.to_wire(),
            "agent_runners": self.agent_runners.to_wire(),
            "lumberjacks": [row.to_wire() for row in self.lumberjacks],
            "latest_lifecycle_event": (
                self.latest_lifecycle_event.to_wire()
                if self.latest_lifecycle_event is not None
                else None
            ),
            "collection_error": (
                self.collection_error.to_wire()
                if self.collection_error is not None
                else None
            ),
        }


@dataclass(frozen=True)
class AxeOrchestratorStatus:
    """Raw and derived orchestrator evidence."""

    state: AxeOrchestratorState
    coherence: AxeOrchestratorCoherence
    live_pids: tuple[int, ...]
    lifecycle_lock_held: bool
    lock_holder: AxeProcessObservation
    orchestrator_pid_file: AxeProcessObservation
    legacy_pid_file: AxeProcessObservation

    def __post_init__(self) -> None:
        object.__setattr__(self, "live_pids", tuple(self.live_pids))

    def to_wire(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "coherence": self.coherence,
            "live_pids": list(self.live_pids),
            "lifecycle_lock_held": self.lifecycle_lock_held,
            "lock_holder": self.lock_holder.to_wire(),
            "orchestrator_pid_file": self.orchestrator_pid_file.to_wire(),
            "legacy_pid_file": self.legacy_pid_file.to_wire(),
        }


@dataclass(frozen=True)
class AxeLumberjackStatus:
    """Raw and derived current state for one lumberjack."""

    name: str
    state: AxeLumberjackState
    stale_threshold_seconds: int | None
    configured: bool
    interval_seconds: int | None
    configured_chops: tuple[str, ...]
    recorded_pid: int | None
    reported_state: AxeLumberjackReportedState | None
    process_live: bool | None
    started_at: str | None
    start_age_seconds: int | None
    heartbeat_at: str | None
    heartbeat_age_seconds: int | None
    cycles_run: int
    errors_encountered: int
    uptime_seconds: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "configured_chops", tuple(self.configured_chops))

    def to_wire(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "stale_threshold_seconds": self.stale_threshold_seconds,
            "configured": self.configured,
            "interval_seconds": self.interval_seconds,
            "configured_chops": list(self.configured_chops),
            "recorded_pid": self.recorded_pid,
            "reported_state": self.reported_state,
            "process_live": self.process_live,
            "started_at": self.started_at,
            "start_age_seconds": self.start_age_seconds,
            "heartbeat_at": self.heartbeat_at,
            "heartbeat_age_seconds": self.heartbeat_age_seconds,
            "cycles_run": self.cycles_run,
            "errors_encountered": self.errors_encountered,
            "uptime_seconds": self.uptime_seconds,
        }


@dataclass(frozen=True)
class AxeStatusIssue:
    """One stable actionable status issue."""

    code: str
    severity: AxeStatusIssueSeverity
    subject: str | None
    summary: str
    suggested_command: str | None

    def to_wire(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "subject": self.subject,
            "summary": self.summary,
            "suggested_command": self.suggested_command,
        }


@dataclass(frozen=True)
class AxeStatusSnapshot:
    """Complete immutable classified AXE status snapshot."""

    schema_version: int
    generated_at: str
    state: AxeStatusState
    health: AxeStatusHealth
    summary: str
    exit_code: int
    desired_state: AxeDesiredStateRecord | None
    orchestrator: AxeOrchestratorStatus
    maintenance: AxeMaintenanceRecord | None
    hook_runners: AxeRunnerOccupancy
    agent_runners: AxeRunnerOccupancy
    lumberjacks: tuple[AxeLumberjackStatus, ...]
    latest_lifecycle_event: AxeLifecycleEvent | None
    issues: tuple[AxeStatusIssue, ...]
    collection_error: AxeStatusCollectionError | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "lumberjacks", tuple(self.lumberjacks))
        object.__setattr__(self, "issues", tuple(self.issues))

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "state": self.state,
            "health": self.health,
            "summary": self.summary,
            "exit_code": self.exit_code,
            "desired_state": (
                self.desired_state.to_wire() if self.desired_state is not None else None
            ),
            "orchestrator": self.orchestrator.to_wire(),
            "maintenance": (
                self.maintenance.to_wire() if self.maintenance is not None else None
            ),
            "hook_runners": self.hook_runners.to_wire(),
            "agent_runners": self.agent_runners.to_wire(),
            "lumberjacks": [row.to_wire() for row in self.lumberjacks],
            "latest_lifecycle_event": (
                self.latest_lifecycle_event.to_wire()
                if self.latest_lifecycle_event is not None
                else None
            ),
            "issues": [issue.to_wire() for issue in self.issues],
            "collection_error": (
                self.collection_error.to_wire()
                if self.collection_error is not None
                else None
            ),
        }
