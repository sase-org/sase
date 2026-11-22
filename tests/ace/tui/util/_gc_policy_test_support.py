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
    """Stub for the ``gc`` module surface the policy uses.

    ``busy`` models CPython's ``gc.collect()`` while another thread's
    collection is in progress: the call returns at once and the gen-2
    ``collections`` counter that ``get_stats()`` reports does not advance.
    """

    def __init__(self, threshold: tuple[int, ...] = (700, 10, 10)) -> None:
        self.threshold = tuple(threshold)
        self.counts = [0, 0, 0]
        self.collections = 0
        self.full_collections = 0
        self.skipped = 0
        self.busy = False
        self.freezes = 0
        self.unfreezes = 0
        self.freeze_count = 0
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
        if self.busy:
            self.skipped += 1
            return 0
        self.full_collections += 1
        return 0

    def get_stats(self) -> list[dict[str, int]]:
        return [
            {"collections": 0, "collected": 0, "uncollectable": 0},
            {"collections": 0, "collected": 0, "uncollectable": 0},
            {"collections": self.full_collections, "collected": 0, "uncollectable": 0},
        ]

    def freeze(self) -> None:
        self.freezes += 1

    def unfreeze(self) -> None:
        self.unfreezes += 1

    def get_freeze_count(self) -> int:
        return self.freeze_count

    def get_objects(self) -> list[object]:
        self.get_objects_calls += 1
        return list(self.objects)


class PricedCollector(Collector):
    """Stub collector whose pause models a frozen heap on the fake clock.

    An ordinary collection scans what accumulated since the last real full
    collection (``state["young"]`` blocks) at ``young_cost_s`` per block; a
    deep one (after ``unfreeze()``) also scans the ``live`` frozen heap at
    ``live_cost_s`` per block. With ``busy_every=N`` every Nth ``collect()``
    is a no-op, as when another thread's collection is in progress.
    """

    def __init__(
        self,
        clock: Clock,
        *,
        live: int,
        state: dict[str, int],
        young_cost_s: float = 1.1e-6,
        live_cost_s: float = 0.15e-6,
        busy_every: int = 0,
    ) -> None:
        super().__init__()
        self._clock = clock
        self._live = live
        self._state = state
        self._young_cost_s = young_cost_s
        self._live_cost_s = live_cost_s
        self._busy_every = busy_every
        self._deep_next = False
        self.pauses: list[float] = []
        self.busy_unfrozen = 0

    def unfreeze(self) -> None:
        super().unfreeze()
        self._deep_next = True

    def collect(self) -> int:
        if self._busy_every:
            self.busy = (self.collections + 1) % self._busy_every == 0
        before = self.full_collections
        super().collect()
        deep, self._deep_next = self._deep_next, False
        if self.full_collections == before:
            if deep:
                self.busy_unfrozen += 1
            return 0
        pause = self._state["young"] * self._young_cost_s
        if deep:
            pause += self._live * self._live_cost_s
        self._clock.advance(pause)
        self.pauses.append(pause)
        self._state["young"] = 0
        return 0


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
    seed_negligible_cost(policy, clock)
    return policy


def seed_negligible_cost(policy: GCPolicy, clock: Clock) -> None:
    """Give the policy a known, negligible estimate so the cost gate stays out."""
    policy._last_full_pause_s = 0.25
    policy._cost_pause_s = 0.001
    policy._cost_accum_s = 60.0
    policy._cost_sample_mono = clock.now
