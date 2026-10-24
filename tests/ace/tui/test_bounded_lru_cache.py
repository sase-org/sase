"""Ownership and concurrency contracts for TUI retained caches."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import weakref

import pytest

from sase.ace.tui import (
    _bead_touches_loader,
    artifact_reads,
    glossary_reads,
    memory_reads,
    skill_uses,
)
from sase.ace.tui.util.bounded_lru import BoundedLRUCache
from sase.ace.tui.widgets._artifact_ref_completion_catalog import (
    _ARTIFACT_INDEX_CACHE,
)


_DERIVED_CACHE_TABLES = (
    memory_reads._memory_reads_cache,
    memory_reads._memory_reads_context_cache,
    artifact_reads._artifact_reads_cache,
    artifact_reads._artifact_reads_context_cache,
    skill_uses._skill_uses_cache,
    skill_uses._skill_uses_context_cache,
    glossary_reads._glossary_reads_cache,
    glossary_reads._glossary_reads_context_cache,
    _bead_touches_loader._bead_touches_cache,
    _bead_touches_loader._bead_touches_context_cache,
)

_SNAPSHOT_CACHE_TABLES = (
    memory_reads._memory_reads_snapshot_cache,
    artifact_reads._artifact_reads_snapshot_cache,
    skill_uses._skill_uses_snapshot_cache,
    glossary_reads._glossary_reads_snapshot_cache,
    _bead_touches_loader._bead_touches_snapshot_cache,
    _bead_touches_loader._bead_views_snapshot_cache,
)


class _Payload:
    pass


def test_lru_hit_refreshes_recency_and_eviction_releases_owner() -> None:
    cache: BoundedLRUCache[str, _Payload] = BoundedLRUCache(2)
    first = _Payload()
    second = _Payload()
    second_ref = weakref.ref(second)
    cache["first"] = first
    cache["second"] = second
    del second

    assert cache.peek("first") is first
    assert cache.get("first") is first
    cache["third"] = _Payload()

    assert cache.peek("first") is first
    assert cache.peek("second") is None
    assert second_ref() is None
    assert len(cache) == 2


@pytest.mark.parametrize("cache", _DERIVED_CACHE_TABLES)
def test_agent_and_context_tables_are_bounded_at_128(cache) -> None:
    cache.clear()
    try:
        assert cache.max_entries == 128
        for index in range(129):
            cache[index] = object()

        assert len(cache) == 128
        assert cache.peek(0) is None
        assert cache.peek(1) is not None
    finally:
        cache.clear()


@pytest.mark.parametrize("cache", _SNAPSHOT_CACHE_TABLES)
def test_source_snapshot_tables_keep_the_eight_project_limit(cache) -> None:
    cache.clear()
    try:
        assert cache.max_entries == 8
        for index in range(9):
            cache[index] = object()

        assert len(cache) == 8
        assert cache.peek(0) is None
        assert cache.peek(1) is not None
    finally:
        cache.clear()


def test_concurrent_cache_access_keeps_bound() -> None:
    cache: BoundedLRUCache[int, int] = BoundedLRUCache(32)

    def exercise(worker: int) -> None:
        for offset in range(500):
            key = (worker * 17 + offset) % 128
            cache[key] = offset
            cache.peek(key)
            cache.get(key)
            cache.touch(key)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(exercise, range(8)))

    assert len(cache) <= 32
