"""Per-repository stitch dispatch for the built-in commit finalizer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import (
    ExecutedCommitObligationFactWire,
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
    collect_repair_remaining_handoff as _collect_repair_remaining_handoff,
    conflict_repair_dirty_after_stitch_message as _conflict_repair_dirty_after_stitch_message,
    format_repair_handoff_failure as _format_repair_handoff_failure,
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
from sase.finalizers.commit_dispatch_support import (
    apply_repair_remaining_handoff as _apply_repair_remaining_handoff,
    call_stitch_runner as _call_stitch_runner,
    context_assigned_bead_id as _context_assigned_bead_id,
    decision_bead_action as _decision_bead_action,
    identical_attempt_message,
    protected_paths_for_decision,
    record_executed_repo as _record_executed_repo,
)
from sase.finalizers.commit_repair import (
    load_commit_results,
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
    initial_attempt_id: int | None = None,
    initial_attempts: Sequence[FinalizerAttemptWire] = (),
    initial_evidence: Sequence[FinalizerOutcomeEvidenceWire] = (),
    initial_diagnostics: Sequence[FinalizerDiagnosticWire] = (),
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
    attempt_id: int | None = initial_attempt_id
    attempts: list[FinalizerAttemptWire] = list(initial_attempts)
    evidence: list[FinalizerOutcomeEvidenceWire] = list(initial_evidence)
    diagnostics: list[FinalizerDiagnosticWire] = list(initial_diagnostics)
    deferred: list[_DeferredRepoOutcome] = []
    current_result = invoke_result
    active_decisions: dict[str, Mapping[str, Any]] = dict(decisions)
    active_deferrals: dict[str, FinalizerDeferralWire] = dict(accepted_deferrals)
    pending = list(ordered_repos)
    original_ids = {repository_decision_id(repo) for repo in ordered_repos}
    executed_ids: set[str] = set()
    executed_facts: list[ExecutedCommitObligationFactWire] = []
    landed: list[tuple[str, str]] = []
    sweep_used = False
    index = 0

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

    while index < len(pending):
        repo = pending[index]
        index += 1
        repo_id = repository_decision_id(repo)
        if repo_id in executed_ids:
            continue
        allow_repair = repo_id in original_ids
        decision = active_decisions[repo_id]
        deferral = active_deferrals.get(repo_id)
        action, protected = protected_paths_for_decision(
            repo,
            decision,
            deferral,
            artifacts=artifacts,
            protected_path_resolver=protected_path_resolver,
        )
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

        if deferral is None:
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
            executed_ids.add(repo_id)
            continue

        message = str(decision.get("message", "")).strip()
        bead_action = _decision_bead_action(decision)
        assigned_bead_id = _context_assigned_bead_id(context)
        attempt_fields = stitch_attempt_input_fields(
            repo,
            message,
            protected,
            bead_action=bead_action,
            assigned_bead_id=assigned_bead_id,
        )
        attempt_fingerprint = stitch_attempt_fingerprint(attempt_fields)
        identical_message = identical_attempt_message(
            repo, context, instance_id, attempt_fingerprint
        )
        if identical_message is not None:
            raise BuiltinCommitFinalizerError(
                identical_message,
                result=failed_result(
                    instance_id,
                    "stitch_retry_skipped_identical_inputs",
                    identical_message,
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
        stitch = _call_stitch_runner(
            stitch_runner,
            repo,
            message,
            protected,
            context,
            bead_action=bead_action,
        )
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
            bead_action=bead_action,
            assigned_bead_id=assigned_bead_id,
        )
        repaired_conflict = False
        repaired_without_commit = False
        if not rescued_bounds_failure:
            if stitch.returncode == EXIT_CODE_CONFLICT:
                if not allow_repair:
                    message_text = _format_repair_handoff_failure(
                        (
                            "commit finalizer hit an unresolved conflict in "
                            f"{repo.name} during continuation"
                        ),
                        landed=landed,
                        remaining=(repo,),
                        continuation_bound=True,
                    )
                    attempts[0] = FinalizerAttemptWire(
                        attempt=consumed_attempt,
                        status="failed",
                        diagnostic_code="repair_handoff_continuation_bound",
                    )
                    raise BuiltinCommitFinalizerError(
                        message_text,
                        result=failed_result(
                            instance_id,
                            "repair_handoff_continuation_bound",
                            message_text,
                            attempts=attempts,
                            evidence=evidence,
                        ),
                        invoke_result=current_result,
                    )
                attempts[0] = FinalizerAttemptWire(
                    attempt=consumed_attempt,
                    status="failed",
                    diagnostic_code="commit_conflict",
                )
                repair_result = resolve_commit_conflict(
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
                    bead_action=bead_action,
                )
                current_result = repair_result.invoke_result
                repaired_conflict = True
                repaired_without_commit = repair_result.resolved_without_commit
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
            if not repaired_without_commit:
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
            state = prepare_dirty_state(project_dir, artifacts)
            _record_executed_repo(
                repo,
                repo_id,
                repo_markers=(),
                executed_ids=executed_ids,
                executed_facts=executed_facts,
                landed=landed,
            )
            if repaired_conflict:
                (
                    pending,
                    index,
                    sweep_used,
                    active_decisions,
                    active_deferrals,
                    context,
                    state,
                ) = _apply_repair_remaining_handoff(
                    pending=pending,
                    index=index,
                    sweep_used=sweep_used,
                    executed_ids=executed_ids,
                    executed_facts=executed_facts,
                    landed=landed,
                    active_decisions=active_decisions,
                    active_deferrals=active_deferrals,
                    context=context,
                    instance_id=instance_id,
                    project_dir=project_dir,
                    artifacts=artifacts,
                    prepare_dirty_state=prepare_dirty_state,
                    current_result=current_result,
                    attempts=attempts,
                    evidence=evidence,
                    state=state,
                    declaration_loader=load_accepted_commit_declaration,
                )
            continue
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
                bead_action=bead_action,
            )
            remaining = follow_up.remaining
            if remaining:
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
            markers = new_commit_markers(before_markers, load_commit_results(artifacts))
            repo_markers = [
                marker for marker in markers if marker_matches_repo(marker, repo)
            ]
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
        _record_executed_repo(
            repo,
            repo_id,
            repo_markers=repo_markers,
            executed_ids=executed_ids,
            executed_facts=executed_facts,
            landed=landed,
        )
        if repaired_conflict:
            (
                pending,
                index,
                sweep_used,
                active_decisions,
                active_deferrals,
                context,
                state,
            ) = _apply_repair_remaining_handoff(
                pending=pending,
                index=index,
                sweep_used=sweep_used,
                executed_ids=executed_ids,
                executed_facts=executed_facts,
                landed=landed,
                active_decisions=active_decisions,
                active_deferrals=active_deferrals,
                context=context,
                instance_id=instance_id,
                project_dir=project_dir,
                artifacts=artifacts,
                prepare_dirty_state=prepare_dirty_state,
                current_result=current_result,
                attempts=attempts,
                evidence=evidence,
                state=state,
                declaration_loader=load_accepted_commit_declaration,
            )

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
