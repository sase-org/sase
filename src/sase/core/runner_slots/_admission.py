"""Deterministic runner-slot counting, queueing, and admission decisions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sase.core.agent_scan_wire import AgentArtifactRecordWire

from ._admission_ordering import normalize_wait_priority
from ._admission_snapshot import runner_capacity_snapshot
from ._admission_types import (
    RecordLiveness,
    RunnerSlotWaiter,
    finite_positive_float,
)

_RUNNER_CAPACITY_HELPER_LIMIT = 1.0e300


def _nonnegative_int_field(data: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = data.get(key)
        if type(value) is int and value >= 0:
            return value
    return None


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
    *,
    effective_limit: float | None = None,
) -> tuple[RunnerSlotWaiter, ...]:
    """Derive the live priority/FIFO queue from waiting-marker projections."""
    snapshot = runner_capacity_snapshot(
        tuple(records),
        is_live,
        effective_limit=(
            _RUNNER_CAPACITY_HELPER_LIMIT
            if effective_limit is None
            else float(effective_limit)
        ),
    )
    waiters = [
        RunnerSlotWaiter(
            artifact_dir=str(waiter.get("artifact_dir") or ""),
            slot_requested_at=str(waiter.get("slot_requested_at") or ""),
            timestamp=str(waiter.get("timestamp") or ""),
            threshold=(
                _nonnegative_int_field(waiter, "queue_capacity", "wait_runners") or 0
            ),
            queue_capacity=_nonnegative_int_field(
                waiter,
                "queue_capacity",
                "wait_runners",
            ),
            queue_capacity_explicit=(
                waiter.get("queue_capacity") is not None
                or waiter.get("wait_runners") is not None
            ),
            admission_limit=finite_positive_float(waiter.get("admission_limit")),
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
