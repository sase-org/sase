"""Deterministic runner-slot counting, queueing, and admission decisions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sase.core.agent_scan_wire import AgentArtifactRecordWire

RecordLiveness = Callable[[AgentArtifactRecordWire], bool]
DEFAULT_WAIT_PRIORITY = 10


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
    """Return whether *record* participates in runner-slot admission."""
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


def running_root_agent_count(
    records: Iterable[AgentArtifactRecordWire],
    is_live: RecordLiveness,
) -> int:
    """Count live admitted agents that currently hold a runner slot.

    ``pending_question.json`` is the authoritative marker for a root that has
    temporarily yielded its slot while awaiting a user answer.  The marker is
    retained if an answer is ready but the root is queued to reacquire capacity,
    and removed only by its successful locked claim.
    """
    return sum(
        1
        for record in records
        if is_runner_slot_user_agent_record(record)
        and record.agent_meta is not None
        and bool(record.agent_meta.run_started_at)
        and record.pending_question is None
        and is_live(record)
    )


def live_runner_slot_waiters(
    records: Iterable[AgentArtifactRecordWire],
    is_live: RecordLiveness,
) -> tuple[RunnerSlotWaiter, ...]:
    """Derive the live priority/FIFO queue from waiting-marker projections."""
    waiters: list[RunnerSlotWaiter] = []
    for record in records:
        waiting = record.waiting
        if (
            not is_runner_slot_user_agent_record(record)
            or waiting is None
            or not waiting.slot_requested_at
            or not is_live(record)
        ):
            continue
        waiters.append(
            RunnerSlotWaiter(
                artifact_dir=record.artifact_dir,
                slot_requested_at=waiting.slot_requested_at,
                timestamp=record.timestamp,
                threshold=(
                    waiting.wait_runners
                    if type(waiting.wait_runners) is int and waiting.wait_runners >= 0
                    else 0
                ),
                priority=normalize_wait_priority(waiting.wait_priority),
            )
        )
    waiters.sort(key=_waiter_sort_key)
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


def _waiter_sort_key(
    waiter: RunnerSlotWaiter,
) -> tuple[int, int, datetime, str, str]:
    return runner_slot_waiter_sort_key(
        priority=waiter.priority,
        slot_requested_at=waiter.slot_requested_at,
        timestamp=waiter.timestamp,
        artifact_dir=waiter.artifact_dir,
    )
