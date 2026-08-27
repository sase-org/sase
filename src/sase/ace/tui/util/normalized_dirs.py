"""Memoized artifact-directory normalization for the agent event lanes.

Every event lane filters a whole project's event log against one agent by
comparing normalized artifact directories, so a detail sweep resolves the same
few thousand paths once per displayed agent and once per lane.
``os.path.realpath`` walks a path component by component, which turns that
repetition into seconds of syscalls per sweep.

Memoizing is safe here because the values are timestamped artifact directories
that are never re-pointed once created, and because both sides of every
comparison resolve through this same cache: an answer that went stale would
still compare equal to itself.
"""

from __future__ import annotations

from functools import lru_cache
import os


@lru_cache(maxsize=16_384)
def _resolved(value: str) -> str:
    try:
        return os.path.realpath(value)
    except (OSError, ValueError):
        return value


def normalize_dir(value: str | None) -> str | None:
    """Return the resolved form of *value*, or ``None`` when it is empty."""
    if not value:
        return None
    return _resolved(value)


__all__ = ["normalize_dir"]
