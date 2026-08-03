"""Serialization and retry helpers for git writes in SDD stores."""

from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
import fcntl
import functools
import json
import logging
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from sase.git_lock_retry import (
    DEFAULT_GIT_LOCK_RETRY_DELAYS as SHARED_GIT_LOCK_RETRY_DELAYS,
    git_lock_retry_delays,
    run_with_git_lock_retry,
)
from sase.sdd._git import run_sdd_git

ENV_GIT_LOCK_RETRY_DELAYS = "SASE_SDD_GIT_LOCK_RETRY_DELAYS"
DEFAULT_GIT_LOCK_RETRY_DELAYS = SHARED_GIT_LOCK_RETRY_DELAYS
ENV_STORE_WRITE_LOCK_TIMEOUT = "SASE_SDD_STORE_WRITE_LOCK_TIMEOUT"
DEFAULT_STORE_WRITE_LOCK_TIMEOUT_SECONDS = 10.0
# A worktree-mutating caller holds the lock across materialization, staging and
# commit, so a legitimate holder now does far more work than a single git write.
# Waiting minutes is cheaper than proceeding unlocked into another process's
# rebase, which is what produced the discarded bead claims this bound guards.
DEFAULT_WORKTREE_MUTATION_LOCK_TIMEOUT_SECONDS = 180.0
DEFAULT_STORE_WRITE_LOCK_SLOW_WAIT_SECONDS = 30.0
STORE_WRITE_LOCK_FILENAME = "sase-store-write.lock"
_STORE_WRITE_LOCK_POLL_SECONDS = 0.05

_logger = logging.getLogger(__name__)
_held_store_write_locks: ContextVar[frozenset[Path]] = ContextVar(
    "held_store_write_locks",
    default=frozenset(),
)


class _StoreWriteLockUsageError(RuntimeError):
    """Raised when store-lock ownership is nested or handed off incorrectly."""


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
    op: str | None = None,
    mutates_worktree: bool = False,
) -> Iterator[bool]:
    """Boundedly serialize a store-repo write transaction.

    The context yields whether the lock was acquired. Acquisition fails open
    after the timeout: transient git lock retries remain the final safety net
    for a single git command if a non-cooperating or long-running process holds
    the lock. That reasoning does not extend to a caller that mutates a shared
    worktree and needs the whole mutate-then-commit sequence to be atomic, so
    such callers pass ``mutates_worktree=True`` to wait far longer, and every
    one of them treats a false yield as a failure rather than proceeding.

    ``op`` names the operation in the fail-open warning, so the next incident
    identifies the caller that proceeded unlocked instead of only the clone.
    """
    default_timeout = (
        DEFAULT_WORKTREE_MUTATION_LOCK_TIMEOUT_SECONDS
        if mutates_worktree
        else DEFAULT_STORE_WRITE_LOCK_TIMEOUT_SECONDS
    )
    timeout_seconds = (
        _store_write_lock_timeout(default_timeout)
        if timeout is None
        else max(0.0, timeout)
    )
    lock_path = _canonical_store_write_lock_path(repo_root)
    held_locks = _held_store_write_locks.get()
    if lock_path in held_locks:
        raise _StoreWriteLockUsageError(
            f"SDD store write lock {lock_path} is already held by this context; "
            "use handoff_store_git_write_lock for an explicitly locked callee"
        )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        timer = _make_store_write_lock_timer(repo_root, op=op)
        holder_before_wait = _read_store_write_lock_holder(lock_file)
        wait_started = time.monotonic()
        acquired = _acquire_store_write_lock(
            lock_file.fileno(),
            timeout=timeout_seconds,
        )
        waited_seconds = time.monotonic() - wait_started
        holder = (
            holder_before_wait
            if acquired
            else _read_store_write_lock_holder(lock_file) or holder_before_wait
        )
        if acquired:
            _write_store_write_lock_holder(
                lock_file,
                {
                    "pid": os.getpid(),
                    "op": op or "an unnamed store write",
                    "acquired_at": datetime.now(UTC).isoformat(),
                },
            )
        _record_store_write_lock_wait(
            timer,
            waited_seconds=waited_seconds,
            acquired=acquired,
            holder=(
                holder
                if not acquired
                or waited_seconds >= DEFAULT_STORE_WRITE_LOCK_SLOW_WAIT_SECONDS
                else None
            ),
        )
        if not acquired:
            _logger.warning(
                "Timed out after %.3fs waiting for SDD store write lock %s "
                "during %s; proceeding without it%s",
                timeout_seconds,
                lock_path,
                op or "an unnamed store write",
                _format_store_write_lock_holder(holder),
            )
        elif waited_seconds >= DEFAULT_STORE_WRITE_LOCK_SLOW_WAIT_SECONDS:
            _logger.warning(
                "Slow SDD store write lock acquisition: waited %.3fs for %s "
                "during %s%s",
                waited_seconds,
                lock_path,
                op or "an unnamed store write",
                _format_store_write_lock_holder(holder),
            )
        token = None
        if acquired:
            token = _held_store_write_locks.set(held_locks | {lock_path})
        try:
            yield acquired
        finally:
            if acquired:
                assert token is not None
                _held_store_write_locks.reset(token)
                try:
                    _clear_store_write_lock_holder(lock_file)
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@contextmanager
def handoff_store_git_write_lock(repo_root: Path) -> Iterator[bool]:
    """Hand an already-held store write lock to a nested transaction.

    This is the explicit counterpart to :func:`store_git_write_lock`. It never
    opens or acquires another descriptor, and it fails loudly unless the
    current execution context owns the canonical lock for *repo_root*.
    """
    lock_path = _canonical_store_write_lock_path(repo_root)
    if lock_path not in _held_store_write_locks.get():
        raise _StoreWriteLockUsageError(
            f"cannot hand off SDD store write lock {lock_path}: "
            "the current context does not hold it"
        )
    yield True


def store_write_lock_is_held(repo_root: Path) -> bool:
    """Report whether this context already owns *repo_root*'s store lock.

    Callers that accept an ``already_locked`` flag but fan out over several
    store repositories use this to hand off only the repository the flag
    actually describes, and to acquire the others normally.
    """
    return _canonical_store_write_lock_path(repo_root) in _held_store_write_locks.get()


def store_git_write_lock_factory(
    *,
    op: str,
    mutates_worktree: bool = False,
    timeout: float | None = None,
) -> Callable[[Path], AbstractContextManager[bool]]:
    """Bind an operation label to the store write lock for ``LockFactory`` use.

    Callers that thread a lock factory through an API (integration, recovery)
    cannot pass keywords at the acquisition site, so they bind them here.
    """
    if timeout is None:
        # Preserve the historical call shape for injected lock factories and
        # let store_git_write_lock select its normal context-sensitive default.
        return functools.partial(
            store_git_write_lock,
            op=op,
            mutates_worktree=mutates_worktree,
        )
    return functools.partial(
        store_git_write_lock,
        op=op,
        mutates_worktree=mutates_worktree,
        timeout=timeout,
    )


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
        return git_lock_retry_delays()
    try:
        delays = tuple(float(value.strip()) for value in raw.split(","))
    except ValueError:
        return DEFAULT_GIT_LOCK_RETRY_DELAYS
    if not delays or any(delay < 0 for delay in delays):
        return DEFAULT_GIT_LOCK_RETRY_DELAYS
    return delays


def _store_write_lock_timeout(default: float) -> float:
    """Resolve the wait bound, letting one env var override every caller.

    The bound stays configurable through a single knob on purpose: operators
    tune store-lock patience for a whole machine, not per call site.
    """
    raw = os.environ.get(ENV_STORE_WRITE_LOCK_TIMEOUT)
    if raw is None:
        return default
    try:
        timeout = float(raw)
    except ValueError:
        return default
    return timeout if timeout >= 0 else default


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


def _canonical_store_write_lock_path(repo_root: Path) -> Path:
    return _store_write_lock_path(repo_root).resolve(strict=False)


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


def _make_store_write_lock_timer(repo_root: Path, *, op: str | None) -> Any:
    try:
        from sase.agent.launch_timing import LaunchTimingRecorder

        return LaunchTimingRecorder(
            "store_git_write_lock",
            {
                "op": op or "an unnamed store write",
                "repo_root": str(repo_root.expanduser().resolve(strict=False)),
            },
            durable=True,
        )
    except Exception:
        _logger.debug("Store write lock timing setup failed", exc_info=True)
        return None


def _record_store_write_lock_wait(
    timer: Any,
    *,
    waited_seconds: float,
    acquired: bool,
    holder: dict[str, Any] | None,
) -> None:
    if timer is None:
        return
    try:
        waited_ms = waited_seconds * 1000.0
        outcome = "acquired" if acquired else "failed_open"
        fields: dict[str, Any] = {
            "waited_ms": waited_ms,
            "acquired": acquired,
            "failed_open": not acquired,
            "outcome": outcome,
        }
        if holder is not None:
            fields["holder"] = holder
        timer.fields.update(fields)
        timer.mark("store_write_lock_wait", elapsed_ms=waited_ms, **fields)
        timer.finish(outcome=outcome)
    except Exception:
        _logger.debug("Store write lock timing record failed", exc_info=True)


def _read_store_write_lock_holder(lock_file: Any) -> dict[str, Any] | None:
    try:
        lock_file.seek(0)
        raw = lock_file.read().strip()
        value = json.loads(raw)
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _write_store_write_lock_holder(
    lock_file: Any,
    holder: dict[str, Any],
) -> None:
    try:
        lock_file.seek(0)
        lock_file.truncate()
        json.dump(holder, lock_file, sort_keys=True)
        lock_file.flush()
    except OSError:
        _logger.debug("Failed to write store lock holder", exc_info=True)


def _clear_store_write_lock_holder(lock_file: Any) -> None:
    try:
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.flush()
    except OSError:
        _logger.debug("Failed to clear store lock holder", exc_info=True)


def _format_store_write_lock_holder(holder: dict[str, Any] | None) -> str:
    if holder is None:
        return ""
    return (
        f"; holder pid {holder.get('pid', 'unknown')} is running "
        f"{holder.get('op', 'an unknown operation')} "
        f"(acquired {holder.get('acquired_at', 'at an unknown time')})"
    )


def _stream_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
