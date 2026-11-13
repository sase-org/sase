"""File locking for ProjectSpec Patch files."""

import errno
import fcntl
import logging
import os
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class _UnparseableEditLock:
    """Sentinel for an edit lock file that is present but unparseable.

    A single shared instance marks "the lock pathname exists but holds no
    parseable ``PID`` line" (empty file, partial fallback publication, or a
    write by an older sase version). It is distinct from ``None``, which
    means the lock pathname is missing.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "<unparseable edit lock>"


_UNPARSEABLE_EDIT_LOCK = _UnparseableEditLock()

_UNPARSEABLE_LOCK_GRACE_SECONDS = 5.0

_LINK_FALLBACK_ERRNOS = frozenset(
    code
    for name in ("EPERM", "ENOTSUP", "EOPNOTSUPP", "EXDEV", "EMLINK", "ENOSYS")
    if (code := getattr(errno, name, None)) is not None
)


class LockTimeoutError(Exception):
    """Raised when file lock acquisition times out."""

    def __init__(self, lock_file: str, timeout: float) -> None:
        self.lock_file = lock_file
        self.timeout = timeout
        super().__init__(f"Timeout waiting for lock on {lock_file} after {timeout}s")


def _process_start_token(pid: int) -> str | None:
    """Return a stable token for this incarnation of a process, when available."""
    try:
        # The comm field is parenthesized and may itself contain spaces or ')'.
        with open(f"/proc/{pid}/stat", encoding="utf-8") as stat_file:
            stat = stat_file.read()
        fields_after_comm = stat[stat.rfind(")") + 2 :].split()
        return f"linux:{fields_after_comm[19]}"  # field 22: process start time
    except (FileNotFoundError, PermissionError, IndexError, OSError):
        pass

    # macOS and other Unix systems without procfs expose process start time via ps.
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            check=False,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    start = result.stdout.strip()
    return f"ps:{start}" if result.returncode == 0 and start else None


def _read_edit_lock(
    project_file: str,
) -> tuple[int, str | None] | _UnparseableEditLock | None:
    """Read PID and optional start token from an edit lock file.

    PID-only files are accepted for compatibility with locks written by older
    versions. New locks use ``PID\nTOKEN`` to distinguish recycled PIDs.

    Returns ``None`` when the lock pathname is missing and the shared
    ``_UNPARSEABLE_EDIT_LOCK`` sentinel when the pathname exists but holds
    no parseable ``PID`` line (empty file, partial fallback publication, or
    a write by an older sase version).
    """
    lock_file = f"{project_file}.edit_lock"
    try:
        with open(lock_file, encoding="utf-8") as f:
            lines = f.read().splitlines()
        pid = int(lines[0])
        token = lines[1] if len(lines) > 1 else None
        return pid, token
    except FileNotFoundError:
        return None
    except (ValueError, IndexError):
        return _UNPARSEABLE_EDIT_LOCK


def _unparseable_lock_is_fresh(project_file: str) -> bool:
    """Return whether a present-but-unparseable lock is within its grace window."""
    try:
        mtime = os.stat(f"{project_file}.edit_lock").st_mtime
    except OSError:
        return False
    return (time.time() - mtime) < _UNPARSEABLE_LOCK_GRACE_SECONDS


def _remove_stale_edit_lock(
    project_file: str,
    expected: tuple[int, str | None] | _UnparseableEditLock | None,
) -> bool:
    """Remove a stale lock while serializing competing stale-lock reapers."""
    lock_file = f"{project_file}.edit_lock"
    try:
        fd = os.open(lock_file, os.O_RDONLY)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        # Recheck both content and inode after locking; another reaper may have
        # replaced this pathname while we waited on the old inode.
        if _read_edit_lock(project_file) != expected:
            return False
        try:
            path_stat = os.stat(lock_file)
            fd_stat = os.fstat(fd)
            if (path_stat.st_dev, path_stat.st_ino) != (fd_stat.st_dev, fd_stat.st_ino):
                return False
            os.unlink(lock_file)
            return True
        except FileNotFoundError:
            return True
    finally:
        os.close(fd)


def acquire_edit_lock(project_file: str) -> None:
    """Create an exclusive .edit_lock sentinel for the current process.

    The lock content is published atomically: it is written to a unique
    temp file in the lock's directory and published with ``os.link`` so
    the lock pathname is never visible empty or partial. On filesystems
    without hard-link support the legacy ``O_CREAT | O_EXCL`` + write path
    is used; a fresh unparseable lock is then treated as held for a short
    grace window (see ``_UNPARSEABLE_LOCK_GRACE_SECONDS``).

    Args:
        project_file: Path to the .gp file to lock.
    """
    lock_file = f"{project_file}.edit_lock"
    lock_dir = os.path.dirname(lock_file)
    if lock_dir and not os.path.exists(lock_dir):
        os.makedirs(lock_dir, exist_ok=True)
    publish_dir = lock_dir or "."
    pid = os.getpid()
    start_token = _process_start_token(pid)
    contents = f"{pid}\n{start_token or ''}\n".encode()
    while True:
        temp_path: str | None = None
        temp_fd: int | None = None
        try:
            temp_fd, temp_path = tempfile.mkstemp(
                dir=publish_dir, prefix=".edit_lock_tmp_"
            )
            try:
                os.write(temp_fd, contents)
            except BaseException:
                try:
                    os.close(temp_fd)
                except OSError:
                    pass
                temp_fd = None
                raise
            try:
                os.close(temp_fd)
            except OSError:
                temp_fd = None
                raise
            temp_fd = None
            try:
                os.link(temp_path, lock_file)
            except FileExistsError:
                raise
            except OSError as exc:
                if exc.errno not in _LINK_FALLBACK_ERRNOS:
                    raise
                try:
                    fallback_fd = os.open(
                        lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
                    )
                except FileExistsError:
                    raise
                try:
                    os.write(fallback_fd, contents)
                except BaseException:
                    try:
                        os.close(fallback_fd)
                    except OSError:
                        pass
                    try:
                        os.unlink(lock_file)
                    except FileNotFoundError:
                        pass
                    raise
                else:
                    os.close(fallback_fd)
                    return
            else:
                return
        except FileExistsError:
            existing = _read_edit_lock(project_file)
            if existing is None:
                continue
            if isinstance(existing, _UnparseableEditLock):
                if _unparseable_lock_is_fresh(project_file):
                    raise
                _remove_stale_edit_lock(project_file, existing)
                continue
            if _is_edit_lock_active(existing):
                raise
            _remove_stale_edit_lock(project_file, existing)
            continue
        finally:
            if temp_fd is not None:
                try:
                    os.close(temp_fd)
                except OSError:
                    pass
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass


def release_edit_lock(project_file: str) -> None:
    """Remove the .edit_lock sentinel file when this process owns it.

    The lock is unlinked only when it records this process's PID (and, when
    the lock records a non-empty start token, the current start token
    matches, unless the current token is unavailable). Stale ownership uses
    the same flock plus inode/content recheck as ``_remove_stale_edit_lock``.
    A missing lock is a no-op; a lock owned by another process is left in
    place with a debug log.

    Args:
        project_file: Path to the .gp file to unlock.
    """
    lock_file = f"{project_file}.edit_lock"
    try:
        fd = os.open(lock_file, os.O_RDONLY)
    except FileNotFoundError:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        current = _read_edit_lock(project_file)
        if current is None:
            return
        if isinstance(current, _UnparseableEditLock):
            logger.debug("Not releasing unparseable edit lock for %s", project_file)
            return
        lock_pid, recorded_token = current
        if lock_pid != os.getpid():
            logger.debug(
                "Not releasing edit lock for %s owned by PID %d", project_file, lock_pid
            )
            return
        if recorded_token:
            current_token = _process_start_token(lock_pid)
            if current_token is not None and current_token != recorded_token:
                logger.debug(
                    "Not releasing edit lock for %s with mismatched start token",
                    project_file,
                )
                return
        try:
            path_stat = os.stat(lock_file)
            fd_stat = os.fstat(fd)
        except FileNotFoundError:
            return
        if (path_stat.st_dev, path_stat.st_ino) != (fd_stat.st_dev, fd_stat.st_ino):
            return
        try:
            os.unlink(lock_file)
        except FileNotFoundError:
            pass
    finally:
        os.close(fd)


def is_edit_locked(project_file: str) -> bool:
    """Check if a project file has an active edit lock.

    Returns True if .edit_lock exists AND the PID within is still alive.
    Removes stale lock files (dead PID) and returns False. A
    present-but-unparseable lock counts as held while it is within the
    grace window; older unparseable locks are reclaimed.

    Args:
        project_file: Path to the .gp file to check.
    """
    lock = _read_edit_lock(project_file)
    if lock is None:
        return False
    if isinstance(lock, _UnparseableEditLock):
        if _unparseable_lock_is_fresh(project_file):
            return True
        _remove_stale_edit_lock(project_file, lock)
        return False
    if _is_edit_lock_active(lock):
        return True
    _remove_stale_edit_lock(project_file, lock)
    return False


def _is_edit_lock_active(lock: tuple[int, str | None]) -> bool:
    pid, recorded_start = lock
    if recorded_start is not None:
        current_start = _process_start_token(pid)
        if current_start is not None and current_start != recorded_start:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_for_edit_lock_release(
    project_file: str,
    poll_interval: float = 0.5,
    timeout: float = 14400,
) -> None:
    """Block until the edit lock on project_file is released.

    Same-process exemption: returns immediately if the lock is held by
    the current process (os.getpid()).

    Args:
        project_file: Path to the .gp file.
        poll_interval: Seconds between checks.
        timeout: Maximum seconds to wait before raising LockTimeoutError.
    """
    lock = _read_edit_lock(project_file)
    if lock is None:
        return
    if not isinstance(lock, _UnparseableEditLock) and lock[0] == os.getpid():
        return

    if not is_edit_locked(project_file):
        return

    basename = os.path.basename(project_file)
    if isinstance(lock, _UnparseableEditLock):
        logger.info("Waiting for edit lock on %s ...", basename)
    else:
        logger.info("Waiting for edit lock on %s (PID %d)...", basename, lock[0])

    start = time.monotonic()
    while is_edit_locked(project_file):
        if time.monotonic() - start >= timeout:
            raise LockTimeoutError(f"{project_file}.edit_lock", timeout)
        time.sleep(poll_interval)

    logger.info("Edit lock released on %s, proceeding", basename)


@contextmanager
def patch_lock(
    project_file: str,
    exclusive: bool = True,
    timeout: float = 30.0,
    poll_interval: float = 0.1,
) -> Iterator[None]:
    """Context manager for locking a ProjectSpec file.

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
        with patch_lock(project_file):
            content = Path(project_file).read_text()
            # ... modify content ...
            write_patch_atomic(project_file, content, "Update XYZ")
    """
    if exclusive:
        wait_for_edit_lock_release(project_file)

    lock_file = f"{project_file}.lock"

    # Create lock file directory if needed
    lock_dir = os.path.dirname(lock_file)
    if lock_dir and not os.path.exists(lock_dir):
        os.makedirs(lock_dir, exist_ok=True)

    # Open lock file (create if needed)
    fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o644)
    lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH

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

    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def write_patch_atomic(
    project_file: str,
    content: str,
    _commit_message: str = "",
) -> None:
    """Write content to a ProjectSpec file atomically.

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
    fd, temp_path = tempfile.mkstemp(dir=project_dir, prefix=".tmp_", suffix=".sase")
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


changespec_lock = patch_lock  # legacy compatibility alias
write_changespec_atomic = write_patch_atomic  # legacy compatibility alias
