"""Tests for persisted plan follow-up artifacts."""

import json
from pathlib import Path
from unittest.mock import patch

from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.axe.run_agent_exec_plan_artifacts import store_followup_prompt_artifact
from sase.axe.run_agent_helpers import create_followup_artifacts
from sase.core.artifact_file_facade import list_explicit_artifact_files
from sase.llm_provider._plan_utils import PlanApprovalResult
from tests._axe_run_agent_exec_plan_helpers import make_ctx, make_state
from tests.plan_validation_helpers import VALID_EPIC_PLAN
from tests.sdd_policy_helpers import patched_sdd_policy


def test_handle_plan_marker_leaves_epic_kickoff_metadata_to_host(
    tmp_path,
) -> None:
    """The agent does not synthesize metadata for the host-owned launch."""
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    plan_file = str(tmp_path / "plan.md")
    (tmp_path / "plan.md").write_text(VALID_EPIC_PLAN)
    approval = PlanApprovalResult(action="epic", plan_file=plan_file)
    with (
        patch("sase.axe.run_agent_exec_plan.normalize_handoff_interruption_state"),
        patch("sase.axe.run_agent_exec_plan.reset_killed"),
        patch("sase.axe.run_agent_exec_plan.was_killed", return_value=False),
        patch("sase.axe.run_agent_exec_plan._write_plan_path_artifact"),
        patch("sase.axe.run_agent_exec_plan.update_step_marker_chat_path"),
        patch("sase.axe.run_agent_exec_plan_accept.promote_to_workflow"),
        patch("sase.axe.run_agent_exec_plan_accept._commit_sdd_spec"),
        patch(
            "sase.llm_provider._plan_utils.handle_plan_approval",
            return_value=approval,
        ),
        patch("sase.history.chat.save_chat_history", return_value="/fake/chat"),
        patch("sase.history.chat_extras.format_extra_sections", return_value=""),
        patch("sase.history.chat_links.format_plan_as_response", return_value="plan"),
        patched_sdd_policy("in_tree"),
        patch("sase.sdd.beads.ensure_beads_initialized"),
        patch(
            "sase.sdd.files.write_sdd_spec",
            return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
        ),
        patch("sase.sdd.files.expand_prompt_for_spec", side_effect=lambda p: p),
    ):
        handle_plan_marker({"plan_file": plan_file}, ctx, state)

    meta = json.loads((tmp_path / "artifacts" / "agent_meta.json").read_text())
    assert "epic_started_at" not in meta
    assert "epic_bead_id" not in meta


def test_create_followup_artifacts_persists_plan_committed_flag(tmp_path) -> None:
    followup = tmp_path / "followup"
    followup.mkdir()

    with patch(
        "sase.axe.run_agent_helpers.create_artifacts_directory",
        return_value=str(followup),
    ):
        result = create_followup_artifacts(
            "test_proj",
            {"model": "opus", "changespec_name": "test"},
            ".code",
            "20260331_120000",
            workspace_num=1,
            relationships={
                "plan_path": str(tmp_path / "plan.md"),
                "plan_committed": False,
                "source_plan_agent_name": "root--plan",
            },
        )

    assert result == str(followup)
    meta = json.loads((followup / "agent_meta.json").read_text())
    assert meta["plan_committed"] is False
    assert meta["source_plan_agent_name"] == "root--plan"


def test_create_followup_artifacts_inherits_model_alias_overrides(tmp_path) -> None:
    followup = tmp_path / "followup-overrides"
    followup.mkdir()

    with patch(
        "sase.axe.run_agent_helpers.create_artifacts_directory",
        return_value=str(followup),
    ):
        create_followup_artifacts(
            "test_proj",
            {"model_alias_overrides": {"coder": "sonnet"}},
            "--code",
            "20260711120000",
        )

    meta = json.loads((followup / "agent_meta.json").read_text())
    assert meta["model_alias_overrides"] == {"coder": "sonnet"}


def test_create_followup_artifacts_inherits_epic_work_metadata(tmp_path) -> None:
    followup = tmp_path / "followup-epic-work"
    followup.mkdir()

    with patch(
        "sase.axe.run_agent_helpers.create_artifacts_directory",
        return_value=str(followup),
    ):
        create_followup_artifacts(
            "test_proj",
            {
                "sdd_plan_path": "sdd/plans/202607/epic.md",
                "epic_plan_ref": "sdd/plans/202607/parent-epic.md",
                "plan_committed": True,
                "epic_bead_id": "sase-7",
                "phase_bead_id": "sase-7.2",
            },
            "--code",
            "20260711120000",
        )

    meta = json.loads((followup / "agent_meta.json").read_text())
    assert meta["sdd_plan_path"] == "sdd/plans/202607/epic.md"
    assert meta["epic_plan_ref"] == "sdd/plans/202607/parent-epic.md"
    assert meta["plan_committed"] is True
    assert meta["epic_bead_id"] == "sase-7"
    assert meta["phase_bead_id"] == "sase-7.2"


def test_store_followup_prompt_artifact_registers_explicit_artifact(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    artifacts_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260508120000"
    )
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": "agent.2"}),
        encoding="utf-8",
    )

    store_followup_prompt_artifact(
        str(artifacts_dir),
        "full rebuilt prompt",
        label="Full feedback prompt",
    )

    artifacts = list_explicit_artifact_files(artifacts_dir)
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.label == "Full feedback prompt"
    assert artifact.kind == "markdown"
    assert artifact.agent_name == "agent.2"
    assert Path(artifact.path).read_text(encoding="utf-8") == "full rebuilt prompt"
