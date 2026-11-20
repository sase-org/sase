"""Shared fixtures and helpers for GC telemetry tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.util import _gc_telemetry_lifecycle as lifecycle_module
from sase.ace.tui.util import _gc_telemetry_recorder as recorder_module
from sase.ace.tui.util import gc_telemetry
from sase.ace.tui.util.gc_telemetry import GCTelemetry


class Clock:
    """Manually advanced monotonic clock for deterministic telemetry tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


@pytest.fixture
def emitted() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def telemetry(
    emitted: list[dict[str, Any]], clock: Clock, tmp_path: Path
) -> Iterator[GCTelemetry]:
    tel = GCTelemetry(
        app_instance_id="test-instance",
        monotonic=clock,
        emit=emitted.append,
        status_path=tmp_path / "missing-status",
        stat_path=tmp_path / "missing-stat",
    )
    previous_active = lifecycle_module._active
    previous_tag = lifecycle_module._trigger_tag
    previous_providers = dict(recorder_module._heartbeat_providers)
    lifecycle_module._active = tel
    try:
        yield tel
    finally:
        lifecycle_module._active = previous_active
        lifecycle_module._trigger_tag = previous_tag
        recorder_module._heartbeat_providers.clear()
        recorder_module._heartbeat_providers.update(previous_providers)
        lifecycle_module._pending_start.start_mono = None
        lifecycle_module._pending_start.thread = ""
        lifecycle_module._pending_start.trigger = gc_telemetry.UNTAGGED_TRIGGER
        lifecycle_module._pending_start.last_input_mono = 0.0
        lifecycle_module._pending_start.start_majflt = None
        lifecycle_module._last_input_mono = 0.0


def record(
    tel: GCTelemetry,
    generation: int,
    duration: float,
    *,
    start: float = 2000.0,
    trigger: str = "automatic",
    collected: int = 10,
) -> None:
    tel._record_stop(
        generation,
        start,
        start + duration,
        "MainThread",
        trigger,
        collected,
        0,
    )
