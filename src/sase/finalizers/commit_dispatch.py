"""Per-repository stitch dispatch for the built-in commit finalizer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDeferralWire,
    FinalizerDiagnosticWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.commit_declaration import (
    load_accepted_commit_declaration,
    repository_decision_id,
)
from sase.finalizers.commit_dispatch_followup import (
    attempt_post_repair_follow_up as _attempt_post_repair_follow_up,
    conflict_repair_dirty_after_stitch_message as _conflict_repair_dirty_after_stitch_message,
    post_repair_declared_message as _post_repair_declared_message,
    rescue_landed_commit_after_bounds_failure as _rescue_landed_commit_after_bounds_failure,
    stitch_bounds_failure_code as _stitch_bounds_failure_code,
)
from sase.finalizers.commit_dispatch_types import (
    BaselineRecordResolver,
    CommitDispatchResult as _CommitDispatchResult,
    DeferredRepoOutcome as _DeferredRepoOutcome,
    PrepareDirtyState,
    ProtectedPathResolver,
    UnexpectedPathResolver,
    merge_deferrals,
    peek_attempt,
    preflight_attempt,
)
from sase.finalizers.commit_repair import (
    load_commit_results,
    load_latest_stitch_attempt,
    marker_evidence,
    marker_matches_repo,
    new_commit_markers,
    record_stitch_artifacts,
    resolve_commit_conflict,
    stitch_attempt_fingerprint,
    stitch_attempt_input_fields,
    stitch_failure_message,
)
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    ResumeRunner,
    StitchCommandResult,
    StitchRunner,
    failed_result,
)
from sase.finalizers.commit_validation import (
    protection_exhausted_message,
    reconcile_commit_file_hooks,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.ledger import FinalizerBudgetError, InstanceLedger
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult, LLMInvocationOptions, ModelTier
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT

_FOLLOW_UP_STILL_DIRTY = "the follow-up commit still left these paths dirty"


def dispatch_commit_decisions(
    ordered_repos: Sequence[DirtyRepo],
    decisions: Mapping[str, Mapping[str, Any]],
    *,
    state: PreparedCommitDirtyState,
    context: FinalizerExecutionContext,
    instance_id: str,
    artifacts: Path | None,
    project_dir: str,
    provider: Any,
    invoke_result: InvokeResult,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    options: LLMInvocationOptions | None,
    stitch_runner: StitchRunner,
    resume_runner: ResumeRunner,
    ledger: InstanceLedger | None,
    prepare_dirty_state: PrepareDirtyState,
    protected_path_resolver: ProtectedPathResolver,
    unexpected_path_resolver: UnexpectedPathResolver,
    baseline_record_resolver: BaselineRecordResolver,
    accepted_deferrals: Mapping[str, FinalizerDeferralWire] = {},
) -> _CommitDispatchResult:
    """Execute accepted commit decisions in host context order.

    A repository named in *accepted_deferrals* skips its stitch entirely; its
    dirt is expected to remain and is reported as a deferred outcome instead
    of a failure. When every repository is deferred, no attempt budget is
    consumed -- the host adjudicated the deferral at submit time, so nothing
    here is retryable.
    """

    needs_commit = any(
        repository_decision_id(repo) not in accepted_deferrals for repo in ordered_repos
    )
    attempt_id: int | None = None
    attempts: list[FinalizerAttemptWire] = []
    evidence: list[FinalizerOutcomeEvidenceWire] = []
    diagnostics: list[FinalizerDiagnosticWire] = []
    deferred: list[_DeferredRepoOutcome] = []
    current_result = invoke_result

    def _consume_attempt() -> int:
        try:
            return (
                (
                    ledger.consume_before_execute()
                    if needs_commit
                    else ledger.allocate_attempt()
                )
                if ledger is not None
                else 1
            )
        except FinalizerBudgetError as exc:
            raise BuiltinCommitFinalizerError(
                str(exc),
                result=failed_result(
                    instance_id,
                    "attempt_budget_exhausted",
                    str(exc),
                    attempts=[
                        FinalizerAttemptWire(
                            attempt=preflight_attempt(ledger),
                            status="failed",
                            diagnostic_code="attempt_budget_exhausted",
                        )
                    ],
                ),
                invoke_result=current_result,
            ) from exc

    for repo in ordered_repos:
        decision = decisions[repository_decision_id(repo)]
        action = str(decision.get("action"))
        if action != "commit":
            message_text = (
                f"commit declaration for {repo.name} has invalid accepted action "
                f"{action!r}"
            )
            result = failed_result(
                instance_id,
                "invalid_commit_declaration",
                message_text,
                attempts=[
                    FinalizerAttemptWire(
                        attempt=preflight_attempt(ledger),
                        status="failed",
                        diagnostic_code="invalid_commit_declaration",
                    )
                ],
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=result,
                invoke_result=current_result,
            )

        deferral = accepted_deferrals.get(repository_decision_id(repo))
        protected: Sequence[str] = ()
        if deferral is None:
            protected = protected_path_resolver(artifacts, repo.path)
            remaining_before_stitch = unexpected_path_resolver(repo.path, protected)
            if protected and not remaining_before_stitch:
                record = baseline_record_resolver(artifacts, repo.path)
                message_text = protection_exhausted_message(repo, protected, record)
                if attempt_id is not None:
                    attempts[0] = FinalizerAttemptWire(
                        attempt=attempt_id,
                        status="failed",
                        diagnostic_code="protected_paths_exhausted",
                    )
                    failure_attempts = attempts
                else:
                    failure_attempts = [
                        FinalizerAttemptWire(
                            attempt=preflight_attempt(ledger),
                            status="failed",
                            diagnostic_code="protected_paths_exhausted",
                        )
                    ]
                raise BuiltinCommitFinalizerError(
                    message_text,
                    result=failed_result(
                        instance_id,
                        "protected_paths_exhausted",
                        message_text,
                        attempts=failure_attempts,
                        evidence=evidence,
                    ),
                    invoke_result=current_result,
                )

        if deferral is not None:
            if attempt_id is None:
                attempt_id = _consume_attempt()
                attempts = [FinalizerAttemptWire(attempt=attempt_id, status="failed")]
            deferred.append(_DeferredRepoOutcome(repo=repo, deferral=deferral))
            evidence.append(
                FinalizerOutcomeEvidenceWire(
                    kind="deferred_repo",
                    value=(
                        f"{repo.name}:{deferral.reason}:" + ",".join(deferral.paths)
                    ),
                )
            )
            continue

        message = str(decision.get("message", "")).strip()
        attempt_fields = stitch_attempt_input_fields(repo, message, protected)
        attempt_fingerprint = stitch_attempt_fingerprint(attempt_fields)
        prior_attempt = load_latest_stitch_attempt(context, instance_id, repo.name)
        if (
            prior_attempt is not None
            and prior_attempt.inputs.get("fingerprint") == attempt_fingerprint
        ):
            reason = stitch_failure_message(
                repo,
                StitchCommandResult(
                    returncode=1,
                    stdout=prior_attempt.stdout,
                    stderr=prior_attempt.stderr,
                ),
            )
            message_text = (
                f"sase stitch create for {repo.name} was not retried: attempt "
                f"{prior_attempt.attempt}'s inputs -- repo HEAD, dirty-path "
                "fingerprints, exclude set, and message digest -- are "
                f"unchanged, so a retry is guaranteed to fail identically. "
                f"{reason}"
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=failed_result(
                    instance_id,
                    "stitch_retry_skipped_identical_inputs",
                    message_text,
                    attempts=[
                        FinalizerAttemptWire(
                            attempt=preflight_attempt(ledger),
                            status="failed",
                            diagnostic_code="stitch_retry_skipped_identical_inputs",
                        )
                    ],
                    evidence=evidence,
                ),
                invoke_result=current_result,
            )

        if attempt_id is None:
            attempt_id = _consume_attempt()
            attempts = [FinalizerAttemptWire(attempt=attempt_id, status="failed")]
        consumed_attempt = attempt_id

        before_markers = load_commit_results(artifacts)
        stitch = stitch_runner(repo, message, protected, context)
        record_stitch_artifacts(
            context,
            instance_id,
            consumed_attempt,
            stitch,
            label=repo.name,
            inputs={**attempt_fields, "fingerprint": attempt_fingerprint},
        )
        rescued_bounds_failure = _rescue_landed_commit_after_bounds_failure(
            stitch,
            repo=repo,
            before_markers=before_markers,
            artifacts=artifacts,
            instance_id=instance_id,
            attempt_id=consumed_attempt,
            attempts=attempts,
            evidence=evidence,
            diagnostics=diagnostics,
            current_result=current_result,
        )
        repaired_conflict = False
        if not rescued_bounds_failure:
            if stitch.returncode == EXIT_CODE_CONFLICT:
                attempts[0] = FinalizerAttemptWire(
                    attempt=consumed_attempt,
                    status="failed",
                    diagnostic_code="commit_conflict",
                )
                current_result = resolve_commit_conflict(
                    repo,
                    context,
                    provider=provider,
                    invoke_result=current_result,
                    model_tier=model_tier,
                    suppress_output=suppress_output,
                    model_override=model_override,
                    options=options,
                    resume_runner=resume_runner,
                    attempts=attempts,
                    evidence=evidence,
                    before_markers=before_markers,
                    attempt_id=consumed_attempt,
                )
                repaired_conflict = True
            elif stitch.returncode != 0:
                message_text = stitch_failure_message(repo, stitch)
                attempts[0] = FinalizerAttemptWire(
                    attempt=consumed_attempt,
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

        markers = new_commit_markers(before_markers, load_commit_results(artifacts))
        repo_markers = [
            marker for marker in markers if marker_matches_repo(marker, repo)
        ]
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
        evidence.extend(marker_evidence(repo_markers[-1]))
        reconcile_commit_file_hooks(
            repo,
            repo_markers[-1],
            workspace_dir=project_dir,
        )

        remaining = unexpected_path_resolver(repo.path, protected)
        if remaining and repaired_conflict:
            follow_up = _attempt_post_repair_follow_up(
                repo,
                protected,
                context,
                instance_id,
                consumed_attempt,
                attempts=attempts,
                evidence=evidence,
                diagnostics=diagnostics,
                stitch_runner=stitch_runner,
                unexpected_path_resolver=unexpected_path_resolver,
                project_dir=project_dir,
                current_result=current_result,
                declaration_loader=load_accepted_commit_declaration,
            )
            remaining = follow_up.remaining
            if not remaining:
                state = prepare_dirty_state(project_dir, artifacts)
                continue
            message_text = _conflict_repair_dirty_after_stitch_message(
                repo,
                remaining,
                primary_marker=repo_markers[-1],
                failure_reason=follow_up.failure_reason or _FOLLOW_UP_STILL_DIRTY,
            )
            result = failed_result(
                instance_id,
                "dirty_after_stitch",
                message_text,
                attempts=attempts,
                evidence=evidence,
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=result,
                invoke_result=current_result,
            )
        if remaining:
            message_text = (
                f"sase stitch create left uncommitted attributable paths in "
                f"{repo.name}: " + ", ".join(remaining)
            )
            result = failed_result(
                instance_id,
                "dirty_after_stitch",
                message_text,
                attempts=attempts,
                evidence=evidence,
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=result,
                invoke_result=current_result,
            )

        state = prepare_dirty_state(project_dir, artifacts)

    return _CommitDispatchResult(
        invoke_result=current_result,
        state=state,
        attempt_id=attempt_id,
        attempts=attempts,
        evidence=evidence,
        deferred=tuple(deferred),
        diagnostics=tuple(diagnostics),
    )


__all__ = [
    "BaselineRecordResolver",
    "PrepareDirtyState",
    "ProtectedPathResolver",
    "UnexpectedPathResolver",
    "_CommitDispatchResult",
    "_DeferredRepoOutcome",
    "_attempt_post_repair_follow_up",
    "_conflict_repair_dirty_after_stitch_message",
    "_post_repair_declared_message",
    "_rescue_landed_commit_after_bounds_failure",
    "_stitch_bounds_failure_code",
    "dispatch_commit_decisions",
    "merge_deferrals",
    "peek_attempt",
    "preflight_attempt",
]
