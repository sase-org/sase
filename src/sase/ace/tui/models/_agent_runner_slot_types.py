"""Immutable display values and formatting for runner-slot presentation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sase.core.runner_slots import DEFAULT_QUEUE_WEIGHT

from .agent import AgentType


@dataclass(frozen=True, slots=True)
class RunnerQueueEntry:
    identity: tuple[AgentType, str, str | None]
    presented_name: str
    threshold: int | None
    wait_runners_explicit: bool
    priority: int
    slot_requested_at: str | None
    status: str
    requested_weight: float = DEFAULT_QUEUE_WEIGHT
    occupied_capacity: float | None = None
    admission_limit: float | None = None
    eligible: bool = False
    blockers: tuple[dict[str, Any], ...] = ()
    parked: bool = False


@dataclass(frozen=True)
class RunnerCapacitySnapshot:
    effective_limit: float = 0.0
    slots_in_use: int = 0
    queued_count: int = 0
    queue: tuple[RunnerQueueEntry, ...] = ()
    occupied_capacity: float | None = None


def format_capacity_value(value: object, *, minimum_decimal: bool = True) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    number = float(value)
    if not math.isfinite(number):
        return "—"
    absolute = abs(number)
    text = (
        f"{number:.6g}"
        if number != 0.0 and (absolute >= 1e9 or absolute < 1e-6)
        else f"{number:.12f}".rstrip("0").rstrip(".")
    )
    if text in {"", "-0"}:
        text = "0"
    if minimum_decimal and "e" not in text and "E" not in text and "." not in text:
        text += ".0"
    return text


def format_queue_weight_badge_value(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    weight = float(value)
    if (
        not math.isfinite(weight)
        or weight <= 0.0
        or math.isclose(weight, DEFAULT_QUEUE_WEIGHT, rel_tol=0.0, abs_tol=1e-9)
    ):
        return None
    return format_capacity_value(weight, minimum_decimal=False)
