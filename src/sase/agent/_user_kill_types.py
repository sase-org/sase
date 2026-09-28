"""Shared types and constants for user-requested agent termination."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sase.agent.process_registry import ProcessRegistry

USER_KILL_INTENT_MARKER = ".sase_user_kill_pending"

# The ``sase tool run`` wrapper escalates its own child from SIGTERM to SIGKILL
# after ``sase.tool.executor_process.TERM_ESCALATE_SECONDS`` (5s). The default
# grace must outlast that so wrappers can clean up their children before the
# tree is SIGKILLed; a test pins the relationship.
DEFAULT_TERMINATE_GRACE_SECONDS = 6.0

# Shared poll interval for the tree-termination and immediate-request stages.
# It was ``_POLL_INTERVAL_SECONDS`` in the combined module; it is public here
# so both stages share one value without importing a private name.
POLL_INTERVAL_SECONDS = 0.05

Killpg = Callable[[int, int], None]
Kill = Callable[[int, int], None]
SleepFn = Callable[[float], None]
TimeFn = Callable[[], float]
RegistryFn = Callable[[int], ProcessRegistry | None]


@dataclass(frozen=True)
class AgentTerminationResult:
    """Outcome of a user-requested agent termination attempt.

    ``survivors`` lists the pids that were still running when termination gave
    up; it is empty whenever ``success`` is true.
    """

    success: bool
    status: str
    pid: int
    pgid: int
    marker_path: str | None = None
    escalated: bool = False
    error: str | None = None
    survivors: tuple[int, ...] = ()


__all__ = [
    "DEFAULT_TERMINATE_GRACE_SECONDS",
    "POLL_INTERVAL_SECONDS",
    "USER_KILL_INTENT_MARKER",
    "AgentTerminationResult",
    "Kill",
    "Killpg",
    "RegistryFn",
    "SleepFn",
    "TimeFn",
]
