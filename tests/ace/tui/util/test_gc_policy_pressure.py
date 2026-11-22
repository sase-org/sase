"""Tests for the GC policy's paging-pressure gate and observed-cost refresh."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.util import _gc_policy_gate as gate_module
from sase.ace.tui.util import _gc_policy_sweep as sweep_module
from sase.ace.tui.util import gc_policy
from sase.ace.tui.util._gc_policy_pressure import paging_pressure
from tests.ace.tui.util._gc_policy_test_support import (
    Clock,
    Collector,
    Recorder,
    idle_policy,
)

_MIB = 1024 * 1024


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def collector() -> Collector:
    return Collector()


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def emitted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    monkeypatch.setattr(
        sweep_module,
        "queue_row",
        lambda event, row: rows.append({"event": event, **row}),
    )
    return rows


def _pressure_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["event"] == "tui_gc_memory_pressure"]


def test_residual_swap_with_zero_faults_does_not_defer(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """Athena held 40-938 MiB of VmSwap at 0.0 major faults/s for hours."""
    sample = {
        "vmswap_bytes": 938 * _MIB,
        "vmswap_growth_bytes": 0,
        "major_faults_per_s": 0.0,
        "sample_age_s": 1.0,
    }
    assert paging_pressure(sample, clock.now) is None
    policy = idle_policy(
        clock, collector, recorder, memory_pressure_probe=lambda: sample
    )
    assert policy.tick(clock.now) == "startup_freeze"
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert collector.collections == 1
    assert _pressure_rows(emitted) == []


def test_swap_growth_or_fault_rate_is_paging_pressure(clock: Clock) -> None:
    growing = {
        "vmswap_bytes": 100 * _MIB,
        "vmswap_growth_bytes": gc_policy.SWAP_GROWTH_PRESSURE_BYTES + 1,
        "major_faults_per_s": 0.0,
        "sample_age_s": 0.0,
    }
    faulting = {
        "vmswap_bytes": 0,
        "vmswap_growth_bytes": 0,
        "major_faults_per_s": gc_policy.MAJOR_FAULTS_PER_S_PRESSURE_THRESHOLD + 1,
        "sample_age_s": 0.0,
    }
    grow_pressure = paging_pressure(growing, clock.now)
    fault_pressure = paging_pressure(faulting, clock.now)
    assert grow_pressure is not None and grow_pressure["signal"] == "swap_growth"
    assert fault_pressure is not None and fault_pressure["signal"] == "major_faults"
    # Stale samples and growth at the threshold are not pressure.
    assert paging_pressure({**growing, "sample_age_s": 21.0}, clock.now) is None
    at_threshold = {
        **growing,
        "vmswap_growth_bytes": gc_policy.SWAP_GROWTH_PRESSURE_BYTES,
    }
    assert paging_pressure(at_threshold, clock.now) is None


def test_pressure_holds_backstop_for_a_bounded_window(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    pressure = {
        "vmswap_bytes": 0,
        "major_faults_per_s": gc_policy.MAJOR_FAULTS_PER_S_PRESSURE_THRESHOLD + 1,
        "sample_age_s": 0.0,
    }
    input_ago = {"s": 10.0}
    policy = idle_policy(
        clock, collector, recorder, memory_pressure_probe=lambda: pressure
    )
    policy._last_input_mono = lambda: clock.now - input_ago["s"]
    # Isolate the pressure window from the separately tested cost gate.
    policy._predicted_pause_s = lambda _now, _trigger="idle", deep=False: 0.0
    assert policy.tick(clock.now) == "startup_freeze"
    policy._own_last_full_mono = clock.now
    recorder.gen1 = 150

    # Pressure holds the opportunistic idle sweep without opening the window.
    clock.advance(61.0)
    assert policy.tick(clock.now) is None
    assert policy._pressure_deferral.deferred_for_s(clock.now) == 0.0

    # Past the 5-minute backstop: the first deferral opens the window.
    clock.advance(gc_policy.FULL_BACKSTOP_S)
    assert policy.tick(clock.now) is None
    rows = _pressure_rows(emitted)
    assert rows[-1]["trigger"] == "backstop"
    assert rows[-1]["pressure_signal"] == "major_faults"
    assert rows[-1]["pressure_deferred_s"] == 0.0

    clock.advance(gc_policy.PRESSURE_MAX_DEFERRAL_S - 1.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 0

    # The window has elapsed, but the user is only briefly quiet.
    clock.advance(1.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 0

    # Quiet long enough: the bounded backstop runs despite ongoing pressure.
    input_ago["s"] = gc_policy.PRESSURE_OVERRIDE_QUIET_S
    assert policy.tick(clock.now) == "backstop"
    assert collector.collections == 1
    # The collection closed the window; the next backstop starts a new one.
    assert policy._pressure_deferral.deferred_for_s(clock.now) == 0.0


def test_pressure_window_closes_when_paging_stops(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    pressure: dict[str, Any] = {
        "vmswap_bytes": 0,
        "major_faults_per_s": gc_policy.MAJOR_FAULTS_PER_S_PRESSURE_THRESHOLD + 1,
        "sample_age_s": 0.0,
    }
    policy = idle_policy(
        clock, collector, recorder, memory_pressure_probe=lambda: pressure
    )
    policy._predicted_pause_s = lambda _now, _trigger="idle", deep=False: 0.0
    assert policy.tick(clock.now) == "startup_freeze"
    policy._own_last_full_mono = clock.now
    recorder.gen1 = 150
    clock.advance(gc_policy.FULL_BACKSTOP_S + 1.0)
    assert policy.tick(clock.now) is None
    assert policy._pressure_deferral._since_mono == clock.now

    # A quiet pass clears the window even if another gate then defers.
    pressure["major_faults_per_s"] = 0.0
    policy._predicted_pause_s = lambda _now, _trigger="idle", deep=False: 99.0
    clock.advance(30.0)
    assert policy.tick(clock.now) is None
    assert emitted[-1]["event"] == "tui_gc_collection_deferred"
    assert policy._pressure_deferral.deferred_for_s(clock.now) == 0.0


def test_automatic_gen2_refreshes_cost_estimate(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rss = {"now": 1_000}
    blocks = {"value": 1_000_000}
    monkeypatch.setattr(gate_module, "latest_rss_bytes", lambda: rss["now"])
    monkeypatch.setattr(sweep_module, "latest_rss_bytes", lambda: rss["now"])
    policy = idle_policy(
        clock,
        collector,
        recorder,
        allocated_blocks_probe=lambda: blocks["value"],
    )
    assert policy.tick(clock.now) == "startup_freeze"
    # No full collection observed since startup: the estimate is unknown.
    policy._last_full_pause_s = None
    policy._cost_sample_mono = None
    rss["now"] = 1_000 + gc_policy.RSS_GROWTH_BACKSTOP_BYTES + 1
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) is None
    assert emitted[-1]["event"] == "tui_gc_collection_deferred"
    assert emitted[-1]["reason"] == "cost_unknown"
    assert emitted[-1]["trigger"] == "rss_backstop"

    # The telemetry recorder measures an automatic gen-2 the policy did not run.
    blocks["value"] = 1_400_000
    recorder.last_full = clock.now
    recorder.last_pause = 0.2
    clock.advance(1.0)
    assert policy.tick(clock.now) is None  # inside the duty floor
    assert policy._last_full_pause_s == pytest.approx(0.2)
    assert policy._cost_sample_mono == recorder.last_full
    assert policy._last_full_scan_blocks == 400_000

    clock.advance(gc_policy.MIN_FULL_INTERVAL_S)
    assert policy.tick(clock.now) == "rss_backstop"
    assert collector.collections == 1


def test_stale_cost_sample_still_prices_backstops(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    policy = idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    policy._own_last_full_mono = clock.now
    policy._cost_sample_mono = clock.now
    clock.advance(gc_policy.COST_SAMPLE_MAX_AGE_S + 1.0)
    assert policy._predicted_pause_s(clock.now, "idle") is None
    assert policy._predicted_pause_s(clock.now, "backstop") is not None

    # The stale sample still lets the due time backstop run on a short quiet.
    recorder.gen1 = 150
    assert policy.tick(clock.now) == "backstop"
    assert collector.collections == 1
    assert [row for row in emitted if row.get("reason") == "cost_unknown"] == []


__all__ = [
    "test_residual_swap_with_zero_faults_does_not_defer",
    "test_swap_growth_or_fault_rate_is_paging_pressure",
    "test_pressure_holds_backstop_for_a_bounded_window",
    "test_pressure_window_closes_when_paging_stops",
    "test_automatic_gen2_refreshes_cost_estimate",
    "test_stale_cost_sample_still_prices_backstops",
]
