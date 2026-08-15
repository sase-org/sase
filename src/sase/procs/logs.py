"""Bounded combined stdout/stderr logs for durable procs."""

from __future__ import annotations

import io
from collections.abc import Iterable, Mapping
from pathlib import Path

from sase.axe.state import read_tail_seek
from sase.logs._bounded import (
    DEFAULT_MAX_BYTES,
    append_bytes_locked,
    log_file_lock,
    max_bytes_from_env,
)
from sase.logs.pipe import BoundedLogPipe

from .models import STORE_LOG_OWNER
from .paths import proc_logs_dir

ENV_MAX_BYTES = "SASE_PROC_LOG_MAX_BYTES"


def proc_log_path(proc_id: str) -> Path:
    """Return the store-owned combined-log path for one proc id."""
    _validate_proc_id_for_path(proc_id)
    return proc_logs_dir() / f"{proc_id}.log"


def _resolve_proc_log_path(proc_id: str, log_path: str | Path | None = None) -> Path:
    """Return the authoritative log path, defaulting to the store-owned location."""
    if log_path is None:
        return proc_log_path(proc_id)
    return Path(log_path)


def _is_store_owned_log_path(path: str | Path) -> bool:
    """Return whether *path* is a store-owned log beneath the proc log root."""
    try:
        resolved = Path(path).resolve()
        root = proc_logs_dir().resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


def open_proc_log(proc_id: str, *, log_path: str | Path | None = None) -> io.TextIOBase:
    """Open a pipe-backed text writer suitable for ``subprocess`` output.

    A daemon drain thread writes through the shared bounded-log primitives.
    The returned object has a real ``fileno()``, so it can be passed directly
    as ``stdout`` with ``stderr=subprocess.STDOUT``.
    """
    return BoundedLogPipe(
        _resolve_proc_log_path(proc_id, log_path), _proc_log_max_bytes()
    )


def append_proc_log_text(
    proc_id: str, text: str, *, log_path: str | Path | None = None
) -> None:
    """Append *text* to a proc's bounded combined log.

    Used by producers that already own their output in memory — the ACE proc
    mirror flushes newly retained lines this way — instead of handing the
    proc log to a child process as a file descriptor.
    """
    if not text:
        return
    path = _resolve_proc_log_path(proc_id, log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with log_file_lock(path):
        append_bytes_locked(
            path,
            text.encode("utf-8"),
            max_bytes=_proc_log_max_bytes(),
            truncate_oversized=True,
        )


def read_proc_log_tail(
    proc_id: str, lines: int, *, log_path: str | Path | None = None
) -> str:
    """Return the newest *lines* retained across the active and rotated log."""
    if lines <= 0:
        return ""
    path = _resolve_proc_log_path(proc_id, log_path)
    rotated = path.with_name(f"{path.name}.1")
    prior = read_tail_seek(rotated, lines)
    current = read_tail_seek(path, lines)
    retained = "".join((prior, current)).splitlines(keepends=True)[-lines:]
    return "".join(retained)


def delete_proc_logs(
    proc_ids: Iterable[str],
    *,
    log_paths: Mapping[str, str] | None = None,
    log_owners: Mapping[str, str] | None = None,
) -> None:
    """Delete store-owned logs that still live under the proc log root."""
    for proc_id in proc_ids:
        owner = (log_owners or {}).get(proc_id, STORE_LOG_OWNER)
        if owner != STORE_LOG_OWNER:
            continue
        raw = (log_paths or {}).get(proc_id)
        try:
            path = _resolve_proc_log_path(proc_id, raw)
        except ValueError:
            continue
        if not _is_store_owned_log_path(path):
            continue
        for candidate in (path, path.with_name(f"{path.name}.1")):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass


def proc_log_max_bytes() -> int:
    """Return the configured combined-log byte bound."""
    return max_bytes_from_env(ENV_MAX_BYTES, DEFAULT_MAX_BYTES)


def _proc_log_max_bytes() -> int:
    return proc_log_max_bytes()


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
    "proc_log_max_bytes",
    "proc_log_path",
    "read_proc_log_tail",
]
