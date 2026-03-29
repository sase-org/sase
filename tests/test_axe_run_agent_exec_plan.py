"""Tests for axe run_agent_exec_plan helpers."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.axe.run_agent_exec_plan import _get_embedded_workflow_refs


def test_get_embedded_workflow_refs_excludes_vcs_when_tag_set(tmp_path) -> None:
    """VCS-tagged workflows are excluded when vcs_tag is set."""
    meta = tmp_path / "embedded_workflows.json"
    meta.write_text(
        json.dumps(
            [
                {"name": "gh", "tags": ["vcs", "rollover"]},
                {"name": "propose", "tags": ["rollover"]},
            ]
        )
    )

    result = _get_embedded_workflow_refs(str(tmp_path), "#gh:sase ")
    assert "#gh" not in result
    assert "#propose" in result


def test_get_embedded_workflow_refs_includes_vcs_when_tag_none(tmp_path) -> None:
    """VCS-tagged workflows ARE included when vcs_tag is None."""
    meta = tmp_path / "embedded_workflows.json"
    meta.write_text(
        json.dumps(
            [
                {"name": "gh", "args": {"repo": "sase"}, "tags": ["vcs", "rollover"]},
                {"name": "propose", "tags": ["rollover"]},
            ]
        )
    )

    result = _get_embedded_workflow_refs(str(tmp_path), None)
    assert "#gh:sase" in result
    assert "#propose" in result


def test_handle_plan_marker_writes_plan_path_to_coder_artifacts(
    tmp_path, monkeypatch
) -> None:
    """handle_plan_marker writes plan_path.json to the coder's artifacts dir."""
    from sase.axe.run_agent_exec import AgentExecContext, LoopState
    from sase.axe.run_agent_exec_plan import handle_plan_marker

    planner_dir = str(tmp_path / "planner_artifacts")
    coder_dir = str(tmp_path / "coder_artifacts")
    Path(planner_dir).mkdir()
    Path(coder_dir).mkdir()

    plan_file = str(tmp_path / "plan.md")
    Path(plan_file).write_text("# Plan\nDo stuff\n")

    ctx = AgentExecContext(
        cl_name="test_cl",
        project_file="/fake/proj.gp",
        workspace_dir=str(tmp_path),
        output_path="/fake/output",
        workspace_num=1,
        timestamp="2026-03-29T00:00:00",
        update_target="",
        project_name="test_project",
        is_home_mode=False,
        artifacts_dir=str(tmp_path / "artifacts"),
        artifacts_timestamp="20260329_000000",
        vcs_tag=None,
        agent_name="test_agent",
        agent_model=None,
        agent_llm_provider=None,
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta={},
        local_xprompts={},
    )

    state = LoopState(
        current_prompt="test prompt",
        current_role_suffix="",
        current_artifacts_dir=planner_dir,
        loop_outcome="",
        sdd_spec_path=None,
        original_prompt="test prompt",
    )

    mock_approval = MagicMock()
    mock_approval.action = "approve"
    mock_approval.plan_file = plan_file
    mock_approval.feedback = None

    mock_write = MagicMock()

    with (
        patch("sase.axe.run_agent_exec_plan.normalize_handoff_interruption_state"),
        patch("sase.axe.run_agent_exec_plan.update_meta_suffix"),
        patch("sase.axe.run_agent_exec_plan.update_meta_field"),
        patch("sase.axe.run_agent_exec_plan.update_step_marker_chat_path"),
        patch("sase.axe.run_agent_exec_plan.reset_killed"),
        patch("sase.axe.run_agent_exec_plan.was_killed", return_value=False),
        patch("sase.axe.run_agent_exec_plan.promote_to_workflow"),
        patch(
            "sase.axe.run_agent_exec_plan.create_followup_artifacts",
            return_value=coder_dir,
        ),
        patch("sase.axe.run_agent_exec_plan._write_plan_path_artifact", mock_write),
        patch(
            "sase.llm_provider._plan_utils.handle_plan_approval",
            return_value=mock_approval,
        ),
        patch("sase.history.chat.save_chat_history", return_value="/fake/chat.md"),
        patch("sase.history.chat_extras.format_extra_sections", return_value=""),
        patch(
            "sase.history.chat_links.format_plan_as_response",
            return_value="plan content",
        ),
        # Make SDD block fail so we skip it cleanly
        patch("sase.sdd.beads.get_sdd_config", side_effect=Exception("skip")),
    ):
        monkeypatch.delenv("SASE_PLAN", raising=False)
        result = handle_plan_marker({"plan_file": plan_file}, ctx, state)

    assert result is None  # continue loop
    assert mock_write.call_count == 2
    # First call: planner artifacts dir
    assert mock_write.call_args_list[0].args[0] == planner_dir
    # Second call: coder artifacts dir
    assert mock_write.call_args_list[1].args[0] == coder_dir
