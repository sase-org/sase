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


def test_load_workflow_agents_infers_image_from_saved_diff(tmp_path: Path) -> None:
    """Appears-as-agent workflow entries recover image attachments from diff_path."""
    home = tmp_path / "home"
    project_dir = home / ".sase" / "projects" / "proj"
    artifacts = project_dir / "artifacts" / "ace-run" / "20260430032430"
    artifacts.mkdir(parents=True)
    (project_dir / "proj.gp").write_text("NAME: proj\n", encoding="utf-8")

    workspace = tmp_path / "workspace"
    image = workspace / "docs" / "images" / "panel.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")
    diff_path = tmp_path / "saved.diff"
    diff_path.write_text(
        "diff --git a/docs/images/panel.png b/docs/images/panel.png\n",
        encoding="utf-8",
    )
    plan_path = str(tmp_path / "plan.md")
    (artifacts / "plan_path.json").write_text(json.dumps({"plan_path": plan_path}))
    (artifacts / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": "tmp_ace_run",
                "status": "completed",
                "appears_as_agent": True,
                "context": {"cl_name": "feature"},
                "steps": [
                    {
                        "name": "agent",
                        "status": "completed",
                        "output": {
                            "diff_path": str(diff_path),
                            "meta_workspace": "101",
                        },
                    }
                ],
            }
        )
    )

    with (
        patch(
            "sase.ace.tui.models._loaders._workflow_loaders.Path.home",
            return_value=home,
        ),
        patch(
            "sase.ace.tui.models._loaders._image_attachments._resolve_workspace_dir",
            return_value=str(workspace),
        ),
    ):
        from sase.ace.tui.models._loaders import load_workflow_agents

        agents = load_workflow_agents()

    assert len(agents) == 1
    assert agents[0].extra_files == [plan_path, str(image.resolve())]
