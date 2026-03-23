"""File locking for ChangeSpec files to prevent race conditions."""

import fcntl
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager


class LockTimeoutError(Exception):
    """Raised when file lock acquisition times out."""

    def __init__(self, lock_file: str, timeout: float) -> None:
        self.lock_file = lock_file
        self.timeout = timeout
        super().__init__(f"Timeout waiting for lock on {lock_file} after {timeout}s")


@contextmanager
def changespec_lock(
    project_file: str,
    exclusive: bool = True,
    timeout: float = 30.0,
    poll_interval: float = 0.1,
) -> Iterator[None]:
    """Context manager for locking a ChangeSpec file.

    Uses fcntl.flock() for advisory locking. All processes must cooperate
    by using this lock for exclusive access to be effective.

    Args:
        project_file: Path to the .gp file to lock.
        exclusive: If True (default), acquire exclusive write lock.
                  If False, acquire shared read lock.
        timeout: Maximum seconds to wait for lock (default 30).
        poll_interval: Seconds between lock acquisition attempts (default 0.1).

    Raises:
        LockTimeoutError: If lock cannot be acquired within timeout.

    Example:
        with changespec_lock(project_file):
            content = Path(project_file).read_text()
            # ... modify content ...
            write_changespec_atomic(project_file, content, "Update XYZ")
    """
    lock_file = f"{project_file}.lock"

    # Create lock file directory if needed
    lock_dir = os.path.dirname(lock_file)
    if lock_dir and not os.path.exists(lock_dir):
        os.makedirs(lock_dir, exist_ok=True)

    # Open lock file (create if needed)
    fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o644)
    lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH

    try:
        start = time.monotonic()
        while True:
            try:
                fcntl.flock(fd, lock_type | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() - start >= timeout:
                    os.close(fd)
                    raise LockTimeoutError(lock_file, timeout) from None
                time.sleep(poll_interval)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def acquire_edit_lock(project_file: str) -> None:
    """Create a .edit_lock sentinel file containing the current PID.

    Args:
        project_file: Path to the .gp file to lock.
    """
    lock_file = f"{project_file}.edit_lock"
    lock_dir = os.path.dirname(lock_file)
    if lock_dir and not os.path.exists(lock_dir):
        os.makedirs(lock_dir, exist_ok=True)
    with open(lock_file, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))


def release_edit_lock(project_file: str) -> None:
    """Remove the .edit_lock sentinel file.

    Args:
        project_file: Path to the .gp file to unlock.
    """
    lock_file = f"{project_file}.edit_lock"
    try:
        os.unlink(lock_file)
    except FileNotFoundError:
        pass


def is_edit_locked(project_file: str) -> bool:
    """Check if a project file has an active edit lock.

    Returns True if .edit_lock exists AND the PID within is still alive.
    Removes stale lock files (dead PID) and returns False.

    Args:
        project_file: Path to the .gp file to check.
    """
    lock_file = f"{project_file}.edit_lock"
    try:
        with open(lock_file, encoding="utf-8") as f:
            pid = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return False

    # Check if the process is still alive
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        # Process is dead — stale lock
        try:
            os.unlink(lock_file)
        except FileNotFoundError:
            pass
        return False
    except PermissionError:
        # Process exists but we can't signal it — treat as locked
        return True

    return True


def write_changespec_atomic(
    project_file: str,
    content: str,
    _commit_message: str = "",
) -> None:
    """Write content to a ChangeSpec file atomically.

    This function should be called WHILE holding a lock on the file.
    It handles the temp file + os.replace() pattern.

    Skips the write entirely if the new content is identical to what is
    already on disk, avoiding unnecessary file modifications (which can
    trigger editor warnings, inotify events, etc.).

    Args:
        project_file: Path to the .gp file.
        content: The full file content to write.
        _commit_message: Deprecated, ignored. Kept for call-site compat.
    """
    # Skip write if content hasn't changed
    try:
        with open(project_file, encoding="utf-8") as f:
            existing = f.read()
        if existing == content:
            return
    except FileNotFoundError:
        pass

    project_dir = os.path.dirname(project_file)
    fd, temp_path = tempfile.mkstemp(dir=project_dir, prefix=".tmp_", suffix=".gp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(temp_path, project_file)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
