"""Shared start-of-process timestamp for the sase ace startup stopwatch.

``__main__`` captures ``time.perf_counter()`` before any ``sase`` imports run,
then writes it into this module via :func:`set_process_start`. Callers read the
value via :func:`get_process_start`. Tests can override the value temporarily
via :func:`override_process_start` to get deterministic stopwatch readings.
"""

from __future__ import annotations

import time

_process_start: float | None = None


def set_process_start(value: float) -> None:
    """Record the process-start perf-counter timestamp."""
    global _process_start
    _process_start = value


def get_process_start() -> float:
    """Return the recorded process-start perf-counter timestamp.

    Falls back to the current ``time.perf_counter()`` value if no start was
    recorded (e.g. when ``sase`` is imported as a library rather than invoked
    via ``python -m sase``). In that case the elapsed time starts at ~0.
    """
    if _process_start is None:
        return time.perf_counter()
    return _process_start
