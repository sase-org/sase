"""Compact snapshot cache retention tests."""

from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest

from sase.ace.tui.models._agent_loader_artifact_cache import ARTIFACT_SNAPSHOT_CACHE
from sase.ace.tui.models._agent_loader_artifact_index_list import (
    query_artifact_index_for_loader_list,
)
from sase.ace.tui.models._agent_loader_sources import (
    load_agents_from_compact_snapshot_sources,
)
from sase.core.agent_scan_list_wire import (
    AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSION,
    AgentArtifactListDoneWire,
    AgentArtifactListRecordWire,
    AgentArtifactListSnapshotWire,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
)


def _compact_snapshot(
    root: Path,
    records: list[AgentArtifactListRecordWire] | None = None,
    *,
    decoded: int = 7,
) -> AgentArtifactListSnapshotWire:
    return AgentArtifactListSnapshotWire(
        schema_version=AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSION,
        projects_root=str(root),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(record_json_decoded=decoded),
        records=[] if records is None else records,
    )


def _compact_record(
    root: Path,
    timestamp: str,
    *,
    outcome: str = "completed",
) -> AgentArtifactListRecordWire:
    artifact_dir = f"{root}/proj/artifacts/ace-run/{timestamp}"
    return AgentArtifactListRecordWire(
        project_name="proj",
        project_dir=f"{root}/proj",
        project_file=f"{root}/proj/proj.sase",
        workflow_dir_name="ace-run",
        artifact_dir=artifact_dir,
        timestamp=timestamp,
        has_done_marker=True,
        done=AgentArtifactListDoneWire(outcome=outcome, cl_name="proj"),
    )


def _query_kwargs(
    tmp_path: Path,
    query_index: Any,
    snapshot: AgentArtifactListSnapshotWire,
    **overrides: Any,
) -> dict[str, Any]:
    index = tmp_path / "agent_artifact_index.sqlite"
    if not index.is_file():
        index.write_text("db", encoding="utf-8")
    kwargs: dict[str, Any] = {
        "full_history": False,
        "freshness": "cached",
        "requested_limit": 25,
        "candidate_filter": None,
        "default_index_path": lambda: index,
        "projects_root": lambda: tmp_path,
        "query_index": query_index,
        "scan_artifacts": lambda _options=None: snapshot,
    }
    kwargs.update(overrides)
    return kwargs


def test_compact_cache_retains_single_generation(tmp_path: Path) -> None:
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
    ) -> AgentArtifactListSnapshotWire:
        nonlocal calls
        calls += 1
        del query, options
        return _compact_snapshot(tmp_path, decoded=calls)

    base = _query_kwargs(tmp_path, query_index, _compact_snapshot(tmp_path))

    first_snapshot, _first_state = query_artifact_index_for_loader_list(**base)
    second_snapshot, _second_state = query_artifact_index_for_loader_list(**base)
    assert calls == 1
    assert second_snapshot is first_snapshot

    other_filter = dict(base)
    other_filter["candidate_filter"] = {"kind": "equals", "field": "p", "value": "q"}
    third_snapshot, _third_state = query_artifact_index_for_loader_list(**other_filter)
    assert calls == 2
    assert third_snapshot is not first_snapshot

    # The previous generation was evicted: the old key misses again.
    query_artifact_index_for_loader_list(**base)
    assert calls == 3
    stats = ARTIFACT_SNAPSHOT_CACHE.stats()
    assert stats.hits == 1
    assert stats.misses == 3
    assert stats.stores == 3
    assert stats.evictions == 2


def test_compact_lock_busy_serves_only_same_key_stale(tmp_path: Path) -> None:
    ARTIFACT_SNAPSHOT_CACHE.clear()
    index = tmp_path / "agent_artifact_index.sqlite"
    index.write_text("db", encoding="utf-8")
    cached = _compact_snapshot(tmp_path)
    calls = 0

    def query_index(
        _index_path: Path,
        _projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactListSnapshotWire | None:
        nonlocal calls
        calls += 1
        del query, options
        return cached if calls == 1 else None

    base = _query_kwargs(
        tmp_path,
        query_index,
        _compact_snapshot(tmp_path),
        scan_artifacts=lambda _options=None: (_ for _ in ()).throw(
            AssertionError("lock busy must not scan")
        ),
    )
    first_snapshot, first_state = query_artifact_index_for_loader_list(**base)
    assert first_snapshot is cached
    assert first_state.repair_reason is None

    index.write_text("db-stale", encoding="utf-8")
    second_snapshot, second_state = query_artifact_index_for_loader_list(
        **base,
        allow_lock_busy_source_scan=False,
    )
    assert second_snapshot is cached
    assert second_state.repair_reason == "artifact_index_lock_busy_served_cached"

    other = dict(base)
    other["candidate_filter"] = {"kind": "equals", "field": "p", "value": "other"}
    _other_snapshot, other_state = query_artifact_index_for_loader_list(
        **other,
        allow_lock_busy_source_scan=False,
    )
    assert other_state.repair_reason == "artifact_index_lock_busy_keep_roster"
    assert other_state.complete_visible_inbox is False


def test_superseded_compact_query_cannot_publish_old_window(
    tmp_path: Path,
) -> None:
    ARTIFACT_SNAPSHOT_CACHE.clear()
    index = tmp_path / "agent_artifact_index.sqlite"
    index.write_text("db", encoding="utf-8")
    first_started = Event()
    release_first = Event()
    calls: list[int | None] = []
    snapshots = {
        25: _compact_snapshot(tmp_path, decoded=25),
        50: _compact_snapshot(tmp_path, decoded=50),
    }

    def query_index(
        _index_path: Path,
        _projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactListSnapshotWire:
        del options
        limit = query.window_limit
        calls.append(limit)
        if limit == 25:
            first_started.set()
            assert release_first.wait(timeout=5)
        assert limit in snapshots
        return snapshots[limit]

    base = _query_kwargs(tmp_path, query_index, _compact_snapshot(tmp_path))
    old_result: list[tuple[AgentArtifactListSnapshotWire, Any]] = []
    old_thread = Thread(
        target=lambda: old_result.append(
            query_artifact_index_for_loader_list(**{**base, "requested_limit": 25})
        )
    )
    old_thread.start()
    assert first_started.wait(timeout=5)

    latest, _state = query_artifact_index_for_loader_list(
        **{**base, "requested_limit": 50},
    )
    assert latest is snapshots[50]
    release_first.set()
    old_thread.join(timeout=5)
    assert not old_thread.is_alive()
    assert old_result[0][0] is snapshots[25]

    repeated, _state = query_artifact_index_for_loader_list(
        **{**base, "requested_limit": 50},
    )
    assert repeated is snapshots[50]
    assert calls == [25, 50]
    assert ARTIFACT_SNAPSHOT_CACHE.stats().stores == 1


def test_list_path_never_decodes_full_records(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("list path must not decode full records")

    monkeypatch.setattr("sase.core.agent_scan_wire_conversion._record_from_dict", _boom)
    records = [_compact_record(tmp_path, "20260519090000")]
    snapshot = _compact_snapshot(tmp_path, records)

    def query_index(
        _index_path: Path,
        _projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactListSnapshotWire:
        del query, options
        return snapshot

    loaded_snapshot, state = query_artifact_index_for_loader_list(
        **_query_kwargs(tmp_path, query_index, snapshot)
    )
    assert loaded_snapshot is snapshot
    assert state.record_count == 1

    agents, _steps = load_agents_from_compact_snapshot_sources(
        loaded_snapshot,
        patch_snapshot=[],
    )
    assert len(agents) == 1
    assert agents[0].record_shape == "list"
