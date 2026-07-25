"""Durable background-task models, ids, logs, paths, and store facade."""

from .ids import TaskRefError, new_task_id, resolve_task_ref, short_task_id
from .logs import (
    delete_task_logs,
    open_task_log,
    read_task_log_tail,
    task_log_path,
)
from .models import (
    ACTIVE_TASK_STATUSES,
    TASK_WIRE_SCHEMA_VERSION,
    TERMINAL_TASK_STATUSES,
    UNSET,
    BackgroundTask,
    TaskAppendOutcome,
    TaskPruneOutcome,
    TaskStoreSnapshot,
    TaskStoreStats,
    TaskUpdate,
    TaskUpdateOutcome,
)
from .paths import task_logs_dir, task_store_path, tasks_dir
from .store import (
    TaskStoreLockTimeoutError,
    append_task,
    filter_tasks,
    get_task,
    prune_tasks,
    read_tasks,
    update_task,
)

__all__ = [
    "ACTIVE_TASK_STATUSES",
    "TASK_WIRE_SCHEMA_VERSION",
    "TERMINAL_TASK_STATUSES",
    "UNSET",
    "BackgroundTask",
    "TaskAppendOutcome",
    "TaskPruneOutcome",
    "TaskRefError",
    "TaskStoreLockTimeoutError",
    "TaskStoreSnapshot",
    "TaskStoreStats",
    "TaskUpdate",
    "TaskUpdateOutcome",
    "append_task",
    "delete_task_logs",
    "filter_tasks",
    "get_task",
    "new_task_id",
    "open_task_log",
    "prune_tasks",
    "read_task_log_tail",
    "read_tasks",
    "resolve_task_ref",
    "short_task_id",
    "task_log_path",
    "task_logs_dir",
    "task_store_path",
    "tasks_dir",
    "update_task",
]
