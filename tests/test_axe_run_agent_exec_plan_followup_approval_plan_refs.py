"""Tests for approved plan follow-up plan references."""

import os
from unittest.mock import call, patch

import pytest

from sase.axe import run_agent_exec_plan_accept as accept_mod
from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.llm_provider._plan_utils import PlanApprovalResult
from tests._axe_run_agent_exec_plan_helpers import (
    make_ctx,
    make_state,
    patched_plan_deps,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN


@pytest.fixture
def patch_plan_deps():
    with patched_plan_deps() as mocks:
        yield mocks


@pytest.mark.usefixtures("patch_plan_deps")
class TestPlanFollowupApprovalPlanRefs:
    """Verify plan references used by approved plan follow-ups."""

    def test_coder_prompt_uses_saved_sdd_plan_ref(self, tmp_path) -> None:
        """Normal approved plans hand off the committed canonical plan file."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "scratch_plan.md")
        (tmp_path / "scratch_plan.md").write_text("# Plan")
        sdd_plan = tmp_path / "sdd" / "plans" / "202605" / "scratch_plan.md"
        sdd_plan.parent.mkdir(parents=True)
        sdd_plan.write_text("# Saved Plan")

        approval = PlanApprovalResult(action="approve", plan_file=plan_file)
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(
                    tmp_path
                    / "sdd"
                    / "plans"
                    / "202605"
                    / "prompts"
                    / "scratch_plan.md",
                    sdd_plan,
                ),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert "@sdd/plans/202605/scratch_plan.md" in state.current_prompt

    def test_coder_prompt_no_commit_uses_archived_plan_ref(
        self, tmp_path, monkeypatch
    ) -> None:
        """No-commit approvals hand off the archived plan, not local SDD."""
        monkeypatch.delenv("SASE_PLAN", raising=False)
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        archived_plan = tmp_path / "archive" / "scratch_plan.md"
        archived_plan.parent.mkdir()
        archived_plan.write_text(VALID_EPIC_PLAN)
        sdd_plan = tmp_path / "sdd" / "plans" / "202605" / "scratch_plan.md"
        sdd_plan.parent.mkdir(parents=True)
        sdd_plan.write_text("# Saved Plan")

        approval = PlanApprovalResult(
            action="approve",
            plan_file=str(archived_plan),
            commit_plan=False,
            run_coder=True,
        )
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(
                    tmp_path
                    / "sdd"
                    / "plans"
                    / "202605"
                    / "prompts"
                    / "scratch_plan.md",
                    sdd_plan,
                ),
            ),
        ):
            handle_plan_marker({"plan_file": str(archived_plan)}, ctx, state)

        assert state.current_prompt.startswith("%model:@claude_coder\n#gh:sase ")
        assert f"@{archived_plan}" in state.current_prompt
        assert "@sdd/plans/202605/scratch_plan.md" not in state.current_prompt
        assert os.environ["SASE_PLAN"] == str(archived_plan)

    def test_coder_prompt_commit_failure_uses_archived_plan_ref(
        self, tmp_path, monkeypatch
    ) -> None:
        """Failed SDD commits do not hand coder agents volatile repo SDD refs."""
        monkeypatch.delenv("SASE_PLAN", raising=False)
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        archived_plan = tmp_path / "archive" / "scratch_plan.md"
        archived_plan.parent.mkdir()
        archived_plan.write_text(VALID_EPIC_PLAN)
        sdd_plan = tmp_path / "sdd" / "plans" / "202605" / "scratch_plan.md"
        sdd_plan.parent.mkdir(parents=True)
        sdd_plan.write_text("# Saved Plan")

        approval = PlanApprovalResult(
            action="approve",
            plan_file=str(archived_plan),
            commit_plan=True,
            run_coder=True,
        )
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(
                    tmp_path
                    / "sdd"
                    / "plans"
                    / "202605"
                    / "prompts"
                    / "scratch_plan.md",
                    sdd_plan,
                ),
            ),
            patch(
                "sase.axe.run_agent_exec_plan_accept._commit_sdd_files",
                return_value=False,
            ),
        ):
            handle_plan_marker({"plan_file": str(archived_plan)}, ctx, state)

        assert f"@{archived_plan}" in state.current_prompt
        assert "@sdd/plans/202605/scratch_plan.md" not in state.current_prompt
        assert os.environ["SASE_PLAN"] == str(archived_plan)
        relationships = accept_mod.create_followup_artifacts.call_args.kwargs[
            "relationships"
        ]
        assert relationships["plan_committed"] is False
        assert call(str(tmp_path / "artifacts"), "plan_committed", False) in (
            accept_mod.update_meta_field.call_args_list
        )

    def test_epic_spec_commit_failure_does_not_block_host_launch(
        self, tmp_path
    ) -> None:
        """A prompt-snapshot failure does not trigger an agent-side launch."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        archived_plan = tmp_path / "archive" / "epic_plan.md"
        archived_plan.parent.mkdir()
        archived_plan.write_text(VALID_EPIC_PLAN)
        sdd_plan = tmp_path / "sdd" / "plans" / "202605" / "epic_plan.md"
        sdd_plan.parent.mkdir(parents=True)
        sdd_plan.write_text("# Saved Plan")

        approval = PlanApprovalResult(
            action="epic",
            plan_file=str(archived_plan),
            commit_plan=True,
            run_coder=True,
        )
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_spec",
                return_value=(
                    tmp_path / "sdd" / "plans" / "202605" / "prompts" / "epic_plan.md",
                    sdd_plan,
                ),
            ),
        ):
            outcome = handle_plan_marker({"plan_file": str(archived_plan)}, ctx, state)

        assert outcome == "epic_approved"
        assert state.current_prompt == "original prompt"
