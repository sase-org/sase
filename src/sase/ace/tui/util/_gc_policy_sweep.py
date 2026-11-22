"""Sweep execution for the full-GC policy: cost gate, tick, and census."""

from __future__ import annotations

import gc
import logging
from collections.abc import Callable
from typing import Any

from sase.ace.tui.util.gc_telemetry import (
    emit_row,
    gc_trigger,
    latest_rss_bytes,
    queue_row,
)

from ._gc_policy_census import (
    TypeCensus,
    census_enabled,
    known_cache_census,
    survivor_census_safe,
    top_types,
)
from ._gc_policy_common import safe_probe
from ._gc_policy_config import (
    CENSUS_INTERVAL_S,
    CENSUS_WATCHLIST,
    COST_PREDICTION_SAFETY_FACTOR,
    COST_SAMPLE_MAX_AGE_S,
    DEEP_SWEEP_INTERVAL_S,
    DEFERRED_TELEMETRY_INTERVAL_S,
    FIRST_SWEEP_BLOCK_BUDGET,
    LONG_IDLE_COLLECTION_INTERVAL_S,
    LONG_IDLE_QUIET_S,
    MAX_PREDICTED_FULL_PAUSE_S,
    TRIM_INTERVAL_S,
)
from ._gc_policy_gate import PolicyGateMixin
from ._gc_policy_pressure import (
    CostDeferral,
    PressureDeferral,
    newer_full_pause,
    paging_pressure,
)

# Preserve the pre-split logger name so existing log capture keeps working.
log = logging.getLogger("sase.ace.tui.util.gc_policy")


class PolicySweepMixin(PolicyGateMixin):
    """Execution half of :class:`GCPolicy`: cost gate, tick, census, trim."""

    _pressure_deferral: PressureDeferral
    _cost_deferral: CostDeferral
    _deep_cost_deferral: CostDeferral
    _last_census_mono: float | None
    _timer: Any
    _froze_startup: bool
    _last_full_scan_blocks: int | None
    _cost_sample_mono: float | None
    _heap_blocks_at_last_full: int | None
    _last_deep_full_mono: float | None
    _last_deferred_emit_mono: dict[str, float]
    _last_trim_mono: float | None
    _logged_survivor_census_skip: bool
    _trim_runner: Callable[[], None]
    _census_emit: Callable[[dict[str, Any]], None] | None
    _memory_pressure_probe: Callable[[], dict[str, Any] | None]

    def _predicted_pause_s(
        self, now_mono: float, trigger: str = "idle", *, deep: bool = False
    ) -> float | None:
        """Estimate the next full sweep from the last pause and heap growth.

        Only ``idle`` needs a sample younger than ``COST_SAMPLE_MAX_AGE_S``;
        a backstop prices itself from the latest observed full collection. A
        bounded deep sweep scans the whole heap, so it scales the sample to
        every allocated block instead of only the growth since the last sweep.
        """
        pause = self._last_full_pause_s
        baseline = self._heap_blocks_at_last_full
        scanned_blocks = self._last_full_scan_blocks
        sampled = self._cost_sample_mono
        current = self._read_allocated_blocks()
        if (
            pause is None
            or baseline is None
            or scanned_blocks is None
            or scanned_blocks <= 0
            or current is None
            or sampled is None
            or (trigger == "idle" and now_mono - sampled > COST_SAMPLE_MAX_AGE_S)
        ):
            return None
        if deep:
            new_blocks = max(1, current)
        else:
            new_blocks = max(1, current - baseline)
        return pause * new_blocks / scanned_blocks * COST_PREDICTION_SAFETY_FACTOR

    def _first_sweep_seed_due(self) -> bool:
        """Return True when one early sweep should seed the cost estimate.

        Right after the freeze-only startup no full collection has been
        observed, so the estimate is unknown and the gate would hold every
        sweep until long idle. While the heap has grown by real garbage but
        is still within ``FIRST_SWEEP_BLOCK_BUDGET``, one ordinary sweep is
        cheap and yields the first real sample.
        """
        if not self._froze_startup:
            return False
        if self._own_last_full_mono is not None:
            return False
        if self._cost_sample_mono is not None or self._last_full_pause_s is not None:
            return False
        current = self._read_allocated_blocks()
        baseline = self._heap_blocks_at_last_full
        if current is None or baseline is None:
            return False
        return 0 < current - baseline <= FIRST_SWEEP_BLOCK_BUDGET

    def _deep_bounded_due(self, now_mono: float) -> bool:
        """Return True when frozen garbage is due a bounded reclaim sweep.

        At most one unfreeze sweep per ``DEEP_SWEEP_INTERVAL_S``, on an
        ordinary quiet window, anchored at the startup freeze so the first
        bounded deep sweep waits a full interval after startup.
        """
        if not self._froze_startup or self._startup_freeze_mono is None:
            return False
        anchor = (
            self._last_deep_full_mono
            if self._last_deep_full_mono is not None
            else self._startup_freeze_mono
        )
        return now_mono - anchor >= DEEP_SWEEP_INTERVAL_S

    def _memory_pressure(self, now_mono: float) -> dict[str, Any] | None:
        """Return a fresh pressure sample only when the process is paging."""
        return paging_pressure(safe_probe(self._memory_pressure_probe, None), now_mono)

    def _refresh_cost_sample(self) -> None:
        """Seed the cost estimate from any newer full collection, even automatic.

        Before the startup freeze a full collection scans the whole heap;
        afterwards only blocks allocated since the last freeze.
        """
        observed = newer_full_pause(self._recorder, self._cost_sample_mono)
        if observed is None:
            return
        self._last_full_pause_s, self._cost_sample_mono = observed
        self._pressure_deferral.clear()
        self._cost_deferral.clear()
        self._deep_cost_deferral.clear()
        scanned = self._read_allocated_blocks() or 1
        baseline = self._heap_blocks_at_last_full
        if self._froze_startup and baseline is not None:
            scanned -= baseline
        self._last_full_scan_blocks = max(1, scanned)

    def _record_deferred(
        self,
        *,
        now_mono: float,
        trigger: str,
        reason: str,
        input_idle_s: float,
        pressure: dict[str, Any] | None = None,
        predicted_pause_s: float | None = None,
        cost_deferral_s: float | None = None,
        deep_due: bool = False,
    ) -> None:
        """Emit a rate-limited row when pressure or the cost gate defers a sweep."""
        key = f"{trigger}:{reason}"
        previous = self._last_deferred_emit_mono.get(key)
        if previous is not None and now_mono - previous < DEFERRED_TELEMETRY_INTERVAL_S:
            return
        self._last_deferred_emit_mono[key] = now_mono
        row: dict[str, Any] = {
            "trigger": trigger,
            "reason": reason,
            "input_idle_s": round(max(0.0, input_idle_s), 3),
            "predicted_pause_s": (
                None
                if predicted_pause_s is None
                else round(max(0.0, predicted_pause_s), 6)
            ),
            "pause_budget_s": MAX_PREDICTED_FULL_PAUSE_S,
        }
        if cost_deferral_s is not None:
            row["cost_deferred_s"] = round(max(0.0, cost_deferral_s), 3)
        if deep_due:
            row["deep_due"] = True
        if pressure is not None:
            row.update(
                {
                    "vmswap_bytes": pressure.get("vmswap_bytes"),
                    "vmswap_growth_bytes": pressure.get("vmswap_growth_bytes"),
                    "major_faults_per_s": pressure.get("major_faults_per_s"),
                    "pressure_signal": pressure.get("signal"),
                    "pressure_sample_age_s": pressure.get("sample_age_s"),
                    "pressure_deferred_s": round(
                        self._pressure_deferral.deferred_for_s(now_mono), 3
                    ),
                }
            )
        queue_row(
            "tui_gc_memory_pressure"
            if reason == "swapping"
            else "tui_gc_collection_deferred",
            row,
        )

    def tick(self, now_mono: float | None = None) -> str | None:
        """Run one 1 s tick; return the collection trigger, if any ran."""
        now = self._monotonic() if now_mono is None else now_mono
        self._refresh_cost_sample()
        if not self._froze_startup:
            if not self._startup_freeze_gate(now):
                return None
            with gc_trigger("startup_freeze"):
                self._collector.freeze()
            self._froze_startup = True
            self._startup_freeze_mono = now
            self._heap_blocks_at_last_full = self._read_allocated_blocks()
            self._rss_at_last_full = latest_rss_bytes()
            return "startup_freeze"

        passes, tag = self.idle_gate(now)
        if not passes:
            return None

        input_idle_s = self._input_idle_s(now)
        long_idle = input_idle_s >= LONG_IDLE_QUIET_S
        pressure = self._memory_pressure(now)
        if pressure is None:
            self._pressure_deferral.clear()
        elif self._pressure_deferral.defers(
            trigger=tag, now_mono=now, input_idle_s=input_idle_s
        ):
            self._record_deferred(
                now_mono=now,
                trigger=tag,
                reason="swapping",
                input_idle_s=input_idle_s,
                pressure=pressure,
            )
            return None

        deep_long_idle_due = long_idle and (
            self._last_deep_full_mono is None
            or now - self._last_deep_full_mono >= LONG_IDLE_COLLECTION_INTERVAL_S
        )
        deep_bounded_due = self._deep_bounded_due(now) if not long_idle else False
        predicted_pause = self._predicted_pause_s(now, tag, deep=deep_bounded_due)
        if not long_idle and (
            predicted_pause is None or predicted_pause > MAX_PREDICTED_FULL_PAUSE_S
        ):
            window = (
                self._deep_cost_deferral if deep_bounded_due else self._cost_deferral
            )
            seed = not deep_bounded_due and self._first_sweep_seed_due()
            if not seed and window.defers(
                trigger=tag, now_mono=now, input_idle_s=input_idle_s
            ):
                self._record_deferred(
                    now_mono=now,
                    trigger=tag,
                    reason="cost_unknown" if predicted_pause is None else "cost_gate",
                    input_idle_s=input_idle_s,
                    predicted_pause_s=predicted_pause,
                    cost_deferral_s=window.deferred_for_s(now),
                    deep_due=deep_bounded_due,
                )
                return None
            # The cap passed, or this is the cheap first post-freeze sweep that
            # seeds the estimate: run on this quiet window despite the gate.

        unfreeze = getattr(self._collector, "unfreeze", None)
        deep_collection = (deep_long_idle_due or deep_bounded_due) and callable(
            unfreeze
        )
        blocks_before = self._read_allocated_blocks()
        if deep_collection and blocks_before is not None:
            scan_blocks: int | None = max(1, blocks_before)
        else:
            baseline = self._heap_blocks_at_last_full
            scan_blocks = (
                None
                if blocks_before is None or baseline is None
                else max(1, blocks_before - baseline)
            )

        start = self._monotonic()
        try:
            if deep_collection and callable(unfreeze):
                unfreeze()
            if tag == "idle" and self._census_due(now):
                self._run_idle_census(now)
            else:
                with gc_trigger(tag):
                    self._collector.collect()
        finally:
            # Re-freezing keeps later gen-2 sweeps proportional to the objects
            # created since this collection. Even a failed collect must not
            # leave the entire old heap exposed to every future full sweep.
            self._collector.freeze()
        pause = self._monotonic() - start
        self._note_full_collection(pause, scan_blocks=scan_blocks)
        if deep_collection:
            self._last_deep_full_mono = self._own_last_full_mono
            self._deep_cost_deferral.clear()
        self._maybe_trim(now)
        return tag

    def tick_safe(self) -> None:
        """Timer entry point: run :meth:`tick` without ever raising."""
        try:
            self.tick()
        except Exception:
            log.exception("GC policy tick failed")

    def _note_full_collection(
        self,
        pause_s: float | None = None,
        *,
        scan_blocks: int | None = None,
    ) -> None:
        """Record an own full collection and refresh the RSS baseline."""
        self._own_last_full_mono = self._monotonic()
        self._pressure_deferral.clear()
        self._cost_deferral.clear()
        self._cost_sample_mono = self._own_last_full_mono
        if pause_s is not None:
            try:
                pause = float(pause_s)
            except Exception:
                pause = None  # type: ignore[assignment]
            if pause is not None:
                if pause < 0.0:
                    pause = 0.0
                self._last_full_pause_s = pause
        self._last_full_scan_blocks = scan_blocks
        self._heap_blocks_at_last_full = self._read_allocated_blocks()
        try:
            self._rss_at_last_full = latest_rss_bytes()
        except Exception:
            pass

    def _census_due(self, now_mono: float) -> bool:
        """Return True when an idle collection should run the opt-in census."""
        if not census_enabled():
            return False
        last = self._last_census_mono
        return last is None or now_mono - last >= CENSUS_INTERVAL_S

    def _run_idle_census(self, now_mono: float) -> None:
        """Idle full collection plus garbage/survivor type census.

        Lengthens the pause: ``gc.DEBUG_SAVEALL`` retains collected cycles
        until a second collect frees them. Rate-limited to once per
        ``CENSUS_INTERVAL_S`` and only on the ``idle`` trigger. The
        surviving-types half needs Python 3.14+; earlier interpreters skip
        ``get_objects()`` and emit ``survivor_census:
        "skipped_unsafe_python"``.
        """
        self._last_census_mono = now_mono
        start = self._monotonic()
        collector = self._collector
        previous_debug = 0
        garbage = TypeCensus(top=[], total=0, watch=[], bytes_total=0)
        get_debug = getattr(collector, "get_debug", None)
        set_debug = getattr(collector, "set_debug", None)
        try:
            if callable(get_debug) and callable(set_debug):
                try:
                    previous_debug = int(get_debug())
                    set_debug(previous_debug | gc.DEBUG_SAVEALL)
                except Exception:
                    set_debug = None
            with gc_trigger("idle"):
                collector.collect()
            garbage = top_types(tuple(gc.garbage))
            gc.garbage.clear()
        finally:
            if callable(set_debug):
                try:
                    set_debug(previous_debug)
                except Exception:
                    pass
            try:
                with gc_trigger("idle"):
                    collector.collect()
            except Exception:
                pass
        survivor_top: list[dict[str, Any]] = []
        survivor_watch: list[dict[str, Any]] = []
        survivor_count: int | None
        survivor_bytes: int | None
        if survivor_census_safe():
            survivor_census = "ok"
            survivor_count = 0
            survivor_bytes = 0
            get_objects = getattr(collector, "get_objects", None)
            if callable(get_objects):
                try:
                    survivors = top_types(get_objects(), watch=CENSUS_WATCHLIST)
                    survivor_top = survivors.top
                    survivor_watch = survivors.watch
                    survivor_count = survivors.total
                    survivor_bytes = survivors.bytes_total
                except Exception:
                    pass
        else:
            survivor_census = "skipped_unsafe_python"
            survivor_count = None
            survivor_bytes = None
            if not self._logged_survivor_census_skip:
                self._logged_survivor_census_skip = True
                log.warning(
                    "Survivor type census skipped: needs Python 3.14+; "
                    "recording collected-garbage types only"
                )
        payload = {
            "garbage_top": garbage.top,
            "survivor_top": survivor_top,
            "survivor_watch": survivor_watch,
            "garbage_count": garbage.total,
            "garbage_bytes": garbage.bytes_total,
            "survivor_count": survivor_count,
            "survivor_bytes": survivor_bytes,
            "survivor_census": survivor_census,
            "known_caches": known_cache_census(),
            "census_duration_s": round(self._monotonic() - start, 6),
        }
        if self._census_emit is not None:
            self._census_emit({"event": "tui_gc_census", **payload})
        else:
            emit_row("tui_gc_census", payload)

    def _maybe_trim(self, now_mono: float) -> bool:
        """Dispatch an off-thread ``malloc_trim`` at most every 10 minutes."""
        if (
            self._last_trim_mono is not None
            and now_mono - self._last_trim_mono < TRIM_INTERVAL_S
        ):
            return False
        self._last_trim_mono = now_mono
        try:
            self._trim_runner()
        except Exception:
            log.exception("GC policy trim dispatch failed")
        return True
