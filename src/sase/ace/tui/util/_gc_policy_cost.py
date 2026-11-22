"""Pause estimate for the full-GC policy: time-priced samples and deep pricing.

An ordinary sweep after a freeze scans only what was created since the last
full collection: survivors plus the cyclic garbage that dominates the pause.
Both accumulate at the session's churn rate, so a sample is stored as a pause
over the seconds of accumulation it swept, and the next sweep is priced as
that rate times the seconds accumulated since. Allocated-block deltas are not
used for ordinary sweeps: refcount frees of old frozen objects shrink the net
total while new garbage still needs scanning, which once priced a 0.647 s
sweep as a single block and predicted a 645,427 s pause.

A deep (unfreeze) sweep scans the frozen set plus the young heap, priced as
the sum of two costs with the safety factor applied once to each: the
measured frozen-container cost times ``gc.get_freeze_count()``, plus the
existing time-based ordinary-sweep estimate for accumulation since the last
full collection. ``gc.get_count()`` collection counters reset on young
collections while promoted objects remain, so they never enter deep pricing.
The frozen coefficient is seeded from the attribute-phase 0.763
us/frozen-container rate and refreshed from verified deep sweeps; the
measured deep pause conservatively includes unfrozen work, so the refreshed
rate is an upper bound, not an exact per-object traversal cost.

Everything here is arithmetic over cached state; nothing runs a collection.
"""

from __future__ import annotations

import math
from typing import Any

from ._gc_policy_common import safe_probe
from ._gc_policy_config import (
    COST_DEFERRAL_GROWTH_S,
    COST_DUE_FRACTION,
    COST_MAX_DEFERRAL_S,
    COST_PREDICTION_SAFETY_FACTOR,
    DEEP_COST_PER_FROZEN_S,
    FULL_GENERATION,
    MAX_PREDICTED_FULL_PAUSE_S,
    MIN_COST_SAMPLE_ACCUM_S,
)
from ._gc_policy_pressure import CostDeferral, PressureDeferral, newer_full_pause


class PolicyCostMixin:
    """Cost half of :class:`GCPolicy`: samples, estimates, and collection proof."""

    _collector: Any
    _recorder: Any
    _pressure_deferral: PressureDeferral
    _cost_deferral: CostDeferral
    _froze_startup: bool
    _last_full_pause_s: float | None
    _cost_sample_mono: float | None
    _cost_pause_s: float | None
    _cost_accum_s: float | None
    _young_since_mono: float | None
    _deep_cost_per_frozen_s: float | None

    @property
    def _deep_cost_per_object_s(self) -> float | None:
        """Deprecated alias for ``_deep_cost_per_frozen_s``."""
        return self._deep_cost_per_frozen_s

    @_deep_cost_per_object_s.setter
    def _deep_cost_per_object_s(self, value: float | None) -> None:
        self._deep_cost_per_frozen_s = value

    def _deep_cost_breakdown(
        self, now_mono: float
    ) -> tuple[float | None, int | None, float | None, float | None]:
        """Return ``(total, frozen_n, frozen_cost, unfrozen_cost)`` for a deep sweep.

        ``None`` total means the bounded deep pass is unpriceable and stays
        gated. The frozen part is the per-frozen-container rate times the
        frozen count, safety factor included; the unfrozen part is the
        ordinary time-priced estimate, safety factor included. Either part
        missing gates the deep pass without holding ordinary sweeps.
        """
        frozen_n = self._read_gc_frozen_count()
        if frozen_n is None:
            return (None, None, None, None)
        per_frozen = self._deep_cost_per_frozen_s
        if per_frozen is None:
            per_frozen = DEEP_COST_PER_FROZEN_S
        try:
            per_f = float(per_frozen)
        except Exception:
            return (None, frozen_n, None, None)
        if not math.isfinite(per_f) or per_f <= 0.0:
            per_f = DEEP_COST_PER_FROZEN_S
        try:
            frozen_cost = per_f * max(0, int(frozen_n)) * COST_PREDICTION_SAFETY_FACTOR
        except Exception:
            return (None, frozen_n, None, None)
        if not math.isfinite(frozen_cost) or frozen_cost < 0.0:
            return (None, frozen_n, None, None)
        unfrozen = self._predicted_pause_s(now_mono, deep=False)
        if unfrozen is None:
            return (None, frozen_n, round(frozen_cost, 6), None)
        try:
            unfrozen_f = float(unfrozen)
        except Exception:
            return (None, frozen_n, round(frozen_cost, 6), None)
        if not math.isfinite(unfrozen_f) or unfrozen_f < 0.0:
            return (None, frozen_n, round(frozen_cost, 6), None)
        total = frozen_cost + unfrozen_f
        if not math.isfinite(total):
            return (None, frozen_n, round(frozen_cost, 6), round(unfrozen_f, 6))
        return (total, frozen_n, round(frozen_cost, 6), round(unfrozen_f, 6))

    def _predicted_pause_s(
        self, now_mono: float, *, deep: bool = False
    ) -> float | None:
        """Estimate the next full sweep's pause, safety factor included.

        Ordinary sweeps scale the latest sample's pause rate by the seconds
        accumulated since the last full collection (or the startup freeze).
        ``None`` means no post-freeze sample exists yet. A deep sweep adds
        the frozen-container cost to the ordinary estimate; ``None`` means
        the frozen probe or the ordinary estimate is missing, so the bounded
        deep pass stays gated while ordinary sweeps still run.
        """
        if deep:
            total, _, _, _ = self._deep_cost_breakdown(now_mono)
            return total
        rate = self._cost_rate_s_per_s()
        since = self._young_since_mono
        if rate is None or since is None:
            return None
        return rate * max(0.0, now_mono - since) * COST_PREDICTION_SAFETY_FACTOR

    def _cost_rate_s_per_s(self) -> float | None:
        """Seconds of expected pause per second of accumulation, if sampled."""
        pause = self._cost_pause_s
        accum = self._cost_accum_s
        if pause is None or accum is None:
            return None
        return max(0.0, pause) / max(accum, MIN_COST_SAMPLE_ACCUM_S)

    def _cost_due(self, now_mono: float) -> bool:
        """Return True once the estimate nears the budget: sweep before it."""
        predicted = self._predicted_pause_s(now_mono)
        return (
            predicted is not None
            and predicted >= COST_DUE_FRACTION * MAX_PREDICTED_FULL_PAUSE_S
        )

    def _cost_deferral_cap_s(self) -> float:
        """How long the cost gate may hold a sweep before it must run.

        The cap lets the expected pause grow by ``COST_DEFERRAL_GROWTH_S`` at
        the sampled rate, clamped to ``COST_MAX_DEFERRAL_S``.
        """
        rate = self._cost_rate_s_per_s()
        if rate is None or rate <= 0.0:
            return COST_MAX_DEFERRAL_S
        return min(COST_MAX_DEFERRAL_S, COST_DEFERRAL_GROWTH_S / rate)

    def _record_cost_sample(
        self,
        pause_s: float,
        *,
        start_mono: float,
        end_mono: float,
        deep: bool,
        census: bool,
        objects_before: int | None = None,
        frozen_before: int | None = None,
    ) -> None:
        """Store the cost evidence of one verified own full collection.

        A census sweep (``DEBUG_SAVEALL`` plus a survivor scan) is no cost
        sample, and a skipped (``collector_busy``) sweep never reaches here.
        A deep sweep only refreshes the per-frozen-container rate as the total
        measured deep pause over the positive frozen count captured before
        unfreezing; the pause conservatively includes unfrozen work, so the
        refreshed rate is an upper bound, not an exact traversal cost. The
        ordinary rate keeps its last young-heap sample. ``objects_before``
        remains as a deprecated alias for ``frozen_before``.
        """
        if frozen_before is None:
            frozen_before = objects_before
        since = self._young_since_mono
        if not census:
            if deep:
                if frozen_before is not None and frozen_before > 0:
                    try:
                        pause_f = float(pause_s)
                    except Exception:
                        pause_f = float("nan")
                    if math.isfinite(pause_f) and pause_f >= 0.0:
                        candidate = pause_f / float(frozen_before)
                        if math.isfinite(candidate) and candidate > 0.0:
                            self._deep_cost_per_frozen_s = candidate
            elif since is not None:
                self._cost_pause_s = pause_s
                self._cost_accum_s = max(MIN_COST_SAMPLE_ACCUM_S, start_mono - since)
        self._young_since_mono = end_mono

    def _refresh_cost_sample(self) -> None:
        """Take a cost sample from any newer full collection, even automatic.

        Before the startup freeze a full collection scans the whole heap and
        only refreshes the duty-floor pause; afterwards it is a rate sample
        over the seconds since the previous full collection.
        """
        observed = newer_full_pause(self._recorder, self._cost_sample_mono)
        if observed is None:
            return
        pause, end_mono = observed
        self._last_full_pause_s, self._cost_sample_mono = observed
        self._pressure_deferral.clear()
        self._cost_deferral.clear()
        since = self._young_since_mono
        if not self._froze_startup or since is None or end_mono <= since:
            return
        start_mono = end_mono - pause
        if start_mono > since:
            self._cost_pause_s = pause
            self._cost_accum_s = max(MIN_COST_SAMPLE_ACCUM_S, start_mono - since)
        self._young_since_mono = end_mono

    def _full_collection_count(self) -> int | None:
        """Cumulative full collections from ``gc.get_stats()``, if exposed."""
        get_stats = getattr(self._collector, "get_stats", None)
        if not callable(get_stats):
            return None
        try:
            stats: Any = get_stats()
            value = stats[FULL_GENERATION]["collections"]
        except Exception:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    def _full_collection_ran(self, before: int | None) -> bool:
        """Return whether a full collection happened since ``before``.

        CPython's ``gc.collect()`` returns at once, collecting nothing, while
        another thread's collection is in progress (its finalizers or
        callbacks can release the GIL mid-collection). Without the counter the
        collection is assumed to have run.
        """
        if before is None:
            return True
        after = self._full_collection_count()
        return after is None or after > before

    def _read_gc_frozen_count(self) -> int | None:
        """Frozen-set size, if the collector exposes ``get_freeze_count``.

        A full unfreeze sweep always traverses the permanent generation; the
        young heap is priced separately by the time-based ordinary estimate,
        so ``gc.get_count()`` collection counters (which reset on young
        collections while promoted objects remain) never enter deep pricing.
        Missing, unreadable, or invalid frozen probes make the bounded deep
        sweep unpriceable, so the hourly cadence stays gated.
        """
        freeze_fn = getattr(self._collector, "get_freeze_count", None)
        if not callable(freeze_fn):
            return None
        freeze_n = safe_probe(freeze_fn, None)
        if isinstance(freeze_n, bool) or not isinstance(freeze_n, int) or freeze_n < 0:
            return None
        return freeze_n

    def _read_gc_tracked_objects(self) -> int | None:
        """Deprecated alias: frozen count only; ``get_count`` is not a population.

        Kept for backward compatibility; new code uses
        :meth:`_read_gc_frozen_count`. The old freeze-plus-counters sum
        undercounted promoted survivors after young collections reset the
        counters.
        """
        return self._read_gc_frozen_count()
