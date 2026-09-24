"""Bounded combined stdout/stderr logs for durable procs."""

from __future__ import annotations

import io
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from sase.axe.state import read_tail_seek
from sase.logs._bounded import (
    DEFAULT_MAX_BYTES,
    append_bytes_locked,
    log_file_lock,
    max_bytes_from_env,
)
from sase.logs.pipe import BoundedLogPipe

from .models import STORE_LOG_OWNER, ProcLogRetentionEntry, ProcLogRetentionResult
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
) -> ProcLogRetentionResult:
    """Delete store-owned current/rotated logs under the proc log root."""
    log_root = proc_logs_dir()
    entries: list[ProcLogRetentionEntry] = []
    scanned = 0
    selected = 0
    removed = 0
    skipped = 0
    errors = 0
    reclaimable_bytes = 0
    reclaimed_bytes = 0
    byte_accounting_complete = True
    for proc_id in proc_ids:
        owner = (log_owners or {}).get(proc_id, STORE_LOG_OWNER)
        if owner != STORE_LOG_OWNER:
            skipped += 1
            entries.append(
                ProcLogRetentionEntry(
                    proc_id=proc_id,
                    path="",
                    status="skipped",
                    reason=f"log owner {owner!r} is external",
                    size_bytes=0,
                )
            )
            continue
        raw = (log_paths or {}).get(proc_id)
        try:
            path = _resolve_proc_log_path(proc_id, raw)
        except ValueError:
            errors += 1
            byte_accounting_complete = False
            entries.append(
                ProcLogRetentionEntry(
                    proc_id=proc_id,
                    path="",
                    status="error",
                    reason="invalid proc id for log path",
                    size_bytes=None,
                )
            )
            continue
        if not _is_store_owned_log_path(path):
            skipped += 1
            entries.append(
                ProcLogRetentionEntry(
                    proc_id=proc_id,
                    path=str(path),
                    status="skipped",
                    reason="log path is outside the proc log root",
                    size_bytes=0,
                )
            )
            continue
        for candidate in (path, path.with_name(f"{path.name}.1")):
            scanned += 1
            try:
                size = candidate.stat().st_size
            except FileNotFoundError:
                skipped += 1
                entries.append(
                    ProcLogRetentionEntry(
                        proc_id=proc_id,
                        path=str(candidate),
                        status="skipped",
                        reason="missing",
                        size_bytes=0,
                    )
                )
                continue
            except OSError as exc:
                errors += 1
                byte_accounting_complete = False
                entries.append(
                    ProcLogRetentionEntry(
                        proc_id=proc_id,
                        path=str(candidate),
                        status="error",
                        reason=f"stat failed: {exc}",
                        size_bytes=None,
                    )
                )
                continue
            selected += 1
            reclaimable_bytes += size
            try:
                candidate.unlink()
                removed += 1
                reclaimed_bytes += size
                entries.append(
                    ProcLogRetentionEntry(
                        proc_id=proc_id,
                        path=str(candidate),
                        status="removed",
                        reason="store-owned log pruned",
                        size_bytes=size,
                    )
                )
            except FileNotFoundError:
                skipped += 1
                entries.append(
                    ProcLogRetentionEntry(
                        proc_id=proc_id,
                        path=str(candidate),
                        status="skipped",
                        reason="already missing",
                        size_bytes=size,
                    )
                )
            except OSError as exc:
                errors += 1
                byte_accounting_complete = False
                entries.append(
                    ProcLogRetentionEntry(
                        proc_id=proc_id,
                        path=str(candidate),
                        status="error",
                        reason=f"unlink failed: {exc}",
                        size_bytes=size,
                    )
                )
    return ProcLogRetentionResult(
        log_root=log_root,
        apply=True,
        scanned=scanned,
        selected=selected,
        removed=removed,
        skipped=skipped,
        errors=errors,
        reclaimable_bytes=reclaimable_bytes,
        reclaimed_bytes=reclaimed_bytes,
        byte_accounting_complete=byte_accounting_complete,
        entries=tuple(entries),
    )


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
    "ProcLogCursor",
    "ProcLogRead",
    "append_proc_log_text",
    "delete_proc_logs",
    "open_proc_log",
    "proc_log_max_bytes",
    "proc_log_path",
    "read_proc_log_tail",
]


@dataclass(frozen=True)
class ProcLogRead:
    """One incremental read from a :class:`ProcLogCursor`."""

    text: str
    lost_bytes: int = 0


@dataclass
class ProcLogCursor:
    """Offset-based tail cursor over one proc's combined log.

    The cursor holds the ``(inode, offset)`` it last read through and returns
    only new bytes on each :meth:`read_new` (capped per read). A rotation —
    an inode change or a shrink below the held offset — drains the rotated
    sibling (``<name>.log.1``) from the held offset onward and reports the
    bytes that vanished underneath as ``lost_bytes``.
    """

    proc_id: str
    log_path: str | Path | None = None
    max_bytes_per_read: int = 65_536
    _inode: int | None = field(default=None, init=False, repr=False)
    _offset: int = field(default=0, init=False, repr=False)

    def seek_end(self) -> None:
        """Skip history already on disk so polling starts with new bytes."""
        try:
            kind = self._stat()
        except FileNotFoundError:
            self._inode = None
            self._offset = 0
            return
        if kind is None:
            return
        inode, size = kind
        self._inode = inode
        self._offset = size

    def read_new(self) -> ProcLogRead:
        """Return bytes appended since the last read, with rotation recovery."""
        try:
            kind = self._stat()
        except FileNotFoundError:
            return ProcLogRead(text="")
        if kind is None:
            return ProcLogRead(text="")
        inode, size = kind
        if self._inode is not None and inode == self._inode and size >= self._offset:
            text, consumed = self._read_range(self._path(), self._offset, size)
            self._offset += consumed
            return ProcLogRead(text=text)
        return self._read_rotated(inode, size)

    def _path(self) -> Path:
        return _resolve_proc_log_path(self.proc_id, self.log_path)

    def _stat(self) -> tuple[int, int] | None:
        try:
            stat = os.stat(self._path())
        except FileNotFoundError:
            raise
        except OSError:
            return None
        return (stat.st_ino, stat.st_size)

    def _read_rotated(self, inode: int, size: int) -> ProcLogRead:
        """Recover post-offset bytes from the rotated sibling, then the log."""
        old_offset = self._offset
        rotated = self._path().with_name(f"{self._path().name}.1")
        recovered = ""
        recovered_bytes = 0
        lost_bytes = old_offset
        try:
            rotated_size = rotated.stat().st_size
        except OSError:
            rotated_size = 0
        else:
            if rotated_size > old_offset:
                recovered, recovered_bytes = _read_bytes(
                    rotated, old_offset, rotated_size, budget=self.max_bytes_per_read
                )
                lost_bytes = 0
            else:
                recovered, recovered_bytes = "", 0
                lost_bytes = old_offset - rotated_size
        budget = max(0, self.max_bytes_per_read - recovered_bytes)
        current, consumed = _read_bytes(self._path(), 0, size, budget=budget)
        self._inode = inode
        self._offset = consumed
        return ProcLogRead(text=recovered + current, lost_bytes=lost_bytes)

    def _read_range(self, path: Path, start: int, end: int) -> tuple[str, int]:
        budget = max(0, self.max_bytes_per_read)
        return _read_bytes(path, start, end, budget=budget)


def _read_bytes(path: Path, start: int, end: int, *, budget: int) -> tuple[str, int]:
    """Decode ``[start, min(end, start + budget)]`` as forgiving UTF-8.

    Returns the decoded text plus the raw byte count consumed, so cursors
    advance by bytes on disk even when undecodable bytes expand under
    ``errors="replace"``.
    """
    if budget <= 0 or end <= start:
        return "", 0
    length = min(end - start, budget)
    try:
        with open(path, "rb") as handle:
            handle.seek(start)
            raw = handle.read(length)
    except OSError:
        return "", 0
    return raw.decode("utf-8", errors="replace"), len(raw)
