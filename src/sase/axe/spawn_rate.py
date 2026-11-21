"""Rolling-window spawn rate shared by routines and their status readers.

A routine records one ``(epoch_seconds, spawns)`` sample for each tick that
spawned at least one job. The rate is the window's spawn total divided by the
window's actual duration, so it stays honest for lanes of any interval: a
3600 s lane that spawns 13 jobs per tick reports about 0.2 a minute, not
``13 x 60``. Because the computation only needs the samples and a clock,
readers recompute it at read time and the rate decays between ticks.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

#: The rolling window never covers less than five minutes.
MIN_SPAWN_RATE_WINDOW_SECONDS = 300.0

#: Shortest observed span used as a denominator, guarding against clock jumps.
_MIN_SPAN_SECONDS = 1.0


def spawn_rate_window_seconds(interval_seconds: float) -> float:
    """Return the rolling window for a routine ticking every *interval_seconds*.

    The window is at least five minutes and at least one interval, so a long
    lane's latest tick stays in view until the next one is due.
    """
    return max(MIN_SPAWN_RATE_WINDOW_SECONDS, float(interval_seconds))


def prune_spawn_samples(
    samples: Iterable[Sequence[float]],
    *,
    now: float,
    window_seconds: float,
) -> list[list[float]]:
    """Keep the samples that spawned something inside ``(now - window, ...]``."""
    cutoff = now - window_seconds
    return [
        [float(sample[0]), sample[1]]
        for sample in samples
        if sample[0] > cutoff and sample[1] > 0
    ]


def spawn_rate_per_minute(
    samples: Iterable[Sequence[float]],
    *,
    now: float,
    window_seconds: float,
    since: float,
) -> float:
    """Return spawns a minute over the rolling window ending at *now*.

    *since* is when observation began. Routines pass their start time minus
    one interval: the first tick runs at start and accounts for the interval
    before it. Until a full window has elapsed the denominator is the
    observed span ``now - since`` rather than the whole window.
    """
    if window_seconds <= 0:
        return 0.0
    cutoff = now - window_seconds
    total = sum(sample[1] for sample in samples if sample[0] > cutoff)
    span = min(window_seconds, max(now - since, _MIN_SPAN_SECONDS))
    return total * 60.0 / span


__all__ = [
    "MIN_SPAWN_RATE_WINDOW_SECONDS",
    "prune_spawn_samples",
    "spawn_rate_per_minute",
    "spawn_rate_window_seconds",
]
