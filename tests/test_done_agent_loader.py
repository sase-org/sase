"""Tests for load_done_agents reading step_output from done.json."""

import json
from pathlib import Path

from sase.axe_run_agent_helpers import extract_step_output_and_diff_path


def test_extract_step_output_from_workflow_state(tmp_path: Path) -> None:
    """Verify extract_step_output_and_diff_path reads workflow_state.json."""
    state_data = {
        "workflow_name": "test",
        "status": "completed",
        "steps": [
            {
                "name": "step1",
                "status": "completed",
                "output": {"meta_id": "abc123", "result": "ok"},
                "output_types": {"meta_id": "text", "result": "text"},
            }
        ],
    }
    state_path = tmp_path / "workflow_state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f)

    step_output, diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert step_output == {"meta_id": "abc123", "result": "ok"}
    assert diff_path is None


def test_extract_diff_path_last_step_multiple_paths_first_wins(
    tmp_path: Path,
) -> None:
    """Verify first path-typed output wins when last step has multiple."""
    state_data = {
        "workflow_name": "test",
        "status": "completed",
        "steps": [
            {
                "name": "step1",
                "status": "completed",
                "output": {
                    "first_path": "/tmp/first.patch",
                    "second_path": "/tmp/second.patch",
                },
                "output_types": {"first_path": "path", "second_path": "path"},
            }
        ],
    }
    state_path = tmp_path / "workflow_state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f)

    _step_output, diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert diff_path == "/tmp/first.patch"


def test_extract_diff_path_fallback_to_direct_key(tmp_path: Path) -> None:
    """Verify diff_path fallback reads direct diff_path key from last step output."""
    state_data = {
        "workflow_name": "test",
        "status": "completed",
        "steps": [
            {
                "name": "step1",
                "status": "completed",
                "output": {"diff_path": "/tmp/changes.diff"},
            }
        ],
    }
    state_path = tmp_path / "workflow_state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f)

    _step_output, diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert diff_path == "/tmp/changes.diff"


def test_extract_returns_none_without_workflow_state(tmp_path: Path) -> None:
    """Verify graceful handling when workflow_state.json doesn't exist."""
    step_output, diff_path = extract_step_output_and_diff_path(str(tmp_path))

    assert step_output is None
    assert diff_path is None
