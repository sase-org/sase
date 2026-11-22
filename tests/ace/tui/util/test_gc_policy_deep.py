"""Fake-clock tests for frozen-plus-young deep-sweep pricing."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

from sase.ace.tui.util import _gc_policy_sweep as sweep_module
from sase.ace.tui.util import gc_policy
from tests.ace.tui.util._gc_policy_test_support import (
    Clock,
    PricedCollector,
    Recorder,
)
from tests.ace.tui.util.test_gc_policy_cost import deferred_by, unsampled_policy

# Attribute-phase production heap (attribute-20261122T165600Z): ~8.5M
# allocated blocks and ~1.8M frozen containers at 0.763 us/frozen-container.
_PRODUCTION_BLOCKS = 8_500_000
_PRODUCTION_FROZEN = 1_800_000
# Frozen-set size that fits the 2 s budget on its frozen part alone with the
# safety factor: 0.763 us x 500k x 2 = 0.763 s. Unfrozen work is priced on top.
_FITTING_FROZEN = 500_000


@pytest.fixture
def clock() -> Clock:
    return Clock()


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


def _advance_past_hourly(
    clock: Clock,
    collector: PricedCollector,
    recorder: Recorder,
    policy: gc_policy.GCPolicy,
    last_input: dict[str, float],
    blocks: dict[str, int],
    *,
    state: dict[str, int],
    young_per_tick: int = 61 * 3_000,
) -> None:
    freeze_mono = clock.now
    while clock.now - freeze_mono < gc_policy.DEEP_SWEEP_INTERVAL_S + 60.0:
        state["young"] += young_per_tick
        blocks["value"] = _PRODUCTION_BLOCKS + state["young"]
        recorder.gen1 = 150
        clock.advance(61.0)
        last_input["t"] = clock.now - 10.0
        assert policy.tick(clock.now) == "idle"
    assert collector.unfreezes == 0


def test_production_heap_hourly_deep_is_gated_at_measured_rate(
    clock: Clock,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """1.8M frozen alone predicts ~2.75 s; plus unfrozen it stays gated."""
    state = {"young": 0}
    collector = PricedCollector(clock, live=_PRODUCTION_FROZEN, state=state)
    collector.freeze_count = _PRODUCTION_FROZEN
    blocks = {"value": _PRODUCTION_BLOCKS}
    last_input = {"t": clock.now - 10.0}
    policy = unsampled_policy(clock, collector, recorder, blocks, last_input=last_input)
    assert policy.tick(clock.now) == "startup_freeze"
    _advance_past_hourly(
        clock, collector, recorder, policy, last_input, blocks, state=state
    )

    frozen_part = (
        gc_policy.DEEP_COST_PER_FROZEN_S
        * _PRODUCTION_FROZEN
        * gc_policy.COST_PREDICTION_SAFETY_FACTOR
    )
    assert frozen_part > gc_policy.MAX_PREDICTED_FULL_PAUSE_S
    deep_rows = deferred_by(emitted, "deep_cost_gate")
    assert deep_rows
    assert all(row.get("deep_due") for row in deep_rows)
    last = deep_rows[-1]
    # New telemetry exposes the split; the retired counters sum is gone.
    assert last["frozen_count"] == _PRODUCTION_FROZEN
    assert "gc_tracked_objects" not in last
    assert last["frozen_cost_s"] == pytest.approx(frozen_part)
    assert last["unfrozen_cost_s"] is not None
    assert last["predicted_pause_s"] == pytest.approx(
        last["frozen_cost_s"] + last["unfrozen_cost_s"]
    )
    assert last["predicted_pause_s"] > gc_policy.MAX_PREDICTED_FULL_PAUSE_S
    # Ordinary sweeps kept running while the hourly deep stayed gated.
    assert collector.unfreezes == 0
    assert max(collector.pauses) < gc_policy.MAX_PREDICTED_FULL_PAUSE_S

    state["young"] += 50_000
    last_input["t"] = clock.now - gc_policy.LONG_IDLE_QUIET_S - 1.0
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert collector.unfreezes == 1
    assert policy._deep_cost_per_frozen_s is not None
    assert policy._deep_cost_per_frozen_s == pytest.approx(
        collector.pauses[-1] / _PRODUCTION_FROZEN, rel=1e-3
    )


def test_hourly_deep_runs_when_combined_estimate_fits_budget(
    clock: Clock,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """500k frozen plus ordinary unfrozen work fits and runs."""
    state = {"young": 0}
    collector = PricedCollector(clock, live=_FITTING_FROZEN, state=state)
    collector.freeze_count = _FITTING_FROZEN
    blocks = {"value": _PRODUCTION_BLOCKS}
    last_input = {"t": clock.now - 10.0}
    policy = unsampled_policy(clock, collector, recorder, blocks, last_input=last_input)
    assert policy.tick(clock.now) == "startup_freeze"
    freeze_mono = clock.now
    while clock.now - freeze_mono < gc_policy.DEEP_SWEEP_INTERVAL_S + 60.0:
        state["young"] += 61 * 3_000
        blocks["value"] = _PRODUCTION_BLOCKS + state["young"]
        recorder.gen1 = 150
        clock.advance(61.0)
        last_input["t"] = clock.now - 10.0
        result = policy.tick(clock.now)
        assert result == "idle"
        if collector.unfreezes:
            break
    assert collector.unfreezes == 1
    assert deferred_by(emitted, "deep_cost_gate") == []
    total, frozen_n, frozen_cost, unfrozen_cost = policy._deep_cost_breakdown(clock.now)
    # Breakdown after the verified deep sweep reflects the refreshed rate;
    # the pre-sweep admission already proved a fitting total ran.
    assert frozen_n == _FITTING_FROZEN
    assert policy._deep_cost_per_frozen_s is not None
    assert max(collector.pauses) < gc_policy.MAX_PREDICTED_FULL_PAUSE_S


def test_small_counters_do_not_erase_unfrozen_estimate(
    clock: Clock,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """Reset generation counters never shrink the deep price.

    A fitting 500k frozen set plus heavy unfrozen accumulation must stay
    gated even when ``get_count()`` reports near-zero counters after young
    collections promoted the survivors.
    """
    frozen = _FITTING_FROZEN
    state = {"young": 0}
    collector = PricedCollector(clock, live=frozen, state=state)
    collector.freeze_count = frozen
    # Simulated post-promotion counters: young collections reset them while
    # the promoted objects remain for a full sweep.
    collector.counts = [0, 0, 5]
    blocks = {"value": _PRODUCTION_BLOCKS}
    last_input = {"t": clock.now - 10.0}
    policy = unsampled_policy(clock, collector, recorder, blocks, last_input=last_input)
    assert policy.tick(clock.now) == "startup_freeze"
    # Heavy young churn: ~610k blocks/tick prices ~0.67 s pauses, so the
    # unfrozen estimate (~1.34 s) plus the fitting frozen part (~0.76 s)
    # pushes the deep total over budget while ordinary sweeps stay under it.
    _advance_past_hourly(
        clock,
        collector,
        recorder,
        policy,
        last_input,
        blocks,
        state=state,
        young_per_tick=61 * 10_000,
    )

    frozen_part = (
        gc_policy.DEEP_COST_PER_FROZEN_S
        * frozen
        * gc_policy.COST_PREDICTION_SAFETY_FACTOR
    )
    assert frozen_part < gc_policy.MAX_PREDICTED_FULL_PAUSE_S
    deep_rows = deferred_by(emitted, "deep_cost_gate")
    assert deep_rows
    last = deep_rows[-1]
    assert last["frozen_count"] == frozen
    assert last["unfrozen_cost_s"] is not None
    assert last["predicted_pause_s"] == pytest.approx(
        last["frozen_cost_s"] + last["unfrozen_cost_s"]
    )
    assert last["predicted_pause_s"] > gc_policy.MAX_PREDICTED_FULL_PAUSE_S
    # The old freeze-plus-counters sum would have admitted this sweep.
    old_tracked = frozen + sum(collector.counts)
    old_predicted = (
        gc_policy.DEEP_COST_PER_FROZEN_S
        * old_tracked
        * gc_policy.COST_PREDICTION_SAFETY_FACTOR
    )
    assert old_predicted < gc_policy.MAX_PREDICTED_FULL_PAUSE_S
    assert collector.unfreezes == 0


def test_counters_are_collections_not_populations_subprocess() -> None:
    """Isolated CPython shows young counters reset while objects survive.

    Runs in a fresh interpreter so pytest's own collector cannot pollute the
    measurement and Bryan's interactive TUI is untouched.
    """
    code = (
        "import gc;"
        "gc.collect();gc.freeze();"
        "leak=[ [i] for i in range(20000) ];"
        "gc.collect(1);"
        "counts=gc.get_count();freeze=gc.get_freeze_count();"
        "total=len(gc.get_objects());"
        "print(f'{counts[0]},{counts[1]},{counts[2]},{freeze},{total}')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    c0, c1, c2, freeze, total = (int(x) for x in proc.stdout.strip().split(","))
    # Young counters are small collection counts after collect(1); the total
    # tracked population (including the 20k retained lists) is far larger.
    assert c0 + c1 + c2 < total // 2
    assert total >= 20000
    assert freeze >= 0


def test_unknown_ordinary_estimate_gates_only_deep() -> None:
    """No post-freeze sample: deep is unpriceable, ordinary still seeds."""
    from tests.ace.tui.util._gc_policy_test_support import Collector

    c = Clock()
    col = Collector()
    col.freeze_count = _FITTING_FROZEN
    rec = Recorder()
    blocks = {"value": _PRODUCTION_BLOCKS}
    pol = unsampled_policy(c, col, rec, blocks, last_input={"t": c.now - 10.0})
    assert pol.tick(c.now) == "startup_freeze"
    # Deep without an ordinary sample cannot price the young half.
    assert pol._predicted_pause_s(c.now, deep=True) is None
    total, frozen_n, frozen_cost, unfrozen_cost = pol._deep_cost_breakdown(c.now)
    assert total is None
    assert frozen_n == _FITTING_FROZEN
    assert unfrozen_cost is None
    # The ordinary sweep still runs immediately and seeds the sample.
    rec.gen1 = 150
    c.advance(61.0)
    assert pol.tick(c.now) == "idle"
    assert col.full_collections == 1
    assert pol._predicted_pause_s(c.now, deep=True) is not None


def test_missing_frozen_probe_gates_only_deep() -> None:
    """A collector without get_freeze_count never admits the bounded deep pass."""

    class NoFreeze:
        def __init__(self, base: PricedCollector) -> None:
            self._base = base

        def __getattr__(self, name: str) -> Any:
            if name == "get_freeze_count":
                raise AttributeError(name)
            return getattr(self._base, name)

    state = {"young": 0}
    clock = Clock()
    base = PricedCollector(clock, live=_FITTING_FROZEN, state=state)
    base.freeze_count = _FITTING_FROZEN
    collector: Any = NoFreeze(base)
    recorder = Recorder()
    blocks = {"value": _PRODUCTION_BLOCKS}
    last_input = {"t": clock.now - 10.0}
    policy = unsampled_policy(clock, collector, recorder, blocks, last_input=last_input)
    # Threshold probing goes through getattr, so the missing probe leaves
    # thresholds alone without raising.
    assert policy.tick(clock.now) == "startup_freeze"
    assert policy._read_gc_frozen_count() is None
    assert policy._predicted_pause_s(clock.now, deep=True) is None
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert base.full_collections == 1


def test_skipped_and_census_deep_do_not_refresh_frozen_rate(
    clock: Clock,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """Busy and census deep sweeps leave the frozen coefficient alone."""
    state = {"young": 0}
    collector = PricedCollector(clock, live=_FITTING_FROZEN, state=state)
    collector.freeze_count = _FITTING_FROZEN
    blocks = {"value": _PRODUCTION_BLOCKS}
    last_input = {"t": clock.now - 10.0}
    policy = unsampled_policy(clock, collector, recorder, blocks, last_input=last_input)
    assert policy.tick(clock.now) == "startup_freeze"
    seed = policy._deep_cost_per_frozen_s
    # A skipped deep sweep (collector busy on the long-idle trigger) never
    # records a sample.
    policy._last_input_mono = lambda: 0.0
    collector.busy = True
    recorder.gen1 = 150
    clock.advance(gc_policy.LONG_IDLE_QUIET_S + 1.0)
    assert policy.tick(clock.now) is None
    assert collector.unfreezes == 1
    assert policy._deep_cost_per_frozen_s == seed
    collector.busy = False
    # Zero frozen count cannot poison the rate via division by zero.
    policy._record_cost_sample(
        0.5,
        start_mono=clock.now - 1.0,
        end_mono=clock.now,
        deep=True,
        census=False,
        frozen_before=0,
    )
    assert policy._deep_cost_per_frozen_s == seed
    # Non-finite pauses never refresh either component.
    policy._record_cost_sample(
        float("inf"),
        start_mono=clock.now - 1.0,
        end_mono=clock.now,
        deep=True,
        census=False,
        frozen_before=_FITTING_FROZEN,
    )
    assert policy._deep_cost_per_frozen_s == seed


def test_deep_pricing_never_walks_the_heap(
    clock: Clock,
    recorder: Recorder,
) -> None:
    """The runtime pricing path must not enumerate ``gc.get_objects()``."""
    state = {"young": 0}
    collector = PricedCollector(clock, live=_FITTING_FROZEN, state=state)
    collector.freeze_count = _FITTING_FROZEN
    blocks = {"value": _PRODUCTION_BLOCKS}
    last_input = {"t": clock.now - 10.0}
    policy = unsampled_policy(clock, collector, recorder, blocks, last_input=last_input)
    assert policy.tick(clock.now) == "startup_freeze"
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    calls_before = collector.get_objects_calls
    assert policy._predicted_pause_s(clock.now, deep=True) is not None
    policy._deep_cost_breakdown(clock.now)
    policy._read_gc_frozen_count()
    assert collector.get_objects_calls == calls_before


__all__ = [
    "test_production_heap_hourly_deep_is_gated_at_measured_rate",
    "test_hourly_deep_runs_when_combined_estimate_fits_budget",
    "test_small_counters_do_not_erase_unfrozen_estimate",
    "test_counters_are_collections_not_populations_subprocess",
    "test_unknown_ordinary_estimate_gates_only_deep",
    "test_missing_frozen_probe_gates_only_deep",
    "test_skipped_and_census_deep_do_not_refresh_frozen_rate",
    "test_deep_pricing_never_walks_the_heap",
]
