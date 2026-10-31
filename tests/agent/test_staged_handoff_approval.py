"""Tests for staged approval inputs that must survive adoption retries."""

from __future__ import annotations

from pathlib import Path

from sase.agent._staged_handoff_approval import ensure_staged_approval_context_locked
from sase.agent.staged_handoff import acquire_adoption_lock
from sase.main.qa_markdown import QARound
from tests._axe_run_agent_exec_plan_helpers import make_ctx, make_state


def test_plan_approval_context_freezes_creator_policy_and_request_identity(
    tmp_path: Path, monkeypatch
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    continuation = type("Continuation", (), {"ctx": ctx, "state": state})()
    staged_record = {"staged_id": "stage-plan-1", "kind": "plan"}
    metadata = {
        "name": "original-planner",
        "model": "model-one",
        "auto_approve_argument": "epic",
    }
    monkeypatch.setenv("SASE_AGENT", "original-agent")
    monkeypatch.setenv("SASE_AGENT_CL_NAME", "original-change")

    with acquire_adoption_lock(Path(state.current_artifacts_dir)):
        first = ensure_staged_approval_context_locked(
            staged_record,
            artifacts_dir=state.current_artifacts_dir,
            run_metadata=metadata,
            continuation=continuation,
        )

    monkeypatch.setenv("SASE_AGENT", "replacement-agent")
    monkeypatch.setenv("SASE_AGENT_CL_NAME", "replacement-change")
    metadata.update(
        name="replacement-planner",
        model="model-two",
        auto_approve_argument="tale",
    )
    state.current_prompt = "changed on retry"
    with acquire_adoption_lock(Path(state.current_artifacts_dir)):
        replay = ensure_staged_approval_context_locked(
            staged_record,
            artifacts_dir=state.current_artifacts_dir,
            run_metadata=metadata,
            continuation=continuation,
        )

    assert replay == first
    assert replay["session_id"] == "stage-plan-1"
    assert replay["plan"]["auto_action"] == "epic"
    assert replay["creator"]["agent"] == "original-agent"
    assert replay["creator"]["agent_cl_name"] == "original-change"


def test_question_approval_context_freezes_base_prompt_rounds_and_auto_policy(
    tmp_path: Path, monkeypatch
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    state.question_gate_artifacts_dir = str(tmp_path / "parent-question-gate")
    continuation = type("Continuation", (), {"ctx": ctx, "state": state})()
    staged_record = {"staged_id": "stage-question-1", "kind": "questions"}
    round_one = QARound(
        questions=[{"question": "Database?"}],
        answers=[{"question": "Database?", "selected": ["SQLite"]}],
        global_note="Keep it local",
    )
    metadata = {"name": "original-agent", "auto_approve_argument": ""}
    monkeypatch.setattr(
        "sase.question_gate_turn.question_base_prompt", lambda _parent: "frozen base"
    )
    monkeypatch.setattr(
        "sase.question_gate_turn.question_rounds", lambda _parent: [round_one]
    )

    with acquire_adoption_lock(Path(state.current_artifacts_dir)):
        first = ensure_staged_approval_context_locked(
            staged_record,
            artifacts_dir=state.current_artifacts_dir,
            run_metadata=metadata,
            continuation=continuation,
        )

    monkeypatch.setattr(
        "sase.question_gate_turn.question_base_prompt", lambda _parent: "changed base"
    )
    monkeypatch.setattr("sase.question_gate_turn.question_rounds", lambda _parent: [])
    metadata["auto_approve_argument"] = None
    with acquire_adoption_lock(Path(state.current_artifacts_dir)):
        replay = ensure_staged_approval_context_locked(
            staged_record,
            artifacts_dir=state.current_artifacts_dir,
            run_metadata=metadata,
            continuation=continuation,
        )

    assert replay == first
    assert replay["questions"]["base_prompt"] == "frozen base"
    assert replay["questions"]["prior_rounds"] == [
        {
            "questions": [{"question": "Database?"}],
            "answers": [{"question": "Database?", "selected": ["SQLite"]}],
            "global_note": "Keep it local",
        }
    ]
    assert replay["questions"]["auto_enabled"] is True
