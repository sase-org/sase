"""Completed epic-approval outcomes retain their semantic TUI status."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.models._loaders._done_loaders import _load_done_agent_for_dir


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    [
        ("epic_approved", "EPIC APPROVED"),
        ("epic_launch_failed", "FAILED"),
    ],
)
def test_fs_loader_maps_epic_terminal_outcomes(
    tmp_path: Path,
    outcome: str,
    expected_status: str,
) -> None:
    artifact_dir = tmp_path / "20260715120000"
    artifact_dir.mkdir()
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "cl_name": "epic_plan",
                "project_file": "/tmp/project.sase",
                "outcome": outcome,
            }
        ),
        encoding="utf-8",
    )

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.status == expected_status
