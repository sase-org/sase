"""Questions/pipe staged adoption, carry inheritance, and mixed dispositions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.staged_handoff import (
    build_pipe_staged_record,
    build_questions_staged_record,
    read_adoption_receipt,
    write_staged_handoff,
    write_staged_handoff_response,
)
from sase.axe.run_agent_exec_staged import (
    CARRIED_CUSTODY_META_KEY,
    StagedInlineContinuation,
    dispatch_completed_staged_handoff,
)
from sase.finalizers.commit import StitchCommandResult
from sase.finalizers.controller_context import ensure_current_declaration
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.types import InvokeResult
from sase.macro.directives import PromptDirectives
from tests.finalizers_carry_test_helpers import submit_repository_actions
from tests.finalizers_protocol_harness_test_helpers import run_controller
from tests.staged_handoff_acceptance_helpers import (
    PLANNER_RESPONSE,
    dual_dirty,
    make_continuation,
    named_stitch,
    patch_dirty_for_settlement,
    prepare_dual_repo_env,
)
from tests.test_axe_run_agent_exec_questions_gate_turn import (
    _fake_creation,
    _questions,
)
from tests.test_staged_custody_adoption import _settled_carry_artifacts

PROVIDER_RESPONSE = PLANNER_RESPONSE


def _stage_questions(
    artifacts: Path, questions: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    record = build_questions_staged_record(
        questions=questions or _questions(),
        dirty_obligations_at_stage=[],
        created_at="2020-01-01T00:00:00Z",
    )
    write_staged_handoff(record, artifacts_dir=str(artifacts))
    write_staged_handoff_response(
        str(record["staged_id"]),
        PROVIDER_RESPONSE,
        artifacts_dir=str(artifacts),
    )
    return record


def _stage_pipe(
    artifacts: Path, *, prompt: str = "finish the review"
) -> dict[str, Any]:
    record = build_pipe_staged_record(
        payload={
            "prompt": prompt,
            "reason": "hand off",
            "model": None,
            "name_token": None,
            "fresh": False,
            "pipe_depth": 0,
        },
        dirty_obligations_at_stage=[],
        created_at="2020-01-01T00:00:00Z",
    )
    write_staged_handoff(record, artifacts_dir=str(artifacts))
    write_staged_handoff_response(
        str(record["staged_id"]),
        PROVIDER_RESPONSE,
        artifacts_dir=str(artifacts),
    )
    return record


def _overwrite_payload(
    artifacts: Path, record: dict[str, Any], payload: dict[str, Any]
) -> None:
    record["payload"] = payload
    (artifacts / ".sase_handoff_staged.json").write_text(
        json.dumps(record), encoding="utf-8"
    )


def test_questions_adopter_records_gate_custodian_and_real_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts, record = _settled_carry_artifacts(tmp_path, monkeypatch)
    _overwrite_payload(artifacts, record, {"questions": _questions()})
    continuation = _continuation_from_custody(tmp_path, artifacts)
    member = tmp_path / "gate-member"
    member.mkdir()
    creation = _fake_creation(gate_state="pending", artifacts_dir=str(member))
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "sase.question_gate_turn.resolve_question_chain_parent", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "sase.question_gate_turn.create_question_gate_turn", lambda *a, **k: creation
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.is_auto_approve_active", lambda: False
    )
    monkeypatch.setattr(
        "sase.history.chat.save_chat_history",
        lambda **kw: captured.update(kw) or "/fake/chat",
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_gate.handle_gate_marker",
        lambda *_a, **_k: "gated",
    )

    result = dispatch_completed_staged_handoff(str(artifacts), continuation)

    assert result is not None and result.adopted
    assert result.outcome == "gated"
    assert captured["response"] == "provider response"
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None and receipt["outcome"] == "adopted"
    assert receipt["refs"]["loop_outcome"] == "gated"
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta[CARRIED_CUSTODY_META_KEY][0]["carried_to"] == str(member)
    assert record["kind"] == "questions"


def test_pipe_adopter_records_successor_custodian_and_real_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts, record = _settled_carry_artifacts(tmp_path, monkeypatch, kind="pipe")
    _overwrite_payload(
        artifacts,
        record,
        {
            "prompt": "finish the review",
            "reason": "hand off",
            "model": None,
            "name_token": None,
            "fresh": False,
            "pipe_depth": 0,
        },
    )
    continuation = _continuation_from_custody(tmp_path, artifacts)
    successor = tmp_path / "pipe-followup"
    captured: dict[str, Any] = {}

    def create(*_a: object, **_k: object) -> str:
        successor.mkdir(exist_ok=True)
        (successor / "agent_meta.json").write_text("{}", encoding="utf-8")
        return str(successor)

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_pipe.save_chat_history",
        lambda **kw: captured.update(kw) or "/fake/chat",
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_pipe.create_followup_artifacts", create
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_pipe.promote_to_workflow", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_pipe._store_followup_prompt_artifact",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_pipe.allocate_agent_session_child_suffix",
        lambda *_a, **_k: "--1",
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_pipe.update_meta_field", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_pipe.update_step_marker_chat_path",
        lambda *_a, **_k: None,
    )

    result = dispatch_completed_staged_handoff(str(artifacts), continuation)

    assert result is not None and result.adopted
    assert captured["response"] == "provider response"
    assert "## Pipe Hand-off" in (captured.get("extra_sections") or "")
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None and receipt["outcome"] == "adopted"
    assert receipt["refs"]["successor_artifacts_dir"] == str(successor)
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta[CARRIED_CUSTODY_META_KEY][0]["carried_to"] == str(successor)


def _continuation_from_custody(
    tmp_path: Path, artifacts: Path
) -> StagedInlineContinuation:
    from tests.test_staged_custody_adoption import _continuation

    return _continuation(tmp_path, artifacts)


def test_dirty_questions_without_declaration_carries_then_followup_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, linked, artifacts, _plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    dirty = dual_dirty(repo, linked)
    _stage_questions(artifacts)
    patch_dirty_for_settlement(monkeypatch, repo, dirty)
    origin_calls: list[str] = []
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create",
        named_stitch(artifacts, dirty, origin_calls),
    )
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))

    ensure_current_declaration(
        provider=object(),
        invoke_result=InvokeResult(content=PROVIDER_RESPONSE),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
        options=None,
        original_prompt="test",
    )
    run_controller(artifacts)
    assert origin_calls == []
    accepted = json.loads(
        (artifacts / "final_submission.json").read_text(encoding="utf-8")
    )
    assert accepted["synthesized"]["kind"] == "handoff_carry"

    member = tmp_path / "gate-member"
    member.mkdir()
    creation = _fake_creation(gate_state="answered", artifacts_dir=str(member))
    successor = tmp_path / "followup"
    inherit_calls: list[tuple[str, str]] = []

    def create(*_a: object, prev_artifacts_dir: str | None = None, **_k: object) -> str:
        successor.mkdir(exist_ok=True)
        (successor / "agent_meta.json").write_text("{}", encoding="utf-8")
        if prev_artifacts_dir:
            inherit_calls.append((prev_artifacts_dir, str(successor)))
            from sase.llm_provider.commit_finalizer_inheritance import (
                inherit_commit_finalizer_responsibility,
            )

            inherit_commit_finalizer_responsibility(
                parent_artifacts_dir=prev_artifacts_dir,
                child_artifacts_dir=str(successor),
                predecessor_name="agent-1",
                successor_name="agent-1--1",
                project_name="sase",
                parent_workspace_dir=str(repo),
                child_workspace_dir=str(repo),
                workspace_num=1,
            )
        return str(successor)

    monkeypatch.setattr(
        "sase.question_gate_turn.resolve_question_chain_parent", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "sase.question_gate_turn.create_question_gate_turn", lambda *a, **k: creation
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.is_auto_approve_active", lambda: True
    )
    monkeypatch.setattr(
        "sase.question_gate_turn.question_rounds",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        "sase.history.chat.save_chat_history",
        lambda **_kw: "/fake/chat",
    )

    def fake_continue(_ctx: object, state: Any, _request: object, **_k: object) -> str:
        create(prev_artifacts_dir=state.current_artifacts_dir)
        state.current_artifacts_dir = str(successor)
        return "agent-1--1"

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_questions.continue_as_successor",
        fake_continue,
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_questions.update_meta_field", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_questions.update_step_marker_chat_path",
        lambda *_a, **_k: None,
    )

    ctx, state = make_continuation(tmp_path, artifacts)
    result = dispatch_completed_staged_handoff(
        str(artifacts), StagedInlineContinuation(ctx=ctx, state=state)
    )
    assert result is not None and result.adopted
    assert inherit_calls == [(str(artifacts), str(successor))]

    follow_calls: list[str] = []
    follow_dirty = dual_dirty(repo, linked)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(successor))
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create",
        named_stitch(successor, follow_dirty, follow_calls),
    )
    patch_dirty_for_settlement(monkeypatch, repo, follow_dirty)
    submit_repository_actions(successor, default_action="commit", persist_plan=True)
    run_controller(successor)
    assert follow_calls == ["main", "plans"]


def test_pipe_successor_inherits_carried_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, linked, artifacts, _plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    dirty = dual_dirty(repo, linked)
    _stage_pipe(artifacts)
    patch_dirty_for_settlement(monkeypatch, repo, dirty)
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create",
        lambda *_a, **_k: StitchCommandResult(returncode=0, stdout="ok\n"),
    )
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    ensure_current_declaration(
        provider=object(),
        invoke_result=InvokeResult(content=PROVIDER_RESPONSE),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
        options=None,
        original_prompt="test",
    )
    run_controller(artifacts)

    successor = tmp_path / "pipe-followup"
    inherit_calls: list[tuple[str, str]] = []

    def create(*_a: object, prev_artifacts_dir: str | None = None, **_k: object) -> str:
        successor.mkdir(exist_ok=True)
        (successor / "agent_meta.json").write_text("{}", encoding="utf-8")
        if prev_artifacts_dir:
            inherit_calls.append((prev_artifacts_dir, str(successor)))
            from sase.llm_provider.commit_finalizer_inheritance import (
                inherit_commit_finalizer_responsibility,
            )

            inherit_commit_finalizer_responsibility(
                parent_artifacts_dir=prev_artifacts_dir,
                child_artifacts_dir=str(successor),
                predecessor_name="agent-1",
                successor_name="agent-1--1",
                project_name="sase",
                parent_workspace_dir=str(repo),
                child_workspace_dir=str(repo),
                workspace_num=1,
            )
        return str(successor)

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_pipe.save_chat_history",
        lambda **_kw: "/fake/chat",
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_pipe.create_followup_artifacts", create
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_pipe.promote_to_workflow", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_pipe._store_followup_prompt_artifact",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_pipe.allocate_agent_session_child_suffix",
        lambda *_a, **_k: "--1",
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_pipe.update_meta_field", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_pipe.update_step_marker_chat_path",
        lambda *_a, **_k: None,
    )

    ctx, state = make_continuation(tmp_path, artifacts)
    result = dispatch_completed_staged_handoff(
        str(artifacts), StagedInlineContinuation(ctx=ctx, state=state)
    )
    assert result is not None and result.adopted
    assert inherit_calls == [(str(artifacts), str(successor))]
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None
    assert receipt["refs"]["successor_artifacts_dir"] == str(successor)


def test_questions_turn_commits_primary_and_carries_linked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, linked, artifacts, _plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    dirty = dual_dirty(repo, linked)
    _stage_questions(artifacts)
    calls: list[str] = []
    patch_dirty_for_settlement(monkeypatch, repo, dirty)
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create",
        named_stitch(artifacts, dirty, calls),
    )
    submit_repository_actions(artifacts, {0: "commit", 1: "carry"})
    run_controller(artifacts)
    assert calls == ["main"]

    member = tmp_path / "gate-member"
    member.mkdir()
    creation = _fake_creation(gate_state="pending", artifacts_dir=str(member))
    monkeypatch.setattr(
        "sase.question_gate_turn.resolve_question_chain_parent", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "sase.question_gate_turn.create_question_gate_turn", lambda *a, **k: creation
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.is_auto_approve_active", lambda: False
    )
    monkeypatch.setattr(
        "sase.history.chat.save_chat_history",
        lambda **_kw: "/fake/chat",
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_gate.handle_gate_marker",
        lambda *_a, **_k: "gated",
    )

    ctx, state = make_continuation(tmp_path, artifacts)
    result = dispatch_completed_staged_handoff(
        str(artifacts), StagedInlineContinuation(ctx=ctx, state=state)
    )
    assert result is not None and result.adopted
    assert result.outcome == "gated"
    payload = json.loads(
        (artifacts / "commit_results.json").read_text(encoding="utf-8")
    )
    assert [item["cwd"] for item in payload] == [str(repo)]
    remaining = {item.path for item in dirty["repos"]}
    assert remaining == {str(linked)}
