"""Deterministic runner-slot counting, queueing, and admission decisions."""

from __future__ import annotations

from importlib import import_module
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    FamilyShellWire,
)
from sase.monitor_state import is_real_monitor_member

RecordLiveness = Callable[[AgentArtifactRecordWire], bool]
DEFAULT_WAIT_PRIORITY = 10
GATE_FAMILY_ROLE = "gate"
DEFAULT_QUEUE_WEIGHT = 1.0
_RUNNER_CAPACITY_HELPER_LIMIT = 1.0e300
_CANDIDATE_OVERRIDE_FIELDS = {
    "live",
    "queue_weight",
    "queue_weight_explicit",
    "pid",
    "run_started_at",
    "slot_requested_at",
    "wait_runners",
    "wait_runners_explicit",
    "wait_priority",
    "eligible_since",
}


def _family_shell_of_kind(
    meta: AgentMetaWire | None, kind: str
) -> FamilyShellWire | None:
    shell = None if meta is None else meta.family_shell
    return shell if shell is not None and shell.kind == kind else None


def normalize_wait_priority(value: object) -> int:
    """Return a valid queue priority, defaulting invalid marker values."""
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_WAIT_PRIORITY


def runner_slot_waiter_sort_key(
    *,
    priority: object,
    slot_requested_at: str | None,
    timestamp: str | None,
    artifact_dir: str | None,
) -> tuple[int, int, datetime, str, str]:
    """Return the canonical priority/FIFO ordering key for one slot waiter."""
    requested_at = slot_requested_at or ""
    try:
        parsed = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        parsed = parsed.astimezone(UTC)
        invalid = 0
    except ValueError:
        parsed = datetime.max.replace(tzinfo=UTC)
        invalid = 1
    return (
        normalize_wait_priority(priority),
        invalid,
        parsed,
        timestamp or "",
        artifact_dir or "",
    )


def runner_slot_queue_display_key(
    *,
    running_count: int,
    threshold: int | None,
    priority: object,
    slot_requested_at: str | None,
    timestamp: str | None,
    artifact_dir: str | None,
) -> tuple[int, int, int, int, datetime, str, str]:
    """Return the capacity-aware presentation key for one slot waiter."""
    effective_threshold = threshold if threshold is not None else 0
    parked = running_count > effective_threshold
    return (
        1 if parked else 0,
        -effective_threshold if parked else 0,
        *runner_slot_waiter_sort_key(
            priority=priority,
            slot_requested_at=slot_requested_at,
            timestamp=timestamp,
            artifact_dir=artifact_dir,
        ),
    )


def deference_window_seconds(
    priority: int,
    *,
    seconds_per_step: int,
    max_seconds: int,
) -> float:
    """Return the bounded admission delay for a deprioritized waiter."""
    if priority <= DEFAULT_WAIT_PRIORITY:
        return 0.0
    return float(
        min(
            (priority - DEFAULT_WAIT_PRIORITY) * seconds_per_step,
            max_seconds,
        )
    )


def deference_satisfied(
    eligible_since: str | None,
    now: datetime,
    window_seconds: float,
) -> bool:
    """Return whether continuous eligibility has lasted for the full window."""
    if window_seconds <= 0:
        return True
    if not eligible_since:
        return False
    try:
        started = datetime.fromisoformat(eligible_since.replace("Z", "+00:00"))
    except ValueError:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    else:
        started = started.astimezone(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)
    elapsed = (now - started).total_seconds()
    return elapsed >= 0 and elapsed >= window_seconds


@dataclass(frozen=True)
class RunnerSlotWaiter:
    """One live user agent waiting in the global runner-slot queue."""

    artifact_dir: str
    slot_requested_at: str
    timestamp: str
    threshold: int = 0
    priority: int = DEFAULT_WAIT_PRIORITY
    requested_weight: float = DEFAULT_QUEUE_WEIGHT
    eligible: bool = False
    blockers: tuple[dict[str, Any], ...] = ()


def _core_runner_capacity_snapshot(request: dict[str, Any]) -> dict[str, Any]:
    """Return the Rust runner-capacity projection for *request*."""
    try:
        snapshot = import_module("sase_core_rs").runner_capacity_snapshot
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            "sase_core_rs.runner_capacity_snapshot is required for weighted "
            "runner-slot admission; rebuild sase_core_rs from the matching "
            "sase-core checkout."
        ) from exc
    result = snapshot(request)
    if not isinstance(result, dict):
        raise RuntimeError("sase_core_rs returned an invalid runner capacity snapshot")
    return result


def _finite_positive_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    weight = float(value)
    if not weight or not weight > 0 or not weight < float("inf"):
        return None
    return weight


def _record_queue_weight(
    record: AgentArtifactRecordWire,
) -> tuple[float | None, bool, bool]:
    """Return effective scan weight fields, with waiting markers overriding meta."""
    waiting = record.waiting
    if waiting is not None:
        if waiting.queue_weight_invalid:
            return None, waiting.queue_weight_explicit, True
        weight = _finite_positive_float(waiting.queue_weight)
        if weight is not None:
            return weight, waiting.queue_weight_explicit, False
        if waiting.queue_weight is not None:
            return None, waiting.queue_weight_explicit, True

    meta = record.agent_meta
    if meta is None:
        return None, False, False
    if meta.queue_weight_invalid:
        return None, meta.queue_weight_explicit, True
    weight = _finite_positive_float(meta.queue_weight)
    if weight is not None:
        return weight, meta.queue_weight_explicit, False
    if meta.queue_weight is not None:
        return None, meta.queue_weight_explicit, True
    return None, False, False


def _record_wait_priority(record: AgentArtifactRecordWire) -> int | None:
    waiting = record.waiting
    if (
        waiting is not None
        and type(waiting.wait_priority) is int
        and waiting.wait_priority >= 0
    ):
        return waiting.wait_priority
    meta = record.agent_meta
    if meta is None or type(meta.wait_priority) is not int or meta.wait_priority < 0:
        return None
    return meta.wait_priority


def _record_wait_runners(record: AgentArtifactRecordWire) -> int | None:
    waiting = record.waiting
    if (
        waiting is not None
        and type(waiting.wait_runners) is int
        and waiting.wait_runners >= 0
    ):
        return waiting.wait_runners
    return None


def _record_pid(record: AgentArtifactRecordWire) -> int | None:
    meta = record.agent_meta
    if meta is not None and meta.pid is not None:
        return meta.pid
    running = record.running
    return None if running is None else running.pid


def _capacity_record_from_scan(
    record: AgentArtifactRecordWire,
    is_live: RecordLiveness,
) -> dict[str, Any]:
    meta = record.agent_meta
    state = record.workflow_state
    waiting = record.waiting
    shell = None if meta is None else meta.family_shell
    queue_weight, queue_weight_explicit, queue_weight_invalid = _record_queue_weight(
        record
    )
    return {
        "artifact_dir": record.artifact_dir,
        "project_name": record.project_name,
        "workflow_dir_name": record.workflow_dir_name,
        "timestamp": record.timestamp,
        "has_agent_meta": meta is not None,
        "has_done_marker": record.has_done_marker,
        "appears_as_agent": True if state is None else state.appears_as_agent,
        "live": is_live(record),
        "pending_question": record.pending_question is not None,
        "pid": _record_pid(record),
        "run_started_at": None if meta is None else meta.run_started_at,
        "parent_timestamp": None if meta is None else meta.parent_timestamp,
        "agent_family": None if meta is None else meta.agent_family,
        "agent_family_role": None if meta is None else meta.agent_family_role,
        "agent_family_parallel": (
            False if meta is None else meta.agent_family_parallel
        ),
        "family_shell_kind": None if shell is None else shell.kind,
        "family_shell_id": None if shell is None else shell.id,
        "family_shell_state": None if shell is None else shell.state,
        "queue_weight": queue_weight,
        "queue_weight_explicit": queue_weight_explicit,
        "queue_weight_invalid": queue_weight_invalid,
        "slot_requested_at": None if waiting is None else waiting.slot_requested_at,
        "wait_runners": _record_wait_runners(record),
        "wait_runners_explicit": (
            False if waiting is None else waiting.wait_runners_explicit
        ),
        "wait_priority": _record_wait_priority(record),
        "eligible_since": None if waiting is None else waiting.eligible_since,
    }


def _project_name_from_artifact_dir(artifacts_dir: str) -> str:
    path = Path(artifacts_dir)
    try:
        return path.parents[2].name
    except IndexError:
        return ""


def _synthetic_capacity_record(
    *,
    artifacts_dir: str,
    timestamp: str,
    slot_requested_at: str,
    wait_runners: int | None,
    wait_runners_explicit: bool,
    wait_priority: int,
    queue_weight: float,
    queue_weight_explicit: bool,
    eligible_since: str | None,
) -> dict[str, Any]:
    return {
        "artifact_dir": artifacts_dir,
        "project_name": _project_name_from_artifact_dir(artifacts_dir),
        "workflow_dir_name": "ace-run",
        "timestamp": timestamp,
        "has_agent_meta": True,
        "has_done_marker": False,
        "appears_as_agent": True,
        "live": True,
        "pending_question": False,
        "pid": None,
        "run_started_at": None,
        "parent_timestamp": None,
        "agent_family": None,
        "agent_family_role": None,
        "agent_family_parallel": False,
        "family_shell_kind": None,
        "family_shell_id": None,
        "family_shell_state": None,
        "queue_weight": queue_weight,
        "queue_weight_explicit": queue_weight_explicit,
        "queue_weight_invalid": False,
        "slot_requested_at": slot_requested_at,
        "wait_runners": wait_runners,
        "wait_runners_explicit": wait_runners_explicit,
        "wait_priority": wait_priority,
        "eligible_since": eligible_since,
    }


def runner_capacity_snapshot(
    records: Iterable[AgentArtifactRecordWire],
    is_live: RecordLiveness,
    *,
    effective_limit: float,
    now: str | None = None,
    deference_seconds_per_step: int = 0,
    deference_max_seconds: int = 0,
    candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the authoritative weighted runner-capacity snapshot."""
    capacity_records: list[dict[str, Any]] = []
    candidate_dir = None if candidate is None else str(candidate["artifact_dir"])
    candidate_seen = False
    for record in records:
        capacity_record = _capacity_record_from_scan(record, is_live)
        if candidate_dir is not None and record.artifact_dir == candidate_dir:
            assert candidate is not None
            capacity_record.update(
                {
                    key: value
                    for key, value in candidate.items()
                    if key in _CANDIDATE_OVERRIDE_FIELDS
                }
            )
            candidate_seen = True
        capacity_records.append(capacity_record)
    if candidate is not None and not candidate_seen:
        capacity_records.append(candidate)
    return runner_capacity_snapshot_from_capacity_records(
        capacity_records,
        effective_limit=effective_limit,
        now=now,
        deference_seconds_per_step=deference_seconds_per_step,
        deference_max_seconds=deference_max_seconds,
    )


def runner_capacity_snapshot_from_capacity_records(
    records: Iterable[Mapping[str, Any]],
    *,
    effective_limit: float,
    now: str | None = None,
    deference_seconds_per_step: int = 0,
    deference_max_seconds: int = 0,
) -> dict[str, Any]:
    """Return the Rust capacity snapshot for already-projected record dicts."""
    request = {
        "effective_limit": float(effective_limit),
        "records": [dict(record) for record in records],
        "now": now,
        "deference_seconds_per_step": int(deference_seconds_per_step),
        "deference_max_seconds": int(deference_max_seconds),
    }
    return _core_runner_capacity_snapshot(request)


def runner_slot_candidate_record(
    *,
    artifacts_dir: str,
    timestamp: str,
    slot_requested_at: str,
    wait_runners: int | None,
    wait_runners_explicit: bool,
    wait_priority: int,
    queue_weight: float,
    queue_weight_explicit: bool,
    eligible_since: str | None,
) -> dict[str, Any]:
    """Build the synthetic candidate override for a locked admission attempt."""
    return _synthetic_capacity_record(
        artifacts_dir=artifacts_dir,
        timestamp=timestamp,
        slot_requested_at=slot_requested_at,
        wait_runners=wait_runners,
        wait_runners_explicit=wait_runners_explicit,
        wait_priority=wait_priority,
        queue_weight=queue_weight,
        queue_weight_explicit=queue_weight_explicit,
        eligible_since=eligible_since,
    )


def is_root_user_agent_record(record: AgentArtifactRecordWire) -> bool:
    """Return whether *record* represents a top-level user agent."""
    if record.workflow_dir_name != "ace-run" or record.has_done_marker:
        return False
    meta = record.agent_meta
    if meta is None or meta.parent_timestamp:
        return False
    state = record.workflow_state
    return state is None or state.appears_as_agent


def is_runner_slot_user_agent_record(record: AgentArtifactRecordWire) -> bool:
    """Return whether *record* may itself be parked and queued at the gate.

    This answers the *admission* question only: a live root or a live
    parallel family member waits for its own slot, while a serial family
    member (a non-parallel child, a monitor, or a monitor follow-up) rides
    the slot its family already holds and is exempt from waiting. It does
    not answer the *occupancy* question of how many slots are in use --
    see `is_runner_slot_occupying_record` / `running_agent_slot_count` for
    that, which is decided per family rather than per record.
    """
    if record.workflow_dir_name != "ace-run" or record.has_done_marker:
        return False
    meta = record.agent_meta
    if meta is None or (meta.parent_timestamp and not meta.agent_family_parallel):
        return False
    state = record.workflow_state
    return state is None or state.appears_as_agent


def better_priority_agent_pending(
    records: Iterable[AgentArtifactRecordWire],
    is_live: RecordLiveness,
    *,
    priority: int,
    me: str,
) -> bool:
    """Return whether a live unparked agent could soon outrank *me*."""
    for record in records:
        meta = record.agent_meta
        waiting = record.waiting
        if (
            not is_runner_slot_user_agent_record(record)
            or record.artifact_dir == me
            or meta is None
            or not is_live(record)
            or bool(meta.run_started_at)
            or (waiting is not None and bool(waiting.slot_requested_at))
        ):
            continue
        if normalize_wait_priority(meta.wait_priority) < priority:
            return True
    return False


def is_runner_slot_occupying_record(
    record: AgentArtifactRecordWire,
    is_live: RecordLiveness,
) -> bool:
    """Return whether *record* is, on its own, occupying a runner slot now.

    This is the primitive `running_agent_slot_count` groups and sums per
    family; unlike `is_runner_slot_user_agent_record`, it intentionally
    ignores lineage (``parent_timestamp``), because a live serial child, a
    live monitor member, or a live post-handoff follow-up agent can each be
    the shell currently holding a family's slot in place of a dead root.

    ``pending_question.json`` is the authoritative marker for a shell that
    has temporarily yielded its slot while awaiting a user answer. The
    marker is retained if an answer is ready but the shell is queued to
    reacquire capacity, and removed only by its successful locked claim.

    "Started" is monitor-aware. An ordinary agent shell needs
    ``agent_meta.run_started_at``, as today. A real monitor member
    (``agent_meta.agent_family_role == "monitor"`` plus a non-empty
    ``agent_meta.monitor_id``) only needs a recorded ``pid``: the supervisor
    pid is written before the starter's runner group is killed, while
    ``run_started_at`` is not written until the monitored command itself
    launches -- requiring it here would open a window across the handoff where
    the starter is already dead and the monitor does not yet count, letting a
    queued agent slip in. Agents that merely inherited ``monitor_id`` still
    use ordinary started semantics.
    """
    if record.workflow_dir_name != "ace-run" or record.has_done_marker:
        return False
    state = record.workflow_state
    if state is not None and not state.appears_as_agent:
        return False
    if record.pending_question is not None:
        return False
    meta = record.agent_meta
    if meta is None:
        return False
    gate_shell = _family_shell_of_kind(meta, "gate")
    if (
        is_real_gate_member_record(record)
        and gate_shell is not None
        and (gate_shell.state or "").strip() == "pending"
    ):
        return False
    monitor_shell = _family_shell_of_kind(meta, "monitor")
    monitor_id = monitor_shell.id if monitor_shell is not None else None
    monitor = is_real_monitor_member(meta.agent_family_role, monitor_id)
    started = meta.pid is not None if monitor else bool(meta.run_started_at)
    if not started:
        return False
    return is_live(record)


def is_real_gate_member_record(record: AgentArtifactRecordWire) -> bool:
    """Return whether *record* is the durable gate-shell member."""
    meta = record.agent_meta
    if meta is None or (meta.agent_family_role or "").strip() != GATE_FAMILY_ROLE:
        return False
    gate_shell = _family_shell_of_kind(meta, "gate")
    gate_id = gate_shell.id if gate_shell is not None else None
    return bool((gate_id or "").strip())


def runner_slot_family_key(record: AgentArtifactRecordWire) -> tuple[str, str]:
    """Return the per-family occupancy grouping key for *record*.

    Grouped by ``(project_name, agent_family)``. A record with no
    ``agent_family`` falls back to its own ``timestamp``, which keeps
    standalone agents and independently launched clan members counting
    individually instead of collapsing into one group.
    """
    meta = record.agent_meta
    family = meta.agent_family if meta is not None and meta.agent_family else None
    return (record.project_name, family or record.timestamp)


def group_records_by_runner_slot_family(
    records: Iterable[AgentArtifactRecordWire],
) -> dict[tuple[str, str], list[AgentArtifactRecordWire]]:
    """Group *records* by the family `running_agent_slot_count` decides over.

    Exposed so display code (the ACE capacity chip, agent listings) can
    reuse this grouping instead of reimplementing it.
    """
    groups: dict[tuple[str, str], list[AgentArtifactRecordWire]] = {}
    for record in records:
        groups.setdefault(runner_slot_family_key(record), []).append(record)
    return groups


def running_agent_slot_count(
    records: Iterable[AgentArtifactRecordWire],
    is_live: RecordLiveness,
) -> int:
    """Count occupied runner lanes from the shared Rust capacity projection."""
    snapshot = runner_capacity_snapshot(
        tuple(records),
        is_live,
        effective_limit=_RUNNER_CAPACITY_HELPER_LIMIT,
    )
    occupied = snapshot.get("occupied_lanes", 0)
    return occupied if type(occupied) is int else 0


def live_runner_slot_waiters(
    records: Iterable[AgentArtifactRecordWire],
    is_live: RecordLiveness,
) -> tuple[RunnerSlotWaiter, ...]:
    """Derive the live priority/FIFO queue from waiting-marker projections."""
    snapshot = runner_capacity_snapshot(
        tuple(records),
        is_live,
        effective_limit=_RUNNER_CAPACITY_HELPER_LIMIT,
    )
    waiters = [
        RunnerSlotWaiter(
            artifact_dir=str(waiter.get("artifact_dir") or ""),
            slot_requested_at=str(waiter.get("slot_requested_at") or ""),
            timestamp=str(waiter.get("timestamp") or ""),
            threshold=(
                int(waiter["wait_runners"])
                if type(waiter.get("wait_runners")) is int
                and waiter["wait_runners"] >= 0
                else 0
            ),
            priority=normalize_wait_priority(waiter.get("priority")),
            requested_weight=float(waiter.get("requested_weight") or 1.0),
            eligible=waiter.get("eligible") is True,
            blockers=tuple(
                blocker
                for blocker in waiter.get("blockers", [])
                if isinstance(blocker, dict)
            ),
        )
        for waiter in snapshot.get("waiters", [])
        if isinstance(waiter, dict)
    ]
    return tuple(waiters)


def may_start(
    running_count: int,
    threshold: int,
    queue: Iterable[RunnerSlotWaiter],
    me: str,
) -> bool:
    """Return whether *me* is the first currently eligible slot waiter."""
    if running_count > threshold:
        return False

    first_eligible = next(
        (
            waiter
            for waiter in queue
            if running_count
            <= (threshold if waiter.artifact_dir == me else waiter.threshold)
        ),
        None,
    )
    return first_eligible is None or first_eligible.artifact_dir == me
