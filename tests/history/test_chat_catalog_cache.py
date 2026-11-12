"""Lock and corruption handling for the chat catalog SQLite cache."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest
from sase.history.chat_catalog_provenance import cache as provenance_cache

from tests.history._chat_catalog_provenance_helpers import _setup_home


def test_locked_catalog_cache_is_not_unlinked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(provenance_cache, "_BUSY_TIMEOUT_MS", 50)
    cache_path = home / "chats_catalog.sqlite"
    with provenance_cache.open_catalog_cache():
        pass

    inode = cache_path.stat().st_ino
    holder = sqlite3.connect(str(cache_path), timeout=0)
    try:
        holder.execute("BEGIN EXCLUSIVE")
        with pytest.raises(sqlite3.OperationalError, match="locked|busy"):
            with provenance_cache.open_catalog_cache():
                pass
        assert cache_path.exists()
        assert cache_path.stat().st_ino == inode
    finally:
        holder.rollback()
        holder.close()

    with provenance_cache.open_catalog_cache() as connection:
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    assert row is not None


def test_corrupt_catalog_cache_file_is_discarded_and_rebuilt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    cache_path = home / "chats_catalog.sqlite"
    cache_path.write_bytes(b"not sqlite")

    with provenance_cache.open_catalog_cache() as connection:
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()

    assert row is not None
    assert cache_path.exists()
