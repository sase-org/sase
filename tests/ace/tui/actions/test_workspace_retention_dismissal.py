"""Dismissal tests for live terminal workspace claims."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._dismiss_persistence import (
    _release_held_workspace_claims,
)
from sase.running_field import WorkspaceClaim, get_claimed_workspaces
from tests._running_field_helpers import create_project_file_with_running


def test_dismiss_releases_live_gate_claim_only_for_its_retention_record(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    diagnostics = artifacts / "diagnostics"
    diagnostics.mkdir(parents=True)
    timestamp = "20260101120000"
    claim = WorkspaceClaim(
        workspace_num=17,
        workflow="ace-gate",
        cl_name="feature",
        pid=os.getpid(),
        artifacts_timestamp=timestamp,
        pinned=True,
    )
    project_file = create_project_file_with_running(tmp_path, [claim])
    record_path = diagnostics / "workspace_retention.json"
    record_path.write_text(
        json.dumps(
            {
                "kind": "terminal_workspace_retention",
                "disposition": "retain",
                "workspace_num": claim.workspace_num,
                "workflow": claim.workflow,
                "cl_name": claim.cl_name,
                "artifacts_timestamp": timestamp,
                "pid": claim.pid,
                "workspace_dir": str(tmp_path / "workspace-17"),
            }
        ),
        encoding="utf-8",
    )

    with (
        patch(
            "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
            return_value=artifacts,
        ),
        patch(
            "sase.ace.hooks.processes.is_process_running",
            return_value=True,
        ) as process_running,
    ):
        released = _release_held_workspace_claims(
            project_file,
            timestamp,
            claim.cl_name,
        )

    assert released == 1
    process_running.assert_not_called()
    assert get_claimed_workspaces(project_file) == []
    settled = json.loads(record_path.read_text(encoding="utf-8"))
    assert settled["settled_reason"] == "dismissed"
    assert settled["settled_at"]
