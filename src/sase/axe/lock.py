"""Lifecycle locking for the axe orchestrator."""

from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path
from types import TracebackType

from . import state as axe_state

AXE_LOCK_FD_ENV = "SASE_AXE_LIFECYCLE_LOCK_FD"


def _axe_lifecycle_lock_path() -> Path:
    """Return the axe lifecycle lock file path."""
    return axe_state.AXE_STATE_DIR / "orchestrator.lock"


class AxeLifecycleLock:
    """Exclusive flock held by the live axe orchestrator."""

    def __init__(self, fd: int) -> None:
        self._fd: int | None = fd

    @classmethod
    def acquire(cls, *, blocking: bool) -> AxeLifecycleLock | None:
        """Acquire the lifecycle lock.

        Returns None when ``blocking`` is false and another process owns the
        lock.
        """
        path = _axe_lifecycle_lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB

        try:
            fcntl.flock(fd, flags)
        except OSError as e:
            os.close(fd)
            if not blocking and e.errno in (errno.EACCES, errno.EAGAIN):
                return None
            raise

        return cls(fd)

    @classmethod
    def from_inherited_env(cls) -> AxeLifecycleLock | None:
        """Adopt a lock fd passed by ``start_axe_daemon``."""
        value = os.environ.pop(AXE_LOCK_FD_ENV, None)
        if value is None:
            return None

        try:
            fd = int(value)
            os.fstat(fd)
        except (OSError, ValueError):
            return None

        return cls(fd)

    @property
    def fd(self) -> int:
        """Return the underlying file descriptor."""
        if self._fd is None:
            raise RuntimeError("Axe lifecycle lock is closed")
        return self._fd

    def release(self) -> None:
        """Unlock and close the lock fd."""
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    def close_after_handoff(self) -> None:
        """Close the parent fd after the child has inherited the lock.

        This intentionally does not call LOCK_UN: the lock is tied to the
        inherited open file description and remains held by the child.
        """
        if self._fd is None:
            return
        os.close(self._fd)
        self._fd = None

    def __enter__(self) -> AxeLifecycleLock:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.release()


def acquire_axe_lifetime_lock() -> AxeLifecycleLock | None:
    """Acquire or adopt the orchestrator's lifetime lock."""
    inherited = AxeLifecycleLock.from_inherited_env()
    if inherited is not None:
        return inherited
    return AxeLifecycleLock.acquire(blocking=False)
