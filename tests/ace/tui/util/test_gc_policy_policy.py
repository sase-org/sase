"""Tests for GC policy timing, eligibility, and backstops."""

from __future__ import annotations

import pytest
from collections.abc import Iterator
from contextlib import contextmanager

from sase.ace.tui.util import _gc_policy_gate as gate_module
from sase.ace.tui.util import _gc_policy_sweep as sweep_module
from sase.ace.tui.util import gc_policy
from sase.ace.tui.util.gc_policy import GCPolicy
from tests.ace.tui.util._gc_policy_test_support import (
    Clock,
    Collector,
    Recorder,
    idle_policy,
    seed_negligible_cost,
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


def test_freeze_happens_once(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    tags: list[str],
) -> None:
    cold = GCPolicy(
        monotonic=clock,
        last_input_mono=lambda: clock.now - 10.0,
        loads_done=lambda: False,
        collector=collector,
        recorder=recorder,
        trim_runner=lambda: None,
    )
    assert cold.tick(clock.now) is None
    assert collector.collections == 0

    policy = idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    assert collector.collections == 0
    assert collector.freezes == 1
    assert tags == ["startup_freeze"]

    # A later full sweep freezes its survivors again.
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert collector.collections == 1
    assert collector.freezes == 2
    assert tags == ["startup_freeze", "idle"]


def test_no_collection_while_input_recent(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
) -> None:
    policy = idle_policy(clock, collector, recorder, last_input_ago=1.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 0


def test_no_collection_while_prompt_active(
    clock: Clock, collector: Collector, recorder: Recorder
) -> None:
    policy = idle_policy(clock, collector, recorder)
    policy._prompt_active = lambda: True
    assert policy.tick(clock.now) is None
    assert collector.collections == 0


def test_no_collection_while_navigating_or_modal(
    clock: Clock, collector: Collector, recorder: Recorder
) -> None:
    policy = idle_policy(clock, collector, recorder)
    policy._navigating = lambda: True
    assert policy.tick(clock.now) is None
    policy._navigating = lambda: False
    policy._modal_input_active = lambda: True
    assert policy.tick(clock.now) is None
    assert collector.collections == 0


def test_no_collection_before_due(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    tags: list[str],
) -> None:
    policy = idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    # One minute later but nothing has piled up: no repeat collection.
    clock.advance(61.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 0
    assert tags == ["startup_freeze"]


def test_collector_counter_marks_due_without_recorder(
    clock: Clock, collector: Collector
) -> None:
    policy = GCPolicy(
        monotonic=clock,
        last_input_mono=lambda: clock.now - 10.0,
        loads_done=lambda: True,
        collector=collector,
        recorder=None,
        trim_runner=lambda: None,
    )
    policy.apply_thresholds()
    assert policy.tick(clock.now) == "startup_freeze"
    seed_negligible_cost(policy, clock)
    clock.advance(61.0)
    collector.counts = [0, 0, 100]
    assert policy.tick(clock.now) == "idle"


def test_time_backstop_relaxes_quiet_window(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    tags: list[str],
) -> None:
    policy = idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    recorder.gen1 = 150
    clock.advance(301.0)
    policy._own_last_full_mono = clock.now - 301.0
    # Only 1.5 s of quiet: too recent even for "backstop" (3 s required).
    quiet_policy = idle_policy(clock, collector, recorder, last_input_ago=1.5)
    quiet_policy._froze_startup = True
    quiet_policy._own_last_full_mono = policy._own_last_full_mono
    assert quiet_policy.tick(clock.now) is None
    # At 3 s of quiet the due backstop runs.
    quiet_policy._last_input_mono = lambda: clock.now - 3.0
    assert quiet_policy.tick(clock.now) == "backstop"
    assert tags[-1] == "backstop"


def test_rss_backstop_relaxes_quiet_window(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
    tags: list[str],
) -> None:
    rss = {"now": 1_000}
    monkeypatch.setattr(gate_module, "latest_rss_bytes", lambda: rss["now"])
    monkeypatch.setattr(sweep_module, "latest_rss_bytes", lambda: rss["now"])
    policy = idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    assert policy._rss_at_last_full == 1_000

    rss["now"] = 1_000 + gc_policy.RSS_GROWTH_BACKSTOP_BYTES + 1
    recorder.gen1 = 150
    clock.advance(61.0)
    quiet_policy = idle_policy(clock, collector, recorder, last_input_ago=1.5)
    quiet_policy._froze_startup = True
    quiet_policy._own_last_full_mono = policy._own_last_full_mono
    quiet_policy._rss_at_last_full = policy._rss_at_last_full
    assert quiet_policy.tick(clock.now) is None
    quiet_policy._last_input_mono = lambda: clock.now - 3.0
    assert quiet_policy.tick(clock.now) == "rss_backstop"
    assert tags[-1] == "rss_backstop"


def test_backstops_require_three_quiet_seconds(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Time and RSS backstops stay ineligible until 3 s of quiet."""
    rss = {"now": 1_000}
    monkeypatch.setattr(gate_module, "latest_rss_bytes", lambda: rss["now"])
    monkeypatch.setattr(sweep_module, "latest_rss_bytes", lambda: rss["now"])
    policy = idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    baseline = policy._rss_at_last_full
    assert baseline == 1_000

    recorder.gen1 = 150
    clock.advance(301.0)
    policy._own_last_full_mono = clock.now - 301.0
    for age in (1.0, 2.0, 2.01):
        policy._last_input_mono = lambda age=age: clock.now - age  # noqa: B023
        passes, tag = policy.idle_gate(clock.now)
        assert passes is False
        assert tag == "backstop"
    policy._last_input_mono = lambda: clock.now - 3.0
    passes, tag = policy.idle_gate(clock.now)
    assert (passes, tag) == (True, "backstop")

    rss["now"] = 1_000 + gc_policy.RSS_GROWTH_BACKSTOP_BYTES + 1
    fresh = idle_policy(clock, collector, recorder, last_input_ago=10.0)
    fresh._froze_startup = True
    # Recent enough that the 5-minute time backstop is not tripped, so the
    # RSS-growth backstop alone relaxes the gate.
    fresh._own_last_full_mono = clock.now - 61.0
    fresh._rss_at_last_full = baseline
    for age in (1.0, 2.0, 2.01):
        fresh._last_input_mono = lambda age=age: clock.now - age  # noqa: B023
        passes, tag = fresh.idle_gate(clock.now)
        assert passes is False
        assert tag == "rss_backstop"
    fresh._last_input_mono = lambda: clock.now - 3.0
    assert fresh.idle_gate(clock.now) == (True, "rss_backstop")


def test_sustained_activity_defers_due_backstop(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    tags: list[str],
) -> None:
    """A due backstop waits through activity, then runs at first quiet tick."""
    policy = idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    recorder.gen1 = 150
    clock.advance(301.0)
    policy._own_last_full_mono = clock.now - 301.0
    policy._last_input_mono = lambda: clock.now - 0.5
    assert policy.tick(clock.now) is None
    assert collector.collections == 0
    policy._last_input_mono = lambda: clock.now - 3.0
    assert policy.tick(clock.now) == "backstop"
    assert tags[-1] == "backstop"


def test_swap_pressure_defers_a_due_full_collection(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pressure = {
        "vmswap_bytes": 2 * gc_policy.SWAP_GROWTH_PRESSURE_BYTES,
        "vmswap_growth_bytes": gc_policy.SWAP_GROWTH_PRESSURE_BYTES + 1,
        "major_faults_per_s": 0.0,
        "sample_age_s": 0.0,
    }
    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(
        sweep_module,
        "queue_row",
        lambda event, row: emitted.append({"event": event, **row}),
    )
    policy = idle_policy(
        clock,
        collector,
        recorder,
        memory_pressure_probe=lambda: pressure,
    )
    assert policy.tick(clock.now) == "startup_freeze"
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 0
    assert emitted[-1]["event"] == "tui_gc_memory_pressure"
    assert emitted[-1]["reason"] == "swapping"
    assert emitted[-1]["pressure_signal"] == "swap_growth"

    # The swapped-out level stays, but it stopped growing: no longer pressure.
    pressure["vmswap_growth_bytes"] = 0
    assert policy.tick(clock.now) == "idle"
    assert collector.collections == 1


def test_major_fault_pressure_defers_a_due_full_collection(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pressure = {
        "vmswap_bytes": 0,
        "major_faults_per_s": gc_policy.MAJOR_FAULTS_PER_S_PRESSURE_THRESHOLD + 1,
        "sample_age_s": 0.0,
    }
    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(
        sweep_module,
        "queue_row",
        lambda event, row: emitted.append({"event": event, **row}),
    )
    policy = idle_policy(
        clock,
        collector,
        recorder,
        memory_pressure_probe=lambda: pressure,
    )
    assert policy.tick(clock.now) == "startup_freeze"
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 0
    assert emitted[-1]["event"] == "tui_gc_memory_pressure"
    assert emitted[-1]["reason"] == "swapping"


def test_cost_gate_defers_until_long_idle_allows_a_deep_sweep(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(
        sweep_module,
        "queue_row",
        lambda event, row: emitted.append({"event": event, **row}),
    )
    policy = idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    # 2 s per 61 s of accumulation: 61 s later the estimate is 2 s x 2.
    policy._last_full_pause_s = 2.0
    policy._cost_pause_s = 2.0
    policy._cost_accum_s = 61.0
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 0
    assert emitted[-1]["event"] == "tui_gc_collection_deferred"
    assert emitted[-1]["reason"] == "cost_gate"
    assert emitted[-1]["predicted_pause_s"] == pytest.approx(4.0)

    clock.advance(gc_policy.LONG_IDLE_QUIET_S)
    policy._last_input_mono = lambda: clock.now - gc_policy.LONG_IDLE_QUIET_S - 1.0
    assert policy.tick(clock.now) == "idle"
    assert collector.collections == 1
    assert collector.unfreezes == 1
    assert collector.freezes == 2


def test_census_cleanup_collection_uses_idle_trigger(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
    tags: list[str],
) -> None:
    """Both census collects carry the idle trigger, not automatic."""
    monkeypatch.setenv(gc_policy.ENV_CENSUS, "1")
    monkeypatch.setattr(sweep_module, "CENSUS_INTERVAL_S", 100.0)
    policy = idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    idle_tags = len(tags)
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert tags[idle_tags:] == ["idle", "idle"]
    assert collector.collections == 2


__all__ = [
    "test_freeze_happens_once",
    "test_no_collection_while_input_recent",
    "test_no_collection_while_prompt_active",
    "test_no_collection_while_navigating_or_modal",
    "test_no_collection_before_due",
    "test_collector_counter_marks_due_without_recorder",
    "test_time_backstop_relaxes_quiet_window",
    "test_rss_backstop_relaxes_quiet_window",
    "test_backstops_require_three_quiet_seconds",
    "test_sustained_activity_defers_due_backstop",
    "test_swap_pressure_defers_a_due_full_collection",
    "test_major_fault_pressure_defers_a_due_full_collection",
    "test_cost_gate_defers_until_long_idle_allows_a_deep_sweep",
    "test_census_cleanup_collection_uses_idle_trigger",
]
