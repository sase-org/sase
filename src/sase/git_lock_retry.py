"""Shared retry and stale-lock recovery policy for git commands."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any

ENV_GIT_LOCK_RETRY_DELAYS = "SASE_GIT_LOCK_RETRY_DELAYS"
DEFAULT_GIT_LOCK_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.6, 3.2)
STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS = 15.0

_logger = logging.getLogger(__name__)
_UNABLE_TO_CREATE_LOCK_RE = re.compile(
    r"unable to create\s+(['\"])(?P<path>.+?index\.lock)\1",
    re.IGNORECASE,
)

type GitLockResultAdapter[ResultT] = Callable[[ResultT], tuple[int, str | bytes | None]]


@dataclass(frozen=True, slots=True)
class GitLockRetryOutcome:
    """Details about the attempts made by :func:`run_with_git_lock_retry`."""

    attempts: int
    lock_removed: bool = False
    lock_path: Path | None = None

    @property
    def attempts_made(self) -> int:
        """Return the attempt count using the plan's descriptive name."""
        return self.attempts


@dataclass(frozen=True, slots=True)
class _LockIdentity:
    inode: int
    mtime_ns: int
    size: int


def is_retryable_git_lock_error(
    returncode: int,
    output: str | bytes | None,
) -> bool:
    """Return whether git failed because another process holds a lock file."""
    if returncode != 128:
        return False
    detail = _stream_text(output).lower()
    return "index.lock" in detail or (
        "unable to create" in detail and ".lock" in detail
    )


def git_lock_retry_delays() -> tuple[float, ...]:
    """Return the configured bounded backoff schedule for git lock failures."""
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


def git_index_lock_path(workspace_dir: str | Path) -> Path | None:
    """Resolve the ``index.lock`` path for *workspace_dir*'s git dir, if any."""
    workspace_path = Path(workspace_dir).expanduser().resolve(strict=False)
    git_path = workspace_path / ".git"
    if git_path.is_dir():
        return git_path / "index.lock"
    # Worktrees/submodules store ``.git`` as a file pointing at the real git
    # dir; ask git where the index lives instead of guessing.
    if not git_path.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    git_dir = result.stdout.strip()
    if result.returncode != 0 or not git_dir:
        return None
    git_dir_path = Path(git_dir)
    if not git_dir_path.is_absolute():
        git_dir_path = workspace_path / git_dir_path
    return git_dir_path.resolve(strict=False) / "index.lock"


def run_with_git_lock_retry[ResultT](
    attempt: Callable[[], ResultT],
    *,
    cwd: str | Path,
    result_adapter: GitLockResultAdapter[ResultT] | None = None,
    delays: Iterable[float] | None = None,
    allow_lock_removal: bool = True,
) -> tuple[ResultT, GitLockRetryOutcome]:
    """Run *attempt* with bounded retry and safe stale-lock recovery.

    The native result object is returned unchanged. ``result_adapter`` converts
    that object to ``(returncode, error_output)`` for classification; objects
    with ``returncode``, ``stderr``, and ``stdout`` attributes use the default
    adapter automatically.
    """
    retry_delays = (
        git_lock_retry_delays() if delays is None else _validated_retry_delays(delays)
    )
    adapter = result_adapter or _default_result_adapter
    repo_path = Path(cwd).expanduser().resolve(strict=False)

    result = attempt()
    attempts = 1
    returncode, output = adapter(result)
    if not is_retryable_git_lock_error(returncode, output):
        return result, GitLockRetryOutcome(attempts=attempts)

    first_lock_path = _resolved_error_index_lock_path(repo_path, output)
    latest_lock_path = first_lock_path
    first_identity = _lock_identity(first_lock_path)
    identity_unchanged = first_identity is not None

    for delay in retry_delays:
        _logger.warning(
            "Git lock contention in %s; retrying attempt %d/%d after %.3fs "
            "(lock=%s, age=%s)",
            repo_path,
            attempts + 1,
            len(retry_delays) + 1,
            delay,
            latest_lock_path or "unknown",
            _format_lock_age(_lock_age_seconds(latest_lock_path)),
        )
        time.sleep(delay)
        result = attempt()
        attempts += 1
        returncode, output = adapter(result)
        if not is_retryable_git_lock_error(returncode, output):
            return result, GitLockRetryOutcome(
                attempts=attempts,
                lock_path=latest_lock_path,
            )

        current_lock_path = _resolved_error_index_lock_path(repo_path, output)
        current_identity = _lock_identity(current_lock_path)
        if current_lock_path != first_lock_path or current_identity != first_identity:
            identity_unchanged = False
        latest_lock_path = current_lock_path

    if not allow_lock_removal or latest_lock_path is None:
        return result, GitLockRetryOutcome(
            attempts=attempts,
            lock_path=latest_lock_path,
        )

    final_identity = _lock_identity(latest_lock_path)
    if final_identity != first_identity:
        identity_unchanged = False
    lock_age = _lock_age_seconds(latest_lock_path)
    persisted_through_retries = sum(retry_delays) > 0 and identity_unchanged
    old_enough = (
        lock_age is not None and lock_age >= STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS
    )
    if not (persisted_through_retries or old_enough):
        return result, GitLockRetryOutcome(
            attempts=attempts,
            lock_path=latest_lock_path,
        )

    if not _remove_lock_if_unchanged(latest_lock_path, final_identity):
        _logger.warning(
            "Failed to remove stale git index lock in %s after attempt %d "
            "(lock=%s, age=%s)",
            repo_path,
            attempts,
            latest_lock_path,
            _format_lock_age(lock_age),
        )
        return result, GitLockRetryOutcome(
            attempts=attempts,
            lock_path=latest_lock_path,
        )

    _logger.warning(
        "Removed stale git index lock in %s after attempt %d "
        "(lock=%s, age=%s); retrying once",
        repo_path,
        attempts,
        latest_lock_path,
        _format_lock_age(lock_age),
    )
    result = attempt()
    attempts += 1
    return result, GitLockRetryOutcome(
        attempts=attempts,
        lock_removed=True,
        lock_path=latest_lock_path,
    )


def _validated_retry_delays(delays: Iterable[float]) -> tuple[float, ...]:
    values = tuple(float(delay) for delay in delays)
    if any(delay < 0 for delay in values):
        raise ValueError("git lock retry delays must be non-negative")
    return values


def _default_result_adapter(result: Any) -> tuple[int, str | bytes | None]:
    try:
        returncode = int(result.returncode)
    except (AttributeError, TypeError, ValueError) as error:
        raise TypeError(
            "result_adapter is required for results without an integer returncode"
        ) from error
    stderr = getattr(result, "stderr", None)
    stdout = getattr(result, "stdout", None)
    output = "\n".join(
        detail for value in (stderr, stdout) if (detail := _stream_text(value))
    )
    return returncode, output


def _resolved_error_index_lock_path(
    repo_path: Path,
    output: str | bytes | None,
) -> Path | None:
    detail = _stream_text(output)
    if "index.lock" not in detail.lower():
        return None

    canonical_path = git_index_lock_path(repo_path)
    if canonical_path is None:
        return None
    canonical_path = canonical_path.resolve(strict=False)

    match = _UNABLE_TO_CREATE_LOCK_RE.search(detail)
    if match is not None:
        parsed_path = Path(match.group("path"))
        if parsed_path.is_absolute():
            candidate = parsed_path.resolve(strict=False)
            return candidate if candidate == canonical_path else None
    return canonical_path


def _lock_identity(lock_path: Path | None) -> _LockIdentity | None:
    if lock_path is None:
        return None
    try:
        stat = lock_path.stat()
    except OSError:
        return None
    return _LockIdentity(
        inode=stat.st_ino,
        mtime_ns=stat.st_mtime_ns,
        size=stat.st_size,
    )


def _lock_age_seconds(lock_path: Path | None) -> float | None:
    if lock_path is None:
        return None
    try:
        return max(0.0, time.time() - lock_path.stat().st_mtime)
    except OSError:
        return None


def _remove_lock_if_unchanged(
    lock_path: Path,
    expected_identity: _LockIdentity | None,
) -> bool:
    if expected_identity is None or _lock_identity(lock_path) != expected_identity:
        return False
    try:
        lock_path.unlink()
    except OSError:
        return False
    return True


def _format_lock_age(age_seconds: float | None) -> str:
    return "unknown" if age_seconds is None else f"{age_seconds:.3f}s"


def _stream_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else ""


__all__ = [
    "DEFAULT_GIT_LOCK_RETRY_DELAYS",
    "ENV_GIT_LOCK_RETRY_DELAYS",
    "GitLockResultAdapter",
    "GitLockRetryOutcome",
    "STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS",
    "git_index_lock_path",
    "git_lock_retry_delays",
    "is_retryable_git_lock_error",
    "run_with_git_lock_retry",
]
