"""Persistent SQLite caches used by the headless chat catalog."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from sase.core.paths import sase_home
from sase.history import chat_catalog
from sase.history.chat_catalog import ChatTranscriptInfo
from sase.history.chat_storage import iter_chat_files

_CACHE_SCHEMA_VERSION = 1
_CACHE_FILENAME = "chats_catalog.sqlite"


def _catalog_cache_path() -> Path:
    """Return the machine-local generated catalog cache path."""

    return sase_home() / _CACHE_FILENAME


@contextmanager
def open_catalog_cache() -> Iterator[sqlite3.Connection]:
    """Open a valid cache, rebuilding generated state after corruption."""

    path = _catalog_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection: sqlite3.Connection | None = None
    try:
        connection = _connect(path)
        _ensure_schema(connection)
    except (sqlite3.DatabaseError, TypeError, ValueError):
        if connection is not None:
            connection.close()
        _discard_broken_cache(path)
        connection = _connect(path)
        _ensure_schema(connection)
    try:
        yield connection
    finally:
        connection.close()


def load_transcript_index(
    connection: sqlite3.Connection,
    *,
    force: bool,
) -> list[ChatTranscriptInfo]:
    """Return newest-first transcript rows, reading heads only on cache misses."""

    cached = {} if force else _cached_transcripts(connection)
    seen: set[str] = set()
    rows: list[ChatTranscriptInfo] = []
    updates: list[tuple[str, int, int, str]] = []
    for path in iter_chat_files():
        absolute = str(path.resolve(strict=False))
        try:
            stat = path.stat()
        except OSError:
            continue
        seen.add(absolute)
        key = (stat.st_mtime_ns, stat.st_size)
        cached_row = cached.get(absolute)
        if cached_row is not None and cached_row[:2] == key:
            rows.append(cached_row[2])
            continue
        info = chat_catalog.read_chat_transcript_info(path, mtime=stat.st_mtime)
        if info is None:
            continue
        rows.append(info)
        updates.append(
            (
                absolute,
                stat.st_mtime_ns,
                stat.st_size,
                json.dumps(asdict(info), separators=(",", ":"), sort_keys=True),
            )
        )

    with connection:
        if updates:
            connection.executemany(
                """
                INSERT INTO transcripts(path, mtime_ns, size_bytes, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    mtime_ns=excluded.mtime_ns,
                    size_bytes=excluded.size_bytes,
                    payload=excluded.payload
                """,
                updates,
            )
        stored_paths = {
            str(row[0]) for row in connection.execute("SELECT path FROM transcripts")
        }
        stale = stored_paths - seen
        if stale:
            connection.executemany(
                "DELETE FROM transcripts WHERE path = ?",
                ((path,) for path in stale),
            )

    rows.sort(key=lambda row: row.mtime, reverse=True)
    return rows


def load_cached_json(
    connection: sqlite3.Connection,
    namespace: str,
    cache_key: str,
    token: str,
) -> object | None:
    """Load one namespaced JSON payload when its generation token matches."""

    row = connection.execute(
        """
        SELECT payload FROM generated_indexes
        WHERE namespace = ? AND cache_key = ? AND token = ?
        """,
        (namespace, cache_key, token),
    ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(str(row[0]))
    except (json.JSONDecodeError, TypeError):
        return None


def store_cached_json(
    connection: sqlite3.Connection,
    namespace: str,
    cache_key: str,
    token: str,
    payload: object,
) -> None:
    """Atomically replace one namespaced generated-index payload."""

    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    with connection:
        connection.execute(
            """
            INSERT INTO generated_indexes(namespace, cache_key, token, payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace, cache_key) DO UPDATE SET
                token=excluded.token,
                payload=excluded.payload
            """,
            (namespace, cache_key, token, encoded),
        )


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=0.25)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=250")
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    row = connection.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is not None and int(row[0]) != _CACHE_SCHEMA_VERSION:
        connection.executescript(
            """
            DROP TABLE IF EXISTS transcripts;
            DROP TABLE IF EXISTS generated_indexes;
            DELETE FROM meta;
            """
        )
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS transcripts (
            path TEXT PRIMARY KEY,
            mtime_ns INTEGER NOT NULL,
            size_bytes INTEGER NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS generated_indexes (
            namespace TEXT NOT NULL,
            cache_key TEXT NOT NULL,
            token TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY(namespace, cache_key)
        );
        """
    )
    connection.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(_CACHE_SCHEMA_VERSION),),
    )
    connection.commit()


def _cached_transcripts(
    connection: sqlite3.Connection,
) -> dict[str, tuple[int, int, ChatTranscriptInfo]]:
    result: dict[str, tuple[int, int, ChatTranscriptInfo]] = {}
    try:
        rows = connection.execute(
            "SELECT path, mtime_ns, size_bytes, payload FROM transcripts"
        )
        for path, mtime_ns, size_bytes, payload in rows:
            decoded: dict[str, Any] = json.loads(str(payload))
            result[str(path)] = (
                int(mtime_ns),
                int(size_bytes),
                ChatTranscriptInfo(**decoded),
            )
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return result


def _discard_broken_cache(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{path}{suffix}")
        try:
            os.unlink(candidate)
        except FileNotFoundError:
            pass


__all__ = [
    "load_cached_json",
    "load_transcript_index",
    "open_catalog_cache",
    "store_cached_json",
]
