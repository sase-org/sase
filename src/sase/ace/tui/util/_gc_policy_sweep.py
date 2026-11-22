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
    DEEP_SWEEP_INTERVAL_S,
    DEFERRED_TELEMETRY_INTERVAL_S,
    LONG_IDLE_COLLECTION_INTERVAL_S,
    LONG_IDLE_QUIET_S,
    MAX_PREDICTED_FULL_PAUSE_S,
    TRIM_INTERVAL_S,
)
from ._gc_policy_gate import PolicyGateMixin
from ._gc_policy_pressure import paging_pressure

# Preserve the pre-split logger name so existing log capture keeps working.
log = logging.getLogger("sase.ace.tui.util.gc_policy")


class PolicySweepMixin(PolicyGateMixin):
    """Execution half of :class:`GCPolicy`: cost gate, tick, census, trim."""

    _last_census_mono: float | None
    _timer: Any
    _last_deep_full_mono: float | None
    _last_deferred_emit_mono: dict[str, float]
    _last_trim_mono: float | None
    _logged_survivor_census_skip: bool
    _trim_runner: Callable[[], None]
    _census_emit: Callable[[dict[str, Any]], None] | None
    _memory_pressure_probe: Callable[[], dict[str, Any] | None]

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
        cost_deferral_cap_s: float | None = None,
        deep_due: bool = False,
        gc_tracked_objects: int | None = None,
    ) -> None:
        """Emit a rate-limited row when pressure, cost, or the collector defers.

        Reasons: ``swapping`` (paging pressure, a ``tui_gc_memory_pressure``
        row), ``cost_gate`` (estimate over budget), ``deep_cost_gate`` (the
        hourly deep sweep priced over budget; an ordinary sweep runs
        instead), and ``collector_busy`` (``gc.collect()`` returned without a
        full collection because another thread's collection was in progress;
        nothing was frozen or recorded, and the next tick retries).
        """
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
        if cost_deferral_cap_s is not None:
            row["cost_deferral_cap_s"] = round(max(0.0, cost_deferral_cap_s), 3)
        if deep_due:
            row["deep_due"] = True
        if gc_tracked_objects is not None:
            row["gc_tracked_objects"] = gc_tracked_objects
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
            self._young_since_mono = now
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
        deep_bounded = not long_idle and self._deep_bounded_admitted(
            now, tag, input_idle_s
        )
        if not long_idle and not deep_bounded:
            # No estimate yet (no post-freeze sample) never defers: waiting
            # only grows the heap, so this sweep seeds the sample instead.
            predicted_pause = self._predicted_pause_s(now)
            if (
                predicted_pause is not None
                and predicted_pause > MAX_PREDICTED_FULL_PAUSE_S
            ):
                cap_s = self._cost_deferral_cap_s()
                if self._cost_deferral.defers(
                    trigger=tag,
                    now_mono=now,
                    input_idle_s=input_idle_s,
                    cap_s=cap_s,
                ):
                    self._record_deferred(
                        now_mono=now,
                        trigger=tag,
                        reason="cost_gate",
                        input_idle_s=input_idle_s,
                        predicted_pause_s=predicted_pause,
                        cost_deferral_s=self._cost_deferral.deferred_for_s(now),
                        cost_deferral_cap_s=cap_s,
                    )
                    return None
                # The cap passed: run on this quiet window despite the gate.
        return self._run_sweep(
            now,
            tag,
            input_idle_s=input_idle_s,
            deep=deep_long_idle_due or deep_bounded,
        )

    def _deep_bounded_admitted(
        self, now_mono: float, tag: str, input_idle_s: float
    ) -> bool:
        """Return True when the hourly deep sweep is due and fits the budget.

        An over-budget (or unpriceable) deep sweep is skipped with a
        rate-limited ``deep_cost_gate`` row; the tick then prices an
        ordinary sweep, so a pending deep sweep never holds ordinary ones.
        """
        if not self._deep_bounded_due(now_mono):
            return False
        predicted = self._predicted_pause_s(now_mono, deep=True)
        if predicted is not None and predicted <= MAX_PREDICTED_FULL_PAUSE_S:
            return True
        self._record_deferred(
            now_mono=now_mono,
            trigger=tag,
            reason="deep_cost_gate",
            input_idle_s=input_idle_s,
            predicted_pause_s=predicted,
            deep_due=True,
            gc_tracked_objects=self._read_gc_tracked_objects(),
        )
        return False

    def _run_sweep(
        self, now_mono: float, tag: str, *, input_idle_s: float, deep: bool
    ) -> str | None:
        """Collect, prove a full collection ran, then freeze and record it."""
        unfreeze = getattr(self._collector, "unfreeze", None)
        deep_collection = deep and callable(unfreeze)
        objects_before = self._read_gc_tracked_objects() if deep_collection else None
        census = tag == "idle" and self._census_due(now_mono)
        collections_before = self._full_collection_count()
        ran = False
        start = self._monotonic()
        try:
            if deep_collection and callable(unfreeze):
                unfreeze()
            if census:
                self._run_idle_census(now_mono)
            else:
                with gc_trigger(tag):
                    self._collector.collect()
        finally:
            ran = self._full_collection_ran(collections_before)
            # Re-freezing keeps later sweeps proportional to the objects
            # created since this collection, so only a proven collection
            # freezes: freezing after a skipped one would move every young
            # cycle into the permanent generation. A deep sweep always
            # re-freezes, so a failed or skipped one cannot leave the entire
            # old heap exposed to every future sweep.
            if ran or deep_collection:
                self._collector.freeze()
        end = self._monotonic()
        if not ran:
            self._record_deferred(
                now_mono=now_mono,
                trigger=tag,
                reason="collector_busy",
                input_idle_s=input_idle_s,
            )
            return None
        self._note_full_collection(
            end - start,
            start_mono=start,
            deep=deep_collection,
            census=census,
            objects_before=objects_before,
        )
        if deep_collection:
            self._last_deep_full_mono = self._own_last_full_mono
        self._maybe_trim(now_mono)
        return tag

    def tick_safe(self) -> None:
        """Timer entry point: run :meth:`tick` without ever raising."""
        try:
            self.tick()
        except Exception:
            log.exception("GC policy tick failed")

    def _note_full_collection(
        self,
        pause_s: float,
        *,
        start_mono: float,
        deep: bool = False,
        census: bool = False,
        objects_before: int | None = None,
    ) -> None:
        """Record a verified own full collection and refresh the RSS baseline."""
        self._own_last_full_mono = self._monotonic()
        self._pressure_deferral.clear()
        self._cost_deferral.clear()
        self._cost_sample_mono = self._own_last_full_mono
        pause = max(0.0, float(pause_s))
        self._last_full_pause_s = pause
        self._record_cost_sample(
            pause,
            start_mono=start_mono,
            end_mono=self._own_last_full_mono,
            deep=deep,
            census=census,
            objects_before=objects_before,
        )
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
