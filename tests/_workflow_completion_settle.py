"""Stage, settle, and host-admission coverage for workflow reviews."""

from __future__ import annotations

import json
from pathlib import Path
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
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.gate_turn.staged_contract import (
    load_staged_gate_resource_bytes,
    read_staged_gate_snapshot_bytes,
)
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.macro.directives import PromptDirectives
from sase.macro.workflow_completion import (
    PreparedWorkflowReview,
    WorkflowReviewIdentity,
    prepare_workflow_review,
    settle_workflow_review,
    stage_workflow_review,
)
from tests._workflow_completion_helpers import (
    PROVIDER_RESPONSE,
    agent_evidence,
    agent_identity,
    workflow_env,
)
from tests.finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    patch_dirty,
    run_controller,
    submit_commit,
    successful_stitch,
)


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


def _script_identity() -> WorkflowReviewIdentity:
    return WorkflowReviewIdentity(
        workflow="review-doc",
        step="build",
        step_type="bash",
    )


def _resolve_plan(artifacts: Path) -> None:
    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )


def test_complete_clean_prompt_with_no_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, artifacts = workflow_env(tmp_path, monkeypatch)
    _resolve_plan(artifacts)
    patch_dirty(monkeypatch, repo, {"repos": ()})
    evidence = agent_evidence()
    review = prepare_workflow_review(
        identity=agent_identity(),
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
    repo, artifacts = workflow_env(tmp_path, monkeypatch)
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


def test_complete_prompt_review_with_accepted_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, artifacts = workflow_env(tmp_path, monkeypatch)
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
    evidence = agent_evidence()
    review = prepare_workflow_review(
        identity=agent_identity(),
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
    repo, artifacts = workflow_env(tmp_path, monkeypatch)
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
    repo, artifacts = workflow_env(tmp_path, monkeypatch)
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
    repo, artifacts = workflow_env(tmp_path, monkeypatch)
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
    repo, artifacts = workflow_env(tmp_path, monkeypatch)
    _resolve_plan(artifacts)
    patch_dirty(monkeypatch, repo, {"repos": ()})
    evidence = agent_evidence()
    first = prepare_workflow_review(
        identity=agent_identity(),
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
            identity=agent_identity(),
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
    repo, artifacts = workflow_env(tmp_path, monkeypatch)
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
        provider_evidence=agent_evidence().to_wire(),
    )
    reservation_id = acquire_staging_reservation(
        artifacts_dir=str(artifacts),
        command="workflow review",
        host=admission,
    )
    assert (artifacts / STAGING_RESERVATION_FILENAME).is_file()
    release_staging_reservation(reservation_id, artifacts_dir=str(artifacts))
