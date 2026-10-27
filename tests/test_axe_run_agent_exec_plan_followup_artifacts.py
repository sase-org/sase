"""Tests for persisted plan follow-up artifacts."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.axe.run_agent_exec_plan_artifacts import store_followup_prompt_artifact
from sase.axe.run_agent_helpers import create_followup_artifacts
from sase.core.artifact_file_facade import list_explicit_artifact_files
from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.llm_provider.commit_finalizer_baseline import (
    FINALIZER_BASELINE_FILENAME,
    capture_dirty_baseline,
    load_finalizer_baseline_records,
)
from sase.llm_provider.commit_finalizer_git import normalize_path
from tests._axe_run_agent_exec_plan_helpers import (
    make_ctx,
    make_state,
    patch_plan_gate_turn_result,
)
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
        patch("sase.axe.run_agent_exec_plan._write_plan_path_artifact"),
        patch("sase.axe.run_agent_exec_plan.update_step_marker_chat_path"),
        patch("sase.axe.run_agent_exec_plan_accept.promote_to_workflow"),
        patch_plan_gate_turn_result(approval),
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


def test_create_followup_artifacts_seeds_main_baseline_for_coder_workspace(
    tmp_path,
    monkeypatch,
) -> None:
    """A plan-approved coder follow-up gets a main record for its workspace."""

    def _init_repo(path: Path, contents: str) -> None:
        path.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
        subprocess.run(
            ["git", "config", "user.name", "SASE Test"], cwd=path, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "sase-test@example.invalid"],
            cwd=path,
            check=True,
        )
        (path / "README.md").write_text(contents, encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=path, check=True)

    workspace = tmp_path / "workspace"
    stale_primary = tmp_path / "primary"
    _init_repo(workspace, "workspace\n")
    _init_repo(stale_primary, "primary\n")
    parent = tmp_path / "parent-artifacts"
    followup = tmp_path / "followup-artifacts"
    followup.mkdir()
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260521_120000")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(workspace))
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    capture_dirty_baseline(str(stale_primary), str(parent))

    with patch(
        "sase.axe.run_agent_helpers.create_artifacts_directory",
        return_value=str(followup),
    ):
        create_followup_artifacts(
            "test_proj",
            {"model": "opus", "workspace_dir": str(workspace)},
            "--code",
            "20261027120000",
            workspace_num=14,
            prev_artifacts_dir=str(parent),
        )

    records = load_finalizer_baseline_records(followup)
    assert records is not None
    mains = [
        record
        for record in records
        if record.kind == "main" and record.scope == "run_start"
    ]
    assert len(mains) == 1
    assert mains[0].path == normalize_path(str(workspace))
    assert (followup / FINALIZER_BASELINE_FILENAME).is_file()


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
