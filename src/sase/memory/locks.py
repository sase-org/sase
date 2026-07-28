"""Shared lock helpers for memory state files."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import errno
import fcntl
from pathlib import Path
import time


class LockTimeoutError(TimeoutError):
    """Raised when a file lock cannot be acquired within the timeout."""

    def __init__(self, lock_path: Path, timeout: float) -> None:
        self.lock_path = lock_path
        self.timeout = timeout
        super().__init__(f"Timeout waiting for lock on {lock_path} after {timeout:g}s")


@contextmanager
def locked_file(
    lock_path: Path,
    flags: int,
    *,
    timeout: float | None = None,
    poll_interval: float = 0.1,
    on_wait: Callable[[Path], None] | None = None,
) -> Iterator[None]:
    """Hold a flock on ``lock_path`` for the duration of the context."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock_file:
        acquired = False
        try:
            if timeout is None:
                fcntl.flock(lock_file.fileno(), flags)
                acquired = True
            else:
                acquired = _acquire_with_timeout(
                    lock_file.fileno(),
                    flags,
                    lock_path=lock_path,
                    timeout=timeout,
                    poll_interval=poll_interval,
                    on_wait=on_wait,
                )
            yield
        finally:
            if acquired:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _acquire_with_timeout(
    fd: int,
    flags: int,
    *,
    lock_path: Path,
    timeout: float,
    poll_interval: float,
    on_wait: Callable[[Path], None] | None,
) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    announced = False
    while True:
        try:
            fcntl.flock(fd, flags | fcntl.LOCK_NB)
            return True
        except OSError as exc:
            if not _is_lock_unavailable(exc):
                raise

        if not announced and on_wait is not None:
            on_wait(lock_path)
            announced = True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LockTimeoutError(lock_path, timeout)
        time.sleep(min(max(0.0, poll_interval), remaining))


def _is_lock_unavailable(exc: OSError) -> bool:
    return isinstance(exc, BlockingIOError) or exc.errno in {
        errno.EACCES,
        errno.EAGAIN,
    }
