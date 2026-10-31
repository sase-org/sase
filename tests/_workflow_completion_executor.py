"""Executor suspension coverage for host-owned workflow reviews."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agent.staged_handoff import (
    read_staged_handoff,
    read_staged_handoff_response,
)
from sase.llm_provider.messages import AIMessage
from sase.macro.directives import PromptDirectives
from sase.macro.workflow_completion import PreparedWorkflowReview
from sase.macro.workflow_executor import WorkflowExecutor, WorkflowSuspended
from sase.macro.workflow_executor_steps_prompt_prepare import _PreparedPromptStep
from sase.macro.workflow_hitl import TUIHITLHandler
from sase.macro.workflow_models import StepStatus, Workflow, WorkflowStep
from sase.macro.workflow_runner import execute_workflow
from tests._workflow_completion_helpers import (
    PROVIDER_RESPONSE,
    agent_evidence,
    agent_identity,
    workflow_env,
)


@pytest.mark.parametrize(
    ("step_type", "step_body"),
    [("bash", 'echo "status=ready"'), ("python", 'print("status=ready")')],
)
def test_script_review_suspends_control_flow_and_runs_finally_before_settlement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    step_type: str,
    step_body: str,
) -> None:
    _repo, artifacts = workflow_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sase.macro.workflow_hitl_gate.workflow_hitl_should_stage_from_agent",
        lambda: True,
    )
    monkeypatch.setattr(
        "sase.notification_gates.service.create_gate",
        lambda *_args, **_kwargs: pytest.fail("workflow review published early"),
    )
    stage_path = artifacts / ".sase_handoff_staged.json"
    cleanup_path = tmp_path / "cleanup-ran"
    next_path = tmp_path / "next-step-ran"
    calls: list[str] = []

    def settle(review: PreparedWorkflowReview, **kwargs: object) -> None:
        del kwargs
        assert review.staged_id
        assert stage_path.is_file()
        assert cleanup_path.is_file()
        assert not next_path.exists()
        calls.append("settled")

    monkeypatch.setattr("sase.macro.workflow_completion.settle_workflow_review", settle)
    stage_step = WorkflowStep(
        name="review",
        bash=step_body if step_type == "bash" else None,
        python=step_body if step_type == "python" else None,
        hitl=True,
        for_loop={"iteration": "[1, 2]"},
    )
    workflow = Workflow(
        name="review-doc",
        steps=[
            stage_step,
            WorkflowStep(name="next", bash=f'touch "{next_path}"'),
            WorkflowStep(
                name="cleanup",
                bash=f'test -f "{stage_path}" && touch "{cleanup_path}"',
                finally_=True,
            ),
        ],
    )
    executor = WorkflowExecutor(
        workflow=workflow,
        args={},
        artifacts_dir=str(artifacts),
        hitl_handler=TUIHITLHandler(str(artifacts), workflow_name=workflow.name),
    )

    outcome = executor.execute()

    assert isinstance(outcome, WorkflowSuspended)
    assert executor.state.status == "waiting_hitl"
    assert executor.state.current_step_index == 0
    assert executor.state.steps[0].status is StepStatus.WAITING_HITL
    assert executor.state.steps[0].output == {"status": "ready"}
    assert executor.state.steps[1].status is StepStatus.PENDING
    assert executor.state.steps[2].status is StepStatus.COMPLETED
    assert calls == ["settled"]
    assert not next_path.exists()
    staged = read_staged_handoff(str(artifacts))
    assert staged is not None
    assert staged["payload"]["spec"]["payload"]["step_type"] == step_type


def test_embedded_review_suspension_runs_embedded_finally_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, artifacts = workflow_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sase.macro.workflow_hitl_gate.workflow_hitl_should_stage_from_agent",
        lambda: True,
    )
    monkeypatch.setattr(
        "sase.notification_gates.service.create_gate",
        lambda *_args, **_kwargs: pytest.fail("workflow review published early"),
    )
    next_path = tmp_path / "embedded-next"
    cleanup_path = tmp_path / "embedded-cleanup"
    workflow = Workflow(name="parent", steps=[])
    executor = WorkflowExecutor(
        workflow=workflow,
        args={},
        artifacts_dir=str(artifacts),
        hitl_handler=TUIHITLHandler(str(artifacts), workflow_name=workflow.name),
    )
    embedded_steps = [
        WorkflowStep(name="review", bash='echo "status=ready"', hitl=True),
        WorkflowStep(name="next", bash=f'touch "{next_path}"'),
        WorkflowStep(
            name="cleanup",
            bash=f'touch "{cleanup_path}"',
            finally_=True,
        ),
    ]

    with pytest.raises(WorkflowSuspended) as caught:
        executor._execute_embedded_workflow_steps(
            embedded_steps,
            {},
            parent_step_name="parent-step",
            embedded_workflow_name="embedded-review",
        )

    assert caught.value.review.identity.workflow == "embedded-review"
    assert cleanup_path.is_file()
    assert not next_path.exists()
    assert executor.state.status == "waiting_hitl"


def test_failed_cleanup_keeps_staged_review_unsettled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, artifacts = workflow_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sase.macro.workflow_hitl_gate.workflow_hitl_should_stage_from_agent",
        lambda: True,
    )
    monkeypatch.setattr(
        "sase.notification_gates.service.create_gate",
        lambda *_args, **_kwargs: pytest.fail("workflow review published early"),
    )
    monkeypatch.setattr(
        "sase.macro.workflow_completion.settle_workflow_review",
        lambda *_args, **_kwargs: pytest.fail("failed cleanup must block settlement"),
    )
    workflow = Workflow(
        name="review-doc",
        steps=[
            WorkflowStep(name="review", bash='echo "status=ready"', hitl=True),
            WorkflowStep(name="cleanup", bash="exit 1", finally_=True),
        ],
    )
    executor = WorkflowExecutor(
        workflow=workflow,
        args={},
        artifacts_dir=str(artifacts),
        hitl_handler=TUIHITLHandler(str(artifacts), workflow_name=workflow.name),
    )

    outcome = executor.execute()

    assert isinstance(outcome, WorkflowSuspended)
    assert executor.state.status == "waiting_hitl"
    assert executor.state.steps[0].status is StepStatus.WAITING_HITL
    assert executor.state.steps[1].status is StepStatus.FAILED
    assert read_staged_handoff(str(artifacts)) is not None


def test_runner_returns_explicit_suspension_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, artifacts = workflow_env(tmp_path, monkeypatch)
    suspension = WorkflowSuspended(object(), provider_content=PROVIDER_RESPONSE)
    monkeypatch.setattr(WorkflowExecutor, "execute", lambda _executor: suspension)
    workflow = Workflow(
        name="review-doc", steps=[WorkflowStep(name="step", bash="true")]
    )

    result = execute_workflow(
        workflow.name,
        [],
        {},
        artifacts_dir=str(artifacts),
        silent=True,
        workflow_obj=workflow,
    )

    assert result.suspension is suspension
    assert result.response_text == PROVIDER_RESPONSE
    assert result.output == ""


def test_agent_review_uses_deferred_provider_and_preserves_real_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, artifacts = workflow_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sase.macro.workflow_hitl_gate.workflow_hitl_should_stage_from_agent",
        lambda: True,
    )
    monkeypatch.setattr(
        "sase.notification_gates.service.create_gate",
        lambda *_args, **_kwargs: pytest.fail("workflow review published early"),
    )
    prepared = _PreparedPromptStep(
        expanded_prompt="draft the report",
        effective_directives=PromptDirectives(),
        embedded_workflows=[],
        pre_step_count=0,
        pre_step_meta={},
        authored_local_request="draft the report",
        continuation_segments=(),
    )
    step = WorkflowStep(name="draft", agent="draft the report", hitl=True)
    workflow = Workflow(name="review-doc", steps=[step])
    calls: list[str] = []

    def settle(review: PreparedWorkflowReview, **kwargs: object) -> None:
        del kwargs
        assert (
            read_staged_handoff_response(
                artifacts_dir=str(artifacts),
                staged_id=review.staged_id,
            )
            == PROVIDER_RESPONSE
        )
        calls.append("settled")

    monkeypatch.setattr("sase.macro.workflow_completion.settle_workflow_review", settle)
    monkeypatch.setattr(
        "sase.macro.workflow_completion.invoke_provider_for_review",
        lambda *_args, **_kwargs: (
            AIMessage(content=PROVIDER_RESPONSE),
            agent_evidence(),
        ),
    )
    monkeypatch.setattr(
        "sase.llm_provider.provider_priority.resolve_provider_routing_context",
        lambda: object(),
    )
    monkeypatch.setattr(
        "sase.macro.workflow_executor_steps_prompt.resolve_prompt_step_launch_selection",
        lambda *_args, **_kwargs: SimpleNamespace(
            model="test-model",
            provider="test-provider",
            reasoning_effort=None,
            alias_trail=[],
            alias_origin=None,
        ),
    )
    monkeypatch.setattr(
        WorkflowExecutor,
        "_prepare_prompt_step",
        lambda *_args, **_kwargs: prepared,
    )
    monkeypatch.setattr(
        "sase.history.chat.save_chat_history",
        lambda **_kwargs: str(artifacts / "chat.md"),
    )
    monkeypatch.setattr(
        "sase.macro.workflow_executor_steps_prompt.capture_vcs_diff",
        lambda: "",
    )
    executor = WorkflowExecutor(
        workflow=workflow,
        args={},
        artifacts_dir=str(artifacts),
        hitl_handler=TUIHITLHandler(str(artifacts), workflow_name=workflow.name),
    )

    outcome = executor.execute()

    assert isinstance(outcome, WorkflowSuspended)
    assert outcome.provider_content == PROVIDER_RESPONSE
    assert outcome.review.identity == agent_identity()
    assert executor.state.status == "waiting_hitl"
    assert executor.state.steps[0].status is StepStatus.WAITING_HITL
    assert executor.state.steps[0].output == {"_raw": PROVIDER_RESPONSE}
    assert calls == ["settled"]
