"""Tests for plan follow-up prompt construction."""

import dataclasses
from unittest.mock import patch

import pytest

from sase.axe import run_agent_exec_plan as plan_mod
from sase.axe import run_agent_exec_questions as questions_mod
from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.axe.run_agent_exec_questions import handle_questions_marker
from sase.llm_provider import WorkerModelResolution
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


def _primary_lane_resolution(
    primary_provider: str, primary_model: str, *_args, **_kwargs
) -> WorkerModelResolution:
    """Stub worker resolution that echoes the planner lane (no config match)."""
    return WorkerModelResolution(
        provider=primary_provider,
        model=primary_model,
        source="primary",
        primary_provider=primary_provider,
        primary_model=primary_model,
    )


@pytest.mark.usefixtures("patch_plan_deps")
class TestPlanFollowupPromptConstruction:
    """Verify plan approval follow-up prompts."""

    @pytest.fixture(autouse=True)
    def _stub_worker_resolution(self):
        """Resolve the contextual worker lane to the planner lane by default.

        Individual tests override this patch to simulate ``worker_models``
        config mappings; the default keeps prefixes deterministic regardless
        of the developer's real ``~/.config/sase/sase.yml``.
        """
        with patch(
            "sase.llm_provider.resolve_worker_provider_model_for_primary",
            side_effect=_primary_lane_resolution,
        ):
            yield

    def _run(
        self,
        tmp_path,
        *,
        action: str,
        agent_model: str | None,
        agent_llm_provider: str | None = "anthropic",
    ):
        ctx = make_ctx(
            tmp_path,
            agent_model=agent_model,
            agent_llm_provider=agent_llm_provider,
        )
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

    @pytest.mark.parametrize("action", ["approve", "epic", "legend"])
    def test_followup_uses_contextual_worker_lane(self, tmp_path, action: str) -> None:
        """With planner provider+model, the follow-up uses the concrete worker lane.

        The default stub echoes the planner lane (no ``worker_models`` config),
        so the prefix is a concrete ``%model:<provider>/<model>`` carrying the
        planner's primary context rather than a bare ``%model:worker``.
        """
        state = self._run(
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
        """Missing planner provider/model falls back to the bare worker alias."""
        state = self._run(
            tmp_path,
            action=action,
            agent_model=agent_model,
            agent_llm_provider=agent_llm_provider,
        )
        assert state.current_prompt.startswith("%model:worker\n")

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
        state = self._run_with_resolution(
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
        state = self._run_with_resolution(
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
        ctx = make_ctx(tmp_path, agent_model="opus", agent_llm_provider="anthropic")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_model="worker",
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
        assert state.current_prompt.startswith("%model:anthropic/opus\n")

    def _run_with_resolution(
        self,
        tmp_path,
        *,
        agent_model: str | None,
        agent_llm_provider: str | None,
        resolution: WorkerModelResolution,
        action: str = "approve",
    ):
        ctx = make_ctx(
            tmp_path,
            agent_model=agent_model,
            agent_llm_provider=agent_llm_provider,
        )
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
            patch(
                "sase.llm_provider.resolve_worker_provider_model_for_primary",
                return_value=resolution,
            ),
        ):
            handle_plan_marker({"plan_file": plan_file}, ctx, state)
        return state

    def test_coder_prompt_picker_model_wins_over_worker(self, tmp_path) -> None:
        """An explicit approval-dialog coder model suppresses the worker default."""
        ctx = make_ctx(tmp_path, agent_model="opus")
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(
            action="approve",
            plan_file=plan_file,
            coder_model="sonnet",
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
        assert state.current_prompt.startswith("%model:sonnet\n")
        assert "%model:worker" not in state.current_prompt

    def test_feedback_followup_stores_full_prompt_artifact(self, tmp_path) -> None:
        """Plan feedback follow-up exposes the rebuilt prompt as an artifact."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = str(tmp_path / "plan.md")
        (tmp_path / "plan.md").write_text("# Plan")

        approval = PlanApprovalResult(
            action="feedback",
            plan_file=plan_file,
            feedback="Add failure handling",
        )
        with patch(
            "sase.llm_provider._plan_utils.handle_plan_approval",
            return_value=approval,
        ):
            outcome = handle_plan_marker({"plan_file": plan_file}, ctx, state)

        assert outcome is None
        assert state.current_prompt == (
            "original prompt\n\n### Additional Requirements\n\n- Add failure handling"
        )
        plan_mod._store_followup_prompt_artifact.assert_called_once_with(
            "/tmp/followup",
            state.current_prompt,
            label="Full feedback prompt",
        )

    def test_question_followup_stores_full_prompt_artifact(self, tmp_path) -> None:
        """Question answers follow-up exposes the rebuilt prompt as an artifact."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        questions = [
            {
                "question": "Which API?",
                "options": [{"label": "REST"}, {"label": "GraphQL"}],
            }
        ]
        response = {
            "answers": [
                {
                    "question": "Which API?",
                    "selected": ["REST"],
                    "custom_feedback": None,
                }
            ],
            "global_note": "Keep it simple",
        }

        with patch(
            "sase.axe.run_agent_exec_questions.handle_questions_flow",
            return_value=response,
        ):
            outcome = handle_questions_marker({"questions": questions}, ctx, state)

        assert outcome is None
        assert "Which API?" in state.current_prompt
        assert "REST" in state.current_prompt
        assert "Keep it simple" in state.current_prompt
        questions_mod._store_followup_prompt_artifact.assert_called_once_with(
            "/tmp/followup",
            state.current_prompt,
            label="Full question prompt",
        )
        assert state.current_role_suffix == "--2"
        assert questions_mod.create_followup_artifacts.call_args.args[2] == "--2"

    def test_question_followup_second_round_uses_next_numeric_suffix(
        self, tmp_path
    ) -> None:
        """Question continuations advance through numeric family suffixes."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        state.agent_step = 2
        state.current_role_suffix = "-2"

        with patch(
            "sase.axe.run_agent_exec_questions.handle_questions_flow",
            return_value={"answers": [], "global_note": ""},
        ):
            outcome = handle_questions_marker({"questions": []}, ctx, state)

        assert outcome is None
        assert state.current_role_suffix == "--3"
        assert questions_mod.create_followup_artifacts.call_args.args[2] == "--3"

    def test_multiple_question_rounds_merge_into_one_section(self, tmp_path) -> None:
        """Two question rounds produce one merged Q&A section with continuous numbering."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)

        round1_questions = [
            {
                "question": "Q1 text",
                "options": [{"label": "A"}],
                "header": "Repro",
            },
            {
                "question": "Q2 text",
                "options": [{"label": "B"}],
                "header": "Symptom",
            },
        ]
        round1_response = {
            "answers": [
                {"selected": ["A"], "custom_feedback": None},
                {"selected": ["B"], "custom_feedback": None},
            ],
            "global_note": "",
        }

        round2_questions = [
            {
                "question": "Q3 text",
                "options": [{"label": "C"}],
                "header": "Launch surface",
            },
            {
                "question": "Q4 text",
                "options": [{"label": "D"}],
                "header": "Symptom",
            },
        ]
        round2_response = {
            "answers": [
                {"selected": ["C"], "custom_feedback": None},
                {"selected": ["D"], "custom_feedback": None},
            ],
            "global_note": "final note",
        }

        with patch(
            "sase.axe.run_agent_exec_questions.handle_questions_flow",
            return_value=round1_response,
        ):
            handle_questions_marker({"questions": round1_questions}, ctx, state)

        # After round 1: one Q&A section with Q1, Q2.
        assert state.current_prompt.count("### Questions and Answers") == 1
        assert "#### Q1: Repro" in state.current_prompt
        assert "#### Q2: Symptom" in state.current_prompt
        assert len(state.qa_rounds) == 1

        with patch(
            "sase.axe.run_agent_exec_questions.handle_questions_flow",
            return_value=round2_response,
        ):
            handle_questions_marker({"questions": round2_questions}, ctx, state)

        # After round 2: still ONE Q&A section, with continuous Q1..Q4.
        assert state.current_prompt.count("### Questions and Answers") == 1
        assert "#### Q1: Repro" in state.current_prompt
        assert "#### Q2: Symptom" in state.current_prompt
        assert "#### Q3: Launch surface" in state.current_prompt
        assert "#### Q4: Symptom" in state.current_prompt
        # Single wrapper pair.
        assert state.current_prompt.count("%xprompts_enabled:false") == 1
        assert state.current_prompt.count("%xprompts_enabled:true") == 1
        # Last-non-empty global note wins.
        assert "final note" in state.current_prompt
        # State carries one QARound per round.
        assert len(state.qa_rounds) == 2

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
        assert not state.current_prompt.startswith("%model:")
        assert "%m:sonnet" in state.current_prompt

    def test_coder_prompt_without_model_directive_uses_contextual_worker(
        self, tmp_path
    ) -> None:
        """Custom prompt without model directive still gets the contextual worker prefix."""
        ctx = make_ctx(tmp_path, agent_model="opus", agent_llm_provider="anthropic")
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
        assert state.current_prompt.startswith("%model:anthropic/opus\n")
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
        """Coder prompt does NOT prepend #fork:<planner_name> by default."""
        state = self._run(tmp_path, action="approve", agent_model="opus")
        assert "#fork:" not in state.current_prompt
        plan_ref = "@plan.md"
        assert plan_ref in state.current_prompt
        assert state.current_prompt.startswith("%model:anthropic/opus\n")

    def test_coder_prompt_preserves_resume_when_env_set(
        self, tmp_path, monkeypatch
    ) -> None:
        """SASE_CODER_INHERIT_PLANNER_CHAT=1 restores the old #fork behavior."""
        monkeypatch.setenv("SASE_CODER_INHERIT_PLANNER_CHAT", "1")
        state = self._run(tmp_path, action="approve", agent_model="opus")
        assert "#fork:test_agent--plan " in state.current_prompt
        assert state.current_prompt.startswith(
            "%model:anthropic/opus\n#fork:test_agent--plan "
        )

    def test_coder_prompt_qa_round_excludes_resume_by_default(self, tmp_path) -> None:
        """Q&A round (agent_step > 2) also drops #fork by default."""
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
        assert "#fork:" not in state.current_prompt
        assert "@plan.md" in state.current_prompt

    def test_coder_prompt_qa_round_resume_env_uses_planner(
        self, tmp_path, monkeypatch
    ) -> None:
        """Chat inheritance after Q&A resumes the planner phase, not the Q&A retry."""
        monkeypatch.setenv("SASE_CODER_INHERIT_PLANNER_CHAT", "1")
        ctx = make_ctx(tmp_path, agent_model="opus")
        state = make_state(tmp_path)
        state.agent_step = 2
        state.current_role_suffix = "-2"
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

        assert "#fork:test_agent--plan " in state.current_prompt
        assert "#fork:test_agent--2 " not in state.current_prompt

    def test_coder_prompt_no_resume_without_agent_name(self, tmp_path) -> None:
        """No #fork prefix when ctx.agent_name is not set."""
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
        assert "#fork:" not in state.current_prompt
