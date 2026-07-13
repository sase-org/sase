"""Deterministic runner-slot counting, queueing, and admission decisions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sase.core.agent_scan_wire import AgentArtifactRecordWire

RecordLiveness = Callable[[AgentArtifactRecordWire], bool]


@dataclass(frozen=True)
class RunnerSlotWaiter:
    """One live root agent waiting in the global runner-slot queue."""

    artifact_dir: str
    slot_requested_at: str
    timestamp: str
    threshold: int = 0


def is_root_user_agent_record(record: AgentArtifactRecordWire) -> bool:
    """Return whether *record* represents a countable root user agent."""
    if record.workflow_dir_name != "ace-run" or record.has_done_marker:
        return False
    meta = record.agent_meta
    if meta is None or meta.parent_timestamp:
        return False
    state = record.workflow_state
    return state is None or state.appears_as_agent


def running_root_agent_count(
    records: Iterable[AgentArtifactRecordWire],
    is_live: RecordLiveness,
) -> int:
    """Count live root user agents that have passed the slot gate."""
    return sum(
        1
        for record in records
        if is_root_user_agent_record(record)
        and record.agent_meta is not None
        and bool(record.agent_meta.run_started_at)
        and is_live(record)
    )


def live_runner_slot_waiters(
    records: Iterable[AgentArtifactRecordWire],
    is_live: RecordLiveness,
) -> tuple[RunnerSlotWaiter, ...]:
    """Derive the live FIFO slot queue from waiting-marker projections."""
    waiters: list[RunnerSlotWaiter] = []
    for record in records:
        waiting = record.waiting
        if (
            not is_root_user_agent_record(record)
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
    """Return whether *me* is the oldest currently eligible slot waiter."""
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


def _waiter_sort_key(waiter: RunnerSlotWaiter) -> tuple[int, datetime, str, str]:
    try:
        requested_at = datetime.fromisoformat(
            waiter.slot_requested_at.replace("Z", "+00:00")
        )
        if requested_at.tzinfo is None:
            requested_at = requested_at.replace(tzinfo=UTC)
        requested_at = requested_at.astimezone(UTC)
        invalid = 0
    except ValueError:
        requested_at = datetime.max.replace(tzinfo=UTC)
        invalid = 1
    return invalid, requested_at, waiter.timestamp, waiter.artifact_dir
