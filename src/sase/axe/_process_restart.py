"""Verified, retried restart orchestration for the axe daemon."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from .config import AxeConfig, AxeConfigError, load_axe_config
from .desired_state import write_desired_state
from .lifecycle_journal import append_lifecycle_event
from .state import append_error, get_timestamp, read_lumberjack_status
from ._process_guard import (
    AXE_LIFECYCLE_TEST_BLOCK_MESSAGE,
    axe_lifecycle_blocked_in_tests,
)
from ._process_probe import get_axe_pid
from ._process_start import start_axe_daemon_result
from ._process_stop import stop_axe_daemon_result
from ._process_types import AxeStartAttempt, AxeStartResult
from ._restart_events import (
    AxeRestartEvent,
    RestartEventCallback,
    RestartFinished,
    RestartPlanned,
    RetryScheduled,
    StartAttemptBegan,
    StartAttemptSettled,
    StartAttemptSpawned,
    StopBegan,
    StopFinished,
    VerifyProgress,
)


_DEFAULT_RETRY_DELAYS = (0.25, 0.5)
_DEFAULT_VERIFICATION_TIMEOUT = 15.0
_VERIFICATION_POLL_INTERVAL = 0.1


def restart_axe_daemon(
    config: AxeConfig | None = None,
    *,
    desired_state_source: str = "axe restart",
) -> int | None:
    """Restart the axe orchestrator and return the verified daemon PID."""
    if desired_state_source == "axe restart":
        return restart_axe_daemon_result(config).pid
    return restart_axe_daemon_result(
        config,
        desired_state_source=desired_state_source,
    ).pid


def restart_axe_daemon_result(
    config: AxeConfig | None = None,
    *,
    max_attempts: int = 3,
    retry_delays: Sequence[float] = _DEFAULT_RETRY_DELAYS,
    verification_timeout: float = _DEFAULT_VERIFICATION_TIMEOUT,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
    desired_state_source: str = "axe restart",
    on_event: RestartEventCallback | None = None,
) -> AxeStartResult:
    """Restart axe, retry startup, and verify every lumberjack heartbeat."""
    start_time = monotonic_fn()
    if axe_lifecycle_blocked_in_tests():
        result = AxeStartResult(
            status="blocked_in_tests",
            message=AXE_LIFECYCLE_TEST_BLOCK_MESSAGE,
        )
        _emit(
            on_event,
            RestartFinished(result=result, elapsed_seconds=monotonic_fn() - start_time),
        )
        return result

    write_desired_state("running", source=desired_state_source)

    try:
        effective_config = config or load_axe_config()
    except AxeConfigError as exc:
        result = AxeStartResult(
            status="failed",
            message=f"Could not load axe configuration for restart: {exc}",
            attempts=(AxeStartAttempt(number=1, status="failed", message=str(exc)),),
        )
        _report_restart_failure(result)
        _journal_restart_result(result, source=desired_state_source)
        _emit(
            on_event,
            RestartFinished(result=result, elapsed_seconds=monotonic_fn() - start_time),
        )
        return result

    lumberjack_names = tuple(sorted(effective_config.lumberjacks))
    heartbeat_baseline = {name: _heartbeat_snapshot(name) for name in lumberjack_names}
    effective_max_attempts = max(1, max_attempts)

    _emit(
        on_event,
        RestartPlanned(
            lumberjacks=lumberjack_names, max_attempts=effective_max_attempts
        ),
    )

    _emit(on_event, StopBegan())
    stop_start = monotonic_fn()
    stop_result = stop_axe_daemon_result(
        desired_state_source=desired_state_source,
        record_desired_state=False,
    )
    _emit(
        on_event,
        StopFinished(result=stop_result, elapsed_seconds=monotonic_fn() - stop_start),
    )

    attempts: list[AxeStartAttempt] = []
    for number in range(1, effective_max_attempts + 1):
        _emit(
            on_event,
            StartAttemptBegan(number=number, max_attempts=effective_max_attempts),
        )
        try:
            started = start_axe_daemon_result(
                effective_config,
                desired_state_source=desired_state_source,
                record_desired_state=False,
            )
        except Exception as exc:  # noqa: BLE001 - preserve every attempt outcome.
            started = AxeStartResult(status="failed", message=str(exc))

        _emit(
            on_event,
            StartAttemptSpawned(
                number=number,
                status=started.status,
                pid=started.pid,
                message=started.message,
            ),
        )

        if started.succeeded and started.pid is not None:
            verified, verification_error = _verify_startup(
                started.pid,
                lumberjack_names=lumberjack_names,
                heartbeat_baseline=heartbeat_baseline,
                timeout=verification_timeout,
                sleep_fn=sleep_fn,
                monotonic_fn=monotonic_fn,
                on_event=on_event,
                attempt_number=number,
            )
            attempt = AxeStartAttempt(
                number=number,
                status=started.status,
                pid=started.pid,
                message=started.message,
                verified=verified,
                verification_error=verification_error,
            )
            attempts.append(attempt)
            _emit(on_event, StartAttemptSettled(attempt=attempt))
            if verified:
                result = AxeStartResult(
                    status=started.status,
                    pid=started.pid,
                    message=f"Axe restarted and verified (pid {started.pid}).",
                    attempts=tuple(attempts),
                    verified=True,
                )
                _journal_restart_result(result, source=desired_state_source)
                _emit(
                    on_event,
                    RestartFinished(
                        result=result, elapsed_seconds=monotonic_fn() - start_time
                    ),
                )
                return result

            # Do not leave a partially-started daemon in place. Keeping the
            # desired-state marker at running lets this retry (and later the
            # watchdog) start from an honestly down state.
            stop_axe_daemon_result(
                desired_state_source=desired_state_source,
                record_desired_state=False,
            )
        else:
            attempt = AxeStartAttempt(
                number=number,
                status=started.status,
                pid=started.pid,
                message=started.message,
            )
            attempts.append(attempt)
            _emit(on_event, StartAttemptSettled(attempt=attempt))

        if number < effective_max_attempts:
            delay_index = min(number - 1, len(retry_delays) - 1)
            delay = retry_delays[delay_index] if retry_delays else 0.0
            _emit(
                on_event,
                RetryScheduled(next_number=number + 1, delay_seconds=delay),
            )
            if delay > 0:
                sleep_fn(delay)

    result = AxeStartResult(
        status="failed",
        message=_restart_failure_message(attempts),
        attempts=tuple(attempts),
    )
    _report_restart_failure(result)
    _journal_restart_result(result, source=desired_state_source)
    _emit(
        on_event,
        RestartFinished(result=result, elapsed_seconds=monotonic_fn() - start_time),
    )
    return result


def _emit(on_event: RestartEventCallback | None, event: AxeRestartEvent) -> None:
    """Best-effort event delivery: a rendering bug must never abort a restart."""
    if on_event is None:
        return
    try:
        on_event(event)
    except Exception:  # noqa: BLE001 - rendering must never break the restart.
        pass


def _heartbeat_snapshot(name: str) -> tuple[int | None, str | None]:
    status = read_lumberjack_status(name)
    if status is None:
        return None, None
    return status.pid, status.last_cycle


def _verify_startup(
    pid: int,
    *,
    lumberjack_names: tuple[str, ...],
    heartbeat_baseline: dict[str, tuple[int | None, str | None]],
    timeout: float,
    sleep_fn: Callable[[float], None],
    monotonic_fn: Callable[[], float],
    on_event: RestartEventCallback | None = None,
    attempt_number: int = 1,
) -> tuple[bool, str | None]:
    """Wait for a live orchestrator and advancing lumberjack heartbeats."""
    verify_start = monotonic_fn()
    deadline = verify_start + max(0.0, timeout)
    pending = set(lumberjack_names)
    while True:
        live_pid = get_axe_pid()
        if live_pid != pid:
            return False, f"orchestrator pid {pid} is not alive"

        fresh = {
            name
            for name in lumberjack_names
            if _heartbeat_advanced(name, heartbeat_baseline.get(name))
        }
        pending = set(lumberjack_names) - fresh
        now = monotonic_fn()
        _emit(
            on_event,
            VerifyProgress(
                number=attempt_number,
                fresh=tuple(sorted(fresh)),
                pending=tuple(sorted(pending)),
                elapsed_seconds=now - verify_start,
                timeout_seconds=timeout,
            ),
        )
        if not pending:
            return True, None

        if now >= deadline:
            names = ", ".join(sorted(pending))
            return False, f"timed out waiting for fresh heartbeats: {names}"
        sleep_fn(min(_VERIFICATION_POLL_INTERVAL, max(0.0, deadline - now)))


def _heartbeat_advanced(
    name: str,
    baseline: tuple[int | None, str | None] | None,
) -> bool:
    status = read_lumberjack_status(name)
    baseline_pid, baseline_cycle = baseline or (None, None)
    return bool(
        status is not None
        and status.status == "running"
        and status.last_cycle is not None
        and status.last_cycle != baseline_cycle
        and status.pid != baseline_pid
    )


def _restart_failure_message(attempts: list[AxeStartAttempt]) -> str:
    if not attempts:
        return "Axe restart failed before a start attempt could run."
    last = attempts[-1]
    detail = last.verification_error or last.message or last.status
    return f"Axe restart failed after {len(attempts)} attempt(s): {detail}"


def _attempt_summary(attempt: AxeStartAttempt) -> str:
    detail = attempt.verification_error or attempt.message or attempt.status
    return f"Attempt {attempt.number}: {detail}"


def _report_restart_failure(result: AxeStartResult) -> None:
    """Best-effort durable surfacing for terminal restart failure."""
    attempt_summaries = [_attempt_summary(attempt) for attempt in result.attempts]
    try:
        append_error(
            {
                "timestamp": get_timestamp(),
                "lumberjack": "orchestrator",
                "job": "restart",
                "error": result.message,
                "traceback": "\n".join(attempt_summaries),
            }
        )
    except Exception:  # noqa: BLE001 - reporting must not hide the result.
        pass

    try:
        from sase.notifications.senders import notify_axe_restart_failed

        notify_axe_restart_failed(result.message, attempt_summaries)
    except Exception:  # noqa: BLE001 - restart result must still reach the caller.
        pass


def _journal_restart_result(result: AxeStartResult, *, source: str) -> None:
    append_lifecycle_event(
        "restart",
        "restarted" if result.succeeded and result.verified else "failed",
        source=source,
        reason=result.message,
        orchestrator_pid=result.pid,
        succeeded=result.succeeded and result.verified,
    )


__all__ = ["restart_axe_daemon", "restart_axe_daemon_result"]
