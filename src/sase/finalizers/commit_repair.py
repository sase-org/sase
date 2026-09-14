"""Stitch dispatch and conflict-repair helpers for builtin@commit."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import sase.finalizers.commit_repair_conflict as _conflict_repair
import sase.finalizers.commit_repair_stitch as _stitch
from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.bounded_subprocess import run_bounded_subprocess
from sase.finalizers.commit_repair_common import _artifact_label
from sase.finalizers.commit_repair_conflict import (
    _ConflictRepairResult,
    _run_conflict_repair_turn,
)
from sase.finalizers.commit_repair_markers import (
    load_commit_results,
    marker_evidence,
    marker_is_unpushed,
    marker_matches_repo,
    new_commit_markers,
)
from sase.finalizers.commit_repair_stitch import (
    load_latest_stitch_attempt,
    record_stitch_artifacts,
    stitch_attempt_fingerprint,
    stitch_bounds_failure_message,
    stitch_failure_message,
)
from sase.finalizers.commit_types import ResumeRunner, StitchCommandResult
from sase.finalizers.executor import FinalizerExecutionContext
from sase.llm_provider.commit_finalizer_git import (
    dirty_path_fingerprints,
    git_changed_files,
)
from sase.llm_provider.commit_finalizer_git_status import git_head_commit_id
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult, LLMInvocationOptions, ModelTier


def run_stitch_create(
    repo: DirtyRepo,
    message: str,
    excludes: Sequence[str],
    context: FinalizerExecutionContext,
    *,
    bead_action: str | None = None,
) -> StitchCommandResult:
    """Run ``sase stitch create`` for one repository."""

    return _stitch.run_stitch_create(
        repo,
        message,
        excludes,
        context,
        bead_action=bead_action,
        subprocess_runner=run_bounded_subprocess,
    )


def run_stitch_resume(
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
    *,
    bead_action: str | None = None,
) -> StitchCommandResult:
    """Resume the checkpointed stitch for one repository."""

    return _stitch.run_stitch_resume(
        repo,
        context,
        bead_action=bead_action,
        subprocess_runner=run_bounded_subprocess,
    )


def resolve_commit_conflict(
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
    *,
    provider: Any,
    invoke_result: InvokeResult,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    options: LLMInvocationOptions | None,
    resume_runner: ResumeRunner,
    attempts: list[FinalizerAttemptWire],
    evidence: list[FinalizerOutcomeEvidenceWire],
    before_markers: Sequence[Mapping[str, Any]],
    attempt_id: int,
    bead_action: str | None = None,
) -> _ConflictRepairResult:
    """Run the one-shot conflict-repair turn and resume the same stitch."""

    return _conflict_repair.resolve_commit_conflict(
        repo,
        context,
        provider=provider,
        invoke_result=invoke_result,
        model_tier=model_tier,
        suppress_output=suppress_output,
        model_override=model_override,
        options=options,
        resume_runner=resume_runner,
        attempts=attempts,
        evidence=evidence,
        before_markers=before_markers,
        attempt_id=attempt_id,
        bead_action=bead_action,
        git_changed_files_fn=git_changed_files,
        git_head_commit_id_fn=git_head_commit_id,
    )


def stitch_attempt_input_fields(
    repo: DirtyRepo,
    message: str,
    excludes: Sequence[str],
    *,
    bead_action: str | None = None,
    assigned_bead_id: str | None = None,
) -> dict[str, Any]:
    """Capture everything that determines whether a stitch attempt can succeed."""

    return _stitch.stitch_attempt_input_fields(
        repo,
        message,
        excludes,
        bead_action=bead_action,
        assigned_bead_id=assigned_bead_id,
        dirty_path_fingerprints_fn=dirty_path_fingerprints,
        git_head_commit_id_fn=git_head_commit_id,
    )


__all__ = [
    "load_commit_results",
    "load_latest_stitch_attempt",
    "marker_evidence",
    "marker_is_unpushed",
    "marker_matches_repo",
    "new_commit_markers",
    "record_stitch_artifacts",
    "resolve_commit_conflict",
    "run_stitch_create",
    "run_stitch_resume",
    "stitch_attempt_fingerprint",
    "stitch_attempt_input_fields",
    "stitch_bounds_failure_message",
    "stitch_failure_message",
]
