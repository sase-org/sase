"""Verified, retried restart orchestration for the axe daemon."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from .config import AxeConfig, AxeConfigError, load_axe_config
from .desired_state import write_desired_state
from .state import append_error, get_timestamp, read_lumberjack_status
from ._process_probe import get_axe_pid
from ._process_start import start_axe_daemon_result
from ._process_stop import stop_axe_daemon_result
from ._process_types import AxeStartAttempt, AxeStartResult


_DEFAULT_RETRY_DELAYS = (0.25, 0.5)
_DEFAULT_VERIFICATION_TIMEOUT = 15.0
_VERIFICATION_POLL_INTERVAL = 0.1


def restart_axe_daemon(config: AxeConfig | None = None) -> int | None:
    """Restart the axe orchestrator and return the verified daemon PID."""
    return restart_axe_daemon_result(config).pid


def restart_axe_daemon_result(
    config: AxeConfig | None = None,
    *,
    max_attempts: int = 3,
    retry_delays: Sequence[float] = _DEFAULT_RETRY_DELAYS,
    verification_timeout: float = _DEFAULT_VERIFICATION_TIMEOUT,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> AxeStartResult:
    """Restart axe, retry startup, and verify every lumberjack heartbeat."""
    write_desired_state("running", source="restart")

    try:
        effective_config = config or load_axe_config()
    except AxeConfigError as exc:
        result = AxeStartResult(
            status="failed",
            message=f"Could not load axe configuration for restart: {exc}",
            attempts=(AxeStartAttempt(number=1, status="failed", message=str(exc)),),
        )
        _report_restart_failure(result)
        return result

    lumberjack_names = tuple(sorted(effective_config.lumberjacks))
    stop_axe_daemon_result(record_desired_state=False)

    attempts: list[AxeStartAttempt] = []
    for number in range(1, max(1, max_attempts) + 1):
        # Each failed attempt can leave newer status files behind. Snapshot
        # immediately before the next start so those stale heartbeats cannot
        # verify a later attempt before its own lumberjacks report readiness.
        heartbeat_baseline = {
            name: _heartbeat_snapshot(name) for name in lumberjack_names
        }
        try:
            started = start_axe_daemon_result(
                effective_config,
                desired_state_source="restart",
                record_desired_state=False,
            )
        except Exception as exc:  # noqa: BLE001 - preserve every attempt outcome.
            started = AxeStartResult(status="failed", message=str(exc))

        if started.succeeded and started.pid is not None:
            verified, verification_error = _verify_startup(
                started.pid,
                lumberjack_names=lumberjack_names,
                heartbeat_baseline=heartbeat_baseline,
                timeout=verification_timeout,
                sleep_fn=sleep_fn,
                monotonic_fn=monotonic_fn,
            )
            attempts.append(
                AxeStartAttempt(
                    number=number,
                    status=started.status,
                    pid=started.pid,
                    message=started.message,
                    verified=verified,
                    verification_error=verification_error,
                )
            )
            if verified:
                return AxeStartResult(
                    status=started.status,
                    pid=started.pid,
                    message=f"Axe restarted and verified (pid {started.pid}).",
                    attempts=tuple(attempts),
                    verified=True,
                )

            # Do not leave a partially-started daemon in place. Keeping the
            # desired-state marker at running lets this retry (and later the
            # watchdog) start from an honestly down state.
            stop_axe_daemon_result(record_desired_state=False)
        else:
            attempts.append(
                AxeStartAttempt(
                    number=number,
                    status=started.status,
                    pid=started.pid,
                    message=started.message,
                )
            )

        if number < max(1, max_attempts):
            delay_index = min(number - 1, len(retry_delays) - 1)
            delay = retry_delays[delay_index] if retry_delays else 0.0
            if delay > 0:
                sleep_fn(delay)

    result = AxeStartResult(
        status="failed",
        message=_restart_failure_message(attempts),
        attempts=tuple(attempts),
    )
    _report_restart_failure(result)
    return result


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
) -> tuple[bool, str | None]:
    """Wait for a live orchestrator and advancing lumberjack heartbeats."""
    deadline = monotonic_fn() + max(0.0, timeout)
    pending = set(lumberjack_names)
    while True:
        live_pid = get_axe_pid()
        if live_pid != pid:
            return False, f"orchestrator pid {pid} is not alive"

        pending = {
            name
            for name in lumberjack_names
            if not _heartbeat_advanced(name, heartbeat_baseline.get(name))
        }
        if not pending:
            return True, None

        now = monotonic_fn()
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


__all__ = ["restart_axe_daemon", "restart_axe_daemon_result"]
