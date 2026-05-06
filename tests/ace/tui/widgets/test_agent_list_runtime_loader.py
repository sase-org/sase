"""Tests for workflow-step runtime metadata loading."""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.models._loaders._workflow_step_loaders import (
    _load_workflow_agent_steps_for_dir,
)


def test_workflow_step_loader_marks_appears_as_agent_parent(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    timestamp_dir = project_dir / "artifacts" / "ace-run" / "20260425143000"
    timestamp_dir.mkdir(parents=True)
    (timestamp_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": "run",
                "status": "running",
                "appears_as_agent": True,
            }
        )
    )
    (timestamp_dir / "prompt_step_main.json").write_text(
        json.dumps(
            {
                "workflow_name": "run",
                "step_name": "main",
                "step_type": "agent",
                "status": "in_progress",
            }
        )
    )

    agents, _ = _load_workflow_agent_steps_for_dir(project_dir, timestamp_dir)

    assert len(agents) == 1
    assert agents[0].parent_workflow == "run"
    assert agents[0].parent_appears_as_agent is True
