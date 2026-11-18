"""Bounded-retention ownership tests: one snapshot generation, bounded detail.

Phase ``bounded-retention`` (child epic ``sase-1t3.10.1``): the TUI retains
one compact snapshot generation and a bounded selected-detail owner instead
of an eight-entry cache plus unbounded per-selection full-record
accumulation.
"""

from __future__ import annotations

import gc
import weakref
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.ace.tui.models._agent_loader_artifact_cache import (
    ARTIFACT_SNAPSHOT_CACHE,
)
from sase.ace.tui.models._agent_loader_artifact_index_list import (
    query_artifact_index_for_loader_list,
)
from sase.ace.tui.models._agent_loader_sources import (
    load_agents_from_compact_snapshot_sources,
)
from sase.ace.tui.models import _projected_record as projected_record
from sase.ace.tui.models._projected_record import (
    hydrate_projected_agent,
    projected_agent_needs_hydration,
    _release_projected_agent_detail,
)
from sase.ace.tui.models.agent import Agent, AgentType, LinkedRepoMetadata
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
    AgentArtifactRecordWire,
    AgentMetaWire,
    DoneMarkerWire,
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


def _full_record(artifact_dir: str, timestamp: str) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="retention-proj",
        project_dir="/tmp/projects/retention-proj",
        project_file="/tmp/projects/retention-proj/retention-proj.sase",
        workflow_dir_name="ace-run",
        artifact_dir=artifact_dir,
        timestamp=timestamp,
        agent_meta=AgentMetaWire(
            linked_repos=[
                {
                    "name": "sase-core",
                    "workspace_dir": "/tmp/sase-core",
                }
            ]
        ),
        done=DoneMarkerWire(
            step_output={
                "_raw": "full detail output " * 5000,
                "meta_keep": "loaded",
            }
        ),
    )


def _list_agent(
    timestamp: str,
    artifact_dir: str,
    *,
    cl_name: str = "retention-proj",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/projects/retention-proj/retention-proj.sase",
        status="DONE",
        start_time=datetime(2026, 5, 19, 9, 0, 0),
        raw_suffix=timestamp,
        step_output={"meta_keep": "projected"},
        record_shape="list",
        index_record_dir=artifact_dir,
    )


def _patch_hydration(
    tmp_path: Path,
    monkeypatch: Any,
    records_by_dir: dict[str, AgentArtifactRecordWire],
) -> None:
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    monkeypatch.setattr(
        "sase.ace.tui.models._projected_record.default_agent_artifact_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models._projected_record.load_agent_artifact_records",
        lambda _index, dirs: [records_by_dir[d] for d in dirs],
    )


def _stamp(timestamp_base: int, i: int) -> str:
    return f"{timestamp_base + i:014d}"


def test_selected_detail_owner_bounds_hydrated_agents(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    timestamps = [_stamp(20260519090000, i) for i in range(20)]
    dirs = [f"/tmp/projects/retention-proj/artifacts/ace-run/{ts}" for ts in timestamps]
    _patch_hydration(
        tmp_path,
        monkeypatch,
        {d: _full_record(d, ts) for d, ts in zip(dirs, timestamps, strict=True)},
    )
    agents = [_list_agent(ts, d) for ts, d in zip(timestamps, dirs, strict=True)]
    compact_outputs = [dict(a.step_output or {}) for a in agents]

    for agent in agents:
        assert hydrate_projected_agent(agent) is True

    # Twenty selections with large outputs retain at most two hydrated
    # generations; everything older falls back to compact list facts.
    assert len(projected_record._detail_owner) == 2
    for i, agent in enumerate(agents):
        if i < 18:
            assert agent.record_shape == "list"
            assert projected_agent_needs_hydration(agent) is True
            assert agent.step_output == compact_outputs[i]
            assert "_raw" not in (agent.step_output or {})
        else:
            assert agent.record_shape == "full"
            assert "_raw" in (agent.step_output or {})


def test_release_restores_compact_list_facts(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    timestamp = _stamp(20260520090000, 0)
    artifact_dir = f"/tmp/projects/retention-proj/artifacts/ace-run/{timestamp}"
    _patch_hydration(
        tmp_path, monkeypatch, {artifact_dir: _full_record(artifact_dir, timestamp)}
    )
    agent = _list_agent(timestamp, artifact_dir, cl_name="retention-release")

    list_facts = {
        "status": agent.status,
        "cl_name": agent.cl_name,
        "agent_name": agent.agent_name,
        "step_output": dict(agent.step_output or {}),
        "linked_repos": agent.linked_repos,
        "extra_files": list(agent.extra_files),
        "error_traceback": agent.error_traceback,
        "response_path": agent.response_path,
        "output_path": agent.output_path,
        "status_bucket": agent.status_bucket,
        "monitor_stop_status": agent.monitor_stop_status,
        "gate_stop_status": agent.gate_stop_status,
    }

    assert hydrate_projected_agent(agent) is True
    assert agent.record_shape == "full"
    assert "_raw" in (agent.step_output or {})
    assert agent.linked_repos == (LinkedRepoMetadata("sase-core", "/tmp/sase-core"),)

    size_before = len(projected_record._detail_owner)
    assert _release_projected_agent_detail(agent) is True
    assert len(projected_record._detail_owner) == size_before - 1

    assert agent.record_shape == "list"
    assert projected_agent_needs_hydration(agent) is True
    for key, value in list_facts.items():
        assert getattr(agent, key) == value, key

    # Detail re-hydrates on the next selection after a release.
    assert hydrate_projected_agent(agent) is True
    assert agent.record_shape == "full"
    assert _release_projected_agent_detail(agent) is True


def test_orphaned_hydrated_agents_stay_collectible(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    timestamp = _stamp(20260521090000, 0)
    artifact_dir = f"/tmp/projects/retention-proj/artifacts/ace-run/{timestamp}"
    _patch_hydration(
        tmp_path, monkeypatch, {artifact_dir: _full_record(artifact_dir, timestamp)}
    )
    agent = _list_agent(timestamp, artifact_dir, cl_name="retention-orphan")
    assert hydrate_projected_agent(agent) is True
    assert agent.record_shape == "full"

    ref = weakref.ref(agent)
    del agent
    gc.collect()
    assert ref() is None

    # A replacement roster's note prunes the dead registration instead of
    # growing the owner or restoring an orphaned generation.
    timestamp2 = _stamp(20260521090000, 1)
    artifact_dir2 = f"/tmp/projects/retention-proj/artifacts/ace-run/{timestamp2}"
    records = {artifact_dir2: _full_record(artifact_dir2, timestamp2)}
    _patch_hydration(tmp_path, monkeypatch, records)
    agent2 = _list_agent(timestamp2, artifact_dir2, cl_name="retention-orphan")
    assert hydrate_projected_agent(agent2) is True
    assert len(projected_record._detail_owner) <= 2
