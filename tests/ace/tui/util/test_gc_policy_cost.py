"""Tests for the GC policy cost bound: seeded estimates and capped deferral."""

from __future__ import annotations

import itertools
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
) -> GCPolicy:
    """Policy with no cost sample, a controllable heap, and no pressure."""
    return GCPolicy(
        monotonic=clock,
        last_input_mono=lambda: clock.now - 10.0,
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
    """One cheap early sweep seeds the estimate instead of waiting for idle."""
    blocks = {"value": 1_000_000}
    policy = unsampled_policy(clock, collector, recorder, blocks)
    policy.apply_thresholds()
    assert policy.tick(clock.now) == "startup_freeze"
    assert policy._predicted_pause_s(clock.now) is None

    blocks["value"] += 50_000
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert collector.collections == 1
    assert tags == ["startup_freeze", "idle"]
    assert policy._cost_sample_mono is not None
    assert policy._last_full_pause_s is not None
    assert policy._predicted_pause_s(clock.now) is not None


def test_seed_needs_heap_growth(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """With no new garbage there is nothing to sample, so the gate still holds."""
    blocks = {"value": 1_000_000}
    policy = unsampled_policy(clock, collector, recorder, blocks)
    policy.apply_thresholds()
    assert policy.tick(clock.now) == "startup_freeze"
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 0
    assert deferred_by(emitted, "cost_unknown")


def test_cost_unknown_cap_forces_sweep_on_quiet_window(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """An unknown estimate holds sweeps for at most COST_MAX_DEFERRAL_S."""
    blocks = {"value": 1_000_000}
    policy = unsampled_policy(clock, collector, recorder, blocks)
    policy.apply_thresholds()
    assert policy.tick(clock.now) == "startup_freeze"
    # Far past the seed budget: the first sweep cannot seed the estimate.
    blocks["value"] = 50_000_000
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 0
    unknown = deferred_by(emitted, "cost_unknown")
    assert unknown and unknown[-1]["cost_deferred_s"] == pytest.approx(0.0)

    # The cap passes while the user is active: still deferred, no quiet window.
    clock.advance(gc_policy.COST_MAX_DEFERRAL_S + 1.0)
    policy._last_input_mono = lambda: clock.now - 1.0
    assert policy.tick(clock.now) is None
    assert collector.collections == 0

    # The next ordinary quiet window runs the sweep despite the unknown cost.
    policy._last_input_mono = lambda: clock.now - 3.0
    assert policy.tick(clock.now) == "idle"
    assert collector.collections == 1

    ages = [row["cost_deferred_s"] for row in deferred_by(emitted, "cost_unknown")]
    assert ages
    assert max(ages) < gc_policy.COST_MAX_DEFERRAL_S + 60.0


def test_cost_gate_cap_forces_over_budget_sweep(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """An over-budget prediction holds sweeps for at most COST_MAX_DEFERRAL_S."""
    blocks = {"value": 1_000_000}
    policy = idle_policy(
        clock,
        collector,
        recorder,
        allocated_blocks_probe=lambda: blocks["value"],
    )
    assert policy.tick(clock.now) == "startup_freeze"
    # 0.25 s x 40M new blocks / 1k scanned x 2: far over the 2 s budget.
    blocks["value"] += 40_000_000
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 0
    gated = deferred_by(emitted, "cost_gate")
    assert gated
    assert gated[-1]["predicted_pause_s"] == pytest.approx(20_000.0)
    assert gated[-1]["cost_deferred_s"] == pytest.approx(0.0)

    clock.advance(gc_policy.COST_MAX_DEFERRAL_S)
    assert policy.tick(clock.now) == "idle"
    assert collector.collections == 1

    ages = [row["cost_deferred_s"] for row in deferred_by(emitted, "cost_gate")]
    assert ages
    assert max(ages) < gc_policy.COST_MAX_DEFERRAL_S + 60.0


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

    # Past the hourly cadence: the quiet sweep unfreezes and reclaims.
    clock.advance(11 * 60.0 + 1.0)
    assert clock.now - freeze_mono > gc_policy.DEEP_SWEEP_INTERVAL_S
    recorder.gen1 = 150
    assert policy.tick(clock.now) == "backstop"
    assert collector.unfreezes == 1
    assert collector.freezes == 6


class PricedCollector(Collector):
    """Stub collector whose ``collect()`` models pause from scanned blocks.

    Ordinary sweeps scan only the garbage accumulated since the last sweep
    (frozen survivors are skipped); a deep sweep scans the whole heap. The
    modeled per-block rate matches the baseline calibration (~0.15 us/block
    without tracemalloc). ``state["garbage"]`` is the heap growth the
    allocated-blocks probe reports.
    """

    def __init__(self, clock: Clock, live: int, state: dict[str, int]) -> None:
        super().__init__()
        self._clock = clock
        self._live = live
        self._state = state
        self._deep_next = False

    def unfreeze(self) -> None:
        super().unfreeze()
        self._deep_next = True

    def collect(self) -> int:
        self.collections += 1
        scan = (
            self._live + self._state["garbage"]
            if self._deep_next
            else self._state["garbage"]
        )
        self._clock.advance(max(scan, 1) * 0.15e-6)
        self._state["garbage"] = 0
        self._deep_next = False
        return 0


def test_bounded_deep_priced_and_cap_forced(
    clock: Clock,
    recorder: Recorder,
    emitted: list[dict[str, Any]],
) -> None:
    """An over-budget deep sweep defers with its own window, then runs capped."""
    live = 2_000_000
    state = {"garbage": 0}
    collector = PricedCollector(clock, live, state)
    policy = GCPolicy(
        monotonic=clock,
        last_input_mono=lambda: clock.now - 10.0,
        prompt_active=lambda: False,
        navigating=lambda: False,
        modal_input_active=lambda: False,
        loads_done=lambda: True,
        collector=collector,
        recorder=recorder,
        trim_runner=lambda: None,
        allocated_blocks_probe=lambda: live + state["garbage"],
        memory_pressure_probe=lambda: {
            "vmswap_bytes": 0,
            "major_faults_per_s": 0.0,
            "sample_age_s": 0.0,
        },
    )
    policy.apply_thresholds()
    assert policy.tick(clock.now) == "startup_freeze"
    freeze_mono = clock.now

    # Two ordinary sweeps establish a real cost sample (~0.035 s each).
    for _ in range(2):
        state["garbage"] += 61 * 3_800
        recorder.gen1 = 150
        clock.advance(61.0)
        assert policy.tick(clock.now) == "idle"
    assert collector.unfreezes == 0
    assert policy._last_full_pause_s == pytest.approx(231_800 * 0.15e-6)

    # The heap explodes just as the hourly deep sweep comes due: the deep
    # estimate prices the whole heap far over budget, so it defers with its
    # own window while ordinary sweeps could still run.
    clock.advance(freeze_mono + gc_policy.DEEP_SWEEP_INTERVAL_S + 1.0 - clock.now)
    state["garbage"] += 40_000_000
    recorder.gen1 = 150
    assert policy.tick(clock.now) is None
    assert collector.collections == 2
    assert collector.unfreezes == 0
    deep_rows = [
        row for row in deferred_by(emitted, "cost_gate") if row.get("deep_due")
    ]
    assert deep_rows
    assert deep_rows[-1]["predicted_pause_s"] > gc_policy.MAX_PREDICTED_FULL_PAUSE_S

    # Ordinary sweeps do not reset the deep window: past its cap the deep
    # sweep runs on the next quiet window.
    clock.advance(gc_policy.COST_MAX_DEFERRAL_S + 1.0)
    recorder.gen1 = 150
    assert policy.tick(clock.now) == "backstop"
    assert collector.unfreezes == 1
    assert collector.collections == 3


def test_active_user_two_hours_sweeps_at_bounded_intervals(
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate an active user (input every 30-150 s) for 2 h of steady growth.

    Baseline shape: ~3,800 blocks/s of cyclic garbage on a ~2M-block live
    heap. The policy must sweep at bounded intervals, never leave a
    cost_unknown deferral past its cap, and never predict (or take) a pause
    over budget after the first sample.
    """
    live = 2_000_000
    growth_per_s = 3_800
    state = {"garbage": 0}
    collector = PricedCollector(clock, live, state)
    recorder = Recorder()
    last_input = {"t": clock.now - 10.0}
    gaps = itertools.cycle([30.0, 60.0, 90.0, 120.0, 150.0])
    gap = {"s": next(gaps)}
    policy = GCPolicy(
        monotonic=clock,
        last_input_mono=lambda: last_input["t"],
        prompt_active=lambda: False,
        navigating=lambda: False,
        modal_input_active=lambda: False,
        loads_done=lambda: True,
        collector=collector,
        recorder=recorder,
        trim_runner=lambda: None,
        allocated_blocks_probe=lambda: live + state["garbage"],
        memory_pressure_probe=lambda: {
            "vmswap_bytes": 0,
            "major_faults_per_s": 0.0,
            "sample_age_s": 0.0,
        },
    )
    policy.apply_thresholds()
    rows: list[dict[str, Any]] = []
    monkeypatch.setattr(
        sweep_module,
        "queue_row",
        lambda event, row: rows.append({"event": event, **row}),
    )
    seen: list[str] = []

    @contextmanager
    def recording(name: str) -> Iterator[None]:
        seen.append(name)
        yield

    monkeypatch.setattr(sweep_module, "gc_trigger", recording)

    predictions: list[tuple[float, float | None]] = []
    original_predict = policy._predicted_pause_s

    def recording_predict(
        now_mono: float, trigger: str = "idle", deep: bool = False
    ) -> float | None:
        predicted = original_predict(now_mono, trigger, deep=deep)
        predictions.append((now_mono, predicted))
        return predicted

    policy._predicted_pause_s = recording_predict  # type: ignore[method-assign]

    assert policy.tick(clock.now) == "startup_freeze"
    freeze_mono = clock.now

    sweeps: list[tuple[float, str, float]] = []
    for _ in range(2 * 60 * 60):
        clock.advance(1.0)
        state["garbage"] += growth_per_s
        recorder.gen1 += 2
        if clock.now - last_input["t"] >= gap["s"]:
            last_input["t"] = clock.now
            gap["s"] = next(gaps)
        result = policy.tick(clock.now)
        if result is not None and result != "startup_freeze":
            recorder.gen1 = 0
            assert policy._last_full_pause_s is not None
            sweeps.append((clock.now, result, float(policy._last_full_pause_s)))

    assert len(sweeps) >= 40
    first_at = sweeps[0][0]
    assert first_at - freeze_mono < 12 * 60.0
    gaps_between = [
        later - earlier
        for (earlier, _, _), (later, _, _) in zip(sweeps, sweeps[1:], strict=False)
    ]
    assert max(gaps_between) < 15 * 60.0
    for _, tag, pause in sweeps[1:]:
        assert pause <= gc_policy.MAX_PREDICTED_FULL_PAUSE_S
        assert tag == "idle"
    sampled_from = first_at
    for at, predicted in predictions:
        if at > sampled_from and predicted is not None:
            assert predicted <= gc_policy.MAX_PREDICTED_FULL_PAUSE_S
    unknown_ages = [row["cost_deferred_s"] for row in deferred_by(rows, "cost_unknown")]
    assert all(age < gc_policy.COST_MAX_DEFERRAL_S + 60.0 for age in unknown_ages)
    # The hourly deep cadence fired on a quiet window within the 2 h run.
    assert collector.unfreezes >= 1


__all__ = [
    "test_first_sweep_seeds_cost_estimate",
    "test_seed_needs_heap_growth",
    "test_cost_unknown_cap_forces_sweep_on_quiet_window",
    "test_cost_gate_cap_forces_over_budget_sweep",
    "test_cost_deferral_bounds_window",
    "test_bounded_deep_waits_for_hourly_cadence",
    "test_bounded_deep_priced_and_cap_forced",
    "test_active_user_two_hours_sweeps_at_bounded_intervals",
]
