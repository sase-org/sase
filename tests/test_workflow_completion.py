"""Host-owned workflow completion seam for staged HITL reviews."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.staged_handoff import (
    STAGED_HANDOFF_RESPONSE_FILENAME,
    STAGING_RESERVATION_FILENAME,
    HostStageAdmission,
    HostStageIdentity,
    StagedHandoffError,
    acquire_staging_reservation,
    admit_stage,
    read_staged_handoff,
    read_staged_handoff_response,
    release_staging_reservation,
)
from sase.finalizers.controller import FinalizerControllerError
from sase.finalizers.declaration import FINAL_SUBMISSION_FILENAME
from sase.finalizers.declaration_manifest_io import load_latest_finalizer_context
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.deferred import (
    ProviderEvidence,
    digest_response,
    record_deferred_provider_evidence,
    take_deferred_provider_evidence,
)
from sase.llm_provider.messages import AIMessage
from sase.llm_provider.preprocessing import _PreprocessResult
from sase.llm_provider.types import InvokeResult
from sase.macro.directives import PromptDirectives
from sase.macro.workflow_completion import (
    PreparedWorkflowReview,
    WorkflowReviewIdentity,
    _WorkflowCompletionError,
    invoke_provider_for_review,
    prepare_workflow_review,
    settle_workflow_review,
    stage_workflow_review,
)
from sase.macro.workflow_executor import WorkflowExecutor, WorkflowSuspended
from sase.macro.workflow_executor_steps_prompt_prepare import _PreparedPromptStep
from sase.macro.workflow_hitl import TUIHITLHandler
from sase.macro.workflow_models import StepStatus, Workflow, WorkflowStep
from sase.macro.workflow_runner import execute_workflow
from sase.gate_turn.staged_contract import (
    load_staged_gate_resource_bytes,
    read_staged_gate_snapshot_bytes,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from tests._failed_close_recovery_helpers import commit_config, use_config
from tests.finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    patch_dirty,
    prepare_agent_env,
    run_controller,
    submit_commit,
    successful_stitch,
)

RUN_ID = "20261030120000"
PROVIDER_RESPONSE = "ordinary final response"


def _stage_and_settle(
    review: PreparedWorkflowReview,
    *,
    artifacts_dir: str,
    provider_content: str | None = None,
    original_prompt: str = "",
) -> Any:
    """Stage a prepared review, then settle it, as the workflow executor does."""
    stage_workflow_review(
        review,
        artifacts_dir=artifacts_dir,
        provider_content=provider_content,
    )
    return settle_workflow_review(
        review,
        artifacts_dir=artifacts_dir,
        provider_content=provider_content,
        original_prompt=original_prompt,
    )


def _workflow_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    """Return ``(repo, artifacts)`` with agent identity and finalizer plan."""
    artifacts = tmp_path / RUN_ID
    artifacts.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    prepare_agent_env(monkeypatch, artifacts, repo)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", RUN_ID)
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "agent-1", "workspace_num": 23}),
        encoding="utf-8",
    )
    use_config(monkeypatch, commit_config())
    return repo, artifacts


def _agent_identity() -> WorkflowReviewIdentity:
    return WorkflowReviewIdentity(
        workflow="review-doc",
        step="draft",
        step_type="agent",
    )


def _script_identity() -> WorkflowReviewIdentity:
    return WorkflowReviewIdentity(
        workflow="review-doc",
        step="build",
        step_type="bash",
    )


def _agent_evidence(content: str = PROVIDER_RESPONSE) -> ProviderEvidence:
    digest, chars = digest_response(content)
    return ProviderEvidence(
        agent_type="workflow-review-doc-draft",
        turn_nonce="nonce-test",
        response_sha256=digest,
        response_chars=chars,
    )


def _fake_agent_invoke(
    monkeypatch: pytest.MonkeyPatch,
    content: str = PROVIDER_RESPONSE,
) -> None:
    """Stand in for ``invoke_agent`` with the deferred branch's evidence."""

    def fake(prompt: object, **kwargs: object) -> AIMessage:
        assert kwargs.get("defer_finalizers") is True
        token = kwargs.get("evidence_token")
        assert isinstance(token, str) and token
        digest, chars = digest_response(content)
        record_deferred_provider_evidence(
            token,
            ProviderEvidence(
                agent_type=str(kwargs.get("agent_type")),
                turn_nonce="nonce-live",
                response_sha256=digest,
                response_chars=chars,
            ),
        )
        return AIMessage(content=content)

    monkeypatch.setattr("sase.llm_provider.invoke_agent", fake)


def _resolve_plan(artifacts: Path) -> None:
    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )


def test_deferred_evidence_registry_round_trip() -> None:
    assert take_deferred_provider_evidence("missing") is None
    first = _agent_evidence("one")
    second = _agent_evidence("two")
    record_deferred_provider_evidence("tok", first)
    record_deferred_provider_evidence("tok", second)
    assert take_deferred_provider_evidence("tok") == second
    assert take_deferred_provider_evidence("tok") is None


def test_deferred_invoke_skips_finalizers_and_records_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider._invoke import invoke_agent

    artifacts = tmp_path / RUN_ID
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.delenv("SASE_FINAL_TURN_NONCE", raising=False)
    with (
        patch(
            "sase.llm_provider._invoke.preprocess_prompt",
            return_value=_PreprocessResult(prompt="preprocessed"),
        ),
        patch("sase.llm_provider._invoke.get_provider"),
        patch(
            "sase.llm_provider._invoke.invoke_with_instructions",
            return_value=InvokeResult(content="review output"),
        ),
        patch("sase.llm_provider._invoke.postprocess_success"),
        patch(
            "sase.finalizers.run_finalizers",
            side_effect=AssertionError("finalizers must be deferred"),
        ),
    ):
        result = invoke_agent(
            "prompt",
            agent_type="workflow-x",
            artifacts_dir=str(artifacts),
            provider_name="fakey",
            suppress_output=True,
            defer_finalizers=True,
            evidence_token="tok-deferred",
        )
    assert result.content == "review output"
    from sase.axe.runner_lifecycle_phase import current_lifecycle_phase

    assert current_lifecycle_phase() == "provider_done"
    from sase.finalizers.declaration import SASE_FINAL_TURN_NONCE_ENV

    assert SASE_FINAL_TURN_NONCE_ENV not in os.environ
    evidence = take_deferred_provider_evidence("tok-deferred")
    assert evidence is not None
    assert evidence.agent_type == "workflow-x"
    assert evidence.turn_nonce
    digest, chars = digest_response("review output")
    assert evidence.response_sha256 == digest
    assert evidence.response_chars == chars


def test_invoke_provider_for_review_returns_completed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_agent_invoke(monkeypatch)
    response, evidence = invoke_provider_for_review(
        "do work",
        agent_type="workflow-review-doc-draft",
        artifacts_dir=str(tmp_path),
        workflow="review-doc",
    )
    assert response.content == PROVIDER_RESPONSE
    assert evidence.turn_nonce == "nonce-live"
    digest, _chars = digest_response(PROVIDER_RESPONSE)
    assert evidence.response_sha256 == digest


def test_invoke_provider_for_review_refuses_missing_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_no_evidence(prompt: object, **kwargs: object) -> AIMessage:
        return AIMessage(content=PROVIDER_RESPONSE)

    monkeypatch.setattr("sase.llm_provider.invoke_agent", fake_no_evidence)
    with pytest.raises(
        _WorkflowCompletionError,
        match="no completed-provider evidence",
    ):
        invoke_provider_for_review(
            "do work",
            agent_type="workflow-review-doc-draft",
            artifacts_dir=str(tmp_path),
        )


def test_prepare_agent_review_requires_provider_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, _artifacts = _workflow_env(tmp_path, monkeypatch)
    with pytest.raises(
        _WorkflowCompletionError,
        match="completed-provider evidence",
    ):
        prepare_workflow_review(
            identity=_agent_identity(),
            output={"text": "draft"},
            artifacts_dir=str(_artifacts),
            has_output=True,
        )


def test_prepare_script_review_needs_no_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, artifacts = _workflow_env(tmp_path, monkeypatch)
    for step_type in ("bash", "python"):
        identity = WorkflowReviewIdentity(
            workflow="review-doc",
            step="build",
            step_type=step_type,
        )
        review = prepare_workflow_review(
            identity=identity,
            output={"exit_code": 0},
            artifacts_dir=str(artifacts),
        )
        assert review.successor_workspace == "inherit"
        assert review.carry_allowed is True
        assert review.evidence_wire is None
        release_staging_reservation(
            review.reservation_id,
            artifacts_dir=str(artifacts),
        )


def test_prepare_review_rejects_unknown_step_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, artifacts = _workflow_env(tmp_path, monkeypatch)
    with pytest.raises(_WorkflowCompletionError, match="step type"):
        prepare_workflow_review(
            identity=WorkflowReviewIdentity(
                workflow="review-doc",
                step="build",
                step_type="shell",
            ),
            output={},
            artifacts_dir=str(artifacts),
        )


def test_complete_clean_prompt_with_no_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, artifacts = _workflow_env(tmp_path, monkeypatch)
    _resolve_plan(artifacts)
    patch_dirty(monkeypatch, repo, {"repos": ()})
    evidence = _agent_evidence()
    review = prepare_workflow_review(
        identity=_agent_identity(),
        output={"text": "draft"},
        artifacts_dir=str(artifacts),
        has_output=True,
        provider_evidence=evidence,
    )
    result = _stage_and_settle(
        review,
        artifacts_dir=str(artifacts),
        provider_content=PROVIDER_RESPONSE,
        original_prompt="do work",
    )
    assert result.content == PROVIDER_RESPONSE
    staged = read_staged_handoff(str(artifacts))
    assert staged is not None
    assert staged["staged_id"] == review.staged_id
    assert staged["kind"] == "gate"
    assert staged["successor_workspace"] == "inherit"
    assert staged["carry_allowed"] is True
    assert (
        read_staged_handoff_response(review.staged_id, artifacts_dir=str(artifacts))
        == PROVIDER_RESPONSE
    )
    context = load_latest_finalizer_context(artifacts)
    assert context.handoff is not None
    assert context.handoff.staged_ref == review.staged_id


def test_staged_workflow_review_freezes_path_output_before_finalizers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, artifacts = _workflow_env(tmp_path, monkeypatch)
    _resolve_plan(artifacts)
    patch_dirty(monkeypatch, repo, {"repos": ()})
    source = tmp_path / "build-report.md"
    source.write_text("review this exact build report\n", encoding="utf-8")
    original = source.read_bytes()
    review = prepare_workflow_review(
        identity=_script_identity(),
        output={"report": str(source)},
        artifacts_dir=str(artifacts),
        has_output=True,
        output_types={"report": "path"},
    )

    with patch(
        "sase.notification_gates.service.create_gate",
        side_effect=AssertionError("staging must not publish a gate"),
    ):
        stage_workflow_review(review, artifacts_dir=str(artifacts))

    payload = review.preparation.payload
    assert payload is not None
    [resource] = payload["resources"]
    resource_path = resource["path"]
    assert resource["origin"] == str(source)
    source.write_text("changed while finalizers ran\n", encoding="utf-8")
    assert (
        read_staged_gate_snapshot_bytes(str(artifacts), review.staged_id, resource_path)
        == original
    )
    assert (
        load_staged_gate_resource_bytes(str(artifacts), review.staged_id, payload)[
            resource_path
        ]
        == original
    )

    settle_workflow_review(review, artifacts_dir=str(artifacts))
    context = load_latest_finalizer_context(artifacts)
    assert context.handoff is not None
    assert context.handoff.staged_ref == review.staged_id
    assert (
        read_staged_gate_snapshot_bytes(str(artifacts), review.staged_id, resource_path)
        == original
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
    _repo, artifacts = _workflow_env(tmp_path, monkeypatch)
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
    _repo, artifacts = _workflow_env(tmp_path, monkeypatch)
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
    _repo, artifacts = _workflow_env(tmp_path, monkeypatch)
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
    _repo, artifacts = _workflow_env(tmp_path, monkeypatch)
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
    _repo, artifacts = _workflow_env(tmp_path, monkeypatch)
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
            _agent_evidence(),
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
    assert outcome.review.identity == _agent_identity()
    assert executor.state.status == "waiting_hitl"
    assert executor.state.steps[0].status is StepStatus.WAITING_HITL
    assert executor.state.steps[0].output == {"_raw": PROVIDER_RESPONSE}
    assert calls == ["settled"]


def test_complete_prompt_review_with_accepted_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, artifacts = _workflow_env(tmp_path, monkeypatch)
    dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create",
        successful_stitch(artifacts, dirty, calls),
    )
    submit_commit(artifacts)
    # CLI admission still refuses after the accepted submission.
    with pytest.raises(StagedHandoffError, match="/sase_final"):
        admit_stage(
            command="sase gate create",
            artifacts_dir=str(artifacts),
        )
    evidence = _agent_evidence()
    review = prepare_workflow_review(
        identity=_agent_identity(),
        output={"text": "draft"},
        artifacts_dir=str(artifacts),
        has_output=True,
        provider_evidence=evidence,
    )
    result = _stage_and_settle(
        review,
        artifacts_dir=str(artifacts),
        provider_content=PROVIDER_RESPONSE,
        original_prompt="do work",
    )
    assert result.content == PROVIDER_RESPONSE
    assert calls == ["main"]
    context = load_latest_finalizer_context(artifacts)
    assert context.handoff is not None
    assert context.handoff.staged_ref == review.staged_id


def test_complete_script_review_that_dirties_repo_carries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, artifacts = _workflow_env(tmp_path, monkeypatch)
    _resolve_plan(artifacts)
    dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)
    review = prepare_workflow_review(
        identity=_script_identity(),
        output={"exit_code": 0},
        artifacts_dir=str(artifacts),
    )
    result = _stage_and_settle(
        review,
        artifacts_dir=str(artifacts),
        original_prompt="make build",
    )
    assert result is not None
    staged = read_staged_handoff(str(artifacts))
    assert staged is not None
    assert staged["staged_id"] == review.staged_id
    # Script steps persist no ordinary provider response.
    assert not (artifacts / STAGED_HANDOFF_RESPONSE_FILENAME).exists()
    submission = json.loads(
        (artifacts / FINAL_SUBMISSION_FILENAME).read_text(encoding="utf-8")
    )
    assert submission["synthesized"]["staged_ref"] == review.staged_id
    assert submission["synthesized"]["kind"] == "handoff_carry"
    context = load_latest_finalizer_context(artifacts)
    assert context.handoff is not None
    assert context.handoff.staged_ref == review.staged_id


def test_complete_script_review_after_finalized_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, artifacts = _workflow_env(tmp_path, monkeypatch)
    dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create",
        successful_stitch(artifacts, dirty, calls),
    )
    # An earlier finalized prompt: declaration accepted and committed.
    submit_commit(artifacts)
    run_controller(artifacts, MagicMock())
    assert dirty["repos"] == ()
    # A later script step dirties different paths and requests review. The
    # changed fingerprints keep the commit retry guard from mistaking the
    # second stitch for an identical retry of the first.
    script_dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            DirtyRepo(
                name="main",
                path=str(repo),
                changed_files=("src/other.py",),
                kind="main",  # type: ignore[arg-type]
            ),
        )
    }
    patch_dirty(monkeypatch, repo, script_dirty)
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/other.py": ("M", "changed")},
    )
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create",
        successful_stitch(artifacts, script_dirty, calls),
    )
    review = prepare_workflow_review(
        identity=_script_identity(),
        output={"exit_code": 0},
        artifacts_dir=str(artifacts),
    )
    result = _stage_and_settle(
        review,
        artifacts_dir=str(artifacts),
        original_prompt="make build",
    )
    assert result is not None
    context = load_latest_finalizer_context(artifacts)
    assert context.handoff is not None
    assert context.handoff.staged_ref == review.staged_id


def test_finalizer_failure_leaves_stage_held(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, artifacts = _workflow_env(tmp_path, monkeypatch)
    patch_dirty(monkeypatch, repo, {"repos": (dirty_repo(repo),)})
    review = prepare_workflow_review(
        identity=_script_identity(),
        output={"exit_code": 0},
        artifacts_dir=str(artifacts),
    )
    with pytest.raises(FinalizerControllerError):
        _stage_and_settle(
            review,
            artifacts_dir=str(artifacts),
            original_prompt="make build",
        )
    staged = read_staged_handoff(str(artifacts))
    assert staged is not None
    assert staged["staged_id"] == review.staged_id
    assert not (artifacts / ".sase_handoff_adopted.json").exists()


def test_host_second_handoff_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, artifacts = _workflow_env(tmp_path, monkeypatch)
    _resolve_plan(artifacts)
    patch_dirty(monkeypatch, repo, {"repos": ()})
    evidence = _agent_evidence()
    first = prepare_workflow_review(
        identity=_agent_identity(),
        output={"text": "one"},
        artifacts_dir=str(artifacts),
        has_output=True,
        provider_evidence=evidence,
    )
    _stage_and_settle(
        first,
        artifacts_dir=str(artifacts),
        provider_content=PROVIDER_RESPONSE,
        original_prompt="do work",
    )
    with pytest.raises(StagedHandoffError, match="pending handoff already exists"):
        prepare_workflow_review(
            identity=_agent_identity(),
            output={"text": "two"},
            artifacts_dir=str(artifacts),
            has_output=True,
            provider_evidence=evidence,
        )
    staged = read_staged_handoff(str(artifacts))
    assert staged is not None
    assert staged["staged_id"] == first.staged_id


def test_host_admission_allows_review_despite_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, artifacts = _workflow_env(tmp_path, monkeypatch)
    dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create",
        successful_stitch(artifacts, dirty, calls),
    )
    submit_commit(artifacts)
    admission = HostStageAdmission(
        identity=HostStageIdentity(
            workflow="review-doc",
            step="draft",
            step_type="agent",
        ),
        provider_evidence=_agent_evidence().to_wire(),
    )
    reservation_id = acquire_staging_reservation(
        artifacts_dir=str(artifacts),
        command="workflow review",
        host=admission,
    )
    assert (artifacts / STAGING_RESERVATION_FILENAME).is_file()
    release_staging_reservation(reservation_id, artifacts_dir=str(artifacts))
