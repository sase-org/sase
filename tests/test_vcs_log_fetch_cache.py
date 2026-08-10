"""Tests for the ``sase stitch log`` fetch freshness cache."""

from __future__ import annotations

from pathlib import Path

from sase.vcs_log.fetch_cache import (
    _FetchCacheEntry,
    _fetch_cache_key,
    _normalize_repo_path,
    _read_fetch_cache,
    _write_fetch_cache,
    fresh_fetch_time,
    record_successful_fetch,
)


def test_fetch_cache_records_and_reads_fresh_timestamp(tmp_path: Path) -> None:
    cache_path = tmp_path / "fetch-cache.json"

    assert record_successful_fetch(
        tmp_path / "repo",
        "origin/main",
        fetched_at=1000.0,
        cache_path=cache_path,
    )

    key = _fetch_cache_key(tmp_path / "repo", "origin/main")
    entries = _read_fetch_cache(cache_path)
    assert entries[key] == _FetchCacheEntry(
        repo_path=_normalize_repo_path(tmp_path / "repo"),
        remote_ref="origin/main",
        fetched_at=1000.0,
    )
    assert (
        fresh_fetch_time(
            tmp_path / "repo",
            "origin/main",
            now=1059.0,
            cache_path=cache_path,
        )
        == 1000.0
    )


def test_fetch_cache_expires_at_ttl_boundary(tmp_path: Path) -> None:
    cache_path = tmp_path / "fetch-cache.json"
    assert record_successful_fetch(
        "/repo", "origin/main", fetched_at=1000.0, cache_path=cache_path
    )

    assert (
        fresh_fetch_time("/repo", "origin/main", now=1060.0, cache_path=cache_path)
        is None
    )
    assert (
        fresh_fetch_time("/repo", "origin/main", now=999.0, cache_path=cache_path)
        is None
    )


def test_fetch_cache_read_ignores_corrupt_and_schema_mismatch(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "fetch-cache.json"

    cache_path.write_text("{nope", encoding="utf-8")
    assert _read_fetch_cache(cache_path) == {}

    cache_path.write_text('{"schema_version": 99, "entries": {}}', encoding="utf-8")
    assert _read_fetch_cache(cache_path) == {}


def test_fetch_cache_write_prunes_old_entries(tmp_path: Path) -> None:
    cache_path = tmp_path / "fetch-cache.json"
    old_key = _fetch_cache_key("/old", "origin/main")
    fresh_key = _fetch_cache_key("/fresh", "origin/main")

    assert _write_fetch_cache(
        {
            old_key: _FetchCacheEntry("/old", "origin/main", 80.0),
            fresh_key: _FetchCacheEntry("/fresh", "origin/main", 95.0),
        },
        cache_path=cache_path,
        now=100.0,
        retention_seconds=10.0,
    )

    assert _read_fetch_cache(cache_path) == {
        fresh_key: _FetchCacheEntry("/fresh", "origin/main", 95.0)
    }
