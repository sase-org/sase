"""Tests for axe run_agent_exec_plan helpers."""

import dataclasses
import json
from unittest.mock import patch

import pytest

from sase.axe.run_agent_exec import AgentExecContext, LoopState
from sase.axe.run_agent_exec_plan import _get_embedded_workflow_refs, handle_plan_marker
from sase.llm_provider._plan_utils import PlanApprovalResult


def test_get_embedded_workflow_refs_excludes_vcs_when_tag_set(tmp_path) -> None:
    """VCS-tagged workflows are excluded when vcs_tag is set."""
    meta = tmp_path / "embedded_workflows.json"
    meta.write_text(
        json.dumps(
            [
                {"name": "gh", "tags": ["vcs", "rollover"]},
                {"name": "propose", "tags": ["rollover"]},
            ]
        )
    )

    result = _get_embedded_workflow_refs(str(tmp_path), "#gh:sase ")
    assert "#gh" not in result
    assert "#propose" in result


def test_get_embedded_workflow_refs_includes_vcs_when_tag_none(tmp_path) -> None:
    """VCS-tagged workflows ARE included when vcs_tag is None."""
    meta = tmp_path / "embedded_workflows.json"
    meta.write_text(
        json.dumps(
            [
                {"name": "gh", "args": {"repo": "sase"}, "tags": ["vcs", "rollover"]},
                {"name": "propose", "tags": ["rollover"]},
            ]
        )
    )

    result = _get_embedded_workflow_refs(str(tmp_path), None)
    assert "#gh:sase" in result
    assert "#propose" in result


# ---------------------------------------------------------------------------
# Fixtures for handle_plan_marker model-inheritance tests
# ---------------------------------------------------------------------------


def _make_ctx(tmp_path, *, agent_model: str | None = None) -> AgentExecContext:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    return AgentExecContext(
        cl_name="test",
        project_file=str(tmp_path / "project.gp"),
        workspace_dir=str(tmp_path),
        output_path=str(tmp_path / "output"),
        workspace_num=1,
        timestamp="20260331T120000",
        update_target="",
        project_name="test_proj",
        is_home_mode=False,
        artifacts_dir=str(artifacts),
        artifacts_timestamp="20260331_120000",
        vcs_tag="#gh:sase ",
        agent_name="test_agent",
        agent_model=agent_model,
        agent_llm_provider="anthropic",
        agent_vcs_provider="github",
        agent_hidden=False,
        agent_meta={"model": agent_model or "default"},
        local_xprompts={},
    )


def _make_state(tmp_path) -> LoopState:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(exist_ok=True)
    # Write agent_meta.json so helpers don't crash
    (artifacts / "agent_meta.json").write_text(json.dumps({"suffix": ".plan"}))
    return LoopState(
        current_prompt="original prompt",
        current_role_suffix=".plan",
        current_artifacts_dir=str(artifacts),
        loop_outcome="",
        sdd_spec_path=None,
        original_prompt="original prompt",
    )


_PLAN_PATCHES = {
    # Top-level imports in run_agent_exec_plan
    "sase.axe.run_agent_exec_plan.normalize_handoff_interruption_state": None,
    "sase.axe.run_agent_exec_plan.update_meta_suffix": None,
    "sase.axe.run_agent_exec_plan.update_meta_field": None,
    "sase.axe.run_agent_exec_plan.reset_killed": None,
    "sase.axe.run_agent_exec_plan.was_killed": lambda: False,
    "sase.axe.run_agent_exec_plan._write_plan_path_artifact": None,
    "sase.axe.run_agent_exec_plan.update_step_marker_chat_path": None,
    "sase.axe.run_agent_exec_plan.create_followup_artifacts": lambda *a, **kw: (
        "/tmp/followup"
    ),
    "sase.axe.run_agent_exec_plan.promote_to_workflow": None,
    "sase.axe.run_agent_exec_plan._commit_sdd_files": None,
    # Lazy imports — patch at source
    "sase.llm_provider._plan_utils.handle_plan_approval": None,
    "sase.history.chat.save_chat_history": lambda **kw: "/fake/chat",
    "sase.history.chat_extras.format_extra_sections": lambda *a: "",
    "sase.history.chat_links.format_plan_as_response": lambda *a: "plan",
    "sase.sdd.beads.get_sdd_config": lambda: True,
    "sase.sdd.beads.ensure_beads_initialized": None,
    "sase.sdd.files.get_sdd_dir": lambda *a: None,
    "sase.sdd.files.write_sdd_files": None,
    "sase.sdd.files.expand_prompt_for_spec": lambda p: p,
    "sase.sdd.files.commit_sdd_files": None,
}


@pytest.fixture
def _patch_plan_deps(tmp_path):
    """Patch heavy side-effects so handle_plan_marker runs fast."""
    patchers = []
    for target, side_effect in _PLAN_PATCHES.items():
        p = patch(target, side_effect=side_effect) if side_effect else patch(target)
        patchers.append(p)
    mocks = [p.start() for p in patchers]
    yield mocks
    for p in patchers:
        p.stop()


# ---------------------------------------------------------------------------
# Tests: model directive in followup prompts
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_patch_plan_deps")
class TestModelInheritance:
    """Verify %model directive is injected into followup prompts."""

    def _run(self, tmp_path, *, action: str, agent_model: str | None):
        ctx = _make_ctx(tmp_path, agent_model=agent_model)
        state = _make_state(tmp_path)
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

    def test_approve_no_coder_commit_true_returns_plan_committed(
        self, tmp_path
    ) -> None:
        """run_coder=False, commit_plan=True -> outcome 'plan_committed', SDD committed."""
        ctx = _make_ctx(tmp_path)
        state = _make_state(tmp_path)
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
        ctx = _make_ctx(tmp_path)
        state = _make_state(tmp_path)
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
        ctx = _make_ctx(tmp_path, agent_model="opus")
        state = _make_state(tmp_path)
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
        ctx = _make_ctx(tmp_path, agent_model="opus")
        state = _make_state(tmp_path)
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
        ctx = _make_ctx(tmp_path)
        state = _make_state(tmp_path)
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

    def test_coder_prompt_includes_resume_prefix(self, tmp_path) -> None:
        """Coder prompt prepends #resume:<planner_name> for named agents."""
        state = self._run(tmp_path, action="approve", agent_model="opus")
        # agent_name is "test_agent", agent_step was 0 -> incremented to 1 for
        # planner (promote_to_workflow) then 2 for coder, so planner = step-1 = 1
        assert "#resume:test_agent.plan " in state.current_prompt
        # Must appear after %model and before vcs_prefix
        assert state.current_prompt.startswith("%model:opus\n#resume:test_agent.plan ")

    def test_coder_prompt_no_resume_without_agent_name(self, tmp_path) -> None:
        """No #resume prefix when ctx.agent_name is not set."""
        ctx = _make_ctx(tmp_path, agent_model=None)
        ctx = dataclasses.replace(ctx, agent_name=None)
        state = _make_state(tmp_path)
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
        ctx = _make_ctx(tmp_path, agent_model="gemini-3.1-pro-preview")
        state = _make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        # Track update_meta_field calls
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
        ctx = _make_ctx(tmp_path, agent_model="opus")
        state = _make_state(tmp_path)
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
