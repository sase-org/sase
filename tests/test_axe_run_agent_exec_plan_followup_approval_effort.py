"""Tests for approved plan follow-up effort metadata."""

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
class TestPlanFollowupApprovalEffort:
    """Verify effort metadata for approved plan follow-ups."""

    def test_approve_followup_records_default_effort(
        self, tmp_path, monkeypatch
    ) -> None:
        """Coder follow-up metadata records llm_provider.default_effort."""
        monkeypatch.setattr(
            "sase.llm_provider.config._get_default_effort", lambda: "xhigh"
        )
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(action="approve", plan_file=plan_file)
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert call("/tmp/followup", "reasoning_effort", "xhigh") in (
            accept_mod.update_meta_field.call_args_list
        )

    def test_epic_approval_has_no_creator_followup_effort(
        self, tmp_path, monkeypatch
    ) -> None:
        """Host-side epic kickoff does not create follow-up model metadata."""
        monkeypatch.setattr(
            "sase.llm_provider.config._get_default_effort", lambda: "high"
        )
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "epic.md")
        (tmp_path / "epic.md").write_text(VALID_EPIC_PLAN)

        approval = PlanApprovalResult(action="epic", plan_file=plan_file)
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_spec",
                return_value=(tmp_path / "spec.md", tmp_path / "epic.md"),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        effort_calls = [
            meta_call
            for meta_call in accept_mod.update_meta_field.call_args_list
            if meta_call.args[1] == "reasoning_effort"
        ]
        assert effort_calls == []
        assert call(str(tmp_path / "artifacts"), "epic_bead_id", "sase-1") in (
            accept_mod.update_meta_field.call_args_list
        )

    def test_custom_coder_prompt_effort_beats_default(
        self, tmp_path, monkeypatch
    ) -> None:
        """A custom coder prompt's explicit %effort wins over the default."""
        monkeypatch.setattr(
            "sase.llm_provider.config._get_default_effort", lambda: "high"
        )
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_prompt="%effort:low\nUse low effort for the handoff.",
        )
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert call("/tmp/followup", "reasoning_effort", "low") in (
            accept_mod.update_meta_field.call_args_list
        )

    def test_followup_model_suffix_effort_beats_default(
        self, tmp_path, monkeypatch
    ) -> None:
        """A %model:...@effort suffix is recorded as explicit effort."""
        monkeypatch.setattr(
            "sase.llm_provider.config._get_default_effort", lambda: "high"
        )
        state = make_state(tmp_path)
        state.current_artifacts_dir = "/tmp/followup"

        accept_mod._write_followup_effort_meta(
            state, "%model:@claude_coder@xhigh\nImplement the approved plan."
        )

        assert call("/tmp/followup", "reasoning_effort", "xhigh") in (
            accept_mod.update_meta_field.call_args_list
        )

    def test_approve_followup_omits_unset_effort(self, tmp_path, monkeypatch) -> None:
        """No explicit/default effort leaves plan-chain follow-up effort absent."""
        monkeypatch.setattr(
            "sase.llm_provider.config._get_default_effort", lambda: None
        )
        ctx = make_ctx(tmp_path)
        ctx.agent_meta["reasoning_effort"] = "xhigh"
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(action="approve", plan_file=plan_file)
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        effort_calls = [
            meta_call
            for meta_call in accept_mod.update_meta_field.call_args_list
            if meta_call.args[1] == "reasoning_effort"
        ]
        assert effort_calls == []
        followup_base_meta = accept_mod.create_followup_artifacts.call_args.args[1]
        assert "reasoning_effort" not in followup_base_meta
