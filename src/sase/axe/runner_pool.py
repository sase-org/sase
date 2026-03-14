"""Concurrency management for sase axe scheduler.

This module provides two runner pool implementations:

- **RunnerPool**: Thread-safe, single-process pool used by the legacy
  monolithic scheduler (``AxeScheduler``).
- **SharedRunnerPool**: File-based, cross-process pool using ``fcntl.flock``
  for the new lumberjack architecture where each lumberjack runs as a
  separate subprocess.
"""

import fcntl
import logging
from pathlib import Path
from threading import Lock
from typing import IO

from sase.ace.changespec import count_all_runners_global
from sase.axe.state import ensure_shared_dir

log = logging.getLogger(__name__)


class RunnerPool:
    """Thread-safe runner pool for concurrency management.

    Tracks runners started within the current scheduler tick and enforces
    the max_runners limit when combined with globally running processes.

    The pool is reset at the start of each scheduler tick via reset_tick().
    """

    def __init__(self, max_runners: int = 5) -> None:
        """Initialize the runner pool.

        Args:
            max_runners: Maximum concurrent runners allowed globally (default: 5).
        """
        self.max_runners = max_runners
        self._lock = Lock()
        self._started_this_tick = 0

    def reset_tick(self) -> None:
        """Reset per-tick counter. Call at start of each scheduler tick."""
        with self._lock:
            self._started_this_tick = 0

    def get_started_this_tick(self) -> int:
        """Get the number of runners started this tick.

        Returns:
            Number of runners started in the current tick.
        """
        with self._lock:
            return self._started_this_tick

    def get_current_runners(self) -> int:
        """Get total current runners (global + started this tick).

        Returns:
            Total number of runners currently active or started this tick.
        """
        with self._lock:
            return count_all_runners_global() + self._started_this_tick

    def get_available_slots(self) -> int:
        """Get number of available runner slots.

        Returns:
            Number of additional runners that can be started.
        """
        with self._lock:
            current = count_all_runners_global() + self._started_this_tick
            return max(0, self.max_runners - current)

    def reserve_slot(self) -> bool:
        """Try to reserve a runner slot.

        Returns:
            True if slot reserved, False if at limit.
        """
        with self._lock:
            current = count_all_runners_global() + self._started_this_tick
            if current >= self.max_runners:
                return False
            self._started_this_tick += 1
            return True

    def reserve_slots(self, count: int) -> int:
        """Reserve up to `count` slots.

        Args:
            count: Maximum number of slots to reserve.

        Returns:
            Number of slots actually reserved.
        """
        with self._lock:
            current = count_all_runners_global() + self._started_this_tick
            available = max(0, self.max_runners - current)
            to_reserve = min(count, available)
            self._started_this_tick += to_reserve
            return to_reserve

    def add_started(self, count: int) -> None:
        """Add to the started count (used when external code starts runners).

        This is used when the actual runner starting is done by external code
        (like check_hooks) that reports back how many it started.

        Args:
            count: Number of runners that were started.
        """
        with self._lock:
            self._started_this_tick += count

    def is_at_limit(self) -> bool:
        """Check if runner limit has been reached.

        Returns:
            True if no more runners can be started, False otherwise.
        """
        return self.get_available_slots() == 0


class SharedRunnerPool:
    """Cross-process runner pool using file-based locking.

    Uses ``fcntl.flock`` on ``~/.sase/axe/shared/runner_count`` to
    coordinate the max_runners limit across multiple lumberjack
    subprocesses.

    The counter file stores the current number of in-flight runners as
    a plain integer.  Each ``reserve_slot`` / ``release_slot`` call
    acquires an exclusive lock, reads the count, updates it, and
    releases the lock.
    """

    def __init__(self, max_runners: int = 5) -> None:
        """Initialize the shared runner pool.

        Args:
            max_runners: Maximum concurrent runners allowed globally.
        """
        self.max_runners = max_runners
        shared_dir = ensure_shared_dir()
        self._counter_path = shared_dir / "runner_count"
        # Seed the file if it doesn't exist
        if not self._counter_path.exists():
            self._counter_path.write_text("0")

    # -- internal helpers ---------------------------------------------------

    def _read_count(self, fh: IO[str]) -> int:
        """Read count from the already-locked file handle."""
        fh.seek(0)
        raw = fh.read().strip()
        return int(raw) if raw else 0

    def _write_count(self, fh: IO[str], value: int) -> None:
        """Write count to the already-locked file handle."""
        fh.seek(0)
        fh.truncate()
        fh.write(str(value))
        fh.flush()

    # -- public API ---------------------------------------------------------

    def get_current_runners(self) -> int:
        """Read the current runner count (includes global runners).

        Combines the file counter with ``count_all_runners_global()``
        for backward compatibility.

        Returns:
            Total number of runners currently active.
        """
        try:
            with open(self._counter_path, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    count = self._read_count(f)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except OSError:
            count = 0
        return count_all_runners_global() + count

    def reserve_slot(self) -> bool:
        """Try to reserve a runner slot across all lumberjack processes.

        Returns:
            True if a slot was reserved, False if at the limit.
        """
        try:
            with open(self._counter_path, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    current = self._read_count(f)
                    global_runners = count_all_runners_global()
                    if global_runners + current >= self.max_runners:
                        return False
                    self._write_count(f, current + 1)
                    return True
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except OSError:
            log.warning("Failed to reserve runner slot", exc_info=True)
            return False

    def release_slot(self) -> None:
        """Release a previously reserved runner slot."""
        try:
            with open(self._counter_path, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    current = self._read_count(f)
                    self._write_count(f, max(0, current - 1))
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except OSError:
            log.warning("Failed to release runner slot", exc_info=True)

    def is_at_limit(self) -> bool:
        """Check if runner limit has been reached.

        Returns:
            True if no more runners can be started.
        """
        try:
            with open(self._counter_path, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    current = self._read_count(f)
                    global_runners = count_all_runners_global()
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
            return global_runners + current >= self.max_runners
        except OSError:
            return False

    def get_counter_path(self) -> Path:
        """Return the path to the counter file (for testing).

        Returns:
            Path to ``~/.sase/axe/shared/runner_count``.
        """
        return self._counter_path
