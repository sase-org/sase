"""Shared atomic file-write and timestamped-backup helpers.

This module has no memory-note or memory-web knowledge: it only knows how to
write bytes to disk durably (tempfile-in-same-dir, fsync, then
``os.replace``/``os.link``) and where a timestamped backup copy should live.
Both :mod:`sase.memory.mutation` (flat notes) and :mod:`sase.memory.web.mutation`
(web strands) build their domain-specific error handling on top of these
primitives.
"""

from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from typing import Literal

from sase.core.paths import sase_home
from sase.core.time import local_now

BACKUP_DIRNAME = "memory-backups"

AtomicWriteScopeKind = Literal["project", "home"]


def content_digest(data: bytes) -> str:
    """Return the SHA-256 hex digest of file bytes.

    Shared by :func:`sase.memory.mutation.memory_note_digest` (flat notes) and
    :func:`sase.memory.web.mutation.memory_strand_digest` (web strands): both
    domains guard their digest-checked writes with the same hash, and putting
    it here — with no memory-note or memory-web knowledge — lets
    ``sase.memory.web.mutation`` use it without importing
    ``sase.memory.mutation``, which would otherwise cycle back through
    ``sase.memory.mutation_validate`` -> ``sase.main.init_memory`` ->
    ``sase.memory.web``.
    """
    return hashlib.sha256(data).hexdigest()


class AtomicWriteConflictError(OSError):
    """Raised when a create-mode atomic write finds the destination exists."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"refusing to overwrite existing file: {path}")


def write_bytes_atomically(path: Path, data: bytes, *, overwrite: bool) -> None:
    """Atomically write *data* to *path*.

    Writes to a sibling temp file in the same directory, fsyncs it, then
    publishes it with ``os.replace`` (overwrite) or ``os.link`` (create-only,
    so a concurrent create loses the race instead of clobbering the winner).
    Raises :class:`AtomicWriteConflictError` when ``overwrite`` is false and
    *path* already exists at publish time.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    published = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            if overwrite and path.exists():
                os.fchmod(stream.fileno(), stat.S_IMODE(path.stat().st_mode))
            else:
                os.fchmod(stream.fileno(), 0o644)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temp_path, path)
        else:
            try:
                os.link(temp_path, path)
            except OSError as exc:
                if exc.errno == errno.EEXIST or isinstance(exc, FileExistsError):
                    raise AtomicWriteConflictError(path) from exc
                raise
            temp_path.unlink()
        published = True
    finally:
        if not published and temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    """Best-effort fsync of a directory's entries after a publish/unlink."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def backup_path_for(
    *,
    content_root: Path,
    scope_key: str,
    scope_kind: AtomicWriteScopeKind,
    label: str,
) -> Path:
    """Return a fresh timestamped backup path for *label* in *scope_kind*."""
    if scope_kind == "home":
        backup_dir = sase_home() / BACKUP_DIRNAME / scope_key
    else:
        backup_dir = content_root / ".sase" / BACKUP_DIRNAME
    stamp = local_now().strftime("%Y%m%dT%H%M%S")
    candidate = backup_dir / f"{label}-{stamp}.md"
    if not candidate.exists():
        return candidate
    suffix = 1
    while True:
        numbered = backup_dir / f"{label}-{stamp}-{suffix:02d}.md"
        if not numbered.exists():
            return numbered
        suffix += 1


__all__ = [
    "AtomicWriteConflictError",
    "AtomicWriteScopeKind",
    "BACKUP_DIRNAME",
    "backup_path_for",
    "content_digest",
    "write_bytes_atomically",
]
