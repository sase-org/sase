"""Capped exponential backoff and crash-loop-window bookkeeping for supervised children."""

from collections import deque
from dataclasses import dataclass, field


@dataclass
class RestartState:
    """Per-child restart history and pending retry state."""

    started_at: float | None = None
    restart_at: float | None = None
    backoff_seconds: float = 0.0
    consecutive_failures: int = 0
    recent_failures: deque[float] = field(default_factory=deque)
    last_exit_code: int | None = None
    alert_sent: bool = False


@dataclass(frozen=True)
class RestartPolicy:
    """Backoff and crash-loop detection parameters for one supervised child kind."""

    initial_backoff_seconds: float
    healthy_run_seconds: float
    max_backoff_seconds: float
    crash_loop_window_seconds: float
    crash_loop_failure_threshold: int


def record_started(state: RestartState, *, now: float) -> None:
    """Clear pending-retry bookkeeping for a freshly (re)started child."""
    state.started_at = now
    state.restart_at = None
    state.last_exit_code = None


def schedule_restart(
    state: RestartState,
    policy: RestartPolicy,
    *,
    now: float,
    exit_code: int | None,
) -> bool:
    """Record a failure, advance capped exponential backoff, and window crash-loop failures.

    A run lasting at least ``policy.healthy_run_seconds`` resets backoff and
    the crash-loop window before the failure is recorded. Returns True the
    instant the crash-loop threshold is first crossed since the last alert,
    so the caller can surface exactly one alert per episode.
    """
    healthy_run = (
        state.started_at is not None
        and now - state.started_at >= policy.healthy_run_seconds
    )
    if healthy_run:
        state.backoff_seconds = 0.0
        state.consecutive_failures = 0
        state.recent_failures.clear()
        state.alert_sent = False

    state.started_at = None
    state.consecutive_failures += 1
    if state.backoff_seconds == 0:
        state.backoff_seconds = policy.initial_backoff_seconds
    else:
        state.backoff_seconds *= 2
    state.backoff_seconds = min(state.backoff_seconds, policy.max_backoff_seconds)
    state.restart_at = now + state.backoff_seconds
    state.last_exit_code = exit_code

    cutoff = now - policy.crash_loop_window_seconds
    while state.recent_failures and state.recent_failures[0] < cutoff:
        state.recent_failures.popleft()
    state.recent_failures.append(now)

    if (
        len(state.recent_failures) >= policy.crash_loop_failure_threshold
        and not state.alert_sent
    ):
        state.alert_sent = True
        return True
    return False
