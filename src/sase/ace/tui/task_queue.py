"""Background task queue for the ace TUI.

Provides TaskInfo (state for a single background task), TaskQueue (thread-safe
registry with per-CL deduplication), and a capture_output() context manager
that redirects stdout/stderr to a StringIO buffer.
"""

from __future__ import annotations

import io
import sys
import threading
import uuid
from contextlib import contextmanager
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TaskInfo:
    """State for a single background task."""

    task_id: str
    task_type: str  # "sync", "mail", "accept"
    cl_name: str
    project_file: str
    status: str  # "running", "success", "error"
    message: str
    started_at: datetime
    finished_at: datetime | None = None
    output: str = ""
    error: str | None = None
    _live_buffer: io.StringIO | None = field(default=None, repr=False)

    def get_live_output(self) -> str:
        """Return live output from the buffer if running, otherwise the final output."""
        if self._live_buffer is not None and self.status == "running":
            return self._live_buffer.getvalue()
        return self.output


@dataclass
class TaskQueue:
    """Thread-safe registry of background tasks with per-CL deduplication."""

    _tasks: dict[str, TaskInfo] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def submit(
        self,
        task_type: str,
        cl_name: str,
        project_file: str,
    ) -> TaskInfo:
        """Create and register a new running task.

        Returns the new TaskInfo. Callers should check get_running_for_cl()
        first to enforce deduplication.
        """
        task_id = uuid.uuid4().hex
        info = TaskInfo(
            task_id=task_id,
            task_type=task_type,
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message=f"{task_type} started for {cl_name}",
            started_at=datetime.now(),
        )
        with self._lock:
            self._tasks[task_id] = info
        return info

    def complete(
        self,
        task_id: str,
        *,
        success: bool,
        message: str,
        output: str,
        error: str | None = None,
    ) -> None:
        """Mark a task as completed (success or error)."""
        with self._lock:
            info = self._tasks.get(task_id)
            if info is None:
                return
            info.status = "success" if success else "error"
            info.message = message
            info.output = output
            info.error = error
            info.finished_at = datetime.now()

    def get_running_for_cl(self, cl_name: str) -> TaskInfo | None:
        """Return the running task for *cl_name*, or None."""
        with self._lock:
            for info in self._tasks.values():
                if info.cl_name == cl_name and info.status == "running":
                    return info
        return None

    @property
    def running_count(self) -> int:
        """Return the number of currently running tasks."""
        with self._lock:
            return sum(1 for t in self._tasks.values() if t.status == "running")

    def get_all(self) -> list[TaskInfo]:
        """Return a snapshot of all tasks (newest first)."""
        with self._lock:
            return sorted(
                self._tasks.values(),
                key=lambda t: t.started_at,
                reverse=True,
            )

    def remove(self, task_id: str) -> None:
        """Remove a task from the registry."""
        with self._lock:
            self._tasks.pop(task_id, None)

    def remove_completed(self) -> None:
        """Remove all completed (non-running) tasks from the registry."""
        with self._lock:
            self._tasks = {
                tid: info
                for tid, info in self._tasks.items()
                if info.status == "running"
            }

    def prune_old(self, max_age_seconds: int = 3600) -> None:
        """Remove completed tasks older than *max_age_seconds*."""
        cutoff = datetime.now()
        with self._lock:
            self._tasks = {
                tid: info
                for tid, info in self._tasks.items()
                if info.status == "running"
                or (
                    info.finished_at is not None
                    and (cutoff - info.finished_at).total_seconds() < max_age_seconds
                )
            }


@contextmanager
def capture_output(
    buffer: io.StringIO | None = None,
) -> Generator[io.StringIO, None, None]:
    """Redirect stdout/stderr to a StringIO buffer.

    If *buffer* is provided it is reused; otherwise a new one is created.
    """
    buf = buffer if buffer is not None else io.StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = buf
    sys.stderr = buf
    try:
        yield buf
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
