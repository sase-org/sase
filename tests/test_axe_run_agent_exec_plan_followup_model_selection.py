"""Tests for plan follow-up worker model selection."""

import pytest

from sase.llm_provider import WorkerModelResolution
from sase.llm_provider._plan_utils import PlanApprovalResult
from tests._axe_run_agent_exec_plan_followup_prompt_helpers import (
    patch_plan_deps,
    run_followup_plan,
    run_plan_approval,
    stub_worker_resolution,
    write_plan_file,
)

pytestmark = pytest.mark.usefixtures(
    patch_plan_deps.__name__,
    stub_worker_resolution.__name__,
)


class TestPlanFollowupModelSelection:
    """Verify plan approval follow-up model prefixes."""

    @pytest.mark.parametrize("action", ["approve", "epic", "legend"])
    def test_followup_uses_contextual_worker_lane(self, tmp_path, action: str) -> None:
        """With planner provider+model, the follow-up uses the concrete worker lane.

        The default stub echoes the planner lane (no ``worker_models`` config),
        so the prefix is a concrete ``%model:<provider>/<model>`` carrying the
        planner's primary context rather than the worker alias.
        """
        state = run_followup_plan(
            tmp_path,
            action=action,
            agent_model="opus",
            agent_llm_provider="anthropic",
        )
        assert state.current_prompt.startswith("%model:anthropic/opus\n")

    @pytest.mark.parametrize(
        ("agent_model", "agent_llm_provider"),
        [
            ("opus", None),
            (None, "anthropic"),
            (None, None),
        ],
    )
    @pytest.mark.parametrize("action", ["approve", "epic", "legend"])
    def test_followup_falls_back_to_worker_alias_without_planner_metadata(
        self,
        tmp_path,
        action: str,
        agent_model: str | None,
        agent_llm_provider: str | None,
    ) -> None:
        """Missing planner provider/model falls back to the worker alias."""
        state = run_followup_plan(
            tmp_path,
            action=action,
            agent_model=agent_model,
            agent_llm_provider=agent_llm_provider,
        )
        assert state.current_prompt.startswith("%model:@worker\n")

    def test_followup_uses_exact_worker_models_mapping(self, tmp_path) -> None:
        """Planner (claude, opus) + worker_models {claude/opus: codex/gpt-5.5}."""
        resolution = WorkerModelResolution(
            provider="codex",
            model="gpt-5.5",
            source="config",
            primary_provider="claude",
            primary_model="opus",
            matched_key="claude/opus",
            configured_target="codex/gpt-5.5",
        )
        state = run_followup_plan(
            tmp_path,
            agent_model="opus",
            agent_llm_provider="claude",
            resolution=resolution,
        )
        assert state.current_prompt.startswith("%model:codex/gpt-5.5\n")

    def test_followup_uses_provider_level_worker_models_mapping(self, tmp_path) -> None:
        """Planner (codex, o3) + provider-level worker_models {codex: claude/opus}."""
        resolution = WorkerModelResolution(
            provider="claude",
            model="opus",
            source="config",
            primary_provider="codex",
            primary_model="o3",
            matched_key="codex",
            configured_target="claude/opus",
        )
        state = run_followup_plan(
            tmp_path,
            agent_model="o3",
            agent_llm_provider="codex",
            resolution=resolution,
        )
        assert state.current_prompt.startswith("%model:claude/opus\n")

    def test_explicit_coder_model_worker_uses_contextual_default(
        self, tmp_path
    ) -> None:
        """coder_model='worker' resolves the contextual worker default, not literal."""
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
            agent_llm_provider="anthropic",
        )
        assert state.current_prompt.startswith("%model:anthropic/opus\n")

    def test_coder_prompt_picker_model_wins_over_worker(self, tmp_path) -> None:
        """An explicit approval-dialog coder model suppresses the worker default."""
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
        assert "%model:@worker" not in state.current_prompt
