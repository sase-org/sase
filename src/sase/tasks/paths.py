"""Canonical durable background-task paths."""

from __future__ import annotations

from pathlib import Path

from sase.core.paths import sase_subdir

TASKS_SUBDIR = "tasks"
TASK_STORE_FILENAME = "tasks.jsonl"
TASK_LOGS_SUBDIR = "logs"


def tasks_dir() -> Path:
    """Return ``~/.sase/tasks`` (or the active ``SASE_HOME`` equivalent)."""
    return sase_subdir(TASKS_SUBDIR)


def task_store_path() -> Path:
    """Return the Rust-owned background-task JSONL path."""
    return tasks_dir() / TASK_STORE_FILENAME


def task_logs_dir() -> Path:
    """Return the directory containing per-task combined logs."""
    return tasks_dir() / TASK_LOGS_SUBDIR


__all__ = ["task_logs_dir", "task_store_path", "tasks_dir"]
