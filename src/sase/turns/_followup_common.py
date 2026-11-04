"""Shared public helpers for turn follow-up splits.

This is an already-private (``_``-prefixed) module: split follow-up
modules import these public names instead of sharing ``_``-prefixed
helpers across files.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FollowupLaunchResult:
    """Outcome of attempting to launch a turn follow-up agent."""

    launched: bool
    degraded_reason: str | None = None
    error: str | None = None
    prompt_path: str | None = None
    agent_name: str | None = None
    artifacts_dir: str | None = None
    pid: int | None = None
    host_completed: bool = False

    def __bool__(self) -> bool:
        return self.launched


__all__ = [
    "FollowupLaunchResult",
]
