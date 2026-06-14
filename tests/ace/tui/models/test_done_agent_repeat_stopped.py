"""Repeat-chain STOP slots load as a distinct ``STOPPED`` agent status.

A repeat slot skipped by a predecessor's ``STOP`` output variable writes
``done.json`` with ``outcome: "completed"`` (so ``%wait`` cascading still
resolves it) plus ``repeat_stopped: true``. Both the direct filesystem loader
and the snapshot loader must surface that as a non-error terminal ``STOPPED``
row rather than a generic ``DONE``.
"""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.models._loaders._done_loaders import (
    _load_done_agent_for_dir,
    load_done_agents_from_snapshot,
)
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    DoneMarkerWire,
)


def _snapshot(record: AgentArtifactRecordWire, root: Path) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(root),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[record],
    )


def test_fs_loader_maps_repeat_stopped_marker_to_stopped(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "20260427125000"
    artifact_dir.mkdir()
    done = {
        "cl_name": "feature_repeat",
        "project_file": "/tmp/project.sase",
        "outcome": "completed",
        "repeat_stopped": True,
        "stopped_by": "repeat_slot_1",
    }
    (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.status == "STOPPED"
    # Not an error: error fields stay empty.
    assert agent.error_message is None
    assert agent.error_traceback is None


def test_fs_loader_completed_without_repeat_stopped_is_done(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "20260427120000"
    artifact_dir.mkdir()
    done = {
        "cl_name": "feature_alpha",
        "project_file": "/tmp/project.sase",
        "outcome": "completed",
    }
    (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.status == "DONE"


def test_snapshot_loader_maps_repeat_stopped_marker_to_stopped(
    tmp_path: Path,
) -> None:
    record = AgentArtifactRecordWire(
        project_name="myproj",
        project_dir=str(tmp_path / "myproj"),
        project_file=str(tmp_path / "myproj" / "myproj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(tmp_path / "artifacts" / "ace-run" / "20260427125000"),
        timestamp="20260427125000",
        done=DoneMarkerWire(
            outcome="completed",
            cl_name="feature_repeat",
            project_file="/tmp/project.sase",
            repeat_stopped=True,
            stopped_by="repeat_slot_1",
        ),
        has_done_marker=True,
    )

    agents = load_done_agents_from_snapshot(_snapshot(record, tmp_path), {}, {})

    assert len(agents) == 1
    assert agents[0].status == "STOPPED"
    assert agents[0].error_message is None
    assert agents[0].error_traceback is None
