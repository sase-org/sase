"""Post-repair stitch handling for built-in commit dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDiagnosticWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.commit_declaration import (
    commit_decisions_for_instance,
    load_accepted_commit_declaration,
    repository_decision_id,
)
from sase.finalizers.commit_dispatch_types import (
    PostRepairFollowUpResult,
    UnexpectedPathResolver,
)
from sase.finalizers.commit_repair import (
    load_commit_results,
    marker_evidence,
    marker_matches_repo,
    new_commit_markers,
    record_stitch_artifacts,
    stitch_attempt_fingerprint,
    stitch_attempt_input_fields,
    stitch_failure_message,
)
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
    StitchRunner,
    failed_result,
)
from sase.finalizers.commit_validation import reconcile_commit_file_hooks
from sase.finalizers.executor import FinalizerExecutionContext
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT

_DeclarationLoader = Callable[[str | None], tuple[Mapping[str, Any], Any, Any, Any]]

_NO_FOLLOW_UP_DECLARATION = (
    "the conflict-repair turn submitted no commit declaration for this repository"
)
_FOLLOW_UP_LOAD_FAILED = "the declaration could not be loaded"
_FOLLOW_UP_STILL_DIRTY = "the follow-up commit still left these paths dirty"


def attempt_post_repair_follow_up(
    repo: DirtyRepo,
    protected: Sequence[str],
    context: FinalizerExecutionContext,
    instance_id: str,
    attempt_id: int,
    *,
    attempts: list[FinalizerAttemptWire],
    evidence: list[FinalizerOutcomeEvidenceWire],
    diagnostics: list[FinalizerDiagnosticWire],
    stitch_runner: StitchRunner,
    unexpected_path_resolver: UnexpectedPathResolver,
    project_dir: str,
    current_result: InvokeResult,
    declaration_loader: _DeclarationLoader | None = None,
) -> PostRepairFollowUpResult:
    message, failure_reason = post_repair_declared_message(
        repo,
        context,
        instance_id,
        declaration_loader=declaration_loader,
    )
    if failure_reason is not None:
        return PostRepairFollowUpResult(
            remaining=unexpected_path_resolver(repo.path, protected),
            failure_reason=failure_reason,
        )
    assert message is not None

    artifacts = (
        Path(context.artifacts_dir) if context.artifacts_dir is not None else None
    )
    before_markers = load_commit_results(artifacts)
    attempt_fields = stitch_attempt_input_fields(repo, message, protected)
    attempt_fingerprint = stitch_attempt_fingerprint(attempt_fields)
    stitch = stitch_runner(repo, message, protected, context)
    follow_up_label = f"{repo.name}.post-repair"
    record_stitch_artifacts(
        context,
        instance_id,
        attempt_id,
        stitch,
        label=follow_up_label,
        inputs={**attempt_fields, "fingerprint": attempt_fingerprint},
    )
    rescued_bounds_failure = rescue_landed_commit_after_bounds_failure(
        stitch,
        repo=repo,
        before_markers=before_markers,
        artifacts=artifacts,
        instance_id=instance_id,
        attempt_id=attempt_id,
        attempts=attempts,
        evidence=evidence,
        diagnostics=diagnostics,
        current_result=current_result,
    )
    if not rescued_bounds_failure:
        if stitch.returncode == EXIT_CODE_CONFLICT:
            message_text = (
                f"commit finalizer hit a second unresolved conflict in {repo.name}"
            )
            result = failed_result(
                instance_id,
                "second_unresolved_conflict",
                message_text,
                attempts=attempts,
                evidence=evidence,
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=result,
                invoke_result=current_result,
            )
        if stitch.returncode != 0:
            message_text = stitch_failure_message(repo, stitch)
            attempts[0] = FinalizerAttemptWire(
                attempt=attempt_id,
                status="failed",
                diagnostic_code="stitch_failed",
            )
            result = failed_result(
                instance_id,
                "stitch_failed",
                message_text,
                attempts=attempts,
                evidence=evidence,
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=result,
                invoke_result=current_result,
            )

    markers = new_commit_markers(
        before_markers,
        load_commit_results(artifacts),
    )
    repo_markers = [marker for marker in markers if marker_matches_repo(marker, repo)]
    if not repo_markers:
        message_text = (
            f"sase stitch create completed for {repo.name}, but no "
            "commit_results.json entry was recorded"
        )
        result = failed_result(
            instance_id,
            "missing_commit_result",
            message_text,
            attempts=attempts,
            evidence=evidence,
        )
        raise BuiltinCommitFinalizerError(
            message_text,
            result=result,
            invoke_result=current_result,
        )
    evidence.append(
        FinalizerOutcomeEvidenceWire(kind="conflict_repair_followup", value="success")
    )
    evidence.extend(marker_evidence(repo_markers[-1]))
    reconcile_commit_file_hooks(
        repo,
        repo_markers[-1],
        workspace_dir=project_dir,
    )
    remaining = unexpected_path_resolver(repo.path, protected)
    if remaining:
        return PostRepairFollowUpResult(
            remaining=remaining,
            failure_reason=_FOLLOW_UP_STILL_DIRTY,
        )
    return PostRepairFollowUpResult(remaining=[])


def post_repair_declared_message(
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
    instance_id: str,
    *,
    declaration_loader: _DeclarationLoader | None = None,
) -> tuple[str | None, str | None]:
    try:
        loader = declaration_loader or load_accepted_commit_declaration
        envelope, _accepted_context, _host_records, _accepted_deferrals = loader(
            context.artifacts_dir
        )
    except Exception as exc:
        return None, f"{_FOLLOW_UP_LOAD_FAILED}: {exc}"
    decision = commit_decisions_for_instance(envelope, instance_id).get(
        repository_decision_id(repo)
    )
    if not isinstance(decision, Mapping):
        return None, _NO_FOLLOW_UP_DECLARATION
    if str(decision.get("action")) != "commit":
        return None, _NO_FOLLOW_UP_DECLARATION
    message = str(decision.get("message", "")).strip()
    if not message:
        return None, _NO_FOLLOW_UP_DECLARATION
    return message, None


def conflict_repair_dirty_after_stitch_message(
    repo: DirtyRepo,
    remaining: Sequence[str],
    *,
    primary_marker: Mapping[str, Any],
    failure_reason: str,
) -> str:
    base = (
        f"sase stitch create left uncommitted attributable paths in "
        f"{repo.name}: " + ", ".join(remaining)
    )
    sha = primary_marker.get("commit_sha")
    landed = (
        f"The primary commit for {repo.name} already landed as {sha}."
        if isinstance(sha, str) and sha
        else (
            f"The primary commit for {repo.name} already landed, but "
            "commit_results.json did not include its commit sha."
        )
    )
    return f"{base}. {landed} Follow-up commit status: {failure_reason}."


def stitch_bounds_failure_code(stitch: StitchCommandResult) -> str | None:
    if stitch.timed_out:
        return "stitch_timeout"
    if stitch.stdout_truncated or stitch.stderr_truncated:
        return "stitch_output_cap"
    return None


def rescue_landed_commit_after_bounds_failure(
    stitch: StitchCommandResult,
    *,
    repo: DirtyRepo,
    before_markers: Sequence[Mapping[str, Any]],
    artifacts: Path | None,
    instance_id: str,
    attempt_id: int,
    attempts: list[FinalizerAttemptWire],
    evidence: list[FinalizerOutcomeEvidenceWire],
    diagnostics: list[FinalizerDiagnosticWire],
    current_result: InvokeResult,
) -> bool:
    """Raise on a bounds failure with no marker; rescue when the commit landed.

    Returns True when a matching ``commit_results.json`` marker proves the
    commit already landed, so the caller should skip returncode failure
    handling and continue with the normal marker-verification path.
    """

    code = stitch_bounds_failure_code(stitch)
    if code is None:
        return False
    markers = new_commit_markers(before_markers, load_commit_results(artifacts))
    repo_markers = [marker for marker in markers if marker_matches_repo(marker, repo)]
    if not repo_markers:
        message_text = f"sase stitch create {code} for {repo.name}"
        attempts[0] = FinalizerAttemptWire(
            attempt=attempt_id,
            status="failed",
            diagnostic_code=code,
        )
        raise BuiltinCommitFinalizerError(
            message_text,
            result=failed_result(
                instance_id,
                code,
                message_text,
                attempts=attempts,
                evidence=evidence,
            ),
            invoke_result=current_result,
        )
    diagnostics.append(
        FinalizerDiagnosticWire(
            code=f"{code}_after_commit",
            severity="warning",
            message=(
                f"sase stitch create {code} for {repo.name}, but the commit "
                "already landed before the process was killed"
            ),
            instance_id=instance_id,
            attempt=attempt_id,
        )
    )
    return True


__all__ = [
    "attempt_post_repair_follow_up",
    "conflict_repair_dirty_after_stitch_message",
    "post_repair_declared_message",
    "rescue_landed_commit_after_bounds_failure",
    "stitch_bounds_failure_code",
]
