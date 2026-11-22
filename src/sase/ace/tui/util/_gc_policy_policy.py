"""Idle-time full-GC gate: duty-cycle bound, backstops, and census triggers."""

from __future__ import annotations

import gc
import sys
import time
from collections.abc import Callable
from typing import Any

from sase.ace.tui.util.gc_telemetry import latest_memory_pressure

from ._gc_policy_config import THRESHOLD_UNSUPPORTED
from ._gc_policy_pressure import CostDeferral, PressureDeferral
from ._gc_policy_sweep import PolicySweepMixin
from ._gc_policy_trim import spawn_trim_thread


class _NullRecorder:
    """Stand-in recorder when GC telemetry is not installed."""

    def last_full_collection_mono(self) -> float | None:
        return None

    def gen1_since_last_full(self) -> int:
        return 0

    def last_full_pause_s(self) -> float | None:
        return None


def _allocated_blocks() -> int | None:
    """Return Python's cheap allocated-block count when the runtime exposes it."""
    probe = getattr(sys, "getallocatedblocks", None)
    if not callable(probe):
        return None
    try:
        return max(0, int(probe()))
    except Exception:
        return None


class GCPolicy(PolicySweepMixin):
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
        self._pressure_deferral = PressureDeferral()
        self._cost_deferral = CostDeferral()
        self._deep_cost_deferral = CostDeferral()
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
        self._refresh_cost_sample()
