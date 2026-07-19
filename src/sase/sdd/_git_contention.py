"""Serialization and retry helpers for git writes in SDD stores."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import fcntl
import logging
import math
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from sase.git_lock_retry import (
    DEFAULT_GIT_LOCK_RETRY_DELAYS as SHARED_GIT_LOCK_RETRY_DELAYS,
    run_with_git_lock_retry,
)
from sase.sdd._git import run_sdd_git

ENV_GIT_LOCK_RETRY_DELAYS = "SASE_SDD_GIT_LOCK_RETRY_DELAYS"
DEFAULT_GIT_LOCK_RETRY_DELAYS = SHARED_GIT_LOCK_RETRY_DELAYS
ENV_STORE_WRITE_LOCK_TIMEOUT = "SASE_SDD_STORE_WRITE_LOCK_TIMEOUT"
DEFAULT_STORE_WRITE_LOCK_TIMEOUT_SECONDS = 10.0
STORE_WRITE_LOCK_FILENAME = "sase-store-write.lock"
_STORE_WRITE_LOCK_POLL_SECONDS = 0.05

_logger = logging.getLogger(__name__)


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
    attempts = 0

    def attempt() -> subprocess.CompletedProcess[Any]:
        nonlocal attempts
        result = run_sdd_git(
            args,
            cwd=cwd,
            op=op,
            timeout=timeout,
            check=False,
            capture_output=capture_output,
            text=text,
            env=env,
            always_log=attempts > 0,
        )
        attempts += 1
        return result

    result, _ = run_with_git_lock_retry(attempt, cwd=cwd, delays=delays)
    return _checked_result(result, check=check)


@contextmanager
def store_git_write_lock(
    repo_root: Path,
    *,
    timeout: float | None = None,
) -> Iterator[bool]:
    """Boundedly serialize a store-repo write transaction.

    The context yields whether the lock was acquired. Acquisition deliberately
    fails open after the timeout: transient git lock retries remain the final
    safety net if a non-cooperating or long-running process holds the lock.
    """
    timeout_seconds = (
        _store_write_lock_timeout() if timeout is None else max(0.0, timeout)
    )
    lock_path = _store_write_lock_path(repo_root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        acquired = _acquire_store_write_lock(
            lock_file.fileno(),
            timeout=timeout_seconds,
        )
        if not acquired:
            _logger.warning(
                "Timed out after %.3fs waiting for SDD store write lock %s; "
                "proceeding without it",
                timeout_seconds,
                lock_path,
            )
        try:
            yield acquired
        finally:
            if acquired:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


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
    if not delays or any(not math.isfinite(delay) or delay < 0 for delay in delays):
        return DEFAULT_GIT_LOCK_RETRY_DELAYS
    return delays


def _store_write_lock_timeout() -> float:
    raw = os.environ.get(ENV_STORE_WRITE_LOCK_TIMEOUT)
    if raw is None:
        return DEFAULT_STORE_WRITE_LOCK_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError:
        return DEFAULT_STORE_WRITE_LOCK_TIMEOUT_SECONDS
    return timeout if timeout >= 0 else DEFAULT_STORE_WRITE_LOCK_TIMEOUT_SECONDS


def _store_write_lock_path(repo_root: Path) -> Path:
    result = run_sdd_git(
        ["rev-parse", "--git-dir"],
        cwd=repo_root,
        op="sdd.store_write_lock.git_dir",
        check=False,
        capture_output=True,
        text=True,
    )
    raw_git_dir = result.stdout.strip() if result.returncode == 0 else ".git"
    git_dir = Path(raw_git_dir or ".git")
    if not git_dir.is_absolute():
        git_dir = repo_root / git_dir
    return git_dir / STORE_WRITE_LOCK_FILENAME


def _acquire_store_write_lock(fd: int, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(_STORE_WRITE_LOCK_POLL_SECONDS, remaining))


def _stream_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
