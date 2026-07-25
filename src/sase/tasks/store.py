"""Python facade over the Rust durable background-task store."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.config.core import get_task_history_limit
from sase.core.rust import require_rust_binding

from .logs import delete_task_logs
from .models import (
    BackgroundTask,
    TaskAppendOutcome,
    TaskPruneOutcome,
    TaskStoreSnapshot,
    TaskUpdate,
    TaskUpdateOutcome,
)
from .paths import task_store_path


class TaskStoreLockTimeoutError(TimeoutError):
    """The task-store lock stayed busy past its bounded wait."""


class _AnySession:
    pass


_ANY_SESSION = _AnySession()


def read_tasks(
    *,
    path: Path | str | None = None,
    status: str | Collection[str] | None = None,
    session_id: str | None | _AnySession = _ANY_SESSION,
    project: str | None = None,
    tag: str | None = None,
    query: str | None = None,
) -> list[BackgroundTask]:
    """Read newest-first tasks, applying the shared CLI/TUI filters."""
    payload: Mapping[str, Any] = _call_binding(
        "read_tasks_snapshot", str(path or task_store_path())
    )
    snapshot = TaskStoreSnapshot.from_dict(payload)
    return filter_tasks(
        snapshot.tasks,
        status=status,
        session_id=session_id,
        project=project,
        tag=tag,
        query=query,
    )


def get_task(task_id: str, *, path: Path | str | None = None) -> BackgroundTask | None:
    """Return the exact task id, or ``None`` when it is absent."""
    return next(
        (task for task in read_tasks(path=path) if task.task_id == task_id),
        None,
    )


def append_task(
    task: BackgroundTask | Mapping[str, Any],
    *,
    path: Path | str | None = None,
    history_limit: int | None = None,
) -> TaskAppendOutcome:
    """Append a task, enforce retention, and remove logs pruned with rows."""
    record = (
        task if isinstance(task, BackgroundTask) else BackgroundTask.from_dict(task)
    )
    payload: Mapping[str, Any] = _call_binding(
        "append_task",
        str(path or task_store_path()),
        record.to_dict(),
        history_limit if history_limit is not None else get_task_history_limit(),
    )
    outcome = TaskAppendOutcome.from_dict(payload)
    delete_task_logs(outcome.pruned_task_ids)
    return outcome


def update_task(
    update: TaskUpdate | Mapping[str, Any] | str,
    *,
    path: Path | str | None = None,
    **changes: Any,
) -> TaskUpdateOutcome:
    """Apply a partial update; a string task id accepts keyword changes."""
    if isinstance(update, str):
        record = TaskUpdate(task_id=update, **changes)
    elif changes:
        raise TypeError("keyword changes require a string task id")
    elif isinstance(update, TaskUpdate):
        record = update
    else:
        record = TaskUpdate.from_dict(update)
    payload: Mapping[str, Any] = _call_binding(
        "update_task", str(path or task_store_path()), record.to_dict()
    )
    return TaskUpdateOutcome.from_dict(payload)


def prune_tasks(
    *,
    path: Path | str | None = None,
    history_limit: int | None = None,
) -> TaskPruneOutcome:
    """Enforce current retention and remove logs for every pruned row."""
    payload: Mapping[str, Any] = _call_binding(
        "prune_tasks",
        str(path or task_store_path()),
        history_limit if history_limit is not None else get_task_history_limit(),
    )
    outcome = TaskPruneOutcome.from_dict(payload)
    delete_task_logs(outcome.pruned_task_ids)
    return outcome


def filter_tasks(
    tasks: Sequence[BackgroundTask],
    *,
    status: str | Collection[str] | None = None,
    session_id: str | None | _AnySession = _ANY_SESSION,
    project: str | None = None,
    tag: str | None = None,
    query: str | None = None,
) -> list[BackgroundTask]:
    """Apply the canonical exact-match fields and free-text task query."""
    statuses = _status_set(status)
    needle = query.casefold() if query else None
    result: list[BackgroundTask] = []
    for task in tasks:
        if statuses is not None and task.status not in statuses:
            continue
        if session_id is not _ANY_SESSION and task.session_id != session_id:
            continue
        if project is not None and task.project != project:
            continue
        if tag is not None and tag not in task.tags:
            continue
        if needle is not None and needle not in _search_text(task).casefold():
            continue
        result.append(task)
    return result


def _status_set(
    status: str | Collection[str] | None,
) -> frozenset[str] | None:
    if status is None:
        return None
    if isinstance(status, str):
        return frozenset({status})
    return frozenset(status)


def _search_text(task: BackgroundTask) -> str:
    return "\n".join(
        (
            task.label,
            " ".join(task.command),
            task.cl_name or "",
        )
    )


def _call_binding(name: str, *args: Any) -> Any:
    binding = require_rust_binding(name)
    try:
        return binding(*args)
    except Exception as exc:
        if isinstance(exc, TimeoutError) or type(exc).__name__ == (
            "TaskStoreLockTimeoutError"
        ):
            raise TaskStoreLockTimeoutError(str(exc)) from exc
        raise


__all__ = [
    "TaskStoreLockTimeoutError",
    "append_task",
    "filter_tasks",
    "get_task",
    "prune_tasks",
    "read_tasks",
    "update_task",
]
