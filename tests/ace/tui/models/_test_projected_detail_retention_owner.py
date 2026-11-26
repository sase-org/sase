"""Selected projected-detail ownership and release tests."""

from __future__ import annotations

import gc
import weakref
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.models import (
    _projected_record_detail as detail_record,
)
from sase.ace.tui.models._agent_graph import (
    copy_agent_graph,
    copy_agent_rows_relinked,
)
from sase.ace.tui.models._projected_record import (
    hydrate_projected_agent,
    projected_agent_needs_hydration,
)
from sase.ace.tui.models.agent import LinkedRepoMetadata
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from ._projected_detail_retention_support import (
    full_record,
    list_agent,
    stamp,
)


def _patch_hydration(
    tmp_path: Path,
    monkeypatch: Any,
    records_by_dir: dict[str, AgentArtifactRecordWire],
) -> None:
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    monkeypatch.setattr(
        "sase.ace.tui.models._projected_record_load.default_agent_artifact_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models._projected_record_load.load_agent_artifact_records",
        lambda _index, dirs: [records_by_dir[d] for d in dirs],
    )


def test_selected_detail_owner_bounds_hydrated_agents(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    timestamps = [stamp(20260519090000, i) for i in range(20)]
    dirs = [f"/tmp/projects/retention-proj/artifacts/ace-run/{ts}" for ts in timestamps]
    _patch_hydration(
        tmp_path,
        monkeypatch,
        {d: full_record(d, ts) for d, ts in zip(dirs, timestamps, strict=True)},
    )
    agents = [list_agent(ts, d) for ts, d in zip(timestamps, dirs, strict=True)]
    compact_outputs = [dict(a.step_output or {}) for a in agents]

    for agent in agents:
        assert hydrate_projected_agent(agent) is True

    # Twenty selections with large outputs retain at most two hydrated
    # generations; everything older falls back to compact list facts.
    assert len(detail_record._detail_owner) == 2
    for i, agent in enumerate(agents):
        if i < 18:
            assert agent.record_shape == "list"
            assert projected_agent_needs_hydration(agent) is True
            assert agent.step_output == compact_outputs[i]
            assert "_raw" not in (agent.step_output or {})
        else:
            assert agent.record_shape == "full"
            assert "_raw" in (agent.step_output or {})


def test_same_identity_replacements_release_displaced_payloads(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    timestamp = stamp(20260519100000, 0)
    artifact_dir = f"/tmp/projects/retention-proj/artifacts/ace-run/{timestamp}"
    _patch_hydration(
        tmp_path,
        monkeypatch,
        {artifact_dir: full_record(artifact_dir, timestamp)},
    )
    replacements = [
        list_agent(timestamp, artifact_dir, cl_name="same-logical-row")
        for _ in range(20)
    ]

    for agent in replacements:
        assert hydrate_projected_agent(agent) is True

    assert len(detail_record._detail_owner) == 2
    for agent in replacements[:-2]:
        assert agent.record_shape == "list"
        assert "_raw" not in (agent.step_output or {})
    assert all(
        agent.record_shape == "full" and "_raw" in (agent.step_output or {})
        for agent in replacements[-2:]
    )
    retained_raw_bytes = sum(
        len(str(agent.step_output.get("_raw", "")))
        for agent in replacements
        if isinstance(agent.step_output, dict)
    )
    assert retained_raw_bytes == 2 * len("full detail output " * 5000)


def test_roster_copies_restore_compact_facts_without_detail(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    timestamps = [stamp(20260519110000, i) for i in range(2)]
    dirs = [
        f"/tmp/projects/retention-proj/artifacts/ace-run/{timestamp}"
        for timestamp in timestamps
    ]
    records = {
        artifact_dir: full_record(artifact_dir, timestamp)
        for timestamp, artifact_dir in zip(timestamps, dirs, strict=True)
    }
    _patch_hydration(tmp_path, monkeypatch, records)
    parent, child = [
        list_agent(timestamp, artifact_dir, cl_name="copy-proj")
        for timestamp, artifact_dir in zip(timestamps, dirs, strict=True)
    ]
    parent.followup_agents = [child]
    child.agent_session_container = parent
    assert hydrate_projected_agent(parent) is True
    assert hydrate_projected_agent(child) is True

    graph_copies = copy_agent_graph([parent, child])
    assert graph_copies[0].followup_agents[0] is graph_copies[1]
    assert graph_copies[1].agent_session_container is graph_copies[0]
    shallow_copies = copy_agent_rows_relinked([parent, child])
    assert shallow_copies[0].followup_agents[0] is shallow_copies[1]
    assert shallow_copies[1].agent_session_container is shallow_copies[0]

    for clone in (*graph_copies, *shallow_copies):
        assert clone.record_shape == "list"
        assert "_raw" not in (clone.step_output or {})
        assert not hasattr(clone, "_projected_detail_stash")
    assert parent.record_shape == child.record_shape == "full"

    assert detail_record._release_projected_agent_detail(parent) is True
    assert detail_record._release_projected_agent_detail(child) is True
    for clone in (*graph_copies, *shallow_copies):
        assert "_raw" not in (clone.step_output or {})


def test_release_restores_compact_list_facts(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    timestamp = stamp(20260520090000, 0)
    artifact_dir = f"/tmp/projects/retention-proj/artifacts/ace-run/{timestamp}"
    _patch_hydration(
        tmp_path, monkeypatch, {artifact_dir: full_record(artifact_dir, timestamp)}
    )
    agent = list_agent(timestamp, artifact_dir, cl_name="retention-release")

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

    size_before = len(detail_record._detail_owner)
    assert detail_record._release_projected_agent_detail(agent) is True
    assert len(detail_record._detail_owner) == size_before - 1

    assert agent.record_shape == "list"
    assert projected_agent_needs_hydration(agent) is True
    for key, value in list_facts.items():
        assert getattr(agent, key) == value, key

    # Detail re-hydrates on the next selection after a release.
    assert hydrate_projected_agent(agent) is True
    assert agent.record_shape == "full"
    assert detail_record._release_projected_agent_detail(agent) is True


def test_orphaned_hydrated_agents_stay_collectible(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    timestamp = stamp(20260521090000, 0)
    artifact_dir = f"/tmp/projects/retention-proj/artifacts/ace-run/{timestamp}"
    _patch_hydration(
        tmp_path, monkeypatch, {artifact_dir: full_record(artifact_dir, timestamp)}
    )
    agent = list_agent(timestamp, artifact_dir, cl_name="retention-orphan")
    assert hydrate_projected_agent(agent) is True
    assert agent.record_shape == "full"

    ref = weakref.ref(agent)
    generation = id(agent)
    del agent
    gc.collect()
    assert ref() is None
    assert generation not in detail_record._detail_owner

    # A replacement roster still prunes any dead registration from earlier
    # versions of the weakref owner before growing or restoring it.
    timestamp2 = stamp(20260521090000, 1)
    artifact_dir2 = f"/tmp/projects/retention-proj/artifacts/ace-run/{timestamp2}"
    records = {artifact_dir2: full_record(artifact_dir2, timestamp2)}
    _patch_hydration(tmp_path, monkeypatch, records)
    agent2 = list_agent(timestamp2, artifact_dir2, cl_name="retention-orphan")
    assert hydrate_projected_agent(agent2) is True
    assert len(detail_record._detail_owner) <= 2
