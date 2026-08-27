"""Tests for run_agent_exec_plan per-round chat agent names."""

import dataclasses
from unittest.mock import patch

import pytest

from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.axe.run_agent_exec_questions import handle_questions_marker
from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.main.qa_prompt import build_qa_round
from tests._axe_run_agent_exec_plan_helpers import (
    make_ctx,
    make_state,
    patch_plan_gate_shell_result,
    patch_question_gate_shell_rounds,
    patched_plan_deps,
)
from tests.plan_validation_helpers import VALID_TALE_PLAN


@pytest.fixture
def patch_plan_deps():
    with patched_plan_deps() as mocks:
        yield mocks


@pytest.mark.usefixtures("patch_plan_deps")
class TestFeedbackRoundChatPath:
    """Verify each feedback round saves a chat file with a round-specific agent name."""

    def _run_plan(
        self,
        tmp_path,
        *,
        role_suffix: str,
        agent_name: str | None = "test_agent",
    ) -> dict:
        ctx = make_ctx(tmp_path)
        ctx.multi_agent_prompt_file = "~/.sase/multi_prompts/202606/main.md"
        if agent_name != "test_agent":
            ctx = dataclasses.replace(ctx, agent_name=agent_name)
        state = make_state(tmp_path)
        state.current_role_suffix = role_suffix
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text(VALID_TALE_PLAN)

        approval = PlanApprovalResult(action="approve", plan_file=plan_file)
        captured: dict = {}

        def capture(**kw):
            captured.update(kw)
            return "/fake/chat"

        with (
            patch_plan_gate_shell_result(approval),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            ),
            patch(
                "sase.history.chat.save_chat_history",
                side_effect=capture,
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)
        return captured

    def test_handle_plan_marker_round1_uses_plan_suffix_in_agent_name(
        self, tmp_path
    ) -> None:
        """Round 1 (no role suffix yet) falls back to '--plan' suffix."""
        captured = self._run_plan(tmp_path, role_suffix="")
        assert captured["agent"] == "test_agent--plan"
        assert captured["metadata_agent"] == "test_agent--plan"
        assert captured["metadata_model"] is None
        assert captured["metadata_llm_provider"] == "claude"
        assert captured["metadata_multi_agent_prompt"] == (
            "~/.sase/multi_prompts/202606/main.md"
        )

    def test_handle_plan_marker_round2_uses_round_suffix_in_agent_name(
        self, tmp_path
    ) -> None:
        """Round 2 uses the round suffix instead of hardcoded '--plan'."""
        captured = self._run_plan(tmp_path, role_suffix=".2")
        assert captured["agent"] == "test_agent--2"
        assert captured["metadata_agent"] == "test_agent--2"

    def test_handle_plan_marker_uses_distinct_agent_per_round(self, tmp_path) -> None:
        """Two rounds with different suffixes must produce distinct agent names."""
        r1_dir = tmp_path / "r1"
        r2_dir = tmp_path / "r2"
        r1_dir.mkdir()
        r2_dir.mkdir()
        round1 = self._run_plan(r1_dir, role_suffix="")
        round2 = self._run_plan(r2_dir, role_suffix=".2")
        assert round1["agent"] != round2["agent"]

    def test_handle_plan_marker_no_agent_name_preserves_none(self, tmp_path) -> None:
        """Agent kwarg is None when ctx.agent_name is None (regression check)."""
        captured = self._run_plan(tmp_path, role_suffix="", agent_name=None)
        assert captured["agent"] is None
        assert captured["metadata_agent"] is None

    def test_handle_questions_marker_uses_interrupted_child_name(
        self, tmp_path
    ) -> None:
        """Question chat history is saved under the interrupted member suffix."""
        ctx = make_ctx(tmp_path)
        ctx.multi_agent_prompt_file = "~/.sase/multi_prompts/202606/main.md"
        state = make_state(tmp_path)
        state.current_role_suffix = ".2"

        captured: dict = {}

        def capture(**kw):
            captured.update(kw)
            return "/fake/chat"

        rounds = [build_qa_round([], {"answers": [], "global_note": ""})]

        with (
            patch_question_gate_shell_rounds(rounds),
            patch(
                "sase.history.chat.save_chat_history",
                side_effect=capture,
            ),
        ):
            handle_questions_marker({"questions": []}, ctx, state)

        assert captured["agent"] == "test_agent--2"
        assert captured["metadata_agent"] == "test_agent--2"
        assert captured["metadata_multi_agent_prompt"] == (
            "~/.sase/multi_prompts/202606/main.md"
        )
        assert "metadata_model" not in captured
        assert "metadata_llm_provider" not in captured
