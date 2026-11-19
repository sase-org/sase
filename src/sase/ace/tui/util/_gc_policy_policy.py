"""Idle-time full-GC gate: duty-cycle bound, backstops, and census triggers."""

from __future__ import annotations

import gc
import logging
import sys
import time
from collections.abc import Callable
from typing import Any

from sase.ace.tui.util.gc_telemetry import (
    emit_row,
    gc_trigger,
    latest_memory_pressure,
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
from ._gc_policy_config import (
    BACKSTOP_QUIET_S,
    CENSUS_INTERVAL_S,
    CENSUS_WATCHLIST,
    COST_PREDICTION_SAFETY_FACTOR,
    COST_SAMPLE_MAX_AGE_S,
    DEFERRED_TELEMETRY_INTERVAL_S,
    DUTY_FACTOR,
    FULL_BACKSTOP_S,
    FULL_GENERATION,
    GEN1_DUE_COUNT,
    IDLE_QUIET_S,
    LONG_IDLE_COLLECTION_INTERVAL_S,
    LONG_IDLE_QUIET_S,
    MAJOR_FAULTS_PER_S_PRESSURE_THRESHOLD,
    MAX_PREDICTED_FULL_PAUSE_S,
    MAX_DUTY_DELAY_S,
    MIN_FULL_INTERVAL_S,
    NONCLASSIC_DUE_S,
    PRESSURE_SAMPLE_MAX_AGE_S,
    RAISED_THRESHOLD2,
    RSS_GROWTH_BACKSTOP_BYTES,
    SWAP_BYTES_PRESSURE_THRESHOLD,
    THRESHOLD_RAISED,
    THRESHOLD_UNSUPPORTED,
    TRIM_INTERVAL_S,
)
from ._gc_policy_trim import spawn_trim_thread

# Preserve the pre-split logger name so existing log capture keeps working.
log = logging.getLogger("sase.ace.tui.util.gc_policy")


def _classic_thresholds(collector: Any) -> tuple[int, int, int] | None:
    """Return the ``(t0, t1, t2)`` thresholds, or ``None`` elsewhere.

    Only the classic three-generation shape qualifies: a three-tuple of
    non-negative ints. Any other collector shape leaves thresholds alone
    and the idle collector still runs with a time-based due check.
    """
    try:
        raw = tuple(collector.get_threshold())
    except Exception:
        return None
    if len(raw) != 3:
        return None
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in raw):
        return None
    return (int(raw[0]), int(raw[1]), int(raw[2]))


class _NullRecorder:
    """Stand-in recorder when GC telemetry is not installed."""

    def last_full_collection_mono(self) -> float | None:
        return None

    def gen1_since_last_full(self) -> int:
        return 0

    def last_full_pause_s(self) -> float | None:
        return None


def _safe_probe(fn: Callable[[], Any], default: Any) -> Any:
    """Call a UI probe, returning ``default`` if it raises."""
    try:
        return fn()
    except Exception:
        return default


def _allocated_blocks() -> int | None:
    """Return Python's cheap allocated-block count when the runtime exposes it."""
    probe = getattr(sys, "getallocatedblocks", None)
    if not callable(probe):
        return None
    try:
        return max(0, int(probe()))
    except Exception:
        return None


class GCPolicy:
    """One installed idle-GC policy: gate state plus threshold ownership.

    All app access flows through small probe callables so the gate is
    drivable with a fake clock and stubbed collector/recorder. The live
    wiring passes app-bound probes from :func:`install_gc_policy`.
    """

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        last_input_mono: Callable[[], float] | None = None,
        prompt_active: Callable[[], bool] | None = None,
        navigating: Callable[[], bool] | None = None,
        modal_input_active: Callable[[], bool] | None = None,
        loads_done: Callable[[], bool] | None = None,
        collector: Any = gc,
        recorder: Any | None = None,
        trim_runner: Callable[[], None] | None = None,
        census_emit: Callable[[dict[str, Any]], None] | None = None,
        allocated_blocks_probe: Callable[[], int | None] | None = None,
        memory_pressure_probe: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None:
        self._monotonic = monotonic
        self._installed_mono = monotonic()
        self._last_input_mono = last_input_mono or (lambda: 0.0)
        self._prompt_active = prompt_active or (lambda: False)
        self._navigating = navigating or (lambda: False)
        self._modal_input_active = modal_input_active or (lambda: False)
        self._loads_done = loads_done or (lambda: False)
        self._collector = collector
        if recorder is not None and not (
            hasattr(recorder, "last_full_collection_mono")
            and hasattr(recorder, "gen1_since_last_full")
        ):
            recorder = None
        self._recorder = recorder if recorder is not None else _NullRecorder()
        self._trim_runner = trim_runner or spawn_trim_thread
        self._census_emit = census_emit
        self._allocated_blocks_probe = allocated_blocks_probe or _allocated_blocks
        self._memory_pressure_probe = memory_pressure_probe or latest_memory_pressure
        self._last_census_mono: float | None = None
        self._timer: Any = None
        self.threshold_policy = THRESHOLD_UNSUPPORTED
        self._original_threshold: tuple[int, int, int] | None = None
        self._froze_startup = False
        self._startup_freeze_mono: float | None = None
        self._own_last_full_mono: float | None = None
        self._rss_at_last_full: int | None = None
        self._last_full_pause_s: float | None = None
        self._last_full_scan_blocks: int | None = None
        self._cost_sample_mono: float | None = None
        self._heap_blocks_at_last_full = self._read_allocated_blocks()
        self._last_deep_full_mono: float | None = None
        self._last_deferred_emit_mono: dict[str, float] = {}
        self._last_trim_mono: float | None = None
        self._logged_survivor_census_skip = False
        try:
            recorded_pause = self._recorder.last_full_pause_s()
            recorded_mono = self._recorder.last_full_collection_mono()
            if (
                isinstance(recorded_pause, (int, float))
                and recorded_pause >= 0.0
                and isinstance(recorded_mono, (int, float))
                and recorded_mono >= 0.0
            ):
                self._last_full_pause_s = float(recorded_pause)
                self._cost_sample_mono = float(recorded_mono)
                self._last_full_scan_blocks = max(
                    1, self._heap_blocks_at_last_full or 1
                )
        except Exception:
            pass

    def duty_floor_s(self) -> float:
        """Minimum gap after the last full collection (duty-cycle bound).

        The next full collection runs no sooner than ``last_pause *
        DUTY_FACTOR`` after the last one, clamped to ``MAX_DUTY_DELAY_S``
        and floored at ``MIN_FULL_INTERVAL_S``. Unknown pause (no own
        collection yet) degrades to ``MIN_FULL_INTERVAL_S``.
        """
        pause = self._last_full_pause_s
        if pause is None:
            return MIN_FULL_INTERVAL_S
        try:
            pause_f = float(pause)
        except Exception:
            return MIN_FULL_INTERVAL_S
        if pause_f < 0.0:
            pause_f = 0.0
        return max(MIN_FULL_INTERVAL_S, min(pause_f * DUTY_FACTOR, MAX_DUTY_DELAY_S))

    def next_full_due_in_s(self, now_mono: float | None = None) -> float:
        """Seconds until the duty floor lets the next full collection run."""
        now = self._monotonic() if now_mono is None else now_mono
        last_full = self.combined_last_full_mono()
        if last_full is None:
            return 0.0
        try:
            remaining = (float(last_full) + self.duty_floor_s()) - float(now)
        except Exception:
            return 0.0
        return max(0.0, remaining)

    def heartbeat_fields(self) -> dict[str, Any]:
        """Extra heartbeat fields published via ``register_heartbeat_provider``."""
        fields: dict[str, Any] = {"threshold_policy": self.threshold_policy}
        try:
            fields["next_full_due_in_s"] = round(self.next_full_due_in_s(), 3)
            if self._last_full_pause_s is not None:
                fields["last_full_pause_s"] = round(float(self._last_full_pause_s), 6)
        except Exception:
            pass
        return fields

    def apply_thresholds(self) -> str:
        """Raise ``threshold2`` on the classic collector; report the policy."""
        classic = _classic_thresholds(self._collector)
        if classic is None:
            self.threshold_policy = THRESHOLD_UNSUPPORTED
            return self.threshold_policy
        t0, t1, _t2 = classic
        self._original_threshold = classic
        try:
            self._collector.set_threshold(t0, t1, RAISED_THRESHOLD2)
        except Exception:
            self._original_threshold = None
            self.threshold_policy = THRESHOLD_UNSUPPORTED
            return self.threshold_policy
        self.threshold_policy = THRESHOLD_RAISED
        return self.threshold_policy

    def restore_thresholds(self) -> None:
        """Restore the thresholds saved by :meth:`apply_thresholds`."""
        original, self._original_threshold = self._original_threshold, None
        if original is None:
            return
        try:
            self._collector.set_threshold(*original)
        except Exception:
            pass

    def combined_last_full_mono(self) -> float | None:
        """End time of the latest full collection from any trigger."""
        candidates = [self._own_last_full_mono]
        try:
            candidates.append(self._recorder.last_full_collection_mono())
        except Exception:
            pass
        known = [
            value
            for value in candidates
            if isinstance(value, (int, float)) and value >= 0
        ]
        return max(known) if known else None

    def collection_due(self, now_mono: float, last_full_mono: float | None) -> bool:
        """Return True when enough gen-1 work has piled up for a full sweep."""
        try:
            if int(self._recorder.gen1_since_last_full()) >= GEN1_DUE_COUNT:
                return True
        except Exception:
            pass
        classic = _classic_thresholds(self._collector)
        if classic is not None:
            try:
                counts = tuple(self._collector.get_count())
                if int(counts[FULL_GENERATION]) >= GEN1_DUE_COUNT:
                    return True
            except Exception:
                pass
        if last_full_mono is None:
            if classic is not None:
                return False
            started = self._startup_freeze_mono
            return started is None or now_mono - started >= NONCLASSIC_DUE_S
        return classic is None and now_mono - last_full_mono >= NONCLASSIC_DUE_S

    def idle_gate(self, now_mono: float) -> tuple[bool, str]:
        """Check the idle gate, returning ``(passes, tag)``.

        The tag names the trigger a passing collection would run under:
        ``"idle"``, or a relaxed ``"backstop"`` / ``"rss_backstop"`` once
        the 5-minute or RSS-growth backstop is tripped.
        """
        if not _safe_probe(self._loads_done, False):
            return (False, "idle")
        last_full = self.combined_last_full_mono()
        relaxed = False
        tag = "idle"
        if last_full is not None and now_mono - last_full >= FULL_BACKSTOP_S:
            relaxed = True
            tag = "backstop"
        else:
            rss_now = latest_rss_bytes()
            baseline = self._rss_at_last_full
            if (
                rss_now is not None
                and baseline is not None
                and rss_now - baseline > RSS_GROWTH_BACKSTOP_BYTES
            ):
                relaxed = True
                tag = "rss_backstop"
        quiet = BACKSTOP_QUIET_S if relaxed else IDLE_QUIET_S
        if self._input_idle_s(now_mono) < quiet:
            return (False, tag)
        if _safe_probe(self._prompt_active, False):
            return (False, tag)
        if _safe_probe(self._navigating, False):
            return (False, tag)
        if _safe_probe(self._modal_input_active, False):
            return (False, tag)
        floor = self.duty_floor_s()
        if last_full is not None and now_mono - last_full < floor:
            return (False, tag)
        if not self.collection_due(now_mono, last_full):
            return (False, tag)
        return (True, tag)

    def _read_allocated_blocks(self) -> int | None:
        value = _safe_probe(self._allocated_blocks_probe, None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None

    def _input_idle_s(self, now_mono: float) -> float:
        """Measure quiet time from the later of last input and policy startup."""
        raw = _safe_probe(self._last_input_mono, 0.0)
        try:
            last_input = float(raw)
        except Exception:
            last_input = 0.0
        reference = last_input if last_input > 0.0 else self._installed_mono
        if self._startup_freeze_mono is not None:
            reference = max(reference, self._startup_freeze_mono)
        return max(0.0, now_mono - reference)

    def _startup_freeze_gate(self, now_mono: float) -> bool:
        """Freeze the settled startup heap on an ordinary idle window."""
        if not _safe_probe(self._loads_done, False):
            return False
        if self._input_idle_s(now_mono) < IDLE_QUIET_S:
            return False
        return not (
            _safe_probe(self._prompt_active, False)
            or _safe_probe(self._navigating, False)
            or _safe_probe(self._modal_input_active, False)
        )

    def _predicted_pause_s(self, now_mono: float) -> float | None:
        """Estimate the next full sweep from the last pause and heap growth."""
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
            or now_mono - sampled > COST_SAMPLE_MAX_AGE_S
        ):
            return None
        new_blocks = max(1, current - baseline)
        return pause * new_blocks / scanned_blocks * COST_PREDICTION_SAFETY_FACTOR

    def _memory_pressure(self, now_mono: float) -> dict[str, Any] | None:
        """Return a fresh pressure sample only when swap/fault thresholds trip."""
        sample = _safe_probe(self._memory_pressure_probe, None)
        if not isinstance(sample, dict):
            return None
        age = sample.get("sample_age_s")
        if not isinstance(age, (int, float)) or age < 0.0:
            return None
        if age > PRESSURE_SAMPLE_MAX_AGE_S:
            return None
        swap = sample.get("vmswap_bytes")
        faults = sample.get("major_faults_per_s")
        swapping = (
            isinstance(swap, int)
            and not isinstance(swap, bool)
            and swap > SWAP_BYTES_PRESSURE_THRESHOLD
        ) or (
            isinstance(faults, (int, float))
            and faults > MAJOR_FAULTS_PER_S_PRESSURE_THRESHOLD
        )
        if not swapping:
            return None
        return {
            "vmswap_bytes": swap,
            "major_faults_per_s": faults,
            "sample_age_s": round(float(age), 3),
            "sampled_at_mono": now_mono - float(age),
        }

    def _record_deferred(
        self,
        *,
        now_mono: float,
        trigger: str,
        reason: str,
        input_idle_s: float,
        pressure: dict[str, Any] | None = None,
        predicted_pause_s: float | None = None,
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
        if pressure is not None:
            row.update(
                {
                    "vmswap_bytes": pressure.get("vmswap_bytes"),
                    "major_faults_per_s": pressure.get("major_faults_per_s"),
                    "pressure_sample_age_s": pressure.get("sample_age_s"),
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
        if pressure is not None:
            self._record_deferred(
                now_mono=now,
                trigger=tag,
                reason="swapping",
                input_idle_s=input_idle_s,
                pressure=pressure,
            )
            return None

        predicted_pause = self._predicted_pause_s(now)
        if not long_idle and (
            predicted_pause is None or predicted_pause > MAX_PREDICTED_FULL_PAUSE_S
        ):
            self._record_deferred(
                now_mono=now,
                trigger=tag,
                reason="cost_unknown" if predicted_pause is None else "cost_gate",
                input_idle_s=input_idle_s,
                predicted_pause_s=predicted_pause,
            )
            return None

        deep_idle_due = long_idle and (
            self._last_deep_full_mono is None
            or now - self._last_deep_full_mono >= LONG_IDLE_COLLECTION_INTERVAL_S
        )
        unfreeze = getattr(self._collector, "unfreeze", None)
        deep_collection = deep_idle_due and callable(unfreeze)
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
