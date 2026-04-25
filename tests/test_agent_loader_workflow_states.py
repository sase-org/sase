"""Tests for workflow-state agent loading (load_workflow_states)."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch


def test_workflow_waiting_hitl_dead_pid_marked_as_failed() -> None:
    """Test that a WAITING INPUT workflow with dead PID is marked as FAILED."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sase_projects = Path(tmpdir) / ".sase" / "projects" / "myproject"
        sase_artifacts = (
            sase_projects / "artifacts" / "workflow-deploy" / "20260101120000"
        )
        sase_artifacts.mkdir(parents=True)
        (sase_projects / "myproject.gp").touch()

        state = {
            "workflow_name": "deploy",
            "status": "waiting_hitl",
            "pid": 99999,
            "context": {"cl_name": "test_cl"},
            "steps": [],
        }
        (sase_artifacts / "workflow_state.json").write_text(json.dumps(state))

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
