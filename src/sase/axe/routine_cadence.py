"""Persisted tick cadence for long-interval routines.

A routine process used to tick the moment it started. For a routine whose
interval is an hour, a service restart or a code-swap restart therefore re-ran
every one of its jobs at once, whatever their last run, and a restart of the
whole service ran every routine's jobs together.

Routines with an interval of at least :data:`PERSISTED_CADENCE_MIN_INTERVAL_SECONDS`
record when each dispatching tick started (``cadence.json`` in the routine's
state directory). A restarted routine waits until that tick plus one interval
before its first tick. Shorter lanes tick within seconds anyway, so they keep
ticking at start and write nothing.

``sase axe routine run ROUTINE --tick-now`` forces the immediate first tick.
"""

from __future__ import annotations

import math
from typing import Any

import sase.axe.state as _state

#: Routines ticking at least this often keep the tick-at-start behaviour.
PERSISTED_CADENCE_MIN_INTERVAL_SECONDS = 60

_CADENCE_FILE = "cadence.json"


def persists_cadence(interval: int) -> bool:
    """Return whether a routine with *interval* seconds persists its cadence."""
    return interval >= PERSISTED_CADENCE_MIN_INTERVAL_SECONDS


def read_last_tick_at(name: str) -> float | None:
    """Return the epoch seconds routine *name*'s last dispatching tick started.

    Returns ``None`` when nothing usable was recorded.
    """
    data = _state.read_json(_state.lumberjack_state_dir(name) / _CADENCE_FILE)
    if not isinstance(data, dict):
        return None
    raw: Any = data.get("last_tick_at")
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    value = float(raw)
    return value if math.isfinite(value) and value > 0 else None


def write_last_tick_at(name: str, *, started_at: float, interval: int) -> None:
    """Record that routine *name* started a dispatching tick at *started_at*."""
    _state.atomic_write_json(
        _state.lumberjack_state_dir(name) / _CADENCE_FILE,
        {"last_tick_at": started_at, "interval": interval},
    )


def first_tick_delay(*, interval: int, last_tick_at: float | None, now: float) -> float:
    """Return how many seconds a (re)started routine waits before its first tick.

    ``0`` means tick at once: a short-interval routine, nothing recorded, or the
    recorded tick is at least one interval old. A recorded tick in the future
    (the wall clock moved back) waits at most one interval.
    """
    if not persists_cadence(interval) or last_tick_at is None:
        return 0.0
    remaining = interval - (now - last_tick_at)
    return min(float(interval), max(0.0, remaining))


__all__ = [
    "PERSISTED_CADENCE_MIN_INTERVAL_SECONDS",
    "first_tick_delay",
    "persists_cadence",
    "read_last_tick_at",
    "write_last_tick_at",
]
