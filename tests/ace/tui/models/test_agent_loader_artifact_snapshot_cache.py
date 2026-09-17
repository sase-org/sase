"""Tests for the TUI bounded artifact snapshot cache."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.models._agent_loader_artifacts import (
    _ARTIFACT_SNAPSHOT_CACHE,
    query_artifact_index_for_loader,
)
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
    _ARTIFACT_SNAPSHOT_CACHE.clear()
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
    stats = _ARTIFACT_SNAPSHOT_CACHE.stats()
    assert stats.misses == 1
    assert stats.hits == 1
    assert stats.stores == 1


def test_cache_key_isolates_candidate_filter(tmp_path: Path) -> None:
    _ARTIFACT_SNAPSHOT_CACHE.clear()
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
    assert _ARTIFACT_SNAPSHOT_CACHE.stats().misses == 2


def test_cache_refuses_mutation_during_read(tmp_path: Path) -> None:
    _ARTIFACT_SNAPSHOT_CACHE.clear()
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
    stats = _ARTIFACT_SNAPSHOT_CACHE.stats()
    assert stats.hits == 0
    assert stats.mutation_refusals == 2


def test_revalidate_bypasses_snapshot_cache(tmp_path: Path) -> None:
    _ARTIFACT_SNAPSHOT_CACHE.clear()
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
    assert _ARTIFACT_SNAPSHOT_CACHE.stats().bypasses == 2
