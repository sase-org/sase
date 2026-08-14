"""Bounded combined stdout/stderr logs for durable procs."""

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

from .paths import proc_logs_dir

ENV_MAX_BYTES = "SASE_PROC_LOG_MAX_BYTES"


def proc_log_path(proc_id: str) -> Path:
    """Return the active combined-log path for one proc."""
    _validate_proc_id_for_path(proc_id)
    return proc_logs_dir() / f"{proc_id}.log"


def open_proc_log(proc_id: str) -> io.TextIOBase:
    """Open a pipe-backed text writer suitable for ``subprocess`` output.

    A daemon drain thread writes through the shared bounded-log primitives.
    The returned object has a real ``fileno()``, so it can be passed directly
    as ``stdout`` with ``stderr=subprocess.STDOUT``.
    """
    return BoundedLogPipe(proc_log_path(proc_id), _proc_log_max_bytes())


def append_proc_log_text(proc_id: str, text: str) -> None:
    """Append *text* to a proc's bounded combined log.

    Used by producers that already own their output in memory — the ACE proc
    mirror flushes newly retained lines this way — instead of handing the
    proc log to a child process as a file descriptor.
    """
    if not text:
        return
    path = proc_log_path(proc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with log_file_lock(path):
        append_bytes_locked(
            path,
            text.encode("utf-8"),
            max_bytes=_proc_log_max_bytes(),
            truncate_oversized=True,
        )


def read_proc_log_tail(proc_id: str, lines: int) -> str:
    """Return the newest *lines* retained across the active and rotated log."""
    if lines <= 0:
        return ""
    path = proc_log_path(proc_id)
    rotated = path.with_name(f"{path.name}.1")
    prior = read_tail_seek(rotated, lines)
    current = read_tail_seek(path, lines)
    retained = "".join((prior, current)).splitlines(keepends=True)[-lines:]
    return "".join(retained)


def delete_proc_logs(proc_ids: Iterable[str]) -> None:
    """Delete active and rotated logs for the supplied proc ids."""
    for proc_id in proc_ids:
        try:
            path = proc_log_path(proc_id)
        except ValueError:
            continue
        for candidate in (path, path.with_name(f"{path.name}.1")):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass


def _proc_log_max_bytes() -> int:
    return max_bytes_from_env(ENV_MAX_BYTES, DEFAULT_MAX_BYTES)


def _validate_proc_id_for_path(proc_id: str) -> None:
    if (
        not proc_id
        or proc_id in {".", ".."}
        or Path(proc_id).name != proc_id
        or "/" in proc_id
        or "\\" in proc_id
        or "\x00" in proc_id
    ):
        raise ValueError(f"invalid proc id for log path: {proc_id!r}")


__all__ = [
    "ENV_MAX_BYTES",
    "append_proc_log_text",
    "delete_proc_logs",
    "open_proc_log",
    "proc_log_path",
    "read_proc_log_tail",
]
