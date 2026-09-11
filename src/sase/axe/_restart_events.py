"""Typed progress events emitted by verified axe restart orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ._process_types import AxeStartAttempt, AxeStartResult, AxeStopResult, StartStatus


@dataclass(frozen=True)
class RestartPlanned:
    """Emitted once, after config load and before stop."""

    lumberjacks: tuple[str, ...]
    max_attempts: int


@dataclass(frozen=True)
class StopBegan:
    """Emitted immediately before the stop phase runs."""


@dataclass(frozen=True)
class StopFinished:
    """Emitted when the stop phase completes (a no-op counts as finished)."""

    result: AxeStopResult
    elapsed_seconds: float


@dataclass(frozen=True)
class StartAttemptBegan:
    """Emitted before each start attempt."""

    number: int
    max_attempts: int


@dataclass(frozen=True)
class StartAttemptSpawned:
    """Emitted when ``start_axe_daemon_result`` returns for one attempt."""

    number: int
    status: StartStatus
    pid: int | None
    message: str


@dataclass(frozen=True)
class VerifyProgress:
    """Emitted on each heartbeat-verification poll iteration."""

    number: int
    fresh: tuple[str, ...]
    pending: tuple[str, ...]
    elapsed_seconds: float
    timeout_seconds: float


@dataclass(frozen=True)
class StartAttemptSettled:
    """Emitted once an attempt's outcome (verified or not) is final."""

    attempt: AxeStartAttempt


@dataclass(frozen=True)
class RetryScheduled:
    """Emitted when a failed/unverified attempt will be retried."""

    next_number: int
    delay_seconds: float


@dataclass(frozen=True)
class RestartFinished:
    """Always the final event, including early-exit paths."""

    result: AxeStartResult
    elapsed_seconds: float


AxeRestartEvent = (
    RestartPlanned
    | StopBegan
    | StopFinished
    | StartAttemptBegan
    | StartAttemptSpawned
    | VerifyProgress
    | StartAttemptSettled
    | RetryScheduled
    | RestartFinished
)

RestartEventCallback = Callable[[AxeRestartEvent], None]

__all__ = [
    "AxeRestartEvent",
    "RestartEventCallback",
    "RestartFinished",
    "RestartPlanned",
    "RetryScheduled",
    "StartAttemptBegan",
    "StartAttemptSettled",
    "StartAttemptSpawned",
    "StopBegan",
    "StopFinished",
    "VerifyProgress",
]
