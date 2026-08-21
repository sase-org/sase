"""Tests for approved plan coder prompt construction."""

import dataclasses
from unittest.mock import patch

import pytest

from sase.llm_provider._plan_utils import PlanApprovalResult
from tests._axe_run_agent_exec_plan_followup_prompt_helpers import (
    patch_plan_deps,
    run_followup_plan,
    run_plan_approval,
    write_plan_file,
)
from tests._axe_run_agent_exec_plan_helpers import make_ctx, make_state

pytestmark = pytest.mark.usefixtures(
    patch_plan_deps.__name__,
)


class TestPlanFollowupCoderPrompt:
    """Verify approved plan coder prompt text and plan-file-only handoff."""

    def test_coder_prompt_model_override_skips_inherited(self, tmp_path) -> None:
        """Custom prompt with %m:sonnet overrides inherited model."""
        plan_file = write_plan_file(tmp_path)
        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_prompt="%m:sonnet",
        )
        _, state, _ = run_plan_approval(
            tmp_path,
            approval=approval,
            agent_model="opus",
        )
        assert not state.current_prompt.startswith("%model:")
        assert "%m:sonnet" in state.current_prompt

    def test_coder_prompt_without_model_directive_uses_size_alias(
        self, tmp_path
    ) -> None:
        """Custom prompt without model directive still gets the size-alias prefix."""
        plan_file = write_plan_file(tmp_path)
        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_prompt="be concise",
        )
        _, state, _ = run_plan_approval(
            tmp_path,
            approval=approval,
            agent_model="opus",
            agent_llm_provider="claude",
        )
        assert state.current_prompt.startswith("%model:@small\n")
        assert "be concise" in state.current_prompt

    def test_approve_prompt_includes_custom_extra_text(self, tmp_path) -> None:
        """coder_prompt with content -> 'Additional instructions:' in prompt."""
        plan_file = write_plan_file(tmp_path)
        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_prompt="#foo\ncustom",
        )
        _, state, _ = run_plan_approval(tmp_path, approval=approval)
        assert "Additional instructions:" in state.current_prompt
        assert "#foo\ncustom" in state.current_prompt

    def test_coder_prompt_never_prepends_planner_fork(self, tmp_path) -> None:
        """Coder prompt does not prepend #fork:<planner_name>."""
        state = run_followup_plan(tmp_path, action="approve", agent_model="opus")
        assert "#fork:" not in state.current_prompt
        plan_ref = "@plan.md"
        assert plan_ref in state.current_prompt
        assert state.current_prompt.startswith("%model:@small\n")

    def test_coder_prompt_qa_round_never_prepends_planner_fork(self, tmp_path) -> None:
        """Q&A round (agent_step > 2) also starts from the plan file alone."""
        ctx = make_ctx(tmp_path, agent_model="opus")
        state = make_state(tmp_path)
        state.agent_step = 2
        plan_file = write_plan_file(tmp_path)
        approval = PlanApprovalResult(action="approve", plan_file=plan_file)

        run_plan_approval(tmp_path, approval=approval, ctx=ctx, state=state)
        assert "#fork:" not in state.current_prompt
        assert "@plan.md" in state.current_prompt

    def test_coder_prompt_no_resume_without_agent_name(self, tmp_path) -> None:
        """No #fork prefix when ctx.agent_name is not set."""
        ctx = make_ctx(tmp_path, agent_model=None)
        ctx = dataclasses.replace(ctx, agent_name=None)
        state = make_state(tmp_path)
        plan_file = write_plan_file(tmp_path)
        approval = PlanApprovalResult(action="approve", plan_file=plan_file)

        run_plan_approval(tmp_path, approval=approval, ctx=ctx, state=state)
        assert "#fork:" not in state.current_prompt

    def test_accepted_plan_sets_question_base_to_code_prompt(self, tmp_path) -> None:
        """handle_accepted_plan records the code prompt as the question base."""
        state = run_followup_plan(tmp_path, action="approve", agent_model="opus")
        assert state.question_base_prompt == state.current_prompt
        assert state.question_base_prompt.startswith("%model:@small\n")
        assert "@plan.md" in state.question_base_prompt

    def test_accepted_plan_stores_complete_coder_prompt_artifact(
        self,
        tmp_path,
    ) -> None:
        with patch(
            "sase.axe.run_agent_exec_plan_accept._store_followup_prompt_artifact"
        ) as store_prompt:
            state = run_followup_plan(
                tmp_path,
                action="approve",
                agent_model="opus",
            )

        store_prompt.assert_called_once_with(
            "/tmp/followup",
            state.current_prompt,
            label="Full coder prompt",
        )
