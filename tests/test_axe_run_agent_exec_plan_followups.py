"""Tests for axe run_agent_exec_plan follow-up prompt handling."""

import dataclasses
import json
from unittest.mock import patch

import pytest

from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.llm_provider._plan_utils import PlanApprovalResult
from tests._axe_run_agent_exec_plan_helpers import (
    make_ctx,
    make_state,
    patched_plan_deps,
)


@pytest.fixture
def patch_plan_deps():
    with patched_plan_deps() as mocks:
        yield mocks


@pytest.mark.usefixtures("patch_plan_deps")
class TestPlanFollowupPrompts:
    """Verify plan approval follow-up prompts and metadata."""

    def _run(self, tmp_path, *, action: str, agent_model: str | None):
        ctx = make_ctx(tmp_path, agent_model=agent_model)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(action=action, plan_file=plan_file)
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
        return state

    def test_coder_prompt_includes_model_when_set(self, tmp_path) -> None:
        state = self._run(tmp_path, action="approve", agent_model="opus")
        assert state.current_prompt.startswith("%model:opus\n")

    def test_coder_prompt_no_model_when_none(self, tmp_path) -> None:
        state = self._run(tmp_path, action="approve", agent_model=None)
        assert not state.current_prompt.startswith("%model:")

    def test_epic_prompt_includes_model_when_set(self, tmp_path) -> None:
        state = self._run(tmp_path, action="epic", agent_model="opus")
        assert state.current_prompt.startswith("%model:opus\n")

    def test_epic_prompt_no_model_when_none(self, tmp_path) -> None:
        state = self._run(tmp_path, action="epic", agent_model=None)
        assert not state.current_prompt.startswith("%model:")

    def test_legend_prompt_uses_legend_sdd_ref(self, tmp_path) -> None:
        """Legend approval writes to sdd/legends and launches bd/new_legend."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "scratch_plan.md")
        (tmp_path / "scratch_plan.md").write_text("# Plan")
        sdd_plan = tmp_path / "sdd" / "legends" / "202605" / "scratch_plan.md"
        sdd_plan.parent.mkdir(parents=True)
        sdd_plan.write_text("# Saved Legend")

        approval = PlanApprovalResult(action="legend", plan_file=plan_file)
        with (
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            ),
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(
                    tmp_path / "sdd" / "prompts" / "202605" / "scratch_plan.md",
                    sdd_plan,
                ),
            ) as write_sdd_files,
            patch("sase.axe.run_agent_exec_plan._commit_sdd_files") as mock_commit,
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert state.current_role_suffix == ".legend"
        assert (
            "#bd/new_legend:sdd/legends/202605/scratch_plan.md" in state.current_prompt
        )
        assert write_sdd_files.call_args.kwargs["plan_kind"] == "legends"
        assert mock_commit.call_args.kwargs["plan_kind"] == "legends"

    def test_approve_no_coder_commit_true_returns_plan_committed(
        self, tmp_path
    ) -> None:
        """run_coder=False, commit_plan=True -> outcome 'plan_committed', SDD committed."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            run_coder=False,
            commit_plan=True,
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
            patch("sase.axe.run_agent_exec_plan._commit_sdd_files") as mock_commit,
        ):
            outcome = handle_plan_marker({"plan_file": plan_file}, ctx, state)
        assert outcome == "plan_committed"
        mock_commit.assert_called_once()

    def test_approve_no_coder_commit_false_skips_commit(self, tmp_path) -> None:
        """run_coder=False, commit_plan=False -> outcome 'plan_committed', no SDD commit."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            run_coder=False,
            commit_plan=False,
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
            patch("sase.axe.run_agent_exec_plan._commit_sdd_files") as mock_commit,
        ):
            outcome = handle_plan_marker({"plan_file": plan_file}, ctx, state)
        assert outcome == "plan_committed"
        mock_commit.assert_not_called()

    def test_coder_prompt_model_override_skips_inherited(self, tmp_path) -> None:
        """Custom prompt with %m:sonnet overrides inherited model."""
        ctx = make_ctx(tmp_path, agent_model="opus")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_prompt="%m:sonnet",
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
        assert not state.current_prompt.startswith("%model:opus")
        assert "%m:sonnet" in state.current_prompt

    def test_coder_prompt_without_model_inherits(self, tmp_path) -> None:
        """Custom prompt without model directive still inherits planner model."""
        ctx = make_ctx(tmp_path, agent_model="opus")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_prompt="be concise",
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
        assert state.current_prompt.startswith("%model:opus\n")
        assert "be concise" in state.current_prompt

    def test_approve_prompt_includes_custom_extra_text(self, tmp_path) -> None:
        """coder_prompt with content -> 'Additional instructions:' in prompt."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_prompt="#foo\ncustom",
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
        assert "Additional instructions:" in state.current_prompt
        assert "#foo\ncustom" in state.current_prompt

    def test_coder_prompt_excludes_resume_prefix_by_default(self, tmp_path) -> None:
        """Coder prompt does NOT prepend #resume:<planner_name> by default."""
        state = self._run(tmp_path, action="approve", agent_model="opus")
        assert "#resume:" not in state.current_prompt
        plan_ref = "@plan.md"
        assert plan_ref in state.current_prompt
        assert state.current_prompt.startswith("%model:opus\n")

    def test_coder_prompt_preserves_resume_when_env_set(
        self, tmp_path, monkeypatch
    ) -> None:
        """SASE_CODER_INHERIT_PLANNER_CHAT=1 restores the old #resume behavior."""
        monkeypatch.setenv("SASE_CODER_INHERIT_PLANNER_CHAT", "1")
        state = self._run(tmp_path, action="approve", agent_model="opus")
        assert "#resume:test_agent.plan " in state.current_prompt
        assert state.current_prompt.startswith("%model:opus\n#resume:test_agent.plan ")

    def test_coder_prompt_qa_round_excludes_resume_by_default(self, tmp_path) -> None:
        """Q&A round (agent_step > 2) also drops #resume by default."""
        ctx = make_ctx(tmp_path, agent_model="opus")
        state = make_state(tmp_path)
        state.agent_step = 2
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
        assert "#resume:" not in state.current_prompt
        assert "@plan.md" in state.current_prompt

    def test_coder_prompt_uses_saved_sdd_plan_ref(self, tmp_path) -> None:
        """Normal approved plans hand off the committed sdd/tales file."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "scratch_plan.md")
        (tmp_path / "scratch_plan.md").write_text("# Plan")
        sdd_plan = tmp_path / "sdd" / "tales" / "202605" / "scratch_plan.md"
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
                    tmp_path / "sdd" / "prompts" / "202605" / "scratch_plan.md",
                    sdd_plan,
                ),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert "@sdd/tales/202605/scratch_plan.md" in state.current_prompt

    def test_coder_prompt_no_resume_without_agent_name(self, tmp_path) -> None:
        """No #resume prefix when ctx.agent_name is not set."""
        ctx = make_ctx(tmp_path, agent_model=None)
        ctx = dataclasses.replace(ctx, agent_name=None)
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
        assert "#resume:" not in state.current_prompt

    def test_coder_meta_updated_when_coder_model_differs(self, tmp_path) -> None:
        """agent_meta.json reflects coder_model when it differs from planner model."""
        ctx = make_ctx(tmp_path, agent_model="gemini-3.1-pro-preview")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        meta_updates: dict[str, str] = {}

        def track_meta(artifacts_dir, key, value):
            meta_updates[key] = value

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_model="gemini-3-flash-preview",
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
            patch(
                "sase.axe.run_agent_exec_plan.update_meta_field",
                side_effect=track_meta,
            ),
            patch(
                "sase.llm_provider.registry.resolve_model_provider",
                return_value=("gemini", "gemini-3-flash-preview"),
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)
        assert meta_updates.get("model") == "gemini-3-flash-preview"
        assert meta_updates.get("llm_provider") == "gemini"

    def test_coder_meta_not_updated_when_model_same(self, tmp_path) -> None:
        """agent_meta.json not updated when coder_model matches planner model."""
        ctx = make_ctx(tmp_path, agent_model="opus")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        meta_updates: dict[str, str] = {}

        def track_meta(artifacts_dir, key, value):
            meta_updates[key] = value

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_model=None,
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
            patch(
                "sase.axe.run_agent_exec_plan.update_meta_field",
                side_effect=track_meta,
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)
        assert "model" not in meta_updates


def test_handle_plan_marker_writes_epic_started_at_on_epic_followup(
    tmp_path,
) -> None:
    """Epic approval persists the launch timestamp on the .epic follow-up."""
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    plan_file = str(tmp_path / "plan.md")
    (tmp_path / "plan.md").write_text("# Plan")
    followup = tmp_path / "followup"
    followup.mkdir()
    (followup / "agent_meta.json").write_text(json.dumps({}))

    approval = PlanApprovalResult(action="epic", plan_file=plan_file)
    with (
        patch("sase.axe.run_agent_exec_plan.normalize_handoff_interruption_state"),
        patch("sase.axe.run_agent_exec_plan.reset_killed"),
        patch("sase.axe.run_agent_exec_plan.was_killed", return_value=False),
        patch("sase.axe.run_agent_exec_plan._write_plan_path_artifact"),
        patch("sase.axe.run_agent_exec_plan.update_step_marker_chat_path"),
        patch("sase.axe.run_agent_exec_plan.promote_to_workflow"),
        patch("sase.axe.run_agent_exec_plan._commit_sdd_files"),
        patch(
            "sase.axe.run_agent_exec_plan.create_followup_artifacts",
            return_value=str(followup),
        ),
        patch(
            "sase.llm_provider._plan_utils.handle_plan_approval",
            return_value=approval,
        ),
        patch("sase.history.chat.save_chat_history", return_value="/fake/chat"),
        patch("sase.history.chat_extras.format_extra_sections", return_value=""),
        patch("sase.history.chat_links.format_plan_as_response", return_value="plan"),
        patch("sase.sdd.beads.get_sdd_config", return_value=True),
        patch("sase.sdd.beads.ensure_beads_initialized"),
        patch(
            "sase.sdd.files.write_sdd_files",
            return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
        ),
        patch("sase.sdd.files.expand_prompt_for_spec", side_effect=lambda p: p),
    ):
        handle_plan_marker({"plan_file": plan_file}, ctx, state)

    meta = json.loads((followup / "agent_meta.json").read_text())
    assert isinstance(meta["epic_started_at"], str)
    assert meta["epic_started_at"].endswith("+00:00")
