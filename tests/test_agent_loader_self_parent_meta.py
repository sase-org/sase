"""Regression tests for self-parent metadata on restored agent roots."""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models._loaders._done_loaders import (
    load_done_agents,
    load_done_agents_from_snapshot,
)
from sase.ace.tui.models._loaders._workflow_loaders import load_workflow_agents
from sase.ace.tui.models._loaders._workflow_snapshot_loaders import (
    load_workflow_agents_from_snapshot,
)
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
    WorkflowStateWire,
)


def test_filesystem_loader_ignores_self_parent_timestamp_on_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_ts = "20260527101010"
    child_ts = "20260527101111"
    sase_home = tmp_path / ".sase"
    project_dir = sase_home / "projects" / "home"
    root_dir = project_dir / "artifacts" / "ace-run" / root_ts
    child_dir = project_dir / "artifacts" / "ace-run" / child_ts
    root_dir.mkdir(parents=True)
    child_dir.mkdir(parents=True)
    monkeypatch.setenv("SASE_HOME", str(sase_home))

    _write_json(
        root_dir / "workflow_state.json",
        {
            "status": "completed",
            "context": {"cl_name": "home"},
            "steps": [],
            "current_step_index": 0,
            "workflow_name": "ace(run)",
            "appears_as_agent": True,
        },
    )
    _write_json(
        root_dir / "agent_meta.json", {"name": "home", "parent_timestamp": root_ts}
    )
    _write_json(
        child_dir / "done.json",
        {
            "outcome": "completed",
            "cl_name": "home",
            "project_file": str(project_dir / "home.sase"),
        },
    )
    _write_json(
        child_dir / "agent_meta.json",
        {"name": "home.code", "parent_timestamp": root_ts},
    )

    roots = load_workflow_agents(timestamp_dirs=[(project_dir, root_dir)])
    children = load_done_agents({}, {})

    assert len(roots) == 1
    assert roots[0].raw_suffix == root_ts
    assert roots[0].parent_timestamp is None
    assert not roots[0].is_workflow_child
    assert [(child.raw_suffix, child.parent_timestamp) for child in children] == [
        (child_ts, root_ts)
    ]
    assert children[0].is_workflow_child

    visible, fold_counts = filter_agents_by_fold_state(
        [roots[0], children[0]], FoldStateManager()
    )
    assert [agent.raw_suffix for agent in visible] == [root_ts]
    assert fold_counts == {root_ts: (1, 0)}


def test_wire_loader_ignores_self_parent_timestamp_on_root() -> None:
    root_ts = "20260527101010"
    child_ts = "20260527101111"
    project_dir = "/tmp/projects/home"
    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[
            AgentArtifactRecordWire(
                project_name="home",
                project_dir=project_dir,
                project_file=f"{project_dir}/home.sase",
                workflow_dir_name="ace-run",
                artifact_dir=f"{project_dir}/artifacts/ace-run/{root_ts}",
                timestamp=root_ts,
                agent_meta=AgentMetaWire(name="home", parent_timestamp=root_ts),
                workflow_state=WorkflowStateWire(
                    workflow_name="ace(run)",
                    cl_name="home",
                    status="completed",
                    appears_as_agent=True,
                ),
            ),
            AgentArtifactRecordWire(
                project_name="home",
                project_dir=project_dir,
                project_file=f"{project_dir}/home.sase",
                workflow_dir_name="ace-run",
                artifact_dir=f"{project_dir}/artifacts/ace-run/{child_ts}",
                timestamp=child_ts,
                agent_meta=AgentMetaWire(name="home.code", parent_timestamp=root_ts),
                done=DoneMarkerWire(
                    outcome="completed",
                    cl_name="home",
                    project_file=f"{project_dir}/home.sase",
                ),
                has_done_marker=True,
            ),
        ],
    )

    roots = load_workflow_agents_from_snapshot(snapshot)
    children = load_done_agents_from_snapshot(snapshot, {}, {})

    assert len(roots) == 1
    assert roots[0].raw_suffix == root_ts
    assert roots[0].parent_timestamp is None
    assert not roots[0].is_workflow_child
    assert [(child.raw_suffix, child.parent_timestamp) for child in children] == [
        (child_ts, root_ts)
    ]
    assert children[0].is_workflow_child

    visible, fold_counts = filter_agents_by_fold_state(
        [roots[0], children[0]], FoldStateManager()
    )
    assert [agent.raw_suffix for agent in visible] == [root_ts]
    assert fold_counts == {root_ts: (1, 0)}


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")
