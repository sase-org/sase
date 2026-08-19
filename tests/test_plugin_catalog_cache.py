"""Tests for the plugin catalog on-disk cache."""

from __future__ import annotations

import json
from typing import Any

from sase.plugins.cache import (
    CACHE_STALENESS_SECONDS,
    SCHEMA_VERSION,
    _cache_path,
    cache_age_seconds,
    is_cache_stale,
    read_cache,
    write_cache,
)
from sase.plugins.github_source import GH_SEARCH_QUERY


def _entries() -> list[dict[str, Any]]:
    return [
        {
            "name": "github",
            "repo": "sase-github",
            "full_name": "sase-org/sase-github",
            "owner": "sase-org",
            "topics": ["sase--plugin", "github"],
            "stars": 12,
        }
    ]


def test_write_then_read_round_trip() -> None:
    write_cache(_entries(), fetched_at=1000.0, query=GH_SEARCH_QUERY)

    cached = read_cache()
    assert cached is not None
    assert cached.fetched_at == 1000.0
    assert cached.query == GH_SEARCH_QUERY
    assert list(cached.entries) == _entries()
    assert _cache_path().exists()


def test_write_cache_is_compact_json() -> None:
    write_cache(_entries(), fetched_at=1000.0, query=GH_SEARCH_QUERY)

    raw = _cache_path().read_text(encoding="utf-8")
    assert "\n" not in raw
    assert "  " not in raw
    assert json.loads(raw)["query"] == GH_SEARCH_QUERY


def test_write_is_atomic_no_temp_files_left_behind() -> None:
    write_cache(_entries(), fetched_at=1000.0, query=GH_SEARCH_QUERY)
    leftovers = list(_cache_path().parent.glob("*.tmp"))
    assert leftovers == []


def test_read_cache_missing_returns_none() -> None:
    assert read_cache() is None


def test_read_cache_rejects_unknown_schema_version() -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION + 1,
                "fetched_at": 1000.0,
                "query": GH_SEARCH_QUERY,
                "entries": _entries(),
            }
        ),
        encoding="utf-8",
    )
    assert read_cache() is None


def test_read_cache_rejects_corrupt_json() -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert read_cache() is None


def test_cache_age_seconds_is_clamped_non_negative() -> None:
    assert cache_age_seconds(1000.0, 1100.0) == 100.0
    assert cache_age_seconds(1000.0, 900.0) == 0.0


def test_is_cache_stale_threshold() -> None:
    assert not is_cache_stale(1000.0, 1000.0 + CACHE_STALENESS_SECONDS - 1)
    assert is_cache_stale(1000.0, 1000.0 + CACHE_STALENESS_SECONDS)
