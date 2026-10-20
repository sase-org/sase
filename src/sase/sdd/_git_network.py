"""Classifier-driven network git retries for SDD operations."""

from collections.abc import Callable, Mapping, Sequence
import logging
import subprocess
import time
from pathlib import Path
from typing import Any

from sase.core.retryability_facade import classify_failure_retryability
from sase.core.retryability_wire import RETRY_OPERATION_GIT, RetryabilityVerdictWire
from sase.sdd._git_config import (
    DEFAULT_NETWORK_GIT_MAX_ATTEMPTS,
    DEFAULT_NETWORK_GIT_RETRY_DELAYS_SECONDS,
    DEFAULT_NETWORK_GIT_TIMEOUT_SECONDS,
    ENV_NETWORK_TIMEOUT,
    SddGitCommandTimeout,
    float_env,
    stream_text,
)
from sase.sdd._git_runner import run_sdd_git

_logger = logging.getLogger(__name__)


def network_git_timeout() -> float:
    """Return the configured timeout for SDD network git operations."""
    return _network_git_timeout()


SddGitRunFn = Callable[..., subprocess.CompletedProcess[Any]]


def run_sdd_network_git(
    args: list[str],
    *,
    cwd: Path,
    op: str,
    timeout: float | None = None,
    deadline: float | None = None,
    check: bool,
    capture_output: bool,
    text: bool = False,
    env: Mapping[str, str] | None = None,
    max_attempts: int = DEFAULT_NETWORK_GIT_MAX_ATTEMPTS,
    backoff_delays: Sequence[float] = DEFAULT_NETWORK_GIT_RETRY_DELAYS_SECONDS,
) -> subprocess.CompletedProcess[Any]:
    """Run a network git command with bounded classifier-driven retries."""

    return run_sdd_network_git_with_retries(
        run_sdd_git,
        args,
        cwd=cwd,
        op=op,
        timeout=timeout,
        deadline=deadline,
        check=check,
        capture_output=capture_output,
        text=text,
        env=env,
        max_attempts=max_attempts,
        backoff_delays=backoff_delays,
    )


def run_sdd_network_git_with_retries(
    run_once: SddGitRunFn,
    args: list[str],
    *,
    cwd: Path,
    op: str,
    timeout: float | None = None,
    deadline: float | None = None,
    check: bool,
    capture_output: bool,
    text: bool = False,
    env: Mapping[str, str] | None = None,
    max_attempts: int = DEFAULT_NETWORK_GIT_MAX_ATTEMPTS,
    backoff_delays: Sequence[float] = DEFAULT_NETWORK_GIT_RETRY_DELAYS_SECONDS,
) -> subprocess.CompletedProcess[Any]:
    """Run one network git command through an injectable execution boundary."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    timeout_seconds = timeout if timeout is not None else _network_git_timeout()
    last_result: subprocess.CompletedProcess[Any] | None = None

    for attempt in range(1, max_attempts + 1):
        attempt_timeout = _network_attempt_timeout(timeout_seconds, deadline)
        if attempt_timeout <= 0.0:
            if last_result is not None:
                return _checked_network_result(last_result, check=check)
            raise SddGitCommandTimeout(
                f"git operation {op!r} deadline expired before attempt in {cwd}"
            )
        try:
            result = run_once(
                args,
                cwd=cwd,
                op=op,
                timeout=attempt_timeout,
                check=False,
                capture_output=capture_output,
                text=text,
                env=env,
            )
        except SddGitCommandTimeout:
            if attempt >= max_attempts or not _sleep_for_network_retry(
                attempt=attempt,
                backoff_delays=backoff_delays,
                deadline=deadline,
                verdict=None,
            ):
                raise
            continue

        last_result = result
        if result.returncode == 0:
            return _checked_network_result(result, check=check)

        verdict = _classify_network_git_failure(result)
        if (
            verdict is None
            or not verdict.retryable
            or attempt >= max_attempts
            or not _sleep_for_network_retry(
                attempt=attempt,
                backoff_delays=backoff_delays,
                deadline=deadline,
                verdict=verdict,
            )
        ):
            return _checked_network_result(result, check=check)

    assert last_result is not None
    return _checked_network_result(last_result, check=check)


def _checked_network_result(
    result: subprocess.CompletedProcess[Any],
    *,
    check: bool,
) -> subprocess.CompletedProcess[Any]:
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def _classify_network_git_failure(
    result: subprocess.CompletedProcess[Any],
) -> RetryabilityVerdictWire | None:
    try:
        return classify_failure_retryability(
            RETRY_OPERATION_GIT,
            exit_status=int(result.returncode),
            stdout=stream_text(result.stdout),
            stderr=stream_text(result.stderr),
        )
    except Exception:
        _logger.debug("failed to classify network git failure", exc_info=True)
        return None


def _sleep_for_network_retry(
    *,
    attempt: int,
    backoff_delays: Sequence[float],
    deadline: float | None,
    verdict: RetryabilityVerdictWire | None,
) -> bool:
    delay = _network_retry_delay(
        attempt=attempt,
        backoff_delays=backoff_delays,
        verdict=verdict,
    )
    if deadline is not None:
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0.0:
            return False
        delay = min(delay, remaining)
    if delay > 0.0:
        time.sleep(delay)
    return deadline is None or time.monotonic() < deadline


def _network_retry_delay(
    *,
    attempt: int,
    backoff_delays: Sequence[float],
    verdict: RetryabilityVerdictWire | None,
) -> float:
    if verdict is not None and verdict.retry_after_seconds is not None:
        return max(0.0, float(verdict.retry_after_seconds))
    if not backoff_delays:
        return 0.0
    return max(0.0, float(backoff_delays[min(attempt - 1, len(backoff_delays) - 1)]))


def _network_attempt_timeout(default: float, deadline: float | None) -> float:
    if deadline is None:
        return max(0.0, default)
    return min(max(0.0, default), max(0.0, deadline - time.monotonic()))


def _network_git_timeout() -> float:
    return float_env(ENV_NETWORK_TIMEOUT, DEFAULT_NETWORK_GIT_TIMEOUT_SECONDS)
