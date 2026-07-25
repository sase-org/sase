"""Durable task-store rows for the Admin Center Tasks tab.

Everything here performs file I/O — stat, store read, session liveness, log
tails — so it must only ever run off the Textual event loop. The pane calls
:func:`load_store_task_rows` from a thread worker and applies the result on
the UI thread.

Store rows are converted into :class:`~..task_queue.TaskInfo` records so the
pane renders one homogeneous list: in-memory tasks stay authoritative for
live output, and rows this process does not own arrive with
``store_backed=True``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sase.core.state_write_guard import pytest_path_is_sandboxed
from sase.tasks import (
    BackgroundTask,
    kill_task,
    read_task_log_tail,
    read_tasks,
    task_store_path,
)

from ..task_queue import TaskInfo

DETAIL_LOG_LINES = 400


@dataclass(frozen=True)
class StoreTasksSnapshot:
    """One off-thread read of the durable store."""

    rows: list[TaskInfo] = field(default_factory=list)
    live_session_ids: frozenset[str] = frozenset()
    mtime: float | None = None
    detail_task_id: str | None = None
    all_sessions: bool = False
    unchanged: bool = False


def load_store_task_rows(
    *,
    session_id: str | None,
    all_sessions: bool,
    known_mtime: float | None = None,
    known_detail_task_id: str | None = None,
    detail_task_id: str | None = None,
) -> StoreTasksSnapshot:
    """Read store rows for the Tasks tab, honoring the store mtime cache.

    Args:
        session_id: This TUI session's id, used for the default scope.
        all_sessions: Include rows from every session when ``True``; otherwise
            keep this session's rows plus unattributed ones.
        known_mtime: Store mtime from the caller's last successful load.
        known_detail_task_id: Row whose log tail the caller already holds.
        detail_task_id: Row whose log tail to read now. Only one tail is read
            per load — reading every row's log each second would be wasteful.

    Returns:
        A snapshot; ``unchanged=True`` means the store and the requested
        detail row both match what the caller already has.
    """
    if not pytest_path_is_sandboxed(task_store_path()):
        return StoreTasksSnapshot(all_sessions=all_sessions)
    mtime = _store_mtime()
    if (
        known_mtime is not None
        and mtime == known_mtime
        and detail_task_id == known_detail_task_id
    ):
        return StoreTasksSnapshot(
            mtime=mtime,
            detail_task_id=detail_task_id,
            all_sessions=all_sessions,
            unchanged=True,
        )

    tasks = read_tasks()
    live_session_ids = _live_session_ids()
    rows = [
        _store_task_row(
            task,
            live_session_ids=live_session_ids,
            with_output=task.task_id == detail_task_id,
        )
        for task in tasks
        if _in_scope(task, session_id=session_id, all_sessions=all_sessions)
    ]
    return StoreTasksSnapshot(
        rows=rows,
        live_session_ids=live_session_ids,
        mtime=mtime,
        detail_task_id=detail_task_id,
        all_sessions=all_sessions,
    )


def _store_task_row(
    task: BackgroundTask,
    *,
    live_session_ids: frozenset[str] = frozenset(),
    with_output: bool = False,
) -> TaskInfo:
    """Adapt one durable task row into a pane row."""
    started_at = _local_datetime(task.started_at or task.created_at) or datetime.now()
    output = ""
    if with_output:
        output = _read_log_tail(task.task_id)
    return TaskInfo(
        task_id=task.task_id,
        task_type=task.kind,
        cl_name=task.cl_name or "",
        project_file="",
        status=task.status,
        message=task.message or "",
        started_at=started_at,
        display_name=task.label,
        finished_at=_local_datetime(task.finished_at),
        output=output,
        error=task.message if task.status in {"error", "killed"} else None,
        command=list(task.command) or None,
        phase=task.phase,
        exit_code=task.exit_code,
        durable_task_id=task.task_id,
        store_backed=True,
        session_id=task.session_id,
        session_label=task.session_label,
        session_live=bool(task.session_id and task.session_id in live_session_ids),
    )


def kill_store_task(task_id: str) -> str | None:
    """Kill a store-backed task, returning an error message on failure."""
    try:
        kill_task(task_id)
    except Exception as exc:
        return " ".join(str(exc).splitlines()) or type(exc).__name__
    return None


def _in_scope(
    task: BackgroundTask,
    *,
    session_id: str | None,
    all_sessions: bool,
) -> bool:
    if all_sessions:
        return True
    return task.session_id is None or task.session_id == session_id


def _store_mtime() -> float | None:
    try:
        return task_store_path().stat().st_mtime
    except OSError:
        return None


def _live_session_ids() -> frozenset[str]:
    try:
        from sase.sessions import live_sessions

        return frozenset(identity.session_id for identity in live_sessions())
    except Exception:
        return frozenset()


def _read_log_tail(task_id: str) -> str:
    try:
        return read_task_log_tail(task_id, DETAIL_LOG_LINES)
    except (OSError, ValueError):
        return ""


def _local_datetime(value: str | None) -> datetime | None:
    """Convert an RFC3339 UTC timestamp into a naive local datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone().replace(tzinfo=None)


def current_tui_session_id() -> str | None:
    """Return this process's session id, or ``None`` when unavailable."""
    try:
        from sase.sessions import current_session_id

        return current_session_id()
    except Exception:
        return None


__all__ = [
    "DETAIL_LOG_LINES",
    "StoreTasksSnapshot",
    "current_tui_session_id",
    "kill_store_task",
    "load_store_task_rows",
]
