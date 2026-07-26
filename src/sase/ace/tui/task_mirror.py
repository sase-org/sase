"""Mirror in-TUI background tasks into the durable task store.

Tasks are submitted from the Textual event loop, and a locked store append
there would violate the "never block the event loop" rule. So this module
follows :mod:`sase.logs.toast_log` exactly: the UI thread only mints an id
and enqueues a record, while one daemon writer thread owns every store
write, every task-log append, and the periodic orphan sweep.

The same thread also answers "how many detached tasks is this session
running?" for the top-bar indicator, so an epic launch approved from
Telegram shows up in the TUI's count without the event loop ever touching
the store.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sase.core.state_write_guard import best_effort_test_state_write_allowed
from sase.tasks import (
    ACTIVE_TASK_STATUSES,
    BackgroundTask,
    TERMINAL_TASK_STATUSES,
    TUI_TASK_KIND,
    append_task,
    append_task_log_text,
    new_task_id,
    read_tasks,
    reconcile_running_tasks,
    task_log_path,
    task_store_path,
    update_task,
)

from .task_queue import TaskInfo

log = logging.getLogger(__name__)

MIRROR_KIND = TUI_TASK_KIND
MIRROR_ORIGIN = "ace"
STATE_WRITE_CATEGORY = "tasks"

POLL_SECONDS = 0.5
DETACHED_POLL_SECONDS = 2.0
RECONCILE_SECONDS = 30.0

_STATUS_BY_TUI_STATUS = {
    "running": "running",
    "success": "success",
    "error": "error",
    "killed": "killed",
}


@dataclass(frozen=True)
class _TrackOp:
    """Start mirroring one in-TUI task."""

    info: TaskInfo
    cl_name: str | None


@dataclass(frozen=True)
class _FinishOp:
    """Write one task's terminal row."""

    task_id: str
    status: str
    message: str
    exit_code: int | None


@dataclass(frozen=True)
class _StopOp:
    """Drain the queue and retire the writer thread."""


@dataclass
class _Tracked:
    """Writer-thread state for one mirrored task."""

    info: TaskInfo
    task_id: str
    status: str
    phase: str | None = None
    emitted_lines: int = 0


@dataclass(frozen=True)
class _MirrorContext:
    """Session attribution shared by every row this process mirrors."""

    session_id: str | None
    session_label: str | None
    project: str | None
    workspace_num: int | None
    cwd: str


@dataclass
class TaskMirror:
    """Durable mirror for the in-memory :class:`~.task_queue.TaskQueue`."""

    on_detached_count: Callable[[int], None] | None = None
    _queue: queue.Queue[object] = field(default_factory=queue.Queue, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _tracked: dict[str, _Tracked] = field(default_factory=dict, repr=False)
    _context: _MirrorContext | None = field(default=None, repr=False)
    _detached_count: int = field(default=0, repr=False)
    _next_detached_poll: float = field(default=0.0, repr=False)
    _next_reconcile: float = field(default=0.0, repr=False)

    @property
    def detached_running_count(self) -> int:
        """Return the last known count of this session's detached tasks."""
        return self._detached_count

    @property
    def running(self) -> bool:
        """Return whether the writer thread is alive."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> bool:
        """Start the writer thread unless store writes are not permitted."""
        if not best_effort_test_state_write_allowed(
            task_store_path(), category=STATE_WRITE_CATEGORY
        ):
            return False
        with self._lock:
            if self.running:
                return True
            thread = threading.Thread(
                target=self._writer_main,
                name="sase-ace-task-mirror",
                daemon=True,
            )
            self._thread = thread
            thread.start()
        return True

    def stop(self, *, timeout: float = 1.0) -> None:
        """Drain queued work and retire the writer thread."""
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread is None or not thread.is_alive():
            return
        try:
            self._queue.put(_StopOp())
            thread.join(timeout=timeout)
        except Exception:
            log.debug("task mirror stop failed", exc_info=True)

    def track(self, info: TaskInfo, *, cl_name: str | None = None) -> str | None:
        """Mint a durable id for *info* and enqueue its store row.

        Returns the durable task id, or ``None`` when mirroring is off. Never
        raises and never blocks: this runs on the UI thread.
        """
        if not self.running:
            return None
        try:
            task_id = new_task_id()
            info.durable_task_id = task_id
            self._queue.put(_TrackOp(info=info, cl_name=cl_name or None))
            return task_id
        except Exception:
            log.debug("task mirror enqueue failed", exc_info=True)
            return None

    def finish(
        self,
        info: TaskInfo,
        *,
        status: str,
        message: str,
        exit_code: int | None = None,
    ) -> None:
        """Enqueue the terminal row for a mirrored task."""
        task_id = info.durable_task_id
        if task_id is None or not self.running:
            return
        try:
            self._queue.put(
                _FinishOp(
                    task_id=task_id,
                    status=_STATUS_BY_TUI_STATUS.get(status, "error"),
                    message=message,
                    exit_code=exit_code,
                )
            )
        except Exception:
            log.debug("task mirror finish enqueue failed", exc_info=True)

    def flush(self, timeout: float | None = None) -> bool:
        """Wait for queued mirror writes to drain.

        Returns ``False`` if *timeout* elapses first.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        condition = self._queue.all_tasks_done
        with condition:
            while self._queue.unfinished_tasks:
                if deadline is None:
                    condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                condition.wait(remaining)
        return True

    def _writer_main(self) -> None:
        while True:
            try:
                op = self._queue.get(timeout=POLL_SECONDS)
            except queue.Empty:
                self._tick()
                continue
            try:
                if isinstance(op, _StopOp):
                    return
                self._apply(op)
            except Exception:
                log.debug("task mirror write failed", exc_info=True)
            finally:
                self._queue.task_done()

    def _apply(self, op: object) -> None:
        if isinstance(op, _TrackOp):
            self._handle_track(op)
        elif isinstance(op, _FinishOp):
            self._handle_finish(op)

    def _handle_track(self, op: _TrackOp) -> None:
        info = op.info
        task_id = info.durable_task_id
        if task_id is None:
            return
        context = self._resolve_context()
        status = _STATUS_BY_TUI_STATUS.get(info.status, "running")
        created_at = _utc_timestamp(info.started_at)
        append_task(
            BackgroundTask(
                task_id=task_id,
                label=info.label,
                kind=MIRROR_KIND,
                status=status,
                command=list(info.command or []),
                cwd=context.cwd,
                project=context.project,
                workspace_num=context.workspace_num,
                session_id=context.session_id,
                session_label=context.session_label,
                origin=MIRROR_ORIGIN,
                cl_name=op.cl_name or info.cl_name or None,
                tags=sorted({MIRROR_ORIGIN, info.task_type} - {""}),
                phase=info.phase,
                message=info.message or None,
                created_at=created_at,
                started_at=created_at,
                log_path=str(task_log_path(task_id)),
            )
        )
        tracked = _Tracked(
            info=info,
            task_id=task_id,
            status=status,
            phase=info.phase,
        )
        self._tracked[task_id] = tracked
        self._flush_log(tracked)

    def _handle_finish(self, op: _FinishOp) -> None:
        tracked = self._tracked.pop(op.task_id, None)
        if tracked is not None:
            self._flush_log(tracked)
        update_task(
            op.task_id,
            status=op.status,
            message=op.message or None,
            exit_code=op.exit_code,
            finished_at=_utc_timestamp(datetime.now()),
        )

    def _tick(self) -> None:
        """Run the periodic writer-thread pass between queued operations."""
        for tracked in list(self._tracked.values()):
            try:
                self._flush_log(tracked)
                self._mirror_progress(tracked)
            except Exception:
                log.debug("task mirror progress write failed", exc_info=True)

        now = time.monotonic()
        if now >= self._next_reconcile:
            self._next_reconcile = now + RECONCILE_SECONDS
            try:
                reconcile_running_tasks()
            except Exception:
                log.debug("task reconciliation failed", exc_info=True)
        if now >= self._next_detached_poll:
            self._next_detached_poll = now + DETACHED_POLL_SECONDS
            try:
                self._refresh_detached_count()
            except Exception:
                log.debug("detached task count refresh failed", exc_info=True)

    def _flush_log(self, tracked: _Tracked) -> None:
        """Append only the lines added since the previous flush."""
        snapshot = tracked.info.log.snapshot()
        total = snapshot.trimmed_count + len(snapshot.lines)
        pending = total - tracked.emitted_lines
        if pending <= 0:
            return
        lines = (
            snapshot.lines[-pending:]
            if pending < len(snapshot.lines)
            else snapshot.lines
        )
        tracked.emitted_lines = total
        append_task_log_text(
            tracked.task_id,
            "".join(f"{line.text}\n" for line in lines),
        )

    def _mirror_progress(self, tracked: _Tracked) -> None:
        info = tracked.info
        status = _STATUS_BY_TUI_STATUS.get(info.status, "running")
        if status in TERMINAL_TASK_STATUSES:
            return
        if status == tracked.status and info.phase == tracked.phase:
            return
        tracked.status = status
        tracked.phase = info.phase
        update_task(tracked.task_id, status=status, phase=info.phase)

    def _refresh_detached_count(self) -> None:
        """Count this session's active tasks that this process does not own."""
        context = self._resolve_context()
        if context.session_id is None:
            return
        rows = read_tasks(
            status=ACTIVE_TASK_STATUSES,
            session_id=context.session_id,
        )
        count = sum(1 for row in rows if row.kind != MIRROR_KIND)
        if count == self._detached_count:
            return
        self._detached_count = count
        if self.on_detached_count is not None:
            self.on_detached_count(count)

    def _resolve_context(self) -> _MirrorContext:
        if self._context is None:
            self._context = _load_context()
        return self._context


def _load_context() -> _MirrorContext:
    """Resolve this process's session attribution (writer thread only)."""
    from sase.sessions import current_session_id, live_sessions, session_display_label

    try:
        session_id: str | None = current_session_id()
    except Exception:
        session_id = None
    identity = None
    if session_id is not None:
        try:
            identity = next(
                (item for item in live_sessions() if item.session_id == session_id),
                None,
            )
        except Exception:
            identity = None
    if identity is None:
        return _MirrorContext(
            session_id=session_id,
            session_label=None,
            project=None,
            workspace_num=None,
            cwd=os.getcwd(),
        )
    return _MirrorContext(
        session_id=identity.session_id,
        session_label=session_display_label(identity),
        project=identity.project,
        workspace_num=identity.workspace_num,
        cwd=identity.cwd or os.getcwd(),
    )


def _utc_timestamp(value: datetime) -> str:
    """Format a naive local (or aware) datetime as an RFC3339 UTC string."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "DETACHED_POLL_SECONDS",
    "MIRROR_KIND",
    "MIRROR_ORIGIN",
    "POLL_SECONDS",
    "RECONCILE_SECONDS",
    "STATE_WRITE_CATEGORY",
    "TaskMirror",
]
