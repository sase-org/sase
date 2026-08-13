"""Bounded combined stdout/stderr logs for durable background tasks."""

from __future__ import annotations

import io
from collections.abc import Iterable
from pathlib import Path

from sase.axe.state import read_tail_seek
from sase.logs._bounded import (
    DEFAULT_MAX_BYTES,
    append_bytes_locked,
    log_file_lock,
    max_bytes_from_env,
)
from sase.logs.pipe import BoundedLogPipe

from .paths import task_logs_dir

ENV_MAX_BYTES = "SASE_TASK_LOG_MAX_BYTES"


def task_log_path(task_id: str) -> Path:
    """Return the active combined-log path for one task."""
    _validate_task_id_for_path(task_id)
    return task_logs_dir() / f"{task_id}.log"


def open_task_log(task_id: str) -> io.TextIOBase:
    """Open a pipe-backed text writer suitable for ``subprocess`` output.

    A daemon drain thread writes through the shared bounded-log primitives.
    The returned object has a real ``fileno()``, so it can be passed directly
    as ``stdout`` with ``stderr=subprocess.STDOUT``.
    """
    return BoundedLogPipe(task_log_path(task_id), _task_log_max_bytes())


def append_task_log_text(task_id: str, text: str) -> None:
    """Append *text* to a task's bounded combined log.

    Used by producers that already own their output in memory — the ACE task
    mirror flushes newly retained lines this way — instead of handing the
    task log to a child process as a file descriptor.
    """
    if not text:
        return
    path = task_log_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with log_file_lock(path):
        append_bytes_locked(
            path,
            text.encode("utf-8"),
            max_bytes=_task_log_max_bytes(),
            truncate_oversized=True,
        )


def read_task_log_tail(task_id: str, lines: int) -> str:
    """Return the newest *lines* retained across the active and rotated log."""
    if lines <= 0:
        return ""
    path = task_log_path(task_id)
    rotated = path.with_name(f"{path.name}.1")
    prior = read_tail_seek(rotated, lines)
    current = read_tail_seek(path, lines)
    retained = "".join((prior, current)).splitlines(keepends=True)[-lines:]
    return "".join(retained)


def delete_task_logs(task_ids: Iterable[str]) -> None:
    """Delete active and rotated logs for the supplied task ids."""
    for task_id in task_ids:
        try:
            path = task_log_path(task_id)
        except ValueError:
            continue
        for candidate in (path, path.with_name(f"{path.name}.1")):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass


def _task_log_max_bytes() -> int:
    return max_bytes_from_env(ENV_MAX_BYTES, DEFAULT_MAX_BYTES)


def _validate_task_id_for_path(task_id: str) -> None:
    if (
        not task_id
        or task_id in {".", ".."}
        or Path(task_id).name != task_id
        or "/" in task_id
        or "\\" in task_id
        or "\x00" in task_id
    ):
        raise ValueError(f"invalid task id for log path: {task_id!r}")


__all__ = [
    "ENV_MAX_BYTES",
    "append_task_log_text",
    "delete_task_logs",
    "open_task_log",
    "read_task_log_tail",
    "task_log_path",
]
