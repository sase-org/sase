"""Pause estimate for the full-GC policy: time-priced samples and deep pricing.

An ordinary sweep after a freeze scans only what was created since the last
full collection: survivors plus the cyclic garbage that dominates the pause.
Both accumulate at the session's churn rate, so a sample is stored as a pause
over the seconds of accumulation it swept, and the next sweep is priced as
that rate times the seconds accumulated since. Allocated-block deltas are not
used for ordinary sweeps: refcount frees of old frozen objects shrink the net
total while new garbage still needs scanning, which once priced a 0.647 s
sweep as a single block and predicted a 645,427 s pause.

A deep (unfreeze) sweep scans GC-tracked objects (the frozen set plus the
young generations), so it is priced per object, from the latest deep sample
or the attribute-phase measured rate.

Everything here is arithmetic over cached state; nothing runs a collection.
"""

from __future__ import annotations

from typing import Any

from ._gc_policy_common import safe_probe
from ._gc_policy_config import (
    COST_DEFERRAL_GROWTH_S,
    COST_DUE_FRACTION,
    COST_MAX_DEFERRAL_S,
    COST_PREDICTION_SAFETY_FACTOR,
    DEEP_COST_PER_OBJECT_S,
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
    _deep_cost_per_object_s: float | None

    def _predicted_pause_s(
        self, now_mono: float, *, deep: bool = False
    ) -> float | None:
        """Estimate the next full sweep's pause, safety factor included.

        Ordinary sweeps scale the latest sample's pause rate by the seconds
        accumulated since the last full collection (or the startup freeze).
        ``None`` means no post-freeze sample exists yet. A deep sweep is
        priced per GC-tracked object over the frozen set plus young generations.
        """
        if deep:
            current = self._read_gc_tracked_objects()
            if current is None:
                return None
            per_object = self._deep_cost_per_object_s
            if per_object is None:
                per_object = DEEP_COST_PER_OBJECT_S
            return per_object * max(1, current) * COST_PREDICTION_SAFETY_FACTOR
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
        objects_before: int | None,
    ) -> None:
        """Store the cost evidence of one verified own full collection.

        A census sweep (``DEBUG_SAVEALL`` plus a survivor scan) is no cost
        sample. A deep sweep only refreshes the per-object deep sample; the
        ordinary rate keeps its last young-heap sample.
        """
        since = self._young_since_mono
        if not census:
            if deep:
                if objects_before is not None and objects_before > 0:
                    self._deep_cost_per_object_s = pause_s / objects_before
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

    def _read_gc_tracked_objects(self) -> int | None:
        """Frozen-set size plus generation counts, if the collector exposes both.

        A full unfreeze collection traverses the permanent generation
        (``get_freeze_count``) and every object still in gen0/1/2
        (``get_count``). Missing or unreadable probes make the deep sweep
        unpriceable, so the hourly cadence stays gated.
        """
        freeze_fn = getattr(self._collector, "get_freeze_count", None)
        if not callable(freeze_fn):
            return None
        freeze_n = safe_probe(freeze_fn, None)
        if isinstance(freeze_n, bool) or not isinstance(freeze_n, int) or freeze_n < 0:
            return None
        count_fn = getattr(self._collector, "get_count", None)
        young = 0
        if callable(count_fn):
            counts = safe_probe(count_fn, None)
            if counts is None:
                return None
            try:
                for n in counts:
                    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
                        return None
                    young += n
            except TypeError:
                return None
        return freeze_n + young
