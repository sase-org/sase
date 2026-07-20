"""Background task queue for the ace TUI.

Provides TaskInfo (state for a single background task), TaskQueue (thread-safe
registry with per-ChangeSpec deduplication), and task-local output storage.
"""

from __future__ import annotations

import io
import os
import signal
import subprocess
import threading
import time
import uuid
from collections.abc import Collection, Generator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sase.project_display_names import humanize_cl_name

TaskLogStream = Literal["stdout", "stderr", "progress", "header", "result"]

_MAX_TASK_LOG_LINES = 5_000
_MAX_TASK_LOG_CHARS = 512 * 1024


@dataclass(frozen=True)
class TaskLogLine:
    """One append-only task log line."""

    text: str
    stream: TaskLogStream
    ts: datetime


@dataclass(frozen=True)
class _TaskLogSnapshot:
    """Immutable view of a task log."""

    lines: tuple[TaskLogLine, ...]
    version: int
    trimmed_count: int


@dataclass
class _TaskLog:
    """Thread-safe, bounded log for one background task."""

    max_lines: int = _MAX_TASK_LOG_LINES
    max_chars: int = _MAX_TASK_LOG_CHARS
    _lines: list[TaskLogLine] = field(default_factory=list, init=False, repr=False)
    _chars: int = field(default=0, init=False, repr=False)
    _trimmed_count: int = field(default=0, init=False, repr=False)
    _version: int = field(default=0, init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    @property
    def version(self) -> int:
        """Return the current monotonically-increasing version."""
        with self._lock:
            return self._version

    def append(self, text: str, *, stream: TaskLogStream = "stdout") -> None:
        """Append text to the log, splitting multi-line chunks into log lines."""
        if text == "":
            return
        entries = text.splitlines() or [text]
        with self._lock:
            for entry in entries:
                self._append_locked(entry.rstrip("\r"), stream=stream)
            self._trim_locked()
            self._version += 1

    def snapshot(self) -> _TaskLogSnapshot:
        """Return an immutable log snapshot."""
        with self._lock:
            return _TaskLogSnapshot(
                lines=tuple(self._lines),
                version=self._version,
                trimmed_count=self._trimmed_count,
            )

    def text(self) -> str:
        """Return the full retained log as plain text."""
        snapshot = self.snapshot()
        lines: list[str] = []
        if snapshot.trimmed_count:
            lines.append(f"... {snapshot.trimmed_count} earlier lines trimmed")
        lines.extend(line.text for line in snapshot.lines)
        if not lines:
            return ""
        return "\n".join(lines) + "\n"

    def _append_locked(self, text: str, *, stream: TaskLogStream) -> None:
        self._lines.append(TaskLogLine(text=text, stream=stream, ts=datetime.now()))
        self._chars += len(text)

    def _trim_locked(self) -> None:
        while self._lines and (
            len(self._lines) > self.max_lines or self._chars > self.max_chars
        ):
            removed = self._lines.pop(0)
            self._chars -= len(removed.text)
            self._trimmed_count += 1


class _TaskLogWriter(io.TextIOBase):
    """Text writer that forwards print-style chunks into a task log."""

    def __init__(self, log: _TaskLog, *, stream: TaskLogStream) -> None:
        self._log = log
        self._stream = stream
        self._pending = ""

    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        if not value:
            return 0
        self._pending += value
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._log.append(line, stream=self._stream)
        return len(value)

    def flush(self) -> None:
        if self._pending:
            self._log.append(self._pending, stream=self._stream)
            self._pending = ""


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
    display_name: str | None = None
    dedup_key: str | None = None
    exclusive_scopes: frozenset[str] = frozenset()
    finished_at: datetime | None = None
    output: str = ""
    error: str | None = None
    log: _TaskLog = field(default_factory=_TaskLog)
    command: list[str] | None = None
    phase: str | None = None
    exit_code: int | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _live_buffer: io.StringIO | None = field(default=None, repr=False)
    _processes: dict[int, subprocess.Popen[str]] = field(
        default_factory=dict, repr=False
    )
    _process_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def label(self) -> str:
        """Return the user-facing task label."""
        if self.display_name:
            return self.display_name
        if self.cl_name:
            return f"{self.task_type} {humanize_cl_name(self.cl_name)}"
        return self.task_type

    def get_live_output(self) -> str:
        """Return retained log output, falling back to legacy/final output."""
        log_text = self.log.text()
        if log_text:
            return log_text
        if self._live_buffer is not None:
            legacy = self._live_buffer.getvalue()
            if legacy:
                return legacy
        return self.output

    def register_process(self, process: subprocess.Popen[str]) -> None:
        """Register a live child process owned by this task."""
        with self._process_lock:
            self._processes[process.pid] = process

    def unregister_process(self, process: subprocess.Popen[str]) -> None:
        """Remove a child process from the live process registry."""
        with self._process_lock:
            self._processes.pop(process.pid, None)

    def terminate_processes(self, *, grace_seconds: float = 1.0) -> None:
        """Terminate all registered child process groups for this task."""
        self.cancel_event.set()
        with self._process_lock:
            processes = list(self._processes.values())

        for process in processes:
            if process.poll() is not None:
                continue
            _terminate_process_group(process)

        deadline = time.monotonic() + grace_seconds
        for process in processes:
            if process.poll() is not None:
                continue
            timeout = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass

        for process in processes:
            if process.poll() is not None:
                continue
            _kill_process_group(process)


@dataclass
class TaskQueue:
    """Thread-safe registry of background tasks with per-ChangeSpec deduplication."""

    _tasks: dict[str, TaskInfo] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def submit(
        self,
        task_type: str,
        cl_name: str,
        project_file: str,
        *,
        display_name: str | None = None,
        dedup_key: str | None = None,
        exclusive_scopes: Collection[str] = (),
    ) -> TaskInfo:
        """Create and register a new running task.

        Returns the new TaskInfo. Callers should check get_running_for_cl()
        first to enforce deduplication.
        """
        label = display_name or f"{task_type} {humanize_cl_name(cl_name)}".strip()
        task_id = uuid.uuid4().hex
        info = TaskInfo(
            task_id=task_id,
            task_type=task_type,
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message=f"{label} started",
            started_at=datetime.now(),
            display_name=display_name,
            dedup_key=dedup_key if dedup_key is not None else cl_name,
            exclusive_scopes=frozenset(exclusive_scopes),
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
            info.output = output or info.get_live_output()
            info.error = error
            info.finished_at = datetime.now()
            if success:
                info.exit_code = 0 if info.exit_code is None else info.exit_code

    def get_running_for_cl(self, cl_name: str) -> TaskInfo | None:
        """Return the running per-ChangeSpec-deduped task for *cl_name*, or None.

        Tasks submitted with a custom dedup key (agent launches, kill/dismiss
        cleanup) opt out of per-ChangeSpec dedup and are never returned here, so they
        cannot block ChangeSpec actions for the same ChangeSpec.
        """
        with self._lock:
            for info in self._tasks.values():
                if (
                    info.cl_name == cl_name
                    and info.dedup_key == cl_name
                    and info.status == "running"
                ):
                    return info
        return None

    def get_running_for_key(self, dedup_key: str) -> TaskInfo | None:
        """Return the running task for *dedup_key*, or None."""
        with self._lock:
            for info in self._tasks.values():
                if info.dedup_key == dedup_key and info.status == "running":
                    return info
        return None

    def get_running_for_scopes(
        self, exclusive_scopes: Collection[str]
    ) -> TaskInfo | None:
        """Return a running task claiming any requested exclusive scope."""
        requested = frozenset(exclusive_scopes)
        if not requested:
            return None
        with self._lock:
            for info in self._tasks.values():
                if info.status == "running" and requested & info.exclusive_scopes:
                    return info
        return None

    def get(self, task_id: str) -> TaskInfo | None:
        """Return a task by id, or None."""
        with self._lock:
            return self._tasks.get(task_id)

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
def redirect_print_to(log: _TaskLog) -> Generator[None, None, None]:
    """Best-effort legacy print capture into a task-local log."""
    out = _TaskLogWriter(log, stream="stdout")
    err = _TaskLogWriter(log, stream="stderr")
    with redirect_stdout(out), redirect_stderr(err):
        try:
            yield
        finally:
            out.flush()
            err.flush()


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        try:
            process.terminate()
        except ProcessLookupError:
            return


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        try:
            process.kill()
        except ProcessLookupError:
            return
