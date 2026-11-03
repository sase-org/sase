"""Hijacked done markers load as HIJACKED / ESCALATED / CONTINUED."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

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
from sase.core.agent_auto_restart_wire import AgentRecoveryWire


def _snapshot(record: AgentArtifactRecordWire, root: Path) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(root),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[record],
    )


def test_fs_loader_maps_hijacked_pending_to_hijacked(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "20260427130000"
    artifact_dir.mkdir()
    done = {
        "cl_name": "feature_hijack",
        "project_file": "/tmp/project.sase",
        "outcome": "hijacked",
        "recovery": {"state": "pending", "kind": "hijack", "hijack_id": "h-1"},
    }
    (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")

    with patch(
        "sase.agent.hijack.core.agent_hijack_status_for_done_marker",
        return_value="HIJACKED",
    ):
        agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.status == "HIJACKED"
    assert agent.error_message is None


def test_snapshot_loader_maps_resolved_model_change_to_escalated(
    tmp_path: Path,
) -> None:
    record = AgentArtifactRecordWire(
        project_name="sase",
        project_dir=str(tmp_path / "sase"),
        project_file=str(tmp_path / "sase" / "sase.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(tmp_path / "20260427130100"),
        timestamp="20260427130100",
        has_done_marker=True,
        done=DoneMarkerWire(
            outcome="hijacked",
            cl_name="feature_hijack",
            project_file="/tmp/project.sase",
            recovery=AgentRecoveryWire(
                state="resolved",
                kind="hijack",
                hijack_id="h-1",
                model_changed=True,
            ),
        ),
    )
    with patch(
        "sase.agent.hijack.core.agent_hijack_status_for_done_marker",
        return_value="ESCALATED",
    ):
        agents = load_done_agents_from_snapshot(_snapshot(record, tmp_path), {}, {})

    assert len(agents) == 1
    assert agents[0].status == "ESCALATED"


def test_snapshot_loader_maps_resolved_same_model_to_continued(
    tmp_path: Path,
) -> None:
    record = AgentArtifactRecordWire(
        project_name="sase",
        project_dir=str(tmp_path / "sase"),
        project_file=str(tmp_path / "sase" / "sase.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(tmp_path / "20260427130200"),
        timestamp="20260427130200",
        has_done_marker=True,
        done=DoneMarkerWire(
            outcome="hijacked",
            cl_name="feature_hijack",
            project_file="/tmp/project.sase",
            recovery=AgentRecoveryWire(
                state="resolved",
                kind="hijack",
                hijack_id="h-1",
                model_changed=False,
            ),
        ),
    )
    with patch(
        "sase.agent.hijack.core.agent_hijack_status_for_done_marker",
        return_value="CONTINUED",
    ):
        agents = load_done_agents_from_snapshot(_snapshot(record, tmp_path), {}, {})

    assert len(agents) == 1
    assert agents[0].status == "CONTINUED"
