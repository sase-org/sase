"""Tests for axe_run_agent helper utilities."""

import json

from sase.axe_run_agent_helpers import normalize_handoff_interruption_state


def test_normalize_handoff_interruption_state_rewrites_sigterm_failures(
    tmp_path,
) -> None:
    artifacts_dir = tmp_path

    state_file = artifacts_dir / "workflow_state.json"
    state_file.write_text(
        json.dumps(
            {
                "status": "failed",
                "error": "Step 'main' failed: LLMInvocationError: exit code -15",
                "traceback": "tb",
                "steps": [
                    {
                        "name": "setup",
                        "status": "completed",
                        "error": None,
                        "traceback": None,
                    },
                    {
                        "name": "main",
                        "status": "failed",
                        "error": "LLMInvocationError: exit code -15",
                        "traceback": "tb",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    marker_file = artifacts_dir / "prompt_step_main.json"
    marker_file.write_text(
        json.dumps(
            {
                "step_name": "main",
                "status": "failed",
                "error": "LLMInvocationError: exit code -15",
                "traceback": "tb",
            }
        ),
        encoding="utf-8",
    )

    normalize_handoff_interruption_state(str(artifacts_dir))

    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["status"] == "completed"
    assert state_data["error"] is None
    assert state_data["traceback"] is None
    assert state_data["steps"][1]["status"] == "completed"
    assert state_data["steps"][1]["error"] is None
    assert state_data["steps"][1]["traceback"] is None

    marker_data = json.loads(marker_file.read_text(encoding="utf-8"))
    assert marker_data["status"] == "completed"
    assert marker_data["error"] is None
    assert marker_data["traceback"] is None


def test_normalize_handoff_interruption_state_keeps_real_failures(tmp_path) -> None:
    artifacts_dir = tmp_path

    state_file = artifacts_dir / "workflow_state.json"
    state_file.write_text(
        json.dumps(
            {
                "status": "failed",
                "error": "Step 'main' failed: API quota exhausted",
                "traceback": "tb",
                "steps": [
                    {
                        "name": "main",
                        "status": "failed",
                        "error": "API quota exhausted",
                        "traceback": "tb",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    marker_file = artifacts_dir / "prompt_step_main.json"
    marker_file.write_text(
        json.dumps(
            {
                "step_name": "main",
                "status": "failed",
                "error": "API quota exhausted",
                "traceback": "tb",
            }
        ),
        encoding="utf-8",
    )

    normalize_handoff_interruption_state(str(artifacts_dir))

    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["status"] == "failed"
    assert state_data["error"] == "Step 'main' failed: API quota exhausted"
    assert state_data["steps"][0]["status"] == "failed"

    marker_data = json.loads(marker_file.read_text(encoding="utf-8"))
    assert marker_data["status"] == "failed"
    assert marker_data["error"] == "API quota exhausted"
