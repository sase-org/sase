"""The scheduler-adjusted test clock still counts sleeps and degrades to wall time."""

from __future__ import annotations

from pathlib import Path
import time

import pytest

from tests import _sched_clock
from tests._sched_clock import SchedulerAdjustedClock


def test_a_sleep_is_not_run_queue_wait() -> None:
    clock = SchedulerAdjustedClock()
    time.sleep(0.05)  # sase-test-wait: the measured sleep itself
    assert clock.elapsed() >= 0.045


def test_without_schedstat_the_clock_is_wall_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(_sched_clock, "_SCHEDSTAT", str(tmp_path / "missing"))
    assert _sched_clock.run_queue_wait_seconds() is None
    clock = SchedulerAdjustedClock()
    started = time.perf_counter()
    time.sleep(0.02)  # sase-test-wait: the measured sleep itself
    wall = time.perf_counter() - started
    assert clock.elapsed() >= wall
