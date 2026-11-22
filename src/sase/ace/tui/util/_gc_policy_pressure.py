"""Paging-pressure gate, cost-gate bound, and observed-cost refresh.

A stable residual ``VmSwap`` is not pressure. Pages swapped out long ago and
never touched again leave the process at zero major faults, and deferring on
that level alone held every policy sweep for twelve hours on athena while
automatic gen-2 collections paused for 12-19 s. Only paging activity counts:
a recent major-fault rate above ``MAJOR_FAULTS_PER_S_PRESSURE_THRESHOLD`` or
``VmSwap`` growth above ``SWAP_GROWTH_PRESSURE_BYTES`` between the telemetry
worker's two latest samples.

Pressure may hold the memory backstops (``backstop`` / ``rss_backstop``) for
at most ``PRESSURE_MAX_DEFERRAL_S``. After that a backstop runs once input
has been quiet for ``PRESSURE_OVERRIDE_QUIET_S``, so sustained paging cannot
starve the backstops indefinitely. The opportunistic ``idle`` trigger stays
deferred while pressure lasts; it turns into ``backstop`` after five minutes.

The cost gate (``cost_gate``) gets the same shape of bound through
``CostDeferral``: it may hold the ``idle`` / ``backstop`` / ``rss_backstop``
triggers for at most a cap derived from the sampled pause rate (never more
than ``COST_MAX_DEFERRAL_S``), then a sweep runs on the next ordinary quiet
window, so an over-budget estimate can never starve sweeps indefinitely.

Everything here reads cached samples only; nothing touches ``/proc`` or runs
a collection.
"""

from __future__ import annotations

from typing import Any, TypeGuard

from ._gc_policy_config import (
    COST_MAX_DEFERRAL_S,
    COST_OVERRIDE_QUIET_S,
    MAJOR_FAULTS_PER_S_PRESSURE_THRESHOLD,
    PRESSURE_MAX_DEFERRAL_S,
    PRESSURE_OVERRIDE_QUIET_S,
    PRESSURE_SAMPLE_MAX_AGE_S,
    SWAP_GROWTH_PRESSURE_BYTES,
)

_BOUNDED_TRIGGERS = frozenset({"backstop", "rss_backstop"})
_COST_BOUNDED_TRIGGERS = frozenset({"idle", "backstop", "rss_backstop"})


def _is_number(value: object) -> TypeGuard[float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def paging_pressure(sample: object, now_mono: float) -> dict[str, Any] | None:
    """Return pressure details when a fresh sample shows paging activity.

    ``sample`` is the telemetry worker's cached snapshot. Stale, malformed,
    or quiet samples return ``None``; so does any ``VmSwap`` level that is
    not growing.
    """
    if not isinstance(sample, dict):
        return None
    age = sample.get("sample_age_s")
    if not _is_number(age) or age < 0.0 or age > PRESSURE_SAMPLE_MAX_AGE_S:
        return None
    growth = sample.get("vmswap_growth_bytes")
    faults = sample.get("major_faults_per_s")
    faulting = _is_number(faults) and faults > MAJOR_FAULTS_PER_S_PRESSURE_THRESHOLD
    swap_growing = (
        isinstance(growth, int)
        and not isinstance(growth, bool)
        and growth > SWAP_GROWTH_PRESSURE_BYTES
    )
    if not (faulting or swap_growing):
        return None
    return {
        "signal": "major_faults" if faulting else "swap_growth",
        "vmswap_bytes": sample.get("vmswap_bytes"),
        "vmswap_growth_bytes": growth,
        "major_faults_per_s": faults,
        "sample_age_s": round(float(age), 3),
        "sampled_at_mono": now_mono - float(age),
    }


class PressureDeferral:
    """Bound how long paging pressure may hold the memory backstops.

    The window opens at the first pressure deferral of a backstop trigger and
    closes when a gate pass sees no pressure or a full collection runs.
    """

    def __init__(self) -> None:
        self._since_mono: float | None = None

    def deferred_for_s(self, now_mono: float) -> float:
        """Seconds pressure has held a backstop in the current window."""
        since = self._since_mono
        return 0.0 if since is None else max(0.0, now_mono - since)

    def defers(self, *, trigger: str, now_mono: float, input_idle_s: float) -> bool:
        """Return True while pressure should still hold a ``trigger`` sweep."""
        if trigger not in _BOUNDED_TRIGGERS:
            return True
        if self._since_mono is None:
            self._since_mono = now_mono
        if now_mono - self._since_mono < PRESSURE_MAX_DEFERRAL_S:
            return True
        return input_idle_s < PRESSURE_OVERRIDE_QUIET_S

    def clear(self) -> None:
        """Close the window: pressure is gone or a full collection ran."""
        self._since_mono = None


class CostDeferral:
    """Bound how long the cost gate may hold a sweep.

    The window opens at the first cost deferral of a bounded trigger and
    closes when fresh cost evidence arrives (an own sweep or a newly observed
    full collection). While the window is younger than its cap (at most
    ``COST_MAX_DEFERRAL_S``) the gate defers; afterwards only a missing quiet
    window still defers, so the sweep runs on the next ordinary quiet tick.
    """

    def __init__(self) -> None:
        self._since_mono: float | None = None

    def deferred_for_s(self, now_mono: float) -> float:
        """Seconds the cost gate has held a sweep in the current window."""
        since = self._since_mono
        return 0.0 if since is None else max(0.0, now_mono - since)

    def defers(
        self,
        *,
        trigger: str,
        now_mono: float,
        input_idle_s: float,
        cap_s: float = COST_MAX_DEFERRAL_S,
    ) -> bool:
        """Return True while the cost gate should still hold a sweep."""
        if trigger not in _COST_BOUNDED_TRIGGERS:
            return True
        if self._since_mono is None:
            self._since_mono = now_mono
        if now_mono - self._since_mono < min(max(0.0, cap_s), COST_MAX_DEFERRAL_S):
            return True
        return input_idle_s < COST_OVERRIDE_QUIET_S

    def clear(self) -> None:
        """Close the window: fresh cost evidence or a full collection ran."""
        self._since_mono = None


def newer_full_pause(
    recorder: Any, sample_mono: float | None
) -> tuple[float, float] | None:
    """Return ``(pause_s, end_mono)`` of a full collection newer than the sample.

    The telemetry recorder measures every gen-2 collection, including
    automatic ones the policy did not start. Policy sweeps record their own
    sample after the collection returns, so only a collection that ended later
    than ``sample_mono`` is new evidence.
    """
    try:
        end_mono = recorder.last_full_collection_mono()
        pause = recorder.last_full_pause_s()
    except Exception:
        return None
    if not _is_number(end_mono) or not _is_number(pause):
        return None
    if end_mono < 0.0 or pause < 0.0:
        return None
    if sample_mono is not None and end_mono <= sample_mono:
        return None
    return (float(pause), float(end_mono))
