"""Fake-clock active-user simulation of the GC policy's bounded sweeps."""

from __future__ import annotations

import random
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from sase.ace.tui.util import _gc_policy_sweep as sweep_module
from sase.ace.tui.util import gc_policy
from sase.ace.tui.util.gc_policy import GCPolicy
from tests.ace.tui.util._gc_policy_test_support import (
    Clock,
    PricedCollector,
    Recorder,
)

# R3 spot-check shape (sase a52054ed45, 55 min, j/k every 30-150 s): ~8.5k
# blocks/s of young garbage and survivors at ~1.1 us/block, so ~0.0094 s of
# pause per second of accumulation, on a frozen heap.
_LIVE_BLOCKS = 2_000_000
_YOUNG_BLOCKS_PER_S = 8_500
_SIM_SECONDS = 2 * 60 * 60
# Old frozen caches freed by refcount drop the net total by this much every
# other five minutes, while young garbage keeps piling up.
_SHRINK_BLOCKS = 1_500_000
# Every fifth ``gc.collect()`` lands inside another thread's collection.
_BUSY_EVERY = 5


def test_active_user_two_hours_keeps_every_pause_within_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two hours of active input: bounded cadence, every pause within budget.

    The two hazards R3 hit are injected: a shrinking net allocated-block
    total and no-op collections. Sweeps must run at bounded intervals, no
    pause or post-sample prediction may exceed the budget, no sweep may be
    cost-deferred, a skipped collection must never freeze, and the hourly
    deep sweep must fire on a quiet window.
    """
    clock = Clock()
    state = {"young": 0}
    collector = PricedCollector(
        clock, live=_LIVE_BLOCKS, state=state, busy_every=_BUSY_EVERY
    )
    recorder = Recorder()
    rng = random.Random(9271)
    last_input = {"t": clock.now - 10.0}
    gap = {"s": rng.uniform(30.0, 150.0)}

    def allocated_blocks() -> int:
        shrink = _SHRINK_BLOCKS if int(clock.now // 300) % 2 else 0
        return _LIVE_BLOCKS + state["young"] - shrink

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
        allocated_blocks_probe=allocated_blocks,
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

    @contextmanager
    def recording(_name: str) -> Iterator[None]:
        yield

    monkeypatch.setattr(sweep_module, "gc_trigger", recording)

    predictions: list[tuple[float, float | None]] = []
    original_predict = policy._predicted_pause_s

    def recording_predict(now_mono: float, *, deep: bool = False) -> float | None:
        predicted = original_predict(now_mono, deep=deep)
        if not deep:
            predictions.append((now_mono, predicted))
        return predicted

    policy._predicted_pause_s = recording_predict  # type: ignore[method-assign]

    assert policy.tick(clock.now) == "startup_freeze"
    freeze_mono = clock.now

    sweeps: list[tuple[float, str]] = []
    for _ in range(_SIM_SECONDS):
        clock.advance(1.0)
        state["young"] += _YOUNG_BLOCKS_PER_S
        recorder.gen1 += 2
        if clock.now - last_input["t"] >= gap["s"]:
            last_input["t"] = clock.now
            gap["s"] = rng.uniform(30.0, 150.0)
        freezes_before = collector.freezes
        full_before = collector.full_collections
        result = policy.tick(clock.now)
        if collector.full_collections == full_before:
            # A skipped or absent collection never freezes young garbage,
            # except a skipped deep sweep restoring its unfrozen heap.
            assert collector.freezes - freezes_before <= (collector.busy_unfrozen and 1)
        if result is not None and result != "startup_freeze":
            recorder.gen1 = 0
            sweeps.append((clock.now, result))

    assert collector.skipped >= 10
    assert [row for row in rows if row["reason"] == "collector_busy"]
    assert collector.freezes == (
        1 + collector.full_collections + collector.busy_unfrozen
    )

    assert sweeps[0][0] - freeze_mono < 3 * 60.0
    assert len(sweeps) >= 100
    gaps = [
        later - earlier
        for (earlier, _), (later, _) in zip(sweeps, sweeps[1:], strict=False)
    ]
    assert max(gaps) <= 2 * 60.0
    assert {tag for _, tag in sweeps} == {"idle"}

    budget = gc_policy.MAX_PREDICTED_FULL_PAUSE_S
    assert max(collector.pauses) <= budget / 2
    assert sum(collector.pauses) / _SIM_SECONDS < 0.03
    first_sample = sweeps[0][0]
    for at, predicted in predictions:
        if at > first_sample and predicted is not None:
            assert predicted <= budget
    reasons = {row["reason"] for row in rows}
    assert "cost_gate" not in reasons
    assert "cost_unknown" not in reasons

    # The hourly deep cadence fired on a quiet window within budget.
    assert collector.unfreezes - collector.busy_unfrozen >= 1
    assert policy._last_deep_full_mono is not None


__all__ = ["test_active_user_two_hours_keeps_every_pause_within_budget"]
