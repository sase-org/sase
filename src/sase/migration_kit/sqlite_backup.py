"""Quiescent, integrity-checked SQLite backups.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

_SQLITE_MAGIC = b"SQLite format 3\x00"
SQLITE_LIKE_SUFFIXES = (".sqlite", ".db")


def looks_like_sqlite_extension(path: Path) -> bool:
    """Return whether *path*'s suffix marks it as a declared SQLite store."""
    return path.suffix.lower() in SQLITE_LIKE_SUFFIXES


def looks_like_sqlite_file(path: Path) -> bool:
    """Return whether *path* begins with the SQLite file-format magic header.

    An empty file (a store created but never opened) is not a SQLite file by
    this check even though it may later become one; callers copy it verbatim.
    """
    try:
        with path.open("rb") as stream:
            header = stream.read(len(_SQLITE_MAGIC))
    except OSError:
        return False
    return header == _SQLITE_MAGIC


@dataclass(frozen=True)
class _SqliteBackupResult:
    """Outcome of backing up one SQLite database file."""

    integrity_check: str
    hot_copy: bool
    ok: bool


def backup_sqlite_file(source: Path, destination: Path) -> _SqliteBackupResult:
    """Copy one SQLite database via the online backup API and verify it.

    The copy is taken through :meth:`sqlite3.Connection.backup`, never by
    reading the live file's bytes directly, so it cannot capture a torn page
    out from under a concurrent writer and needs no WAL/SHM sidecars copied
    alongside it. The migration kit has no mechanism to stop an unknown
    writer for an arbitrary declared root, so every copy is taken "hot" --
    that describes provenance, not a lower safety guarantee, since the online
    backup API is concurrent-safe by construction.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dest_conn = sqlite3.connect(destination)
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()

    check_conn = sqlite3.connect(destination)
    try:
        row = check_conn.execute("PRAGMA integrity_check").fetchone()
    finally:
        check_conn.close()
    integrity_check = str(row[0]) if row else "unknown"
    return _SqliteBackupResult(
        integrity_check=integrity_check,
        hot_copy=True,
        ok=integrity_check == "ok",
    )
