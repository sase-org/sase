"""Tests for axe_run_agent handoff helper utilities."""

import json
from unittest.mock import patch

from sase.axe.run_agent_helpers import (
    finalize_handoff_artifacts_as_completed,
    normalize_handoff_interruption_state,
    update_step_marker_chat_path,
)


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


def test_normalize_handoff_interruption_state_rewrites_agy_exit_code_1(
    tmp_path,
) -> None:
    """agy traps SIGTERM and exits 1 with its own message, unlike claude/codex."""
    artifacts_dir = tmp_path
    agy_error = (
        "LLMInvocationError: Error running LLM provider command (exit code 1)\n"
        "stderr: Error: timeout waiting for response"
    )

    state_file = artifacts_dir / "workflow_state.json"
    state_file.write_text(
        json.dumps(
            {
                "status": "failed",
                "error": agy_error,
                "traceback": "tb",
                "steps": [
                    {
                        "name": "main",
                        "status": "failed",
                        "error": agy_error,
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
                "error": agy_error,
                "traceback": "tb",
                "step_type": "agent",
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
    assert state_data["steps"][0]["traceback"] is None

    marker_data = json.loads(marker_file.read_text(encoding="utf-8"))
    assert marker_data["status"] == "completed"
    assert marker_data["error"] is None
    assert marker_data["traceback"] is None


def test_normalize_handoff_interruption_state_keeps_embedded_step_failures(
    tmp_path,
) -> None:
    """A failed agent marker normalizes; a failed embedded bash marker does not."""
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
                        "name": "main",
                        "status": "failed",
                        "error": "LLMInvocationError: exit code -15",
                        "traceback": "tb",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    agent_marker_file = artifacts_dir / "prompt_step_main.json"
    agent_marker_file.write_text(
        json.dumps(
            {
                "step_name": "main",
                "status": "failed",
                "error": "LLMInvocationError: exit code -15",
                "traceback": "tb",
                "step_type": "agent",
            }
        ),
        encoding="utf-8",
    )

    bash_marker_file = artifacts_dir / "prompt_step_gh__diff.json"
    bash_marker_file.write_text(
        json.dumps(
            {
                "step_name": "gh__diff",
                "status": "failed",
                "error": "gh: command not found",
                "traceback": "tb",
                "step_type": "bash",
            }
        ),
        encoding="utf-8",
    )

    normalize_handoff_interruption_state(str(artifacts_dir))

    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["status"] == "completed"
    assert state_data["steps"][0]["status"] == "completed"

    agent_marker_data = json.loads(agent_marker_file.read_text(encoding="utf-8"))
    assert agent_marker_data["status"] == "completed"
    assert agent_marker_data["error"] is None
    assert agent_marker_data["traceback"] is None

    bash_marker_data = json.loads(bash_marker_file.read_text(encoding="utf-8"))
    assert bash_marker_data["status"] == "failed"
    assert bash_marker_data["error"] == "gh: command not found"


def test_normalize_handoff_interruption_state_treats_missing_step_type_as_agent(
    tmp_path,
) -> None:
    """A marker with no step_type key defaults to agent and is normalized."""
    artifacts_dir = tmp_path

    (artifacts_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "error": "LLMInvocationError: exit code -15",
                "steps": [
                    {
                        "name": "main",
                        "status": "failed",
                        "error": "LLMInvocationError: exit code -15",
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
                "error": "LLMInvocationError: exit code -15",
                "traceback": "tb",
            }
        ),
        encoding="utf-8",
    )

    normalize_handoff_interruption_state(str(artifacts_dir))

    marker_data = json.loads(marker_file.read_text(encoding="utf-8"))
    assert marker_data["status"] == "completed"
    assert marker_data["error"] is None


def test_normalize_handoff_interruption_state_noop_leaves_index_untouched(
    tmp_path,
) -> None:
    """An artifacts dir already at completed triggers zero index refreshes."""
    artifacts_dir = tmp_path

    (artifacts_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "error": None,
                "traceback": None,
                "steps": [
                    {
                        "name": "main",
                        "status": "completed",
                        "error": None,
                        "traceback": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (artifacts_dir / "prompt_step_main.json").write_text(
        json.dumps(
            {
                "step_name": "main",
                "status": "completed",
                "error": None,
                "traceback": None,
                "step_type": "agent",
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    with patch(
        "sase.axe.run_agent_helpers.update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        normalize_handoff_interruption_state(str(artifacts_dir))

    assert calls == []


def test_normalize_handoff_interruption_state_coalesces_index_update(
    tmp_path,
) -> None:
    """State + step marker rewrites produce one artifact-index refresh."""
    artifacts_dir = tmp_path
    (artifacts_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "error": "LLMInvocationError: exit code -15",
                "steps": [
                    {
                        "status": "failed",
                        "error": "LLMInvocationError: exit code -15",
                        "traceback": "tb",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (artifacts_dir / "prompt_step_main.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "error": "LLMInvocationError: exit code -15",
                "traceback": "tb",
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    with patch(
        "sase.axe.run_agent_helpers.update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        normalize_handoff_interruption_state(str(artifacts_dir))

    assert calls == [str(artifacts_dir)]


def test_finalize_handoff_artifacts_completes_non_terminal_state(tmp_path) -> None:
    """In-process SDK SIGTERM leaves markers at in_progress; finalize -> completed."""
    artifacts_dir = tmp_path

    state_file = artifacts_dir / "workflow_state.json"
    state_file.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "steps": [
                    {"name": "plan", "status": "in_progress"},
                ],
            }
        ),
        encoding="utf-8",
    )
    marker_file = artifacts_dir / "prompt_step_plan.json"
    marker_file.write_text(
        json.dumps({"step_name": "plan", "status": "in_progress"}),
        encoding="utf-8",
    )

    finalize_handoff_artifacts_as_completed(str(artifacts_dir))

    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["status"] == "completed"
    assert state_data["steps"][0]["status"] == "completed"

    marker_data = json.loads(marker_file.read_text(encoding="utf-8"))
    assert marker_data["status"] == "completed"


def test_finalize_handoff_artifacts_completes_waiting_hitl(tmp_path) -> None:
    """HITL-save-before-kill leaves marker at waiting_hitl -> completed at handoff."""
    artifacts_dir = tmp_path

    (artifacts_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "status": "waiting_hitl",
                "steps": [{"name": "plan", "status": "waiting_hitl"}],
            }
        ),
        encoding="utf-8",
    )
    marker_file = artifacts_dir / "prompt_step_plan.json"
    marker_file.write_text(
        json.dumps({"step_name": "plan", "status": "waiting_hitl"}),
        encoding="utf-8",
    )

    finalize_handoff_artifacts_as_completed(str(artifacts_dir))

    state_data = json.loads(
        (artifacts_dir / "workflow_state.json").read_text(encoding="utf-8")
    )
    assert state_data["status"] == "completed"
    assert state_data["steps"][0]["status"] == "completed"
    assert json.loads(marker_file.read_text(encoding="utf-8"))["status"] == "completed"


def test_finalize_handoff_artifacts_preserves_real_failures(tmp_path) -> None:
    """A pre-existing non-SIGTERM failure must survive the handoff finalize."""
    artifacts_dir = tmp_path

    state_file = artifacts_dir / "workflow_state.json"
    state_file.write_text(
        json.dumps(
            {
                "status": "failed",
                "error": "API quota exhausted",
                "traceback": "tb",
                "steps": [
                    {
                        "name": "plan",
                        "status": "failed",
                        "error": "API quota exhausted",
                        "traceback": "tb",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    marker_file = artifacts_dir / "prompt_step_plan.json"
    marker_file.write_text(
        json.dumps(
            {
                "step_name": "plan",
                "status": "failed",
                "error": "API quota exhausted",
                "traceback": "tb",
            }
        ),
        encoding="utf-8",
    )

    finalize_handoff_artifacts_as_completed(str(artifacts_dir))

    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["status"] == "failed"
    assert state_data["error"] == "API quota exhausted"
    assert state_data["steps"][0]["status"] == "failed"

    marker_data = json.loads(marker_file.read_text(encoding="utf-8"))
    assert marker_data["status"] == "failed"
    assert marker_data["error"] == "API quota exhausted"


def test_finalize_handoff_artifacts_coalesces_index_update(tmp_path) -> None:
    """State + step rewrites produce exactly one artifact-index refresh."""
    artifacts_dir = tmp_path
    (artifacts_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "status": "in_progress",
                "steps": [{"name": "plan", "status": "in_progress"}],
            }
        ),
        encoding="utf-8",
    )
    (artifacts_dir / "prompt_step_plan.json").write_text(
        json.dumps({"step_name": "plan", "status": "in_progress"}),
        encoding="utf-8",
    )
    calls: list[str] = []

    with patch(
        "sase.axe.run_agent_helpers.update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        finalize_handoff_artifacts_as_completed(str(artifacts_dir))

    assert calls == [str(artifacts_dir)]


def test_update_step_marker_chat_path_coalesces_index_update(tmp_path) -> None:
    """Multiple prompt_step marker edits refresh the index once."""
    (tmp_path / "prompt_step_one.json").write_text(
        json.dumps({"step_name": "one"}),
        encoding="utf-8",
    )
    (tmp_path / "prompt_step_two.json").write_text(
        json.dumps({"step_name": "two", "response_path": None}),
        encoding="utf-8",
    )
    (tmp_path / "prompt_step_embedded__child.json").write_text(
        json.dumps({"step_name": "child"}),
        encoding="utf-8",
    )
    calls: list[str] = []

    with patch(
        "sase.axe.run_agent_helpers.update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        update_step_marker_chat_path(str(tmp_path), "/tmp/chat.md")

    assert calls == [str(tmp_path)]
    assert (
        json.loads((tmp_path / "prompt_step_one.json").read_text())["response_path"]
        == "/tmp/chat.md"
    )
    assert "response_path" not in json.loads(
        (tmp_path / "prompt_step_embedded__child.json").read_text()
    )
