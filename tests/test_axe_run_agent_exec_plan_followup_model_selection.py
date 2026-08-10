"""Tests for plan follow-up model selection."""

import pytest

from sase.llm_provider._plan_utils import PlanApprovalResult
from tests._axe_run_agent_exec_plan_followup_prompt_helpers import (
    patch_plan_deps,
    run_followup_plan,
    run_plan_approval,
    write_plan_file,
)

pytestmark = pytest.mark.usefixtures(
    patch_plan_deps.__name__,
)


class TestPlanFollowupModelSelection:
    """Verify plan approval follow-up model prefixes."""

    @pytest.mark.parametrize(
        "size",
        ["xsmall", "small", "medium", "large", "xlarge"],
    )
    def test_coder_followup_uses_tale_size_phase_worker_alias(
        self, tmp_path, size: str
    ) -> None:
        """An approved tale routes its follow-up through ``@<size>_phase_worker``."""
        plan_file = write_plan_file(tmp_path, size=size)
        approval = PlanApprovalResult(action="approve", plan_file=plan_file)
        _, state, _ = run_plan_approval(
            tmp_path,
            approval=approval,
            agent_model="opus",
            agent_llm_provider="claude",
        )
        assert state.current_prompt.startswith(f"%model:@{size}_phase_worker\n")
        assert "%model:@worker" not in state.current_prompt

    def test_sizeless_legacy_tale_defaults_to_medium_phase_worker(
        self, tmp_path
    ) -> None:
        plan_file = write_plan_file(tmp_path, size=None)
        approval = PlanApprovalResult(action="approve", plan_file=plan_file)
        _, state, _ = run_plan_approval(
            tmp_path,
            approval=approval,
            agent_model="opus",
            agent_llm_provider=None,
        )
        assert state.current_prompt.startswith("%model:@medium_phase_worker\n")

    def test_tale_size_alias_ignores_planner_provider(self, tmp_path) -> None:
        state = run_followup_plan(
            tmp_path,
            action="approve",
            agent_model=None,
            agent_llm_provider="codex",
        )
        assert state.current_prompt.startswith("%model:@small_phase_worker\n")

    def test_epic_approval_has_no_creator_model_followup(self, tmp_path) -> None:
        """Epic approval launches bead work directly without a model-prefixed child."""
        state = run_followup_plan(
            tmp_path,
            action="epic",
            agent_model="opus",
            agent_llm_provider="claude",
        )
        assert state.current_prompt == "original prompt"

    def test_explicit_coder_model_worker_falls_back_to_coder_alias(
        self, tmp_path
    ) -> None:
        """coder_model='worker' is treated as no explicit pick, not a literal model."""
        plan_file = write_plan_file(tmp_path)
        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_model="worker",
        )
        _, state, _ = run_plan_approval(
            tmp_path,
            approval=approval,
            agent_model="opus",
            agent_llm_provider="claude",
        )
        assert state.current_prompt.startswith("%model:@small_phase_worker\n")
        assert "%model:@worker" not in state.current_prompt

    def test_coder_prompt_picker_model_wins_over_default(self, tmp_path) -> None:
        """An explicit approval-dialog coder model suppresses the coder-alias default."""
        plan_file = write_plan_file(tmp_path)
        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_model="sonnet",
        )
        _, state, _ = run_plan_approval(
            tmp_path,
            approval=approval,
            agent_model="opus",
        )
        assert state.current_prompt.startswith("%model:sonnet\n")
        assert "%model:@small_phase_worker" not in state.current_prompt
        assert "%model:@worker" not in state.current_prompt
