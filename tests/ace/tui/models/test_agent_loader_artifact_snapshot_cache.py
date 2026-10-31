"""Tests for the TUI bounded artifact snapshot cache."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.models._agent_loader_artifact_cache import ARTIFACT_SNAPSHOT_CACHE
from sase.ace.tui.models._agent_loader_artifacts import query_artifact_index_for_loader
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactIndexWindowWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
)


def _snapshot(root: Path, *, decoded: int = 7) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=1,
        projects_root=str(root),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(record_json_decoded=decoded),
        index_window=AgentArtifactIndexWindowWire(
            requested_limit=25,
            returned_record_count=0,
        ),
        records=[],
    )


def test_cached_bounded_index_read_reuses_snapshot(tmp_path: Path) -> None:
    ARTIFACT_SNAPSHOT_CACHE.clear()
    index = tmp_path / "agent_artifact_index.sqlite"
    index.write_text("db", encoding="utf-8")
    calls = 0
    snapshot = _snapshot(tmp_path)

    def query_index(
        _index_path: Path,
        _projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        nonlocal calls
        calls += 1
        assert query.freshness == "cached"
        assert options.include_prompt_step_markers is True
        return snapshot

    kwargs = {
        "full_history": False,
        "freshness": "cached",
        "requested_limit": 25,
        "candidate_filter": {"kind": "equals", "field": "project", "value": "p"},
        "default_index_path": lambda: index,
        "projects_root": lambda: tmp_path,
        "query_index": query_index,
        "scan_artifacts": lambda _options=None: _snapshot(tmp_path, decoded=99),
    }

    first_snapshot, first_state = query_artifact_index_for_loader(**kwargs)
    second_snapshot, second_state = query_artifact_index_for_loader(**kwargs)

    assert first_snapshot is snapshot
    assert second_snapshot is snapshot
    assert first_state.record_json_decoded == 7
    assert second_state.record_json_decoded == 0
    assert calls == 1
    stats = ARTIFACT_SNAPSHOT_CACHE.stats()
    assert stats.misses == 1
    assert stats.hits == 1
    assert stats.stores == 1


def test_cache_key_isolates_candidate_filter(tmp_path: Path) -> None:
    ARTIFACT_SNAPSHOT_CACHE.clear()
    index = tmp_path / "agent_artifact_index.sqlite"
    index.write_text("db", encoding="utf-8")
    calls = 0

    def query_index(
        _index_path: Path,
        _projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        nonlocal calls
        calls += 1
        del query, options
        return _snapshot(tmp_path, decoded=calls)

    base = {
        "full_history": False,
        "freshness": "cached",
        "requested_limit": 25,
        "default_index_path": lambda: index,
        "projects_root": lambda: tmp_path,
        "query_index": query_index,
        "scan_artifacts": lambda _options=None: _snapshot(tmp_path, decoded=99),
    }

    query_artifact_index_for_loader(
        **base,
        candidate_filter={"kind": "equals", "field": "project", "value": "a"},
    )
    query_artifact_index_for_loader(
        **base,
        candidate_filter={"kind": "equals", "field": "project", "value": "b"},
    )

    assert calls == 2
    assert ARTIFACT_SNAPSHOT_CACHE.stats().misses == 2


def test_cache_refuses_mutation_during_read(tmp_path: Path) -> None:
    ARTIFACT_SNAPSHOT_CACHE.clear()
    index = tmp_path / "agent_artifact_index.sqlite"
    index.write_text("db", encoding="utf-8")
    calls = 0

    def query_index(
        _index_path: Path,
        _projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        nonlocal calls
        calls += 1
        del query, options
        (tmp_path / "agent_artifact_index.sqlite-wal").write_text(
            "x" * calls,
            encoding="utf-8",
        )
        return _snapshot(tmp_path)

    kwargs = {
        "full_history": False,
        "freshness": "cached",
        "requested_limit": 25,
        "candidate_filter": None,
        "default_index_path": lambda: index,
        "projects_root": lambda: tmp_path,
        "query_index": query_index,
        "scan_artifacts": lambda _options=None: _snapshot(tmp_path, decoded=99),
    }

    query_artifact_index_for_loader(**kwargs)
    query_artifact_index_for_loader(**kwargs)

    assert calls == 2
    stats = ARTIFACT_SNAPSHOT_CACHE.stats()
    assert stats.hits == 0
    assert stats.mutation_refusals == 2


def test_revalidate_bypasses_snapshot_cache(tmp_path: Path) -> None:
    ARTIFACT_SNAPSHOT_CACHE.clear()
    index = tmp_path / "agent_artifact_index.sqlite"
    index.write_text("db", encoding="utf-8")
    calls = 0

    def query_index(
        _index_path: Path,
        _projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        nonlocal calls
        calls += 1
        assert query.freshness == "revalidate"
        del options
        return _snapshot(tmp_path)

    kwargs = {
        "full_history": False,
        "freshness": "revalidate",
        "requested_limit": 25,
        "candidate_filter": None,
        "default_index_path": lambda: index,
        "projects_root": lambda: tmp_path,
        "query_index": query_index,
        "scan_artifacts": lambda _options=None: _snapshot(tmp_path, decoded=99),
    }

    query_artifact_index_for_loader(**kwargs)
    query_artifact_index_for_loader(**kwargs)

    assert calls == 2
    assert ARTIFACT_SNAPSHOT_CACHE.stats().bypasses == 2


def test_lock_busy_serves_stale_same_key_snapshot(tmp_path: Path) -> None:
    ARTIFACT_SNAPSHOT_CACHE.clear()
    index = tmp_path / "agent_artifact_index.sqlite"
    index.write_text("db", encoding="utf-8")
    cached = _snapshot(tmp_path, decoded=7)
    calls = 0

    def query_index(
        _index_path: Path,
        _projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire | None:
        nonlocal calls
        calls += 1
        del query, options
        if calls == 1:
            return cached
        return None

    kwargs = {
        "full_history": False,
        "freshness": "cached",
        "requested_limit": 25,
        "candidate_filter": None,
        "default_index_path": lambda: index,
        "projects_root": lambda: tmp_path,
        "query_index": query_index,
        "scan_artifacts": lambda _options=None: (_ for _ in ()).throw(
            AssertionError("lock busy must not scan")
        ),
    }

    first_snapshot, first_state = query_artifact_index_for_loader(**kwargs)
    index.write_text("db-stale", encoding="utf-8")
    second_snapshot, second_state = query_artifact_index_for_loader(
        **kwargs,
        allow_lock_busy_source_scan=False,
    )

    assert first_snapshot is cached
    assert second_snapshot is cached
    assert first_state.repair_reason is None
    assert second_state.repair_reason == "artifact_index_lock_busy_served_cached"
    assert second_state.index_error == "artifact index operation lock busy"
    assert second_state.complete_history is False
    assert second_state.complete_visible_inbox is False
    assert second_state.used_artifact_index is True
    assert calls == 2


def test_lock_busy_does_not_serve_different_key_snapshot(tmp_path: Path) -> None:
    ARTIFACT_SNAPSHOT_CACHE.clear()
    index = tmp_path / "agent_artifact_index.sqlite"
    index.write_text("db", encoding="utf-8")
    cached = _snapshot(tmp_path, decoded=7)
    scan_calls = 0

    def query_index(
        _index_path: Path,
        _projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire | None:
        del options
        filter_value = None
        if isinstance(query.candidate_filter, dict):
            filter_value = query.candidate_filter.get("value")
        if filter_value == "a":
            return cached
        return None

    def scan_artifacts(_options=None) -> AgentArtifactScanWire:
        nonlocal scan_calls
        scan_calls += 1
        del _options
        return _snapshot(tmp_path, decoded=99)

    base = {
        "full_history": False,
        "freshness": "cached",
        "requested_limit": 25,
        "default_index_path": lambda: index,
        "projects_root": lambda: tmp_path,
        "query_index": query_index,
        "scan_artifacts": scan_artifacts,
    }

    first_snapshot, _first_state = query_artifact_index_for_loader(
        **base,
        candidate_filter={"kind": "equals", "field": "project", "value": "a"},
    )
    second_snapshot, second_state = query_artifact_index_for_loader(
        **base,
        candidate_filter={"kind": "equals", "field": "project", "value": "b"},
        allow_lock_busy_source_scan=False,
    )

    assert first_snapshot is cached
    assert second_snapshot is not cached
    assert second_state.repair_reason == "artifact_index_lock_busy_keep_roster"
    assert second_state.complete_history is False
    assert scan_calls == 0


def test_lock_busy_without_cache_keeps_roster_when_startup_scan_disabled(
    tmp_path: Path,
) -> None:
    ARTIFACT_SNAPSHOT_CACHE.clear()
    index = tmp_path / "agent_artifact_index.sqlite"
    index.write_text("db", encoding="utf-8")
    scan_calls = 0

    def scan_artifacts(_options=None) -> AgentArtifactScanWire:
        nonlocal scan_calls
        scan_calls += 1
        del _options
        return _snapshot(tmp_path, decoded=99)

    _snapshot_result, state = query_artifact_index_for_loader(
        full_history=False,
        freshness="cached",
        requested_limit=25,
        candidate_filter=None,
        default_index_path=lambda: index,
        projects_root=lambda: tmp_path,
        query_index=lambda *_args, **_kwargs: None,
        scan_artifacts=scan_artifacts,
        allow_lock_busy_source_scan=False,
    )

    assert state.repair_reason == "artifact_index_lock_busy_keep_roster"
    assert state.complete_visible_inbox is False
    assert scan_calls == 0
