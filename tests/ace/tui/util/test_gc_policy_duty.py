"""Tests for the GC policy duty-cycle bound on full collections."""

from __future__ import annotations

import pytest

from sase.ace.tui.util import gc_policy
from tests.ace.tui.util._gc_policy_test_support import (
    Clock,
    Collector,
    Recorder,
    idle_policy,
)


class SlowCollector(Collector):
    """Stub collector whose ``collect()`` consumes fake-clock time."""

    def __init__(
        self, clock: Clock, pause_s: float, threshold: tuple[int, ...] = (700, 10, 10)
    ) -> None:
        super().__init__(threshold)
        self._clock = clock
        self.pause_s = pause_s

    def collect(self) -> int:
        self.collections += 1
        self._clock.advance(self.pause_s)
        return 0


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


def _run_startup(clock: Clock, collector: Collector, recorder: Recorder):
    policy = idle_policy(clock, collector, recorder)
    assert policy.tick(clock.now) == "startup_freeze"
    return policy


def test_duty_floor_defaults_to_min_interval() -> None:
    clock = Clock()
    policy = idle_policy(clock, Collector(), Recorder())
    assert policy._last_full_pause_s is None
    assert policy.duty_floor_s() == gc_policy.MIN_FULL_INTERVAL_S
    assert policy.next_full_due_in_s(clock.now) == 0.0


def test_two_second_pause_defers_next_full_about_sixty_seconds() -> None:
    clock = Clock()
    recorder = Recorder()
    collector = SlowCollector(clock, pause_s=2.0)
    policy = _run_startup(clock, collector, recorder)
    assert policy._last_full_pause_s == pytest.approx(2.0)
    assert policy.duty_floor_s() == pytest.approx(60.0)

    recorder.gen1 = 150
    # 59 s later: still inside the 60 s floor.
    clock.advance(59.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 1
    # At 60 s the floor elapses and the due collection runs.
    clock.advance(1.0)
    assert policy.tick(clock.now) == "idle"
    assert collector.collections == 2


def test_large_pause_clamps_to_fifteen_minutes() -> None:
    clock = Clock()
    recorder = Recorder()
    collector = SlowCollector(clock, pause_s=40.0)
    policy = _run_startup(clock, collector, recorder)
    assert policy._last_full_pause_s == pytest.approx(40.0)
    assert policy.duty_floor_s() == pytest.approx(gc_policy.MAX_DUTY_DELAY_S)
    assert gc_policy.MAX_DUTY_DELAY_S == pytest.approx(15 * 60.0)

    recorder.gen1 = 150
    clock.advance(899.0)
    assert policy.tick(clock.now) is None
    assert collector.collections == 1
    clock.advance(1.0)
    assert policy.tick(clock.now) == "backstop"
    assert collector.collections == 2


def test_twenty_second_pause_defers_ten_minutes() -> None:
    clock = Clock()
    recorder = Recorder()
    collector = SlowCollector(clock, pause_s=20.0)
    policy = _run_startup(clock, collector, recorder)
    assert policy.duty_floor_s() == pytest.approx(600.0)
    recorder.gen1 = 150
    clock.advance(599.0)
    assert policy.tick(clock.now) is None
    clock.advance(1.0)
    assert policy.tick(clock.now) == "backstop"


def test_backstop_triggers_honor_duty_floor() -> None:
    clock = Clock()
    recorder = Recorder()
    collector = SlowCollector(clock, pause_s=20.0)
    policy = _run_startup(clock, collector, recorder)
    recorder.gen1 = 150

    # Well past the 5-minute time backstop, but inside the 15-min duty floor.
    clock.advance(301.0)
    passes, tag = policy.idle_gate(clock.now)
    assert (passes, tag) == (False, "backstop")
    assert policy.tick(clock.now) is None
    assert collector.collections == 1

    clock.advance(600.0)
    passes, tag = policy.idle_gate(clock.now)
    assert passes is True
    assert policy.tick(clock.now) == "backstop"


def test_rss_backstop_honors_duty_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    recorder = Recorder()
    collector = SlowCollector(clock, pause_s=5.0)
    rss = {"now": 1_000}
    monkeypatch.setattr(gc_policy, "latest_rss_bytes", lambda: rss["now"])
    policy = _run_startup(clock, collector, recorder)
    assert policy.duty_floor_s() == pytest.approx(150.0)

    recorder.gen1 = 150
    rss["now"] = 1_000 + gc_policy.RSS_GROWTH_BACKSTOP_BYTES + 1
    clock.advance(61.0)
    passes, tag = policy.idle_gate(clock.now)
    assert (passes, tag) == (False, "rss_backstop")

    clock.advance(89.0)
    passes, tag = policy.idle_gate(clock.now)
    assert (passes, tag) == (True, "rss_backstop")
    assert policy.tick(clock.now) == "rss_backstop"


def test_heartbeat_reports_next_due_delay() -> None:
    clock = Clock()
    recorder = Recorder()
    collector = SlowCollector(clock, pause_s=2.0)
    policy = _run_startup(clock, collector, recorder)
    fields = policy.heartbeat_fields()
    assert fields["threshold_policy"] == "raised"
    assert fields["last_full_pause_s"] == pytest.approx(2.0)
    assert fields["next_full_due_in_s"] == pytest.approx(60.0, abs=0.01)
    assert policy.next_full_due_in_s(clock.now) == pytest.approx(60.0, abs=0.01)
    clock.advance(60.0)
    assert policy.next_full_due_in_s(clock.now) == pytest.approx(0.0, abs=0.01)


__all__ = [
    "test_duty_floor_defaults_to_min_interval",
    "test_two_second_pause_defers_next_full_about_sixty_seconds",
    "test_large_pause_clamps_to_fifteen_minutes",
    "test_twenty_second_pause_defers_ten_minutes",
    "test_backstop_triggers_honor_duty_floor",
    "test_rss_backstop_honors_duty_floor",
    "test_heartbeat_reports_next_due_delay",
]
