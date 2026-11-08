"""Elapsed time that does not count waiting for a CPU.

Latency bounds such as "this handler takes under one frame" or "cleanup stops
at its budget" are about the code's own work, sleeps, and blocking waits. On
the contention lane every process gets a small slice of two pinned CPUs, so
plain wall time mostly measures how long the thread sat runnable in the run
queue. That is scheduling pressure, not a regression.

``SchedulerAdjustedClock`` subtracts this thread's run-queue wait, which Linux
reports in ``/proc/thread-self/schedstat``. Sleeps, I/O, lock waits, and waits
on child processes still count, so a handler that blocks or a cleanup that
sleeps out a backoff still fails the bound. Without schedstat (other
platforms, or kernels built without it) the clock is plain wall time.
"""

from __future__ import annotations

import time

_SCHEDSTAT = "/proc/thread-self/schedstat"


def run_queue_wait_seconds() -> float | None:
    """Return this thread's cumulative run-queue wait, or None if unavailable."""
    try:
        with open(_SCHEDSTAT, "rb") as handle:
            fields = handle.read().split()
        return int(fields[1]) / 1_000_000_000
    except (OSError, ValueError, IndexError):
        return None


class SchedulerAdjustedClock:
    """Measure wall time minus this thread's run-queue wait since creation.

    Create and read it on the thread doing the measured work.
    """

    def __init__(self) -> None:
        self._started = time.perf_counter()
        self._waited = run_queue_wait_seconds()

    def elapsed(self) -> float:
        """Return seconds elapsed, excluding time spent waiting for a CPU."""
        wall = time.perf_counter() - self._started
        waited_now = run_queue_wait_seconds()
        if self._waited is None or waited_now is None:
            return wall
        return max(0.0, wall - (waited_now - self._waited))


__all__ = ["SchedulerAdjustedClock", "run_queue_wait_seconds"]
