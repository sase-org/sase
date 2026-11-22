"""Tests for the GC policy cost bound: time-priced estimates and capped deferral."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from sase.ace.tui.util import _gc_policy_sweep as sweep_module
from sase.ace.tui.util import gc_policy
from sase.ace.tui.util._gc_policy_pressure import CostDeferral
from sase.ace.tui.util.gc_policy import GCPolicy
from tests.ace.tui.util._gc_policy_test_support import (
    Clock,
    Collector,
    PricedCollector,
    Recorder,
    idle_policy,
)


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
def tags(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    @contextmanager
    def recording(name: str) -> Iterator[None]:
        seen.append(name)
        yield

    monkeypatch.setattr(sweep_module, "gc_trigger", recording)
    return seen


@pytest.fixture
def emitted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    monkeypatch.setattr(
        sweep_module,
        "queue_row",
        lambda event, row: rows.append({"event": event, **row}),
    )
    return rows


def unsampled_policy(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    blocks: dict[str, int],
    *,
    last_input: dict[str, float] | None = None,
) -> GCPolicy:
    """Policy with no cost sample, a controllable heap, and no pressure."""
    policy = GCPolicy(
        monotonic=clock,
        last_input_mono=(
            (lambda: last_input["t"])
            if last_input is not None
            else (lambda: clock.now - 10.0)
        ),
        prompt_active=lambda: False,
        navigating=lambda: False,
        modal_input_active=lambda: False,
        loads_done=lambda: True,
        collector=collector,
        recorder=recorder,
        trim_runner=lambda: None,
        allocated_blocks_probe=lambda: blocks["value"],
        memory_pressure_probe=lambda: {
            "vmswap_bytes": 0,
            "major_faults_per_s": 0.0,
            "sample_age_s": 0.0,
        },
    )
    policy.apply_thresholds()
    return policy


def deferred_by(rows: list[dict[str, Any]], reason: str) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row["event"] == "tui_gc_collection_deferred" and row["reason"] == reason
    ]


def test_first_sweep_seeds_cost_estimate(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    tags: list[str],
) -> None:
    """The first post-freeze sweep yields a rate sample over its accumulation."""
    blocks = {"value": 1_000_000}
    policy = unsampled_policy(clock, collector, recorder, blocks)
    assert policy.tick(clock.now) == "startup_freeze"
    assert policy._predicted_pause_s(clock.now) is None

    blocks["value"] += 50_000
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert collector.collections == 1
    assert tags == ["startup_freeze", "idle"]
    assert policy._cost_accum_s == pytest.approx(61.0)
    assert policy._cost_pause_s == pytest.approx(0.0)
    assert policy._predicted_pause_s(clock.now) is not None


def test_unknown_estimate_never_defers_even_on_a_huge_heap(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """Waiting only grows the heap, so an unknown estimate sweeps at once."""
    blocks = {"value": 1_000_000}
    policy = unsampled_policy(clock, collector, recorder, blocks)
    assert policy.tick(clock.now) == "startup_freeze"
    blocks["value"] = 50_000_000
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert collector.collections == 1
    assert deferred_by(emitted, "cost_unknown") == []
    assert deferred_by(emitted, "cost_gate") == []


def test_shrinking_heap_does_not_poison_the_estimate(
    clock: Clock,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """R3: old frozen caches freed while new garbage piles up.

    The net allocated total shrinks across a sweep that still scans ~8.5k
    blocks/s of young garbage. A block-delta estimator priced that 0.57 s
    sweep as one block; the time-priced estimate stays near the real pause.
    """
    live = 6_000_000
    state = {"young": 0}
    shrink = {"blocks": 0}
    collector = PricedCollector(clock, live=live, state=state)
    blocks = {"value": live}
    policy = unsampled_policy(clock, collector, recorder, blocks)
    assert policy.tick(clock.now) == "startup_freeze"

    pauses: list[float] = []
    for _ in range(4):
        state["young"] += 61 * 8_500
        shrink["blocks"] += 1_500_000
        blocks["value"] = live + state["young"] - shrink["blocks"]
        recorder.gen1 = 150
        clock.advance(61.0)
        assert policy.tick(clock.now) == "idle"
        assert policy._last_full_pause_s is not None
        pauses.append(policy._last_full_pause_s)
        blocks["value"] = live - shrink["blocks"]

    expected_pause = 61 * 8_500 * 1.1e-6
    assert pauses == pytest.approx([expected_pause] * 4)
    predicted = policy._predicted_pause_s(clock.now + 60.0)
    assert predicted is not None
    assert predicted == pytest.approx(
        expected_pause * 60.0 / 61.0 * gc_policy.COST_PREDICTION_SAFETY_FACTOR,
        rel=1e-3,
    )
    assert predicted < gc_policy.MAX_PREDICTED_FULL_PAUSE_S
    assert deferred_by(emitted, "cost_gate") == []


def test_skipped_collection_neither_freezes_nor_records(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """R3: ``gc.collect()`` returned in 19 us during another thread's sweep.

    Freezing then would move every young cycle into the permanent generation,
    and recording it would reset the duty floor and the estimate.
    """
    policy = idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    assert collector.freezes == 1
    pause_before = policy._last_full_pause_s
    sample_before = (policy._cost_pause_s, policy._cost_accum_s)
    young_since = policy._young_since_mono

    collector.busy = True
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 1
    assert collector.full_collections == 0
    assert collector.freezes == 1
    assert policy._own_last_full_mono is None
    assert policy._last_full_pause_s == pause_before
    assert (policy._cost_pause_s, policy._cost_accum_s) == sample_before
    assert policy._young_since_mono == young_since
    busy = deferred_by(emitted, "collector_busy")
    assert busy and busy[-1]["trigger"] == "idle"

    # The next tick retries and the proven collection freezes as usual.
    collector.busy = False
    clock.advance(1.0)
    assert policy.tick(clock.now) == "idle"
    assert collector.full_collections == 1
    assert collector.freezes == 2
    assert policy._own_last_full_mono == clock.now


def test_skipped_deep_collection_restores_the_frozen_set(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """A skipped unfreeze sweep re-freezes and stays due."""
    policy = idle_policy(clock, collector, recorder, last_input_ago=10.0)
    assert policy.tick(clock.now) == "startup_freeze"
    # Quiet time counts from the freeze: wait out the long-idle threshold.
    policy._last_input_mono = lambda: 0.0
    collector.busy = True
    recorder.gen1 = 150
    clock.advance(gc_policy.LONG_IDLE_QUIET_S + 1.0)
    assert policy.tick(clock.now) is None
    assert collector.unfreezes == 1
    assert collector.freezes == 2
    assert policy._last_deep_full_mono is None
    assert deferred_by(emitted, "collector_busy")

    collector.busy = False
    clock.advance(1.0)
    assert policy.tick(clock.now) == "idle"
    assert collector.unfreezes == 2
    assert collector.freezes == 3
    assert policy._last_deep_full_mono == clock.now


def test_cost_due_sweep_runs_before_the_duty_minimum(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
) -> None:
    """A sweep is due once its estimate reaches half the budget."""
    policy = idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    # 0.6 s per 30 s: the estimate reaches 1.0 s (half the budget) at 25 s.
    policy._last_full_pause_s = 0.6
    policy._cost_pause_s = 0.6
    policy._cost_accum_s = 30.0
    policy._own_last_full_mono = clock.now
    recorder.gen1 = 0

    clock.advance(20.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 0

    clock.advance(6.0)
    assert policy.duty_floor_s(cost_due=True) == pytest.approx(18.0)
    assert policy.tick(clock.now) == "idle"
    assert collector.collections == 1
    assert 26.0 < gc_policy.MIN_FULL_INTERVAL_S


def test_cost_gate_cap_follows_the_sampled_rate(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """An over-budget estimate defers only while it grows by 0.5 s."""
    prompt = {"active": False}
    policy = idle_policy(clock, collector, recorder)
    policy._prompt_active = lambda: prompt["active"]
    assert policy.tick(clock.now) == "startup_freeze"
    policy._cost_pause_s = 1.0
    policy._cost_accum_s = 100.0  # 0.01 s/s: cap = 0.5 s / 0.01 = 50 s

    # A long prompt holds every sweep; the estimate passes the budget.
    prompt["active"] = True
    recorder.gen1 = 150
    clock.advance(150.0)
    assert policy.tick(clock.now) is None
    prompt["active"] = False
    assert policy.tick(clock.now) is None
    assert collector.collections == 0
    gated = deferred_by(emitted, "cost_gate")
    assert gated
    assert gated[-1]["predicted_pause_s"] == pytest.approx(3.0)
    assert gated[-1]["cost_deferral_cap_s"] == pytest.approx(50.0)
    assert gated[-1]["cost_deferred_s"] == pytest.approx(0.0)
    assert policy._cost_deferral_cap_s() < gc_policy.COST_MAX_DEFERRAL_S

    clock.advance(49.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 0

    clock.advance(1.5)
    assert policy.tick(clock.now) == "idle"
    assert collector.collections == 1


def test_cost_deferral_bounds_window() -> None:
    """CostDeferral mirrors PressureDeferral with the ordinary quiet window."""
    window = CostDeferral()
    assert window.deferred_for_s(1000.0) == 0.0
    assert window.defers(trigger="idle", now_mono=1000.0, input_idle_s=10.0) is True
    assert window.deferred_for_s(1000.0) == 0.0
    just_inside = 1000.0 + gc_policy.COST_MAX_DEFERRAL_S - 1.0
    assert window.defers(trigger="idle", now_mono=just_inside, input_idle_s=10.0)
    past_cap = 1000.0 + gc_policy.COST_MAX_DEFERRAL_S + 1.0
    assert window.defers(trigger="idle", now_mono=past_cap, input_idle_s=1.0)
    assert not window.defers(trigger="idle", now_mono=past_cap, input_idle_s=3.0)
    assert window.defers(trigger="startup_freeze", now_mono=past_cap, input_idle_s=60.0)
    window.clear()
    assert window.deferred_for_s(past_cap) == 0.0

    # A rate-derived cap shortens the window; it never exceeds the maximum.
    short = CostDeferral()
    assert short.defers(trigger="idle", now_mono=0.0, input_idle_s=10.0, cap_s=30.0)
    assert short.defers(trigger="idle", now_mono=29.0, input_idle_s=10.0, cap_s=30.0)
    assert not short.defers(trigger="idle", now_mono=31.0, input_idle_s=3.0, cap_s=30.0)
    long = CostDeferral()
    assert long.defers(trigger="idle", now_mono=0.0, input_idle_s=10.0, cap_s=1e9)
    assert not long.defers(
        trigger="idle",
        now_mono=gc_policy.COST_MAX_DEFERRAL_S + 1.0,
        input_idle_s=3.0,
        cap_s=1e9,
    )


def test_bounded_deep_waits_for_hourly_cadence(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
) -> None:
    """Frozen garbage is reclaimed at most hourly on an ordinary quiet window."""
    blocks = {"value": 1_000_000}
    policy = idle_policy(
        clock,
        collector,
        recorder,
        allocated_blocks_probe=lambda: blocks["value"],
    )
    assert policy.tick(clock.now) == "startup_freeze"
    freeze_mono = clock.now
    for _ in range(3):
        recorder.gen1 = 150
        clock.advance(61.0)
        assert policy.tick(clock.now) == "idle"
    assert collector.unfreezes == 0

    # Fifty minutes after the freeze: ordinary sweeps only, no deep pass.
    clock.advance(50 * 60.0 - 3 * 61.0)
    recorder.gen1 = 150
    assert policy.tick(clock.now) == "backstop"
    assert collector.unfreezes == 0

    # Past the hourly cadence: the quiet sweep unfreezes and reclaims. A
    # stub with freeze_count 0 prices as one GC-tracked object and fits.
    clock.advance(11 * 60.0 + 1.0)
    assert clock.now - freeze_mono > gc_policy.DEEP_SWEEP_INTERVAL_S
    recorder.gen1 = 150
    assert policy.tick(clock.now) == "backstop"
    assert collector.unfreezes == 1
    assert collector.freezes == 6


def test_over_budget_deep_never_runs_or_holds_ordinary_sweeps(
    clock: Clock,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """A full-heap sweep over budget waits for long idle; ordinary ones go on."""
    live = 20_000_000
    state = {"young": 0}
    collector = PricedCollector(clock, live=live, state=state)
    collector.freeze_count = live
    blocks = {"value": live}
    last_input = {"t": clock.now - 10.0}
    policy = unsampled_policy(clock, collector, recorder, blocks, last_input=last_input)
    assert policy.tick(clock.now) == "startup_freeze"
    freeze_mono = clock.now

    ordinary = 0
    while clock.now - freeze_mono < gc_policy.DEEP_SWEEP_INTERVAL_S + 30 * 60.0:
        state["young"] += 61 * 3_000
        blocks["value"] = live + state["young"]
        recorder.gen1 = 150
        clock.advance(61.0)
        last_input["t"] = clock.now - 10.0
        assert policy.tick(clock.now) == "idle"
        ordinary += 1
    assert collector.unfreezes == 0
    assert ordinary == collector.full_collections
    deep_rows = deferred_by(emitted, "deep_cost_gate")
    assert deep_rows
    assert all(row.get("deep_due") for row in deep_rows)
    # 20M GC-tracked objects x 0.763 us/object x 2 ≈ 30.5 s, far over budget.
    assert deep_rows[-1]["predicted_pause_s"] == pytest.approx(
        gc_policy.DEEP_COST_PER_OBJECT_S
        * collector.freeze_count
        * gc_policy.COST_PREDICTION_SAFETY_FACTOR,
        rel=0.05,
    )
    assert deep_rows[-1]["gc_tracked_objects"] == collector.freeze_count
    assert max(collector.pauses) < gc_policy.MAX_PREDICTED_FULL_PAUSE_S
    assert deferred_by(emitted, "cost_gate") == []

    # Long idle keeps the unpriced deep pass, which samples its own rate.
    state["young"] += 50_000
    blocks["value"] = live + state["young"]
    last_input["t"] = clock.now - gc_policy.LONG_IDLE_QUIET_S - 1.0
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert collector.unfreezes == 1
    deep_pause = live * 0.15e-6 + 50_000 * 1.1e-6
    assert collector.pauses[-1] == pytest.approx(deep_pause)
    assert policy._deep_cost_per_object_s == pytest.approx(
        deep_pause / collector.freeze_count, rel=1e-3
    )


__all__ = [
    "test_first_sweep_seeds_cost_estimate",
    "test_unknown_estimate_never_defers_even_on_a_huge_heap",
    "test_shrinking_heap_does_not_poison_the_estimate",
    "test_skipped_collection_neither_freezes_nor_records",
    "test_skipped_deep_collection_restores_the_frozen_set",
    "test_cost_due_sweep_runs_before_the_duty_minimum",
    "test_cost_gate_cap_follows_the_sampled_rate",
    "test_cost_deferral_bounds_window",
    "test_bounded_deep_waits_for_hourly_cadence",
    "test_over_budget_deep_never_runs_or_holds_ordinary_sweeps",
]
