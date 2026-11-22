"""Fake-clock tests for GC-tracked-object deep-sweep pricing."""

from __future__ import annotations

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
# allocated blocks and ~1.8M frozen containers at 0.763 us/object.
_PRODUCTION_BLOCKS = 8_500_000
_PRODUCTION_FROZEN = 1_800_000
# Frozen-set size that fits the 2 s budget at the measured rate with the
# safety factor: 0.763 us × 500k × 2 = 0.763 s. The same 8.5M allocated
# blocks at the old 0.3 us/block default predicted ~5.1 s and gated.
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
) -> None:
    freeze_mono = clock.now
    while clock.now - freeze_mono < gc_policy.DEEP_SWEEP_INTERVAL_S + 60.0:
        state["young"] += 61 * 3_000
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
    """1.8M frozen × 0.763 us × 2 ≈ 2.75 s: hourly cadence stays gated."""
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

    predicted = (
        gc_policy.DEEP_COST_PER_OBJECT_S
        * _PRODUCTION_FROZEN
        * gc_policy.COST_PREDICTION_SAFETY_FACTOR
    )
    assert predicted > gc_policy.MAX_PREDICTED_FULL_PAUSE_S
    deep_rows = deferred_by(emitted, "deep_cost_gate")
    assert deep_rows
    assert all(row.get("deep_due") for row in deep_rows)
    assert deep_rows[-1]["predicted_pause_s"] == pytest.approx(predicted)
    assert deep_rows[-1]["gc_tracked_objects"] == _PRODUCTION_FROZEN
    # Old allocated-block formula would have predicted ~5.1 s; object pricing
    # is the value on the row.
    block_price = 0.3e-6 * blocks["value"] * gc_policy.COST_PREDICTION_SAFETY_FACTOR
    assert deep_rows[-1]["predicted_pause_s"] < block_price
    assert collector.unfreezes == 0
    assert max(collector.pauses) < gc_policy.MAX_PREDICTED_FULL_PAUSE_S

    state["young"] += 50_000
    last_input["t"] = clock.now - gc_policy.LONG_IDLE_QUIET_S - 1.0
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert collector.unfreezes == 1
    assert policy._deep_cost_per_object_s is not None
    assert policy._deep_cost_per_object_s == pytest.approx(
        collector.pauses[-1] / _PRODUCTION_FROZEN, rel=1e-3
    )


def test_hourly_deep_runs_when_gc_tracked_objects_fit_budget(
    clock: Clock,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """8.5M allocated blocks would gate; 500k frozen objects fit and run."""
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
    predicted = (
        gc_policy.DEEP_COST_PER_OBJECT_S
        * _FITTING_FROZEN
        * gc_policy.COST_PREDICTION_SAFETY_FACTOR
    )
    assert predicted < gc_policy.MAX_PREDICTED_FULL_PAUSE_S
    assert policy._deep_cost_per_object_s is not None
    assert max(collector.pauses) < gc_policy.MAX_PREDICTED_FULL_PAUSE_S


def test_young_generation_counts_join_freeze_count_in_the_price(
    clock: Clock,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """Young-gen objects on top of a fitting frozen set push the estimate over."""
    frozen = _FITTING_FROZEN
    young = 1_000_000
    state = {"young": 0}
    collector = PricedCollector(clock, live=frozen, state=state)
    collector.freeze_count = frozen
    collector.counts = [young, 0, 0]
    blocks = {"value": _PRODUCTION_BLOCKS}
    last_input = {"t": clock.now - 10.0}
    policy = unsampled_policy(clock, collector, recorder, blocks, last_input=last_input)
    assert policy.tick(clock.now) == "startup_freeze"
    _advance_past_hourly(
        clock, collector, recorder, policy, last_input, blocks, state=state
    )

    tracked = frozen + young
    predicted = (
        gc_policy.DEEP_COST_PER_OBJECT_S
        * tracked
        * gc_policy.COST_PREDICTION_SAFETY_FACTOR
    )
    assert predicted > gc_policy.MAX_PREDICTED_FULL_PAUSE_S
    deep_rows = deferred_by(emitted, "deep_cost_gate")
    assert deep_rows
    assert deep_rows[-1]["predicted_pause_s"] == pytest.approx(predicted)
    assert deep_rows[-1]["gc_tracked_objects"] == tracked
    assert collector.unfreezes == 0


__all__ = [
    "test_production_heap_hourly_deep_is_gated_at_measured_rate",
    "test_hourly_deep_runs_when_gc_tracked_objects_fit_budget",
    "test_young_generation_counts_join_freeze_count_in_the_price",
]
