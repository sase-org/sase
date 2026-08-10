"""Tests for question follow-up prompt reconstruction."""

import json
from unittest.mock import patch

import pytest

from sase.axe import run_agent_exec_plan as plan_mod
from sase.axe import run_agent_exec_questions as questions_mod
from sase.axe.run_agent_exec_questions import handle_questions_marker
from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.sdd.store import SddStore
from tests._axe_run_agent_exec_plan_followup_prompt_helpers import (
    approve_followup_plan,
    patch_plan_deps,
    run_plan_approval,
    write_plan_file,
)
from tests._axe_run_agent_exec_plan_helpers import make_ctx, make_state

pytestmark = pytest.mark.usefixtures(
    patch_plan_deps.__name__,
)


class TestPlanFollowupQuestions:
    """Verify feedback and question follow-up prompts."""

    @pytest.mark.parametrize(
        ("stored_priority", "expected_priority"),
        [
            (3, 3),
            (None, 10),
            (-1, 10),
            ("3", 10),
        ],
    )
    def test_question_reacquisition_keeps_normalized_authored_priority(
        self,
        tmp_path,
        stored_priority,
        expected_priority,
    ) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        meta: dict[str, object] = {"role_suffix": ".plan"}
        if stored_priority is not None:
            meta["wait_priority"] = stored_priority
        (tmp_path / "artifacts" / "agent_meta.json").write_text(json.dumps(meta))
        captured: dict[str, object] = {}

        def fake_wait_for_runner_slot(*_args, **kwargs):
            captured["wait_runners"] = kwargs["wait_runners"]
            captured["wait_priority"] = kwargs["wait_priority"]
            return kwargs["claim"]()

        def fake_questions_flow(_questions, _artifacts_dir, **kwargs):
            kwargs["reacquire_runner_slot"](lambda: "claimed")
            return {"answers": [], "global_note": ""}

        with (
            patch(
                "sase.axe.run_agent_exec_questions.handle_questions_flow",
                side_effect=fake_questions_flow,
            ),
            patch(
                "sase.axe.run_agent_exec_questions.wait_for_runner_slot",
                side_effect=fake_wait_for_runner_slot,
            ),
        ):
            outcome = handle_questions_marker({"questions": []}, ctx, state)

        assert outcome is None
        assert captured == {
            "wait_runners": None,
            "wait_priority": expected_priority,
        }

    def test_feedback_followup_stores_full_prompt_artifact(self, tmp_path) -> None:
        """Plan feedback follow-up exposes the rebuilt prompt as an artifact."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = write_plan_file(tmp_path)
        approval = PlanApprovalResult(
            action="feedback",
            plan_file=plan_file,
            feedback="Add failure handling",
        )
        _, state, outcome = run_plan_approval(
            tmp_path,
            approval=approval,
            ctx=ctx,
            state=state,
        )

        assert outcome is None
        assert state.current_role_suffix == "--plan-0"
        assert plan_mod.create_followup_artifacts.call_args.args[2] == "--plan-0"
        assert state.current_prompt == (
            "original prompt\n\n### Additional Requirements\n\n- Add failure handling"
        )
        plan_mod._store_followup_prompt_artifact.assert_called_once_with(
            "/tmp/followup",
            state.current_prompt,
            label="Full feedback prompt",
        )

    def test_feedback_followup_second_round_uses_next_plan_token(
        self, tmp_path
    ) -> None:
        """Plan feedback rounds allocate '--plan-0', then '--plan-1'."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        first_plan = write_plan_file(tmp_path, "plan1.md")
        first = PlanApprovalResult(
            action="feedback",
            plan_file=first_plan,
            feedback="Add failure handling",
        )
        run_plan_approval(tmp_path, approval=first, ctx=ctx, state=state)
        assert state.current_role_suffix == "--plan-0"

        plan_mod.create_followup_artifacts.reset_mock()
        second_plan = write_plan_file(tmp_path, "plan2.md")
        second = PlanApprovalResult(
            action="feedback",
            plan_file=second_plan,
            feedback="Add retries",
        )
        _, state, outcome = run_plan_approval(
            tmp_path,
            approval=second,
            ctx=ctx,
            state=state,
        )

        assert outcome is None
        assert state.current_role_suffix == "--plan-1"
        assert plan_mod.create_followup_artifacts.call_args.args[2] == "--plan-1"

    def test_plan_question_followup_stores_full_prompt_artifact(self, tmp_path) -> None:
        """Plan-phase questions continue in the first feedback-number slot."""
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
        assert state.current_role_suffix == "--plan-0"
        assert questions_mod.create_followup_artifacts.call_args.args[2] == "--plan-0"
        assert (
            questions_mod.create_followup_artifacts.call_args.kwargs[
                "agent_family_role"
            ]
            == "feedback"
        )

    def test_generic_root_question_followup_uses_one_slot(self, tmp_path) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        state.current_role_suffix = None

        with patch(
            "sase.axe.run_agent_exec_questions.handle_questions_flow",
            return_value={"answers": [], "global_note": ""},
        ):
            outcome = handle_questions_marker({"questions": []}, ctx, state)

        assert outcome is None
        assert state.current_role_suffix == "--1"
        assert questions_mod.create_followup_artifacts.call_args.args[2] == "--1"
        assert (
            questions_mod.create_followup_artifacts.call_args.kwargs[
                "agent_family_role"
            ]
            == "q"
        )

    def test_external_sdd_question_snapshot_is_committed(self, tmp_path) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        prompt_path = tmp_path / "202607" / "prompts" / "test_plan.md"
        prompt_path.parent.mkdir(parents=True)
        prompt_path.write_text("Original prompt", encoding="utf-8")
        state.sdd_spec_path = str(prompt_path)
        store = SddStore(
            storage="sidecar_repos",
            sdd_dir=tmp_path,
            repo_root=tmp_path,
        )

        with (
            patch(
                "sase.axe.run_agent_exec_questions.handle_questions_flow",
                return_value={"answers": [], "global_note": "answer"},
            ),
            patch("sase.sdd.store.resolve_sdd_store", return_value=store),
            patch("sase.sdd.files.commit_sdd_store_files") as commit,
        ):
            outcome = handle_questions_marker({"questions": []}, ctx, state)

        assert outcome is None
        assert "### Questions and Answers" in prompt_path.read_text(encoding="utf-8")
        commit.assert_called_once_with(
            store,
            "Add Q&A to test_plan prompt",
            auto_commit_type="sdd",
            paths=[prompt_path],
            artifacts_dir="/tmp/followup",
        )

    def test_in_tree_sdd_question_snapshot_is_not_committed(self, tmp_path) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        prompt_path = tmp_path / "sdd" / "plans" / "202607" / "prompts" / "p.md"
        prompt_path.parent.mkdir(parents=True)
        prompt_path.write_text("Original prompt\n", encoding="utf-8")
        state.sdd_spec_path = str(prompt_path)
        store = SddStore(
            storage="in_tree",
            sdd_dir=tmp_path / "sdd",
            repo_root=tmp_path,
        )

        with (
            patch(
                "sase.axe.run_agent_exec_questions.handle_questions_flow",
                return_value={"answers": [], "global_note": "answer"},
            ),
            patch("sase.sdd.store.resolve_sdd_store", return_value=store),
            patch("sase.sdd.files.commit_sdd_store_files") as commit,
        ):
            outcome = handle_questions_marker({"questions": []}, ctx, state)

        assert outcome is None
        assert "### Questions and Answers" in prompt_path.read_text(encoding="utf-8")
        commit.assert_not_called()

    def test_sdd_question_snapshot_commit_failure_warns_and_continues(
        self,
        tmp_path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        prompt_path = tmp_path / "202607" / "prompts" / "test_plan.md"
        prompt_path.parent.mkdir(parents=True)
        prompt_path.write_text("Original prompt\n", encoding="utf-8")
        state.sdd_spec_path = str(prompt_path)
        store = SddStore(
            storage="sidecar_repos",
            sdd_dir=tmp_path,
            repo_root=tmp_path,
        )

        with (
            caplog.at_level("WARNING", logger=questions_mod.__name__),
            patch(
                "sase.axe.run_agent_exec_questions.handle_questions_flow",
                return_value={"answers": [], "global_note": "answer"},
            ),
            patch("sase.sdd.store.resolve_sdd_store", return_value=store),
            patch(
                "sase.sdd.files.commit_sdd_store_files",
                side_effect=RuntimeError("commit failed"),
            ),
        ):
            outcome = handle_questions_marker({"questions": []}, ctx, state)

        assert outcome is None
        assert "### Questions and Answers" in prompt_path.read_text(encoding="utf-8")
        assert "SDD prompt Q&A snapshot update failed" in caplog.text

    def test_question_followup_second_round_uses_next_root_suffix(
        self, tmp_path
    ) -> None:
        """Question continuations advance through numeric family suffixes."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        state.agent_step = 2
        state.current_role_suffix = "--1"

        with patch(
            "sase.axe.run_agent_exec_questions.handle_questions_flow",
            return_value={"answers": [], "global_note": ""},
        ):
            outcome = handle_questions_marker({"questions": []}, ctx, state)

        assert outcome is None
        assert state.current_role_suffix == "--2"
        assert questions_mod.create_followup_artifacts.call_args.args[2] == "--2"

    def test_question_followup_ambiguous_root_numeric_uses_q_metadata(
        self, tmp_path
    ) -> None:
        """A root question '--2' row uses metadata to continue as '--3'."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        state.agent_step = 3
        state.current_role_suffix = "--2"
        state.saved_chat_paths.append(("--1", "/fake/round1.md"))
        meta_path = tmp_path / "artifacts" / "agent_meta.json"
        meta_path.write_text(
            json.dumps({"role_suffix": "--2", "agent_family_role": "q"}),
            encoding="utf-8",
        )

        with patch(
            "sase.axe.run_agent_exec_questions.handle_questions_flow",
            return_value={"answers": [], "global_note": ""},
        ):
            outcome = handle_questions_marker({"questions": []}, ctx, state)

        assert outcome is None
        assert state.current_role_suffix == "--3"
        assert questions_mod.create_followup_artifacts.call_args.args[2] == "--3"
        assert (
            questions_mod.create_followup_artifacts.call_args.kwargs[
                "agent_family_role"
            ]
            == "q"
        )

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

        assert state.current_prompt.count("### Questions and Answers") == 1
        assert "#### Q1: Repro" in state.current_prompt
        assert "#### Q2: Symptom" in state.current_prompt
        assert len(state.qa_rounds) == 1

        with patch(
            "sase.axe.run_agent_exec_questions.handle_questions_flow",
            return_value=round2_response,
        ):
            handle_questions_marker({"questions": round2_questions}, ctx, state)

        assert state.current_prompt.count("### Questions and Answers") == 1
        assert "#### Q1: Repro" in state.current_prompt
        assert "#### Q2: Symptom" in state.current_prompt
        assert "#### Q3: Launch surface" in state.current_prompt
        assert "#### Q4: Symptom" in state.current_prompt
        assert state.current_prompt.count("%xprompts_enabled:false") == 1
        assert state.current_prompt.count("%xprompts_enabled:true") == 1
        assert "final note" in state.current_prompt
        assert len(state.qa_rounds) == 2

    def test_question_from_code_phase_rebuilds_from_code_prompt(self, tmp_path) -> None:
        """A code-phase question keeps the code prompt + size alias, not the planner.

        Approve a Claude-authored plan, then simulate ``/sase_questions`` from
        the resulting code phase. The follow-up prompt must be the code-agent
        prompt (size-derived ``%model:@small_phase_worker`` directive,
        ``@plan`` ref, "implement it now") plus the merged Q&A.
        """
        ctx, state = approve_followup_plan(
            tmp_path,
            agent_model="opus",
            agent_llm_provider="claude",
        )
        code_prompt = state.current_prompt
        assert code_prompt.startswith("%model:@small_phase_worker\n")
        assert state.question_base_prompt == code_prompt

        # The coder ran in a real (interrupted) phase dir; keep marker writes
        # inside tmp_path (the mocked follow-up dir is the throwaway /tmp path).
        code_dir = tmp_path / "code_phase"
        code_dir.mkdir()
        state.current_artifacts_dir = str(code_dir)

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
            "global_note": "",
        }
        with patch(
            "sase.axe.run_agent_exec_questions.handle_questions_flow",
            return_value=response,
        ):
            outcome = handle_questions_marker({"questions": questions}, ctx, state)

        assert outcome is None
        assert state.current_role_suffix == "--code-0"
        assert questions_mod.create_followup_artifacts.call_args.args[2] == "--code-0"
        assert (
            questions_mod.create_followup_artifacts.call_args.kwargs[
                "agent_family_role"
            ]
            == "code"
        )
        assert state.current_prompt.startswith("%model:@small_phase_worker\n")
        assert "@plan.md" in state.current_prompt
        assert "Implement it now." in state.current_prompt
        assert "Which API?" in state.current_prompt
        assert "REST" in state.current_prompt
        assert not state.current_prompt.startswith("original prompt")
        assert state.current_prompt.count("### Questions and Answers") == 1
        assert state.question_base_prompt == code_prompt

    def test_code_phase_repeated_question_rounds_keep_one_section(
        self, tmp_path
    ) -> None:
        """Repeated code-phase questions rebuild from one code base, one Q&A section."""
        ctx, state = approve_followup_plan(tmp_path, agent_model="opus")
        code_prompt = state.current_prompt
        assert code_prompt.startswith("%model:@small_phase_worker\n")

        round1_q = [
            {"question": "Q1 text", "options": [{"label": "A"}], "header": "Repro"}
        ]
        round1 = {
            "answers": [{"selected": ["A"], "custom_feedback": None}],
            "global_note": "",
        }
        round2_q = [
            {"question": "Q2 text", "options": [{"label": "B"}], "header": "Symptom"}
        ]
        round2 = {
            "answers": [{"selected": ["B"], "custom_feedback": None}],
            "global_note": "",
        }

        # Keep marker/index writes inside tmp_path for each round.
        round1_dir = tmp_path / "code_phase_r1"
        round1_dir.mkdir()
        state.current_artifacts_dir = str(round1_dir)
        with patch(
            "sase.axe.run_agent_exec_questions.handle_questions_flow",
            return_value=round1,
        ):
            handle_questions_marker({"questions": round1_q}, ctx, state)
        assert state.current_role_suffix == "--code-0"
        assert state.current_prompt.startswith("%model:@small_phase_worker\n")
        assert state.current_prompt.count("### Questions and Answers") == 1
        assert state.question_base_prompt == code_prompt

        round2_dir = tmp_path / "code_phase_r2"
        round2_dir.mkdir()
        state.current_artifacts_dir = str(round2_dir)
        with patch(
            "sase.axe.run_agent_exec_questions.handle_questions_flow",
            return_value=round2,
        ):
            handle_questions_marker({"questions": round2_q}, ctx, state)
        assert state.current_role_suffix == "--code-1"
        assert state.current_prompt.startswith("%model:@small_phase_worker\n")
        assert state.current_prompt.count("### Questions and Answers") == 1
        assert "#### Q1: Repro" in state.current_prompt
        assert "#### Q2: Symptom" in state.current_prompt
        assert state.question_base_prompt == code_prompt

    def test_question_followup_inherits_code_phase_model_metadata(
        self, tmp_path
    ) -> None:
        """Follow-up meta is seeded from the interrupted phase's agent_meta.json."""
        ctx = make_ctx(tmp_path, agent_model="opus", agent_llm_provider="claude")
        state = make_state(tmp_path)
        code_dir = tmp_path / "code_phase"
        code_dir.mkdir()
        (code_dir / "agent_meta.json").write_text(
            json.dumps(
                {
                    "model": "gpt-5.6-sol",
                    "llm_provider": "codex",
                    "name": "test_agent--code",
                }
            )
        )
        state.current_artifacts_dir = str(code_dir)

        with patch(
            "sase.axe.run_agent_exec_questions.handle_questions_flow",
            return_value={"answers": [], "global_note": ""},
        ):
            handle_questions_marker({"questions": []}, ctx, state)

        base_meta = questions_mod.create_followup_artifacts.call_args.args[1]
        assert base_meta["model"] == "gpt-5.6-sol"
        assert base_meta["llm_provider"] == "codex"

    def test_question_followup_metadata_falls_back_when_meta_unreadable(
        self, tmp_path
    ) -> None:
        """Missing interrupted agent_meta.json falls back to ctx.agent_meta."""
        ctx = make_ctx(tmp_path, agent_model="opus", agent_llm_provider="claude")
        state = make_state(tmp_path)
        state.current_artifacts_dir = str(tmp_path / "does_not_exist")

        with patch(
            "sase.axe.run_agent_exec_questions.handle_questions_flow",
            return_value={"answers": [], "global_note": ""},
        ):
            handle_questions_marker({"questions": []}, ctx, state)

        base_meta = questions_mod.create_followup_artifacts.call_args.args[1]
        assert base_meta is ctx.agent_meta
