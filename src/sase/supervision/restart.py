"""Capped exponential backoff and crash-loop-window bookkeeping for supervised children."""

from collections import deque
from dataclasses import dataclass, field

from sase.service.restart import (
    ServiceExit,
    ServiceRestartHistory,
    ServiceRestartTuning,
    decide_service_restart,
)


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
    decision = decide_service_restart(
        "always",
        ServiceExit(exit_code=exit_code),
        ServiceRestartHistory(
            started_at=state.started_at,
            backoff_seconds=state.backoff_seconds,
            consecutive_failures=state.consecutive_failures,
            recent_failures=tuple(state.recent_failures),
            alert_sent=state.alert_sent,
        ),
        now=now,
        tuning=ServiceRestartTuning(
            initial_backoff_seconds=policy.initial_backoff_seconds,
            max_backoff_seconds=policy.max_backoff_seconds,
            healthy_run_seconds=policy.healthy_run_seconds,
            crash_loop_window_seconds=policy.crash_loop_window_seconds,
            crash_loop_threshold=policy.crash_loop_failure_threshold,
        ),
    )
    state.started_at = decision.history.started_at
    state.restart_at = decision.restart_at
    state.backoff_seconds = decision.history.backoff_seconds
    state.consecutive_failures = decision.history.consecutive_failures
    state.recent_failures.clear()
    state.recent_failures.extend(decision.history.recent_failures)
    state.last_exit_code = exit_code
    state.alert_sent = decision.history.alert_sent

    return decision.notify
