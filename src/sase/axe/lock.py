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
    return axe_state.axe_state_dir() / "orchestrator.lock"


def _read_recorded_lock_holder_pid() -> int | None:
    """Read the PID recorded in the lifecycle lock file, if present."""
    path = _axe_lifecycle_lock_path()
    try:
        raw = path.read_text().strip()
    except OSError:
        return None
    try:
        pid = int(raw)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _find_proc_lock_holder_pid() -> int | None:
    """Find the process currently holding the lifecycle flock on Linux."""
    path = _axe_lifecycle_lock_path()
    try:
        stat = path.stat()
    except OSError:
        return None

    target_major = os.major(stat.st_dev)
    target_minor = os.minor(stat.st_dev)
    target_inode = stat.st_ino

    try:
        with open("/proc/locks") as locks_file:
            lines = locks_file.readlines()
    except OSError:
        return None

    for line in lines:
        parts = line.split()
        if len(parts) < 6 or parts[1] != "FLOCK":
            continue
        try:
            pid = int(parts[4])
        except ValueError:
            continue

        lock_id = parts[5].split(":")
        if len(lock_id) != 3:
            continue
        major_text, minor_text, inode_text = lock_id
        try:
            major = int(major_text, 16)
            minor = int(minor_text, 16)
            inode = int(inode_text)
        except ValueError:
            continue
        if major == target_major and minor == target_minor and inode == target_inode:
            return pid if pid > 0 else None
    return None


def read_lock_holder_pid() -> int | None:
    """Return the lifecycle lock holder PID when it can be determined."""
    recorded_pid = _read_recorded_lock_holder_pid()
    if recorded_pid is not None:
        from sase.ace.hooks.processes import is_process_running

        if is_process_running(recorded_pid):
            return recorded_pid

    proc_holder_pid = _find_proc_lock_holder_pid()
    if proc_holder_pid is not None and proc_holder_pid != os.getpid():
        return proc_holder_pid
    return recorded_pid


def clear_lock_holder_pid() -> None:
    """Clear any recorded holder PID from the lifecycle lock file."""
    path = _axe_lifecycle_lock_path()
    try:
        with open(path, "r+") as lock_file:
            lock_file.truncate(0)
    except OSError:
        pass


def is_lifecycle_lock_held() -> bool:
    """Return True when another process currently holds the lifecycle lock."""
    lock = AxeLifecycleLock.acquire(blocking=False)
    if lock is None:
        return True
    lock.release()
    return False


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

    def write_holder_pid(self, pid: int | None = None) -> None:
        """Record the PID of the process that owns the lifecycle lock."""
        if self._fd is None:
            raise RuntimeError("Axe lifecycle lock is closed")
        holder_pid = os.getpid() if pid is None else pid
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.ftruncate(self._fd, 0)
        os.write(self._fd, f"{holder_pid}\n".encode())
        os.fsync(self._fd)

    def clear_holder_pid(self) -> None:
        """Clear the recorded lifecycle lock holder PID."""
        if self._fd is None:
            return
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.ftruncate(self._fd, 0)
        os.fsync(self._fd)

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
