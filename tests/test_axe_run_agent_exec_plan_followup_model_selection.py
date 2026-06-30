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

    @pytest.mark.parametrize("provider", ["claude", "codex", "agy"])
    def test_coder_followup_uses_provider_coder_alias(
        self, tmp_path, provider: str
    ) -> None:
        """An approved plan routes its coder through ``@<planner_provider>_coder``.

        A Claude-authored plan launches its coder with ``%model:@claude_coder``,
        a Codex plan with ``%model:@codex_coder``, and so on for every registered
        provider — never the retired ``%model:@worker`` lane.
        """
        state = run_followup_plan(
            tmp_path,
            action="approve",
            agent_model="opus",
            agent_llm_provider=provider,
        )
        assert state.current_prompt.startswith(f"%model:@{provider}_coder\n")
        assert "%model:@worker" not in state.current_prompt

    def test_coder_followup_falls_back_to_coder_alias_without_provider(
        self, tmp_path
    ) -> None:
        """Missing planner provider metadata falls back to the generic ``@coder``."""
        state = run_followup_plan(
            tmp_path,
            action="approve",
            agent_model="opus",
            agent_llm_provider=None,
        )
        assert state.current_prompt.startswith("%model:@coder\n")

    def test_coder_alias_depends_only_on_planner_provider(self, tmp_path) -> None:
        """The coder alias is chosen from the provider, ignoring a missing model."""
        state = run_followup_plan(
            tmp_path,
            action="approve",
            agent_model=None,
            agent_llm_provider="codex",
        )
        assert state.current_prompt.startswith("%model:@codex_coder\n")

    def test_epic_followup_uses_epic_creator_alias(self, tmp_path) -> None:
        """An epic follow-up (``#bd/new_epic``) defaults to ``%model:@epic_creator``."""
        state = run_followup_plan(
            tmp_path,
            action="epic",
            agent_model="opus",
            agent_llm_provider="claude",
        )
        assert state.current_prompt.startswith("%model:@epic_creator\n")
        assert "%model:@worker" not in state.current_prompt

    def test_legend_followup_uses_default_alias(self, tmp_path) -> None:
        """A legend follow-up (``#bd/new_legend``) falls through to ``%model:@default``."""
        state = run_followup_plan(
            tmp_path,
            action="legend",
            agent_model="opus",
            agent_llm_provider="claude",
        )
        assert state.current_prompt.startswith("%model:@default\n")
        assert "%model:@worker" not in state.current_prompt

    @pytest.mark.parametrize(
        ("agent_model", "agent_llm_provider"),
        [
            ("opus", None),
            (None, "claude"),
            (None, None),
        ],
    )
    def test_epic_creator_alias_independent_of_planner_metadata(
        self,
        tmp_path,
        agent_model: str | None,
        agent_llm_provider: str | None,
    ) -> None:
        """The epic role alias does not depend on planner provider/model metadata."""
        state = run_followup_plan(
            tmp_path,
            action="epic",
            agent_model=agent_model,
            agent_llm_provider=agent_llm_provider,
        )
        assert state.current_prompt.startswith("%model:@epic_creator\n")

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
        assert state.current_prompt.startswith("%model:@claude_coder\n")
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
        assert "%model:@claude_coder" not in state.current_prompt
        assert "%model:@worker" not in state.current_prompt
