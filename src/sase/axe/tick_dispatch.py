"""Bounded, deterministic job dispatch for one routine tick.

A tick runs at most ``max_concurrent_jobs`` jobs at once. When more jobs are
eligible than the cap allows, the longest-running jobs start first (by their
last observed wall time), so a long job never waits behind a queue of short
ones and stretches the tick. Jobs with no known duration, and ties, keep their
configured order.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from .config import ChopConfig
from .state import read_chop_run, read_chop_run_index

#: Newest history entries inspected per job when seeding durations; the
#: newest ones are often coalesced trigger skips that carry no duration.
_SEED_HISTORY_DEPTH = 5


def dispatch_order(
    chops: Sequence[ChopConfig], durations: Mapping[str, float]
) -> list[ChopConfig]:
    """Return *chops* longest-known-duration first, otherwise in config order."""
    # ``sorted`` is stable, so unknown durations and ties keep config order.
    return sorted(chops, key=lambda chop: -max(0.0, durations.get(chop.name, 0.0)))


def _last_run_duration_seconds(lumberjack_name: str, chop_name: str) -> float | None:
    """Return the wall seconds of the newest recorded run that executed."""
    for run_id in read_chop_run_index(lumberjack_name, chop_name)[:_SEED_HISTORY_DEPTH]:
        entry = read_chop_run(lumberjack_name, chop_name, run_id)
        if entry is None or entry.finished_at is None or entry.status == "skipped":
            continue
        duration_ms = (
            entry.script_duration_ms
            if entry.script_duration_ms is not None
            else entry.duration_ms
        )
        if duration_ms >= 0:
            return duration_ms / 1000.0
    return None


def seed_durations(lumberjack_name: str, chop_names: Iterable[str]) -> dict[str, float]:
    """Read each job's last recorded wall time from its run history."""
    seeded: dict[str, float] = {}
    for chop_name in chop_names:
        try:
            duration = _last_run_duration_seconds(lumberjack_name, chop_name)
        except OSError:
            duration = None
        if duration is not None:
            seeded[chop_name] = duration
    return seeded


__all__ = [
    "dispatch_order",
    "seed_durations",
]
