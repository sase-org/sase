"""Bounded combined stdout/stderr logs for durable background tasks."""

from __future__ import annotations

import io
import os
import threading
from collections.abc import Iterable
from pathlib import Path

from sase.axe.state import read_tail_seek
from sase.logs._bounded import (
    DEFAULT_MAX_BYTES,
    append_bytes_locked,
    log_file_lock,
    max_bytes_from_env,
)

from .paths import task_logs_dir

ENV_MAX_BYTES = "SASE_TASK_LOG_MAX_BYTES"
_READ_CHUNK_BYTES = 64 * 1024


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
    return _BoundedTaskLogPipe(task_log_path(task_id), _task_log_max_bytes())


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


class _BoundedTaskLogPipe(io.TextIOBase):
    def __init__(self, path: Path, max_bytes: int) -> None:
        super().__init__()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._max_bytes = max_bytes
        with log_file_lock(path):
            fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
            os.close(fd)
        self._read_fd, self._write_fd = os.pipe()
        self._write_error: OSError | None = None
        self._thread = threading.Thread(
            target=self._drain,
            name=f"sase-task-log-{path.stem}",
            daemon=True,
        )
        self._thread.start()

    def writable(self) -> bool:
        return True

    def fileno(self) -> int:
        self._check_closed()
        return self._write_fd

    def write(self, value: str) -> int:
        self._check_closed()
        encoded = value.encode("utf-8")
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(self._write_fd, remaining)
            remaining = remaining[written:]
        return len(value)

    def flush(self) -> None:
        self._check_closed()

    def close(self) -> None:
        if self.closed:
            return
        try:
            os.close(self._write_fd)
        except OSError:
            pass
        self._thread.join(timeout=5)
        super().close()
        if self._write_error is not None:
            raise self._write_error

    def _drain(self) -> None:
        try:
            while chunk := os.read(self._read_fd, _READ_CHUNK_BYTES):
                with log_file_lock(self._path):
                    append_bytes_locked(
                        self._path,
                        chunk,
                        max_bytes=self._max_bytes,
                        truncate_oversized=True,
                    )
        except OSError as exc:
            self._write_error = exc
        finally:
            try:
                os.close(self._read_fd)
            except OSError:
                pass

    def _check_closed(self) -> None:
        if self.closed:
            raise ValueError("I/O operation on closed task log")


__all__ = [
    "ENV_MAX_BYTES",
    "delete_task_logs",
    "open_task_log",
    "read_task_log_tail",
    "task_log_path",
]
