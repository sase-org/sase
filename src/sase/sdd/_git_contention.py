"""Retry helpers for transient git lock contention in SDD stores."""

from collections.abc import Mapping
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from sase.sdd._git import run_sdd_git

ENV_GIT_LOCK_RETRY_DELAYS = "SASE_SDD_GIT_LOCK_RETRY_DELAYS"
DEFAULT_GIT_LOCK_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.6, 3.2)


class SddGitCommandError(subprocess.CalledProcessError):
    """A checked git failure whose message includes captured stderr."""

    @classmethod
    def from_error(cls, error: subprocess.CalledProcessError) -> "SddGitCommandError":
        return cls(
            error.returncode,
            error.cmd,
            output=error.output,
            stderr=error.stderr,
        )

    def __str__(self) -> str:
        message = super().__str__()
        detail = _stream_text(self.stderr).strip()
        return f"{message}: {detail}" if detail else message


def is_retryable_git_lock_error(
    returncode: int,
    stderr: str | bytes | None,
) -> bool:
    """Return whether git failed because another process holds a lock file."""
    if returncode != 128:
        return False
    detail = _stream_text(stderr).lower()
    return "index.lock" in detail or (
        "unable to create" in detail and ".lock" in detail
    )


def run_sdd_git_write(
    args: list[str],
    *,
    cwd: Path,
    op: str,
    timeout: float | None = None,
    check: bool,
    capture_output: bool,
    text: bool = False,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[Any]:
    """Run a git write, retrying boundedly on transient lock contention."""
    delays = _git_lock_retry_delays()
    retry_attempt = 0
    while True:
        result = run_sdd_git(
            args,
            cwd=cwd,
            op=op,
            timeout=timeout,
            check=False,
            capture_output=capture_output,
            text=text,
            env=env,
            always_log=retry_attempt > 0,
        )
        if not is_retryable_git_lock_error(result.returncode, result.stderr):
            return _checked_result(result, check=check)
        if retry_attempt >= len(delays):
            return _checked_result(result, check=check)
        time.sleep(delays[retry_attempt])
        retry_attempt += 1


def _checked_result(
    result: subprocess.CompletedProcess[Any],
    *,
    check: bool,
) -> subprocess.CompletedProcess[Any]:
    if check and result.returncode != 0:
        raise SddGitCommandError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def _git_lock_retry_delays() -> tuple[float, ...]:
    raw = os.environ.get(ENV_GIT_LOCK_RETRY_DELAYS)
    if raw is None:
        return DEFAULT_GIT_LOCK_RETRY_DELAYS
    try:
        delays = tuple(float(value.strip()) for value in raw.split(","))
    except ValueError:
        return DEFAULT_GIT_LOCK_RETRY_DELAYS
    if not delays or any(delay < 0 for delay in delays):
        return DEFAULT_GIT_LOCK_RETRY_DELAYS
    return delays


def _stream_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
