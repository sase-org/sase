"""Tests for workflow-state agent loading (load_workflow_states)."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    WorkflowStateWire,
)


def test_workflow_waiting_hitl_dead_pid_marked_as_failed() -> None:
    """Test that a WAITING INPUT workflow with dead PID is marked as FAILED."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sase_projects = Path(tmpdir) / ".sase" / "projects" / "myproject"
        workflow_artifacts = (
            sase_projects / "artifacts" / "workflow-deploy" / "20260101120000"
        )
        workflow_artifacts.mkdir(parents=True)
        (sase_projects / "myproject.sase").touch()

        state = {
            "workflow_name": "deploy",
            "status": "waiting_hitl",
            "pid": 99999,
            "context": {"cl_name": "test_cl"},
            "steps": [],
        }
        (workflow_artifacts / "workflow_state.json").write_text(json.dumps(state))

        with (
            patch(
                "sase.ace.tui.models._loaders._workflow_loaders.Path.home",
                return_value=Path(tmpdir),
            ),
            patch(
                "sase.ace.tui.models._loaders._workflow_loaders.is_process_running",
                return_value=False,
            ),
        ):
            from sase.ace.tui.models._loaders import load_workflow_states

            entries = load_workflow_states()

        assert len(entries) == 1
        assert entries[0].status == "FAILED"


def test_load_workflow_states_preserves_activity_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sase_projects = Path(tmpdir) / ".sase" / "projects" / "myproject"
        workflow_artifacts = (
            sase_projects / "artifacts" / "workflow-deploy" / "20260101120000"
        )
        workflow_artifacts.mkdir(parents=True)
        (sase_projects / "myproject.sase").touch()

        state = {
            "workflow_name": "deploy",
            "status": "running",
            "pid": None,
            "context": {"cl_name": "test_cl"},
            "steps": [],
            "activity": "PDF 2/5 docs/notes.md",
        }
        (workflow_artifacts / "workflow_state.json").write_text(json.dumps(state))

        with patch(
            "sase.ace.tui.models._loaders._workflow_loaders.Path.home",
            return_value=Path(tmpdir),
        ):
            from sase.ace.tui.models._loaders import (
                load_workflow_agents,
                load_workflow_states,
            )

            entries = load_workflow_states()
            agents = load_workflow_agents()

    assert entries[0].activity == "PDF 2/5 docs/notes.md"
    assert agents[0].activity == "PDF 2/5 docs/notes.md"


def test_load_workflow_states_from_snapshot_preserves_activity_metadata() -> None:
    from sase.ace.tui.models._loaders import (
        load_workflow_agents_from_snapshot,
        load_workflow_states_from_snapshot,
    )

    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/.sase/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[
            AgentArtifactRecordWire(
                project_name="myproject",
                project_dir="/tmp/.sase/projects/myproject",
                project_file="/tmp/.sase/projects/myproject/myproject.sase",
                workflow_dir_name="workflow-deploy",
                artifact_dir="/tmp/.sase/projects/myproject/artifacts/workflow-deploy/20260101120000",
                timestamp="20260101120000",
                workflow_state=WorkflowStateWire(
                    workflow_name="deploy",
                    cl_name="test_cl",
                    status="running",
                    activity="PDFs done 4/5 (1 skipped)",
                ),
            )
        ],
    )

    entries = load_workflow_states_from_snapshot(snapshot)
    agents = load_workflow_agents_from_snapshot(snapshot)

    assert entries[0].activity == "PDFs done 4/5 (1 skipped)"
    assert agents[0].activity == "PDFs done 4/5 (1 skipped)"
