"""Cheap per-phase timing for one monitor start.

A start is a chain of reads and writes (lane resolution, workspace claim,
member creation, ToolRun reservation, supervisor spawn and ack). When one of
them regresses -- as when an implicit in-agent start began scanning the whole
project history and outlived a yielding harness -- the phase that grew should
be visible without re-deriving it by hand. The timings go to the debug log
always, and to ``monitor_start_timing.json`` in the member's artifacts dir
once a start has created one.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from sase.core.atomic_json import write_json_marker_atomic

logger = logging.getLogger(__name__)

MONITOR_START_TIMING_FILENAME = "monitor_start_timing.json"


class StartTimer:
    """Attribute the time between successive :meth:`mark` calls to phases."""

    def __init__(self) -> None:
        self._started = time.monotonic()
        self._last = self._started
        self._phases: dict[str, float] = {}

    def mark(self, phase: str) -> None:
        """Charge the time since the previous mark (or the start) to *phase*."""
        now = time.monotonic()
        self._phases[phase] = self._phases.get(phase, 0.0) + (now - self._last)
        self._last = now

    def snapshot(self) -> dict[str, object]:
        return {
            "total_seconds": round(self._last - self._started, 3),
            "phases": {name: round(secs, 3) for name, secs in self._phases.items()},
        }

    def log(self, lane: str) -> None:
        logger.debug("monitor start timing for lane %s: %s", lane, self.snapshot())

    def write(self, artifacts_dir: str | Path) -> None:
        """Persist the timings next to the member's markers; never raises."""
        try:
            write_json_marker_atomic(
                Path(artifacts_dir) / MONITOR_START_TIMING_FILENAME, self.snapshot()
            )
        except OSError:
            logger.debug("could not write %s", MONITOR_START_TIMING_FILENAME)


__all__ = ["MONITOR_START_TIMING_FILENAME", "StartTimer"]
