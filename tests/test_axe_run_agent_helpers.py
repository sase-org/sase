"""Tests for axe_run_agent helper utilities."""

import json
import os
from unittest.mock import patch

from sase.axe.run_agent_helpers import (
    create_followup_artifacts,
    normalize_handoff_interruption_state,
    promote_to_workflow,
    update_meta_field,
)
from sase.plan_chain import PLAN_CHAIN_PARENT_TIMESTAMP_FIELD


def test_update_meta_field_sets_key(tmp_path) -> None:
    """update_meta_field reads, sets a key, and writes back."""
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"pid": 123}))

    update_meta_field(str(tmp_path), "plan_submitted_at", "2025-06-15T10:05:00+00:00")

    meta = json.loads(meta_path.read_text())
    assert meta["plan_submitted_at"] == "2025-06-15T10:05:00+00:00"
    assert meta["pid"] == 123


def test_update_meta_field_missing_file(tmp_path) -> None:
    """update_meta_field is a no-op when agent_meta.json is missing."""
    update_meta_field(str(tmp_path), "key", "value")
    # No error raised, no file created
    assert not (tmp_path / "agent_meta.json").exists()


def test_promote_to_workflow_renames_and_adds_workflow_name(tmp_path) -> None:
    """promote_to_workflow sets name to base.plan and adds workflow_name."""
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"name": "a", "pid": 123}))

    promote_to_workflow(str(tmp_path), "a")

    meta = json.loads(meta_path.read_text())
    assert meta["name"] == "a.plan"
    assert meta["workflow_name"] == "a"
    assert meta["role_suffix"] == ".plan"
    assert meta["pid"] == 123


def test_promote_to_workflow_can_promote_question_phase(tmp_path) -> None:
    """Question handoff roots are named with the question suffix."""
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"name": "a", "pid": 123}))

    promote_to_workflow(str(tmp_path), "a", role_suffix=".q")

    meta = json.loads(meta_path.read_text())
    assert meta["name"] == "a.q"
    assert meta["workflow_name"] == "a"
    assert meta["role_suffix"] == ".q"


def test_create_followup_with_name_override(tmp_path) -> None:
    """agent_name_override replaces the inherited name in followup meta."""
    new_dir = str(tmp_path / "new")
    os.makedirs(new_dir)

    with patch(
        "sase.axe.run_agent_helpers.create_artifacts_directory",
        return_value=new_dir,
    ):
        create_followup_artifacts(
            "proj",
            {"name": "a", "model": "test"},
            ".coder",
            "20260326120000",
            agent_name_override="a.coder",
            workflow_name="a",
        )

    meta = json.loads((tmp_path / "new" / "agent_meta.json").read_text())
    assert meta["name"] == "a.coder"
    assert meta["workflow_name"] == "a"
    assert meta["role_suffix"] == ".coder"
    assert meta["parent_timestamp"] == "20260326120000"
    assert meta[PLAN_CHAIN_PARENT_TIMESTAMP_FIELD] == "20260326120000"


def test_create_followup_inherits_name_without_override(tmp_path) -> None:
    """Without agent_name_override, name is inherited from base_meta."""
    new_dir = str(tmp_path / "new")
    os.makedirs(new_dir)

    with patch(
        "sase.axe.run_agent_helpers.create_artifacts_directory",
        return_value=new_dir,
    ):
        create_followup_artifacts(
            "proj",
            {"name": "a", "model": "test"},
            ".code",
            "20260326120000",
        )

    meta = json.loads((tmp_path / "new" / "agent_meta.json").read_text())
    assert meta["name"] == "a"
    assert "workflow_name" not in meta


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


def test_normalize_handoff_interruption_state_rewrites_exit_code_143(
    tmp_path,
) -> None:
    """Exit code 143 (128+15) is the shell-wrapped SIGTERM variant."""
    artifacts_dir = tmp_path

    state_file = artifacts_dir / "workflow_state.json"
    state_file.write_text(
        json.dumps(
            {
                "status": "failed",
                "error": "Step 'main' failed: LLMInvocationError: Error running LLM provider command (exit code 143)",
                "traceback": "tb",
                "steps": [
                    {
                        "name": "main",
                        "status": "failed",
                        "error": "LLMInvocationError: Error running LLM provider command (exit code 143)",
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
                "error": "LLMInvocationError: Error running LLM provider command (exit code 143)",
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
    assert state_data["steps"][0]["status"] == "completed"
    assert state_data["steps"][0]["error"] is None

    marker_data = json.loads(marker_file.read_text(encoding="utf-8"))
    assert marker_data["status"] == "completed"
    assert marker_data["error"] is None


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
