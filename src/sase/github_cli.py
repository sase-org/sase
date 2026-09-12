"""Retrying, non-interactive ``gh`` CLI execution boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import json
import logging
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Protocol

from sase.core.retryability_facade import (
    classify_failure_retryability,
    is_retryable_failure,
)
from sase.core.retryability_wire import (
    RETRYABILITY_VERDICT_TRANSIENT,
    RETRYABILITY_WIRE_SCHEMA_VERSION,
    RETRY_OPERATION_GH,
    RetryabilityVerdictWire,
)
from sase.workspace_provider.utils import non_interactive_git_env

_logger = logging.getLogger(__name__)

ENV_GH_TIMEOUT = "SASE_GH_TIMEOUT"
ENV_GH_MAX_RETRY_SLEEP = "SASE_GH_MAX_RETRY_SLEEP"

DEFAULT_GH_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_DELAYS_SECONDS = (1.0, 2.0)
DEFAULT_MAX_RETRY_SLEEP_SECONDS = 60.0


class GhSubprocessRunner(Protocol):
    """Injectable subprocess-compatible ``gh`` runner for deterministic tests."""

    def __call__(
        self,
        args: Sequence[str],
        *,
        cwd: str | Path | None = None,
        capture_output: bool = True,
        text: bool = True,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
        stdin: Any = None,
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True)
class GhCommandResult:
    """Structured result for one bounded ``gh`` command execution."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    attempts: int
    duration_ms: float
    timeout_seconds: float
    verdict: RetryabilityVerdictWire | None = None

    def completed_process(self) -> subprocess.CompletedProcess[str]:
        """Return a subprocess-shaped result for legacy call sites."""
        return subprocess.CompletedProcess(
            list(self.args),
            self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


class GhCommandError(RuntimeError):
    """A structured ``gh`` failure after retries are exhausted."""

    def __init__(
        self,
        message: str,
        *,
        result: GhCommandResult | None = None,
    ) -> None:
        super().__init__(message)
        self.result = result


def run_gh(
    args: Sequence[str],
    *,
    cwd: str | Path | None = None,
    timeout: float | None = None,
    check: bool = False,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_delays: Sequence[float] = DEFAULT_BACKOFF_DELAYS_SECONDS,
    max_retry_sleep: float | None = None,
    run_fn: GhSubprocessRunner | None = None,
    sleep_fn: Any = time.sleep,
    time_fn: Any = time.time,
    monotonic_fn: Any = time.perf_counter,
    op: str = "gh",
) -> GhCommandResult:
    """Run ``gh`` with bounded retries classified by the Rust core."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    timeout_seconds = timeout if timeout is not None else _gh_timeout()
    max_sleep_seconds = (
        max_retry_sleep if max_retry_sleep is not None else _max_retry_sleep_seconds()
    )
    runner = subprocess.run if run_fn is None else run_fn
    argv = ("gh", *tuple(args))
    env = _noninteractive_gh_env()
    last_result: GhCommandResult | None = None
    start_all = monotonic_fn()

    for attempt in range(1, max_attempts + 1):
        attempt_start = monotonic_fn()
        try:
            completed = runner(
                argv,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = (monotonic_fn() - attempt_start) * 1000.0
            stdout = _stream_text(exc.output)
            stderr = _stream_text(exc.stderr) or (
                f"`gh {' '.join(args)}` timed out after {timeout_seconds:g}s"
            )
            timeout_verdict = _classify_timeout(stdout=stdout, stderr=stderr)
            _log_gh_operation(
                op=op,
                cmd=list(argv),
                cwd=cwd,
                status="timeout",
                duration_ms=duration_ms,
                timeout_seconds=timeout_seconds,
                returncode=None,
                stdout=stdout,
                stderr=stderr,
                attempt=attempt,
                attempts=max_attempts,
                verdict=timeout_verdict,
            )
            if attempt < max_attempts and timeout_verdict.retryable:
                _sleep_before_retry(
                    attempt=attempt,
                    backoff_delays=backoff_delays,
                    max_retry_sleep=max_sleep_seconds,
                    sleep_fn=sleep_fn,
                    verdict=timeout_verdict,
                    stdout=stdout,
                    stderr=stderr,
                    time_fn=time_fn,
                )
                continue
            raise GhCommandError(
                _failure_message(
                    argv,
                    attempts=attempt,
                    returncode=None,
                    detail=stderr,
                    timed_out=True,
                )
            ) from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise GhCommandError(
                f"`{' '.join(argv)}` could not be run: {type(exc).__name__}: {exc}"
            ) from exc

        stdout = _stream_text(completed.stdout)
        stderr = _stream_text(completed.stderr)
        verdict: RetryabilityVerdictWire | None = None
        if completed.returncode != 0:
            verdict = classify_failure_retryability(
                RETRY_OPERATION_GH,
                exit_status=completed.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        duration_ms = (monotonic_fn() - attempt_start) * 1000.0
        result = GhCommandResult(
            args=tuple(str(part) for part in completed.args),
            returncode=int(completed.returncode),
            stdout=stdout,
            stderr=stderr,
            attempts=attempt,
            duration_ms=(monotonic_fn() - start_all) * 1000.0,
            timeout_seconds=timeout_seconds,
            verdict=verdict,
        )
        last_result = result
        _log_gh_operation(
            op=op,
            cmd=list(argv),
            cwd=cwd,
            status="ok" if result.returncode == 0 else "nonzero",
            duration_ms=duration_ms,
            timeout_seconds=timeout_seconds,
            returncode=result.returncode,
            stdout=stdout,
            stderr=stderr,
            attempt=attempt,
            attempts=max_attempts,
            verdict=verdict,
        )
        if result.returncode == 0:
            return result
        if attempt < max_attempts and verdict is not None and verdict.retryable:
            _sleep_before_retry(
                attempt=attempt,
                backoff_delays=backoff_delays,
                max_retry_sleep=max_sleep_seconds,
                sleep_fn=sleep_fn,
                verdict=verdict,
                stdout=stdout,
                stderr=stderr,
                time_fn=time_fn,
            )
            continue
        if check:
            raise GhCommandError(
                _failure_message(
                    argv,
                    attempts=attempt,
                    returncode=result.returncode,
                    detail=_first_nonempty_line(stderr, stdout),
                    timed_out=False,
                ),
                result=result,
            )
        return result

    assert last_result is not None
    if check:
        raise GhCommandError(
            _failure_message(
                argv,
                attempts=last_result.attempts,
                returncode=last_result.returncode,
                detail=_first_nonempty_line(last_result.stderr, last_result.stdout),
                timed_out=False,
            ),
            result=last_result,
        )
    return last_result


def gh_api_json(
    endpoint: str,
    *,
    method: str = "GET",
    cwd: str | Path | None = None,
    timeout: float | None = None,
    expect_object: bool = True,
    run_fn: GhSubprocessRunner | None = None,
    sleep_fn: Any = time.sleep,
    op: str = "gh.api",
) -> Mapping[str, Any] | Any:
    """Run ``gh api`` and parse the response JSON."""
    result = run_gh(
        ["api", "-X", method, endpoint],
        cwd=cwd,
        timeout=timeout,
        check=True,
        run_fn=run_fn,
        sleep_fn=sleep_fn,
        op=op,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GhCommandError(
            f"could not parse `gh api` output as JSON: {exc}",
            result=result,
        ) from exc
    if expect_object and not isinstance(payload, Mapping):
        raise GhCommandError(
            "`gh api` returned JSON that was not an object",
            result=result,
        )
    return payload


def _noninteractive_gh_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = non_interactive_git_env(base)
    env["GH_PROMPT_DISABLED"] = "1"
    return env


def _classify_timeout(*, stdout: str, stderr: str) -> RetryabilityVerdictWire:
    if is_retryable_failure(
        operation_kind=RETRY_OPERATION_GH,
        exit_status=None,
        stdout=stdout,
        stderr=stderr,
    ):
        return classify_failure_retryability(
            RETRY_OPERATION_GH,
            exit_status=None,
            stdout=stdout,
            stderr=stderr,
        )
    return RetryabilityVerdictWire(
        schema_version=RETRYABILITY_WIRE_SCHEMA_VERSION,
        verdict=RETRYABILITY_VERDICT_TRANSIENT,
        reason="python: gh command timed out",
        retryable=True,
        retry_after_seconds=None,
    )


def _sleep_before_retry(
    *,
    attempt: int,
    backoff_delays: Sequence[float],
    max_retry_sleep: float,
    sleep_fn: Any,
    verdict: RetryabilityVerdictWire,
    stdout: str,
    stderr: str,
    time_fn: Any,
) -> None:
    delay = _retry_delay_seconds(
        attempt=attempt,
        backoff_delays=backoff_delays,
        verdict=verdict,
        stdout=stdout,
        stderr=stderr,
        now=time_fn(),
    )
    if max_retry_sleep > 0:
        delay = min(delay, max_retry_sleep)
    if delay > 0:
        sleep_fn(delay)


def _retry_delay_seconds(
    *,
    attempt: int,
    backoff_delays: Sequence[float],
    verdict: RetryabilityVerdictWire,
    stdout: str,
    stderr: str,
    now: float,
) -> float:
    if verdict.retry_after_seconds is not None:
        return max(0.0, float(verdict.retry_after_seconds))
    signal_delay = _delay_from_rate_limit_signal(stdout, stderr, now=now)
    if signal_delay is not None:
        return signal_delay
    if not backoff_delays:
        return 0.0
    return max(0.0, float(backoff_delays[min(attempt - 1, len(backoff_delays) - 1)]))


def _delay_from_rate_limit_signal(
    stdout: str,
    stderr: str,
    *,
    now: float,
) -> float | None:
    headers = f"{stderr}\n{stdout}"
    retry_after = _header_value(headers, "retry-after")
    if retry_after is not None:
        parsed = _parse_retry_after(retry_after, now=now)
        if parsed is not None:
            return parsed
    reset = _header_value(headers, "x-ratelimit-reset")
    if reset is not None:
        try:
            return max(0.0, float(reset.strip()) - now)
        except ValueError:
            return None
    return None


def _header_value(text: str, name: str) -> str | None:
    needle = name.casefold()
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip().casefold() == needle:
            return value.strip()
    return None


def _parse_retry_after(value: str, *, now: float) -> float | None:
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, parsed.timestamp() - now)


def _failure_message(
    args: Sequence[str],
    *,
    attempts: int,
    returncode: int | None,
    detail: str | None,
    timed_out: bool,
) -> str:
    attempt_word = "attempt" if attempts == 1 else "attempts"
    if timed_out:
        base = f"`{' '.join(args)}` timed out after {attempts} {attempt_word}"
    else:
        base = (
            f"`{' '.join(args)}` failed after {attempts} {attempt_word} "
            f"(exit {returncode})"
        )
    return f"{base}: {detail}" if detail else base


def _log_gh_operation(
    *,
    op: str,
    cmd: list[str],
    cwd: str | Path | None,
    status: str,
    duration_ms: float,
    timeout_seconds: float,
    returncode: int | None,
    stdout: str,
    stderr: str,
    attempt: int,
    attempts: int,
    verdict: RetryabilityVerdictWire | None,
) -> None:
    try:
        from sase.logs import log_tui_git_operation

        log_tui_git_operation(
            {
                "ts": time.time(),
                "event": "gh_operation",
                "operation": op,
                "status": status,
                "duration_ms": round(duration_ms, 3),
                "timeout_seconds": timeout_seconds,
                "returncode": returncode,
                "cwd": None if cwd is None else str(cwd),
                "cmd": cmd,
                "attempt": attempt,
                "attempts": attempts,
                "verdict": None if verdict is None else verdict.verdict,
                "retry_after_seconds": (
                    None if verdict is None else verdict.retry_after_seconds
                ),
                "stdout_preview": _preview_stream(stdout),
                "stderr_preview": _preview_stream(stderr),
            }
        )
    except Exception:
        _logger.debug("failed to write gh operation telemetry", exc_info=True)


def _first_nonempty_line(*texts: str) -> str | None:
    for text in texts:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return None


def _preview_stream(value: str, limit: int = 500) -> str | None:
    text = value.strip()
    if not text:
        return None
    return text[:limit]


def _stream_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _gh_timeout() -> float:
    return _float_env(ENV_GH_TIMEOUT, DEFAULT_GH_TIMEOUT_SECONDS)


def _max_retry_sleep_seconds() -> float:
    return _float_env(ENV_GH_MAX_RETRY_SLEEP, DEFAULT_MAX_RETRY_SLEEP_SECONDS)


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


__all__ = [
    "DEFAULT_GH_TIMEOUT_SECONDS",
    "GhCommandError",
    "GhCommandResult",
    "GhSubprocessRunner",
    "gh_api_json",
    "run_gh",
]
