"""Shared fixtures and test doubles for GC policy tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.ace.tui.util.gc_policy import GCPolicy


class Clock:
    """Manually advanced monotonic clock for deterministic policy tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class Collector:
    """Stub for the ``gc`` module surface the policy uses."""

    def __init__(self, threshold: tuple[int, ...] = (700, 10, 10)) -> None:
        self.threshold = tuple(threshold)
        self.counts = [0, 0, 0]
        self.collections = 0
        self.freezes = 0
        self.unfreezes = 0
        self.objects: list[object] = []
        self.get_objects_calls = 0

    def get_threshold(self) -> tuple[int, ...]:
        return self.threshold

    def set_threshold(self, *values: int) -> None:
        self.threshold = tuple(values)

    def get_count(self) -> tuple[int, int, int]:
        return (self.counts[0], self.counts[1], self.counts[2])

    def collect(self) -> int:
        self.collections += 1
        return 0

    def freeze(self) -> None:
        self.freezes += 1

    def unfreeze(self) -> None:
        self.unfreezes += 1

    def get_objects(self) -> list[object]:
        self.get_objects_calls += 1
        return list(self.objects)


class Recorder:
    """Stub for the telemetry handle the policy reads the last full from."""

    def __init__(self) -> None:
        self.last_full: float | None = None
        self.last_pause: float | None = None
        self.gen1 = 0

    def last_full_collection_mono(self) -> float | None:
        return self.last_full

    def gen1_since_last_full(self) -> int:
        return self.gen1

    def last_full_pause_s(self) -> float | None:
        return self.last_pause


def idle_policy(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    *,
    last_input_ago: float = 10.0,
    trim_runner: Any = None,
    allocated_blocks_probe: Callable[[], int | None] | None = None,
    memory_pressure_probe: Callable[[], dict[str, Any] | None] | None = None,
) -> GCPolicy:
    policy = GCPolicy(
        monotonic=clock,
        last_input_mono=lambda: clock.now - last_input_ago,
        prompt_active=lambda: False,
        navigating=lambda: False,
        modal_input_active=lambda: False,
        loads_done=lambda: True,
        collector=collector,
        recorder=recorder,
        trim_runner=(lambda: None) if trim_runner is None else trim_runner,
        allocated_blocks_probe=allocated_blocks_probe or (lambda: 1_000_000),
        memory_pressure_probe=memory_pressure_probe
        or (
            lambda: {
                "vmswap_bytes": 0,
                "major_faults_per_s": 0.0,
                "sample_age_s": 0.0,
            }
        ),
    )
    policy.apply_thresholds()
    policy._last_full_pause_s = 0.25
    policy._last_full_scan_blocks = 1_000
    policy._cost_sample_mono = clock.now
    return policy
