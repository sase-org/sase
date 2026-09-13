"""Shared constants and value types for runner-slot admission."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sase.core.agent_scan_wire import AgentArtifactRecordWire

RecordLiveness = Callable[[AgentArtifactRecordWire], bool]
DEFAULT_WAIT_PRIORITY = 10
DEFAULT_QUEUE_WEIGHT = 1.0


def finite_positive_float(value: object) -> float | None:
    """Return *value* as a float, or ``None`` if it is not finite and positive."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    weight = float(value)
    if not weight or not weight > 0 or not weight < float("inf"):
        return None
    return weight


@dataclass(frozen=True)
class RunnerSlotWaiter:
    """One live user agent waiting in the global runner-slot queue."""

    artifact_dir: str
    slot_requested_at: str
    timestamp: str
    threshold: int = 0
    queue_capacity: int | None = None
    queue_capacity_explicit: bool = False
    admission_limit: float | None = None
    priority: int = DEFAULT_WAIT_PRIORITY
    requested_weight: float = DEFAULT_QUEUE_WEIGHT
    eligible: bool = False
    blockers: tuple[dict[str, Any], ...] = ()
