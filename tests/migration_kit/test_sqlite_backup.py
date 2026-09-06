"""Tests for the online SQLite backup and integrity-check helper."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from sase.migration_kit.sqlite_backup import (
    backup_sqlite_file,
    looks_like_sqlite_file,
)


def _make_sqlite_db(path: Path, *, wal: bool = False) -> None:
    conn = sqlite3.connect(path)
    try:
        if wal:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1), (2), (3)")
        conn.commit()
    finally:
        conn.close()


def test_looks_like_sqlite_file_true_for_real_database(tmp_path: Path) -> None:
    db_path = tmp_path / "data.sqlite"
    _make_sqlite_db(db_path)
    assert looks_like_sqlite_file(db_path)


def test_looks_like_sqlite_file_false_for_plain_text(tmp_path: Path) -> None:
    fake = tmp_path / "fake.sqlite"
    fake.write_text("not a database", encoding="utf-8")
    assert not looks_like_sqlite_file(fake)


def test_looks_like_sqlite_file_false_for_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.sqlite"
    empty.touch()
    assert not looks_like_sqlite_file(empty)


def test_backup_sqlite_file_produces_consistent_readable_copy(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _make_sqlite_db(source)
    destination = tmp_path / "dest" / "source.sqlite"

    result = backup_sqlite_file(source, destination)

    assert result.ok
    assert result.integrity_check == "ok"
    assert result.hot_copy is True
    conn = sqlite3.connect(destination)
    try:
        rows = conn.execute("SELECT x FROM t ORDER BY x").fetchall()
    finally:
        conn.close()
    assert rows == [(1,), (2,), (3,)]


def test_backup_sqlite_file_survives_wal_mode_with_open_writer(tmp_path: Path) -> None:
    """The backup must be consistent even while a WAL writer connection is open.

    This is the exact case the census flags: a byte-wise copy of a live WAL
    database (main file plus -wal/-shm sidecars) can be unusable, which is
    why the engine must use SQLite's own online backup API instead.
    """
    source = tmp_path / "source.sqlite"
    _make_sqlite_db(source, wal=True)

    writer = sqlite3.connect(source)
    writer.execute("INSERT INTO t VALUES (4)")
    writer.commit()
    try:
        destination = tmp_path / "dest" / "source.sqlite"
        result = backup_sqlite_file(source, destination)

        assert result.ok
        assert result.integrity_check == "ok"
        conn = sqlite3.connect(destination)
        try:
            rows = conn.execute("SELECT x FROM t ORDER BY x").fetchall()
        finally:
            conn.close()
        assert rows == [(1,), (2,), (3,), (4,)]
    finally:
        writer.close()
