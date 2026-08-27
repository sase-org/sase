"""Tests for question follow-up prompt reconstruction."""

from dataclasses import replace
import json
from unittest.mock import patch

import pytest

from sase.axe import run_agent_exec_plan as plan_mod
from sase.axe import run_agent_exec_questions as questions_mod
from sase.axe.run_agent_exec_questions import handle_questions_marker
from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.main.qa_prompt import build_qa_round
from sase.sdd.store import SddStore
from tests._axe_run_agent_exec_plan_followup_prompt_helpers import (
    approve_followup_plan,
    patch_plan_deps,
    run_plan_approval,
    write_plan_file,
)
from tests._axe_run_agent_exec_plan_helpers import (
    make_ctx,
    make_state,
    patch_question_gate_shell_rounds,
)

pytestmark = pytest.mark.usefixtures(
    patch_plan_deps.__name__,
)


class TestPlanFollowupQuestions:
    """Verify feedback and question follow-up prompts."""

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

    def test_feedback_followup_unnamed_agent_uses_round_index_fallback(
        self, tmp_path
    ) -> None:
        ctx = replace(make_ctx(tmp_path), agent_name=None)
        state = make_state(tmp_path)
        plan_file = write_plan_file(tmp_path)
        approval = PlanApprovalResult(
            action="feedback",
            plan_file=plan_file,
            feedback="Tighten the test",
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
        assert (
            plan_mod.create_followup_artifacts.call_args.kwargs["agent_name_override"]
            is None
        )
        assert (
            plan_mod.create_followup_artifacts.call_args.kwargs["workflow_name"] is None
        )
        plan_mod.promote_to_workflow.assert_not_called()

    def test_feedback_followup_records_metadata_before_artifact_creation(
        self, tmp_path
    ) -> None:
        order: list[str] = []

        def record_meta(_artifacts_dir, key, _value):
            if key in {"feedback_submitted_at", "followup_agent_name", "plan_path"}:
                order.append(f"meta:{key}")

        def create(*args, **_kwargs):
            order.append(f"create:{args[2]}")
            return "/tmp/followup"

        plan_mod.update_meta_field.side_effect = record_meta
        plan_mod.create_followup_artifacts.side_effect = create
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        plan_file = write_plan_file(tmp_path)
        approval = PlanApprovalResult(
            action="feedback",
            plan_file=plan_file,
            feedback="Tighten the test",
        )

        _, state, outcome = run_plan_approval(
            tmp_path,
            approval=approval,
            ctx=ctx,
            state=state,
        )

        assert outcome is None
        assert state.current_artifacts_dir == "/tmp/followup"
        assert "create:--plan-0" in order
        create_index = order.index("create:--plan-0")
        assert any(
            item == "meta:feedback_submitted_at" for item in order[:create_index]
        )
        assert any(item == "meta:followup_agent_name" for item in order[:create_index])
        assert any(item == "meta:plan_path" for item in order[:create_index])

    def test_plan_question_followup_stores_full_prompt_artifact(self, tmp_path) -> None:
        """Plan-phase questions continue in the next ordinary family slot."""
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
        rounds = [build_qa_round(questions, response)]

        with patch_question_gate_shell_rounds(rounds):
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
        assert state.current_role_suffix == "--1"
        assert questions_mod.create_followup_artifacts.call_args.args[2] == "--1"
        assert (
            questions_mod.create_followup_artifacts.call_args.kwargs[
                "agent_family_role"
            ]
            == "plan"
        )

    def test_generic_question_followup_uses_one_slot(self, tmp_path) -> None:
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        state.current_role_suffix = None
        rounds = [build_qa_round([], {"answers": [], "global_note": ""})]

        with patch_question_gate_shell_rounds(rounds):
            outcome = handle_questions_marker({"questions": []}, ctx, state)

        assert outcome is None
        assert state.current_role_suffix == "--1"
        assert questions_mod.create_followup_artifacts.call_args.args[2] == "--1"
        assert (
            questions_mod.create_followup_artifacts.call_args.kwargs[
                "agent_family_role"
            ]
            == "agent"
        )

    def test_unnamed_plan_question_followup_uses_ordinary_child_fallback(
        self,
        tmp_path,
    ) -> None:
        ctx = replace(make_ctx(tmp_path), agent_name=None)
        state = make_state(tmp_path)
        rounds = [build_qa_round([], {"answers": [], "global_note": ""})]

        with patch_question_gate_shell_rounds(rounds):
            outcome = handle_questions_marker({"questions": []}, ctx, state)

        assert outcome is None
        assert state.current_role_suffix == "--1"
        assert questions_mod.create_followup_artifacts.call_args.args[2] == "--1"
        assert (
            questions_mod.create_followup_artifacts.call_args.kwargs[
                "agent_family_role"
            ]
            == "plan"
        )

    def test_question_followup_second_round_uses_next_root_suffix(
        self, tmp_path
    ) -> None:
        """Question continuations advance through numeric family suffixes."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        state.agent_step = 2
        state.current_role_suffix = "--1"
        rounds = [build_qa_round([], {"answers": [], "global_note": ""})]

        with patch_question_gate_shell_rounds(rounds):
            outcome = handle_questions_marker({"questions": []}, ctx, state)

        assert outcome is None
        assert state.current_role_suffix == "--2"
        assert questions_mod.create_followup_artifacts.call_args.args[2] == "--2"

    def test_question_followup_ambiguous_numeric_inherits_custom_metadata(
        self, tmp_path
    ) -> None:
        """A custom numeric row uses metadata to continue as an ordinary child."""
        ctx = make_ctx(tmp_path)
        state = make_state(tmp_path)
        state.agent_step = 3
        state.current_role_suffix = "--2"
        state.saved_chat_paths.append(("--1", "/fake/round1.md"))
        meta_path = tmp_path / "artifacts" / "agent_meta.json"
        meta_path.write_text(
            json.dumps({"role_suffix": "--2", "agent_family_role": "review"}),
            encoding="utf-8",
        )
        rounds = [build_qa_round([], {"answers": [], "global_note": ""})]

        with patch_question_gate_shell_rounds(rounds):
            outcome = handle_questions_marker({"questions": []}, ctx, state)

        assert outcome is None
        assert state.current_role_suffix == "--3"
        assert questions_mod.create_followup_artifacts.call_args.args[2] == "--3"
        assert (
            questions_mod.create_followup_artifacts.call_args.kwargs[
                "agent_family_role"
            ]
            == "review"
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

        rounds = [build_qa_round(round1_questions, round1_response)]
        with patch_question_gate_shell_rounds(rounds):
            handle_questions_marker({"questions": round1_questions}, ctx, state)

        assert state.current_prompt.count("### Questions and Answers") == 1
        assert "#### Q1: Repro" in state.current_prompt
        assert "#### Q2: Symptom" in state.current_prompt

        rounds = [*rounds, build_qa_round(round2_questions, round2_response)]
        with patch_question_gate_shell_rounds(rounds):
            handle_questions_marker({"questions": round2_questions}, ctx, state)

        assert state.current_prompt.count("### Questions and Answers") == 1
        assert "#### Q1: Repro" in state.current_prompt
        assert "#### Q2: Symptom" in state.current_prompt
        assert "#### Q3: Launch surface" in state.current_prompt
        assert "#### Q4: Symptom" in state.current_prompt
        assert state.current_prompt.count("%xprompts_enabled:false") == 1
        assert state.current_prompt.count("%xprompts_enabled:true") == 1
        assert "final note" in state.current_prompt

    def test_question_from_code_phase_rebuilds_from_code_prompt(self, tmp_path) -> None:
        """A code-phase question keeps the code prompt + size alias, not the planner.

        Approve a Claude-authored plan, then simulate ``/sase_questions`` from
        the resulting code phase. The follow-up prompt must be the code-agent
        prompt (size-derived ``%model:@small`` directive,
        ``@plan`` ref, "implement it now") plus the merged Q&A.
        """
        ctx, state = approve_followup_plan(
            tmp_path,
            agent_model="opus",
            agent_llm_provider="claude",
        )
        code_prompt = state.current_prompt
        assert code_prompt.startswith("%model:@small\n")
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
        rounds = [build_qa_round(questions, response)]
        with patch_question_gate_shell_rounds(rounds):
            outcome = handle_questions_marker({"questions": questions}, ctx, state)

        assert outcome is None
        assert state.current_role_suffix == "--1"
        assert questions_mod.create_followup_artifacts.call_args.args[2] == "--1"
        assert (
            questions_mod.create_followup_artifacts.call_args.kwargs[
                "agent_family_role"
            ]
            == "code"
        )
        assert state.current_prompt.startswith("%model:@small\n")
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
        assert code_prompt.startswith("%model:@small\n")

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
        rounds = [build_qa_round(round1_q, round1)]
        with patch_question_gate_shell_rounds(rounds):
            handle_questions_marker({"questions": round1_q}, ctx, state)
        assert state.current_role_suffix == "--1"
        assert state.current_prompt.startswith("%model:@small\n")
        assert state.current_prompt.count("### Questions and Answers") == 1
        assert state.question_base_prompt == code_prompt

        round2_dir = tmp_path / "code_phase_r2"
        round2_dir.mkdir()
        state.current_artifacts_dir = str(round2_dir)
        rounds = [*rounds, build_qa_round(round2_q, round2)]
        with patch_question_gate_shell_rounds(rounds):
            handle_questions_marker({"questions": round2_q}, ctx, state)
        assert state.current_role_suffix == "--2"
        assert state.current_prompt.startswith("%model:@small\n")
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
        rounds = [build_qa_round([], {"answers": [], "global_note": ""})]

        with patch_question_gate_shell_rounds(rounds):
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
        rounds = [build_qa_round([], {"answers": [], "global_note": ""})]

        with patch_question_gate_shell_rounds(rounds):
            handle_questions_marker({"questions": []}, ctx, state)

        base_meta = questions_mod.create_followup_artifacts.call_args.args[1]
        assert base_meta is ctx.agent_meta


class TestQuestionSddPromptSnapshot:
    """Verify the Q&A prompt snapshot shared by the code path and gate-shell settlement.

    ``_update_question_sdd_prompt_snapshot`` (``sase.question_shell.followup``)
    is the single implementation both the gate-shell settlement hook
    (``question_next_action``) and, historically, the runner's inline
    question handling shared. The runner no longer calls it directly -- a
    question gate shell's settlement calls it once the gate settles -- so
    these tests drive it directly instead of through
    ``handle_questions_marker``.
    """

    def test_external_sdd_question_snapshot_is_committed(self, tmp_path) -> None:
        from sase.question_shell.followup import _update_question_sdd_prompt_snapshot

        prompt_path = tmp_path / "202607" / "prompts" / "test_plan.md"
        prompt_path.parent.mkdir(parents=True)
        prompt_path.write_text("Original prompt", encoding="utf-8")
        store = SddStore(
            storage="sidecar_repos",
            sdd_dir=tmp_path,
            repo_root=tmp_path,
        )

        with (
            patch("sase.sdd.store.resolve_sdd_store", return_value=store),
            patch("sase.sdd.files.commit_sdd_store_files") as commit,
        ):
            _update_question_sdd_prompt_snapshot(
                str(prompt_path),
                "### Questions and Answers\n\nanswer",
                workspace_dir=str(tmp_path),
                workspace_num=1,
                artifacts_dir="/tmp/followup",
            )

        assert "### Questions and Answers" in prompt_path.read_text(encoding="utf-8")
        commit.assert_called_once_with(
            store,
            "Add Q&A to test_plan prompt",
            auto_commit_type="sdd",
            paths=[prompt_path],
            artifacts_dir="/tmp/followup",
        )

    def test_in_tree_sdd_question_snapshot_is_not_committed(self, tmp_path) -> None:
        from sase.question_shell.followup import _update_question_sdd_prompt_snapshot

        prompt_path = tmp_path / "sdd" / "plans" / "202607" / "prompts" / "p.md"
        prompt_path.parent.mkdir(parents=True)
        prompt_path.write_text("Original prompt\n", encoding="utf-8")
        store = SddStore(
            storage="in_tree",
            sdd_dir=tmp_path / "sdd",
            repo_root=tmp_path,
        )

        with (
            patch("sase.sdd.store.resolve_sdd_store", return_value=store),
            patch("sase.sdd.files.commit_sdd_store_files") as commit,
        ):
            _update_question_sdd_prompt_snapshot(
                str(prompt_path),
                "### Questions and Answers\n\nanswer",
                workspace_dir=str(tmp_path),
                workspace_num=1,
                artifacts_dir="/tmp/followup",
            )

        assert "### Questions and Answers" in prompt_path.read_text(encoding="utf-8")
        commit.assert_not_called()

    def test_sdd_question_snapshot_commit_failure_warns_and_continues(
        self,
        tmp_path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import sase.question_shell.followup as followup_mod

        prompt_path = tmp_path / "202607" / "prompts" / "test_plan.md"
        prompt_path.parent.mkdir(parents=True)
        prompt_path.write_text("Original prompt\n", encoding="utf-8")
        store = SddStore(
            storage="sidecar_repos",
            sdd_dir=tmp_path,
            repo_root=tmp_path,
        )
        meta = {
            "question_sdd_spec_path": str(prompt_path),
            "workspace_dir": str(tmp_path),
            "workspace_num": 1,
        }

        with (
            caplog.at_level("WARNING", logger=followup_mod.__name__),
            patch(
                "sase.question_shell.rounds.question_base_prompt",
                return_value="Original prompt",
            ),
            patch(
                "sase.question_shell.rounds.question_rounds",
                return_value=[
                    build_qa_round(
                        [],
                        {"answers": [], "global_note": "answer"},
                    )
                ],
            ),
            patch("sase.sdd.store.resolve_sdd_store", return_value=store),
            patch(
                "sase.sdd.files.commit_sdd_store_files",
                side_effect=RuntimeError("commit failed"),
            ),
        ):
            declared = followup_mod.question_next_action(
                artifacts_dir="/tmp/followup",
                meta=meta,
                envelope={},
                response={},
                declared="fallback",
            )

        assert declared is not None
        assert "SDD prompt Q&A snapshot update failed" in caplog.text
