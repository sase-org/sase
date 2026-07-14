from __future__ import annotations

from sase.agent_family import (
    STANDARD_PLAN_CHAIN_ID,
    build_handoff_event,
    evaluate_handoff_event,
    evaluate_plan_approval_transition,
    evaluate_questions_transition,
    family_state_snapshot,
    standard_plan_chain_definition,
)
from sase.plan_approval_choices import PLAN_APPROVAL_CHOICE_IDS


def test_standard_plan_chain_definition_exposes_current_protocol_choices() -> None:
    definition = standard_plan_chain_definition()
    plan_gate = next(gate for gate in definition.gates if gate.id == "plan_review")
    completion_event = next(
        event for event in definition.events if event.id == "role_completed"
    )

    assert definition.id == STANDARD_PLAN_CHAIN_ID
    assert {role.id for role in definition.roles} >= {
        "root",
        "plan",
        "q",
        "feedback",
        "code",
        "commit",
    }
    assert "epic" not in {role.id for role in definition.roles}
    assert tuple(choice.id for choice in plan_gate.choices) == PLAN_APPROVAL_CHOICE_IDS
    run_choice = next(choice for choice in plan_gate.choices if choice.id == "run")
    assert run_choice.compatibility_response == {
        "action": "approve",
        "commit_plan": False,
        "run_coder": True,
    }
    assert run_choice.goto_role == "code"
    epic_choice = next(choice for choice in plan_gate.choices if choice.id == "epic")
    assert epic_choice.goto_role is None
    assert epic_choice.terminal == "completed"
    assert epic_choice.side_effect_ids[-2:] == (
        "create_epic_beads",
        "launch_epic_work",
    )
    assert completion_event.terminal is True
    assert completion_event.composition_rule == (
        "after_followup_workflow_including_embedded_vcs_refs"
    )


def test_handoff_event_routes_to_standard_chain_gate_metadata() -> None:
    event = build_handoff_event(
        kind="plan_submitted",
        artifacts_dir="/tmp/artifacts",
        payload={"plan_file": "/tmp/plan.md"},
        current_role_suffix="--plan",
    )
    snapshot = family_state_snapshot(current_role_suffix="--plan")

    evaluation = evaluate_handoff_event(event, snapshot)
    meta = evaluation.runtime_metadata.as_meta_fields()

    assert event.interrupted_role == "plan"
    assert evaluation.gate_id == "plan_review"
    assert evaluation.renderer == "plan_approval"
    assert meta["agent_family_config_id"] == STANDARD_PLAN_CHAIN_ID
    assert meta["active_gate_id"] == "plan_review"
    assert meta["active_gate_renderer"] == "plan_approval"
    assert meta["family_state"] == {
        "current_role": "plan",
        "current_role_suffix": "--plan",
        "feedback_count": 0,
        "qa_round_count": 0,
        "saved_chat_suffixes": [],
        "visit_counts": {"plan": 1},
    }


def test_role_completed_event_terminates_standard_chain() -> None:
    event = build_handoff_event(
        kind="role_completed",
        artifacts_dir="/tmp/artifacts-code",
        payload={
            "outcome": "success",
            "artifacts_ref": "/tmp/artifacts-code",
        },
        current_role_suffix="--code",
    )
    snapshot = family_state_snapshot(current_role_suffix="--code")

    evaluation = evaluate_handoff_event(event, snapshot)
    meta = evaluation.runtime_metadata.as_meta_fields()

    assert event.interrupted_role == "code"
    assert event.payload["outcome"] == "success"
    assert evaluation.gate_id is None
    assert evaluation.renderer is None
    assert evaluation.terminal is True
    assert evaluation.composition_rule == (
        "after_followup_workflow_including_embedded_vcs_refs"
    )
    assert meta["active_gate_id"] is None
    assert meta["active_gate_renderer"] is None
    assert meta["family_state"]["current_role"] == "code"


def test_plan_approval_transition_selects_standard_roles() -> None:
    coder = evaluate_plan_approval_transition(
        action="approve",
        commit_plan=False,
        run_coder=True,
        feedback_count=0,
        qa_round_count=0,
    )
    terminal_commit = evaluate_plan_approval_transition(
        action="approve",
        commit_plan=True,
        run_coder=False,
        feedback_count=0,
        qa_round_count=0,
    )
    feedback = evaluate_plan_approval_transition(
        action="feedback",
        commit_plan=True,
        run_coder=True,
        feedback_count=1,
        qa_round_count=0,
    )
    epic = evaluate_plan_approval_transition(
        action="epic",
        commit_plan=True,
        run_coder=True,
        feedback_count=0,
        qa_round_count=0,
    )

    assert coder.target_role == "code"
    assert coder.role_suffix == "--code"
    assert "set_sase_plan_env" in coder.side_effect_ids
    assert terminal_commit.target_role == "commit"
    assert terminal_commit.terminal_outcome == "plan_committed"
    assert terminal_commit.role_suffix == "--commit"
    assert feedback.target_role == "feedback"
    assert feedback.suffix_template == "--plan-@"
    assert epic.target_role == "plan"
    assert epic.terminal_outcome == "completed"
    assert "create_epic_beads" in epic.side_effect_ids


def test_questions_transition_preserves_interrupted_role_suffix_sequence() -> None:
    root = evaluate_questions_transition(
        interrupted_suffix="--0",
        interrupted_role="q",
        feedback_count=0,
        qa_round_count=1,
    )
    code = evaluate_questions_transition(
        interrupted_suffix="--code",
        interrupted_role="code",
        feedback_count=0,
        qa_round_count=1,
    )
    custom = evaluate_questions_transition(
        interrupted_suffix="--reviewer",
        interrupted_role="reviewer",
        feedback_count=0,
        qa_round_count=1,
    )

    assert root.followup_role == "q"
    assert root.suffix_template == "--@"
    assert code.followup_role == "code"
    assert code.suffix_template == "--code-@"
    assert custom.followup_role == "reviewer"
    assert custom.suffix_template == "--reviewer-@"
