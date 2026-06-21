from __future__ import annotations

import json
from pathlib import Path

from sase.ace.revert_agent import agent_is_reverted
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


def _write_done_marker(artifact_dir: Path) -> None:
    artifact_dir.mkdir()
    done = {
        "cl_name": "feature_reverted",
        "project_file": "/tmp/project.sase",
        "outcome": "completed",
    }
    (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")


def _snapshot(record: AgentArtifactRecordWire, root: Path) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(root),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[record],
    )


def test_agent_is_reverted_detects_revert_result_marker(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "20260621120000"

    assert agent_is_reverted(str(artifact_dir)) is False

    artifact_dir.mkdir()
    (artifact_dir / "revert_result.json").write_text("{}\n", encoding="utf-8")

    assert agent_is_reverted(str(artifact_dir)) is True


def test_fs_done_loader_sets_reverted_from_marker(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "20260621120100"
    _write_done_marker(artifact_dir)
    (artifact_dir / "revert_result.json").write_text("{}\n", encoding="utf-8")

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.reverted is True


def test_fs_done_loader_defaults_reverted_false_without_marker(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "20260621120200"
    _write_done_marker(artifact_dir)

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.reverted is False


def test_snapshot_done_loader_sets_reverted_from_record_artifact_dir(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "artifacts" / "ace-run" / "20260621120300"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "revert_result.json").write_text("{}\n", encoding="utf-8")
    record = AgentArtifactRecordWire(
        project_name="myproj",
        project_dir=str(tmp_path / "myproj"),
        project_file=str(tmp_path / "myproj" / "myproj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(artifact_dir),
        timestamp="20260621120300",
        done=DoneMarkerWire(
            outcome="completed",
            cl_name="feature_reverted",
            project_file="/tmp/project.sase",
        ),
        has_done_marker=True,
    )

    agents = load_done_agents_from_snapshot(_snapshot(record, tmp_path), {}, {})

    assert len(agents) == 1
    assert agents[0].reverted is True
