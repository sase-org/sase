"""Main orchestration for the built-in ``builtin@commit`` finalizer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDiagnosticWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.commit_bead import ensure_no_residual_dirt
from sase.finalizers.commit_declaration import (
    accepted_deferrals_for_instance,
    accepted_repos_from_host,
    commit_decisions_for_instance,
    dirty_repos_in_context_order,
    is_missing_declaration,
    load_accepted_commit_declaration,
    reject_stale_repository_obligation,
    repository_decision_id,
)
from sase.finalizers.commit_dispatch import dispatch_commit_decisions
from sase.finalizers.commit_dispatch_types import (
    DeferredRepoOutcome,
    merge_deferrals,
    peek_attempt,
    preflight_attempt,
)
from sase.finalizers.commit_checkpoint_recovery import resume_owned_pending_checkpoint
from sase.finalizers.commit_repair import (
    load_commit_results,
    run_stitch_create,
    run_stitch_resume,
)
from sase.finalizers.commit_transient import (
    already_clean_fingerprint_before,
    context_for_accepted_assigned_bead,
    extra_dirty_message,
    refresh_state_for_transient_extra_dirty,
)
from sase.finalizers.commit_types import (
    BuiltinCommitExecution,
    BuiltinCommitFinalizerError,
    ResumeRunner,
    StitchRunner,
    deferred_result,
    failed_result,
    success_result,
)
from sase.finalizers.commit_unpushed_resume import resume_unpushed_already_clean_repos
from sase.finalizers.commit_validation import (
    protected_baseline_record,
    raise_if_unpublished_machine_state,
    reject_discarded_dirty_work,
    resolve_protected_baseline_paths,
    resolve_unexpected_remaining_paths,
)
from sase.finalizers.config import ConfiguredFinalizerInstance
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.ledger import InstanceLedger
from sase.finalizers.reconciliation import (
    auto_commit_separate_sdd_store_if_possible,
    pre_reconciliation_dirty_state,
    pre_reconciliation_fingerprints,
    prepare_commit_dirty_state,
    reject_unproven_reconciliation_transition,
)
from sase.llm_provider.commit_finalizer_artifacts import artifact_root
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.llm_provider.commit_finalizer_git import progress_fingerprint
from sase.llm_provider.commit_finalizer_types import DirtyState
from sase.llm_provider.types import InvokeResult, LLMInvocationOptions, ModelTier

_COMMIT_PROVIDER_REF = "builtin@commit"


def execute_commit_finalizer(
    instance: ConfiguredFinalizerInstance,
    context: FinalizerExecutionContext,
    *,
    provider: Any,
    invoke_result: InvokeResult,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    options: LLMInvocationOptions | None = None,
    stitch_runner: StitchRunner | None = None,
    resume_runner: ResumeRunner | None = None,
    ledger: InstanceLedger | None = None,
    ledger_before_already_clean: Sequence[Mapping[str, Any]] | None = None,
) -> BuiltinCommitExecution:
    """Execute accepted ``commit`` declarations through ``sase stitch create``."""

    if instance.provider_ref != _COMMIT_PROVIDER_REF:
        raise BuiltinCommitFinalizerError(
            f"commit executor received provider {instance.provider_ref!r}",
            result=failed_result(
                instance.instance_id,
                "invalid_provider",
                f"commit executor received provider {instance.provider_ref!r}",
            ),
            invoke_result=invoke_result,
        )

    artifacts = artifact_root(context.artifacts_dir)
    project_dir = resolve_finalizer_project_dir()
    # Snapshot the ledger and dirty worktree before machine-owned
    # reconciliation so auto-commits can prove accepted repos without making
    # the declaration look stale. Stitch checks use a later snapshot so they
    # still require their own markers.
    ledger_before_reconciliation = load_commit_results(artifacts)
    already_clean_ledger_before = (
        ledger_before_already_clean
        if ledger_before_already_clean is not None
        else ledger_before_reconciliation
    )
    state = prepare_commit_dirty_state(project_dir, artifacts)
    ledger_after_reconciliation = load_commit_results(artifacts)
    dirty_before_decisions = state.dirty_state
    dirty_before_reconciliation = pre_reconciliation_dirty_state(state)
    try:
        (
            envelope,
            accepted_context,
            host_records,
            accepted_deferrals_raw,
        ) = load_accepted_commit_declaration(context.artifacts_dir)
    except Exception as exc:
        if state.dirty_state.is_clean and is_missing_declaration(exc):
            raise_if_unpublished_machine_state(
                state,
                instance_id=instance.instance_id,
                invoke_result=invoke_result,
            )
            return BuiltinCommitExecution(
                invoke_result=invoke_result,
                result=success_result(
                    instance.instance_id,
                    attempts=(),
                    evidence=(),
                ),
            )
        result = failed_result(
            instance.instance_id,
            "missing_commit_declaration",
            f"commit finalizer requires a current accepted declaration: {exc}",
            attempts=[
                FinalizerAttemptWire(
                    attempt=preflight_attempt(ledger),
                    status="failed",
                    diagnostic_code="missing_commit_declaration",
                )
            ],
        )
        raise BuiltinCommitFinalizerError(
            result.diagnostics[0].message,
            result=result,
            invoke_result=invoke_result,
        ) from exc
    stitch_context = context_for_accepted_assigned_bead(context, accepted_context)

    obligation_by_id = {
        obligation.obligation_id: obligation
        for obligation in accepted_context.obligations
        if obligation.kind == "repository"
    }
    decisions = commit_decisions_for_instance(envelope, instance.instance_id)
    accepted_deferrals = accepted_deferrals_for_instance(
        accepted_deferrals_raw, instance.instance_id
    )
    current_result = invoke_result
    (
        state,
        ledger_after_reconciliation,
        dirty_before_decisions,
        (dirty_before_reconciliation),
    ) = refresh_state_for_transient_extra_dirty(
        state,
        obligation_by_id,
        project_dir=project_dir,
        artifacts=artifacts,
        ledger_after_reconciliation=ledger_after_reconciliation,
        prepare_dirty_state=prepare_commit_dirty_state,
        load_results=load_commit_results,
    )
    # Paired with `dirty_before_decisions`: later `state =
    # prepare_commit_dirty_state(...)` re-assignments in the
    # checkpoint-recovery and already-clean branches do not change
    # `dirty_before_decisions`, so they must not change this fingerprint
    # either. A lazy capture would compare HEAD with itself and disable the
    # shared-clone exemption.
    fingerprint_before_decisions = progress_fingerprint(dirty_before_decisions)
    current_repo_ids = {
        repository_decision_id(repo) for repo in state.dirty_state.repos
    }
    for repo in dirty_before_reconciliation.repos:
        repo_id = repository_decision_id(repo)
        if repo_id not in obligation_by_id and repo_id not in current_repo_ids:
            continue
        reject_stale_repository_obligation(
            repo,
            obligation_by_id,
            instance.instance_id,
            attempt=peek_attempt(ledger),
            ledger=ledger,
            fingerprints=pre_reconciliation_fingerprints(state, repo),
        )
    ordered = dirty_repos_in_context_order(
        state.dirty_state,
        decisions,
        accepted_context,
        attempt=peek_attempt(ledger),
        ledger=ledger,
    )
    attempts: list[FinalizerAttemptWire] = []
    evidence: list[FinalizerOutcomeEvidenceWire] = []
    diagnostics: Sequence[FinalizerDiagnosticWire] = ()
    attempt_id: int | None = None
    deferred_outcomes: Sequence[DeferredRepoOutcome] = ()
    runner = stitch_runner or run_stitch_create
    resume = resume_runner or run_stitch_resume
    accepted_repos = accepted_repos_from_host(
        accepted_context,
        host_records,
        instance_id=instance.instance_id,
    )
    current_by_id = {
        repository_decision_id(repo): repo for repo in state.dirty_state.repos
    }
    extra_dirty_ids = sorted(set(current_by_id) - set(obligation_by_id))
    if extra_dirty_ids:
        extra_repos = [current_by_id[repo_id] for repo_id in extra_dirty_ids]
        message_text = extra_dirty_message(extra_repos)
        raise BuiltinCommitFinalizerError(
            message_text,
            result=failed_result(
                instance.instance_id,
                "stale_commit_declaration",
                message_text,
            ),
            invoke_result=invoke_result,
        )
    checkpoint_recovery = resume_owned_pending_checkpoint(
        accepted_repos,
        decisions=decisions,
        artifacts=artifacts,
        context=stitch_context,
        instance_id=instance.instance_id,
        resume_runner=resume,
        ledger=ledger,
        current_result=current_result,
        repository_decision_id=repository_decision_id,
        peek_attempt=peek_attempt,
    )
    resumed_attempt_id = None
    if checkpoint_recovery is not None:
        resumed_attempt_id, resume_attempts, resume_evidence = checkpoint_recovery
        attempts = resume_attempts
        evidence.extend(resume_evidence)
        attempt_id = resumed_attempt_id
        state = prepare_commit_dirty_state(project_dir, artifacts)
        current_by_id = {
            repository_decision_id(repo): repo for repo in state.dirty_state.repos
        }
        ordered = dirty_repos_in_context_order(
            state.dirty_state,
            decisions,
            accepted_context,
            attempt=peek_attempt(ledger),
            ledger=ledger,
        )
    reject_unproven_reconciliation_transition(
        dirty_before_reconciliation,
        state.dirty_state,
        fingerprints_before=state.fingerprints_before,
        artifacts=artifacts,
        ledger_before=ledger_before_reconciliation,
        instance_id=instance.instance_id,
        attempt=peek_attempt(ledger),
        ledger=ledger,
        invoke_result=invoke_result,
    )

    already_clean = tuple(
        repo
        for repo in accepted_repos
        if repository_decision_id(repo) not in current_by_id
    )
    if already_clean:
        reject_discarded_dirty_work(
            DirtyState(
                project_dir=state.dirty_state.project_dir,
                repos=already_clean,
                details="accepted",
            ),
            DirtyState(
                project_dir=state.dirty_state.project_dir,
                repos=(),
                details="",
            ),
            fingerprint_before=already_clean_fingerprint_before(
                already_clean, host_records
            ),
            artifacts=artifacts,
            project_dir=project_dir,
            instance_id=instance.instance_id,
            attempts=attempts,
            evidence=evidence,
            invoke_result=current_result,
            ledger_before=already_clean_ledger_before,
        )
        (
            unpushed_attempt_id,
            resume_attempts,
            resume_evidence,
        ) = resume_unpushed_already_clean_repos(
            already_clean,
            decisions=decisions,
            artifacts=artifacts,
            context=stitch_context,
            instance_id=instance.instance_id,
            resume_runner=resume,
            ledger=ledger,
            current_result=current_result,
        )
        if resume_attempts:
            resumed_attempt_id = unpushed_attempt_id
            attempts = resume_attempts
            evidence.extend(resume_evidence)
            attempt_id = resume_attempts[0].attempt
            state = prepare_commit_dirty_state(project_dir, artifacts)
        state = prepare_commit_dirty_state(project_dir, artifacts)
        ordered = dirty_repos_in_context_order(
            state.dirty_state,
            decisions,
            accepted_context,
            attempt=peek_attempt(ledger),
            ledger=ledger,
        )

    if not accepted_repos and state.dirty_state.is_clean:
        raise_if_unpublished_machine_state(
            state,
            instance_id=instance.instance_id,
            invoke_result=invoke_result,
        )
        return BuiltinCommitExecution(
            invoke_result=invoke_result,
            result=success_result(
                instance.instance_id,
                attempts=(),
                evidence=(),
            ),
        )

    dispatched = dispatch_commit_decisions(
        ordered,
        decisions,
        state=state,
        context=stitch_context,
        instance_id=instance.instance_id,
        artifacts=artifacts,
        project_dir=project_dir,
        provider=provider,
        invoke_result=current_result,
        model_tier=model_tier,
        suppress_output=suppress_output,
        model_override=model_override,
        options=options,
        stitch_runner=runner,
        resume_runner=resume,
        ledger=ledger,
        prepare_dirty_state=prepare_commit_dirty_state,
        protected_path_resolver=resolve_protected_baseline_paths,
        unexpected_path_resolver=resolve_unexpected_remaining_paths,
        baseline_record_resolver=protected_baseline_record,
        accepted_deferrals=accepted_deferrals,
        initial_attempt_id=resumed_attempt_id,
        initial_attempts=attempts,
        initial_evidence=evidence,
        initial_diagnostics=diagnostics,
    )
    current_result = dispatched.invoke_result
    state = dispatched.state
    attempt_id = dispatched.attempt_id
    attempts = dispatched.attempts
    evidence = dispatched.evidence
    diagnostics = dispatched.diagnostics
    deferred_outcomes = dispatched.deferred

    reject_discarded_dirty_work(
        dirty_before_decisions,
        state.dirty_state,
        fingerprint_before=fingerprint_before_decisions,
        artifacts=artifacts,
        project_dir=project_dir,
        instance_id=instance.instance_id,
        attempts=attempts,
        evidence=evidence,
        invoke_result=current_result,
        ledger_before=ledger_after_reconciliation,
    )

    state = ensure_no_residual_dirt(
        state,
        deferred_outcomes,
        project_dir=project_dir,
        artifacts=artifacts,
        instance_id=instance.instance_id,
        invoke_result=current_result,
        attempts=attempts,
        evidence=evidence,
        auto_bead_sync=auto_commit_separate_sdd_store_if_possible,
        prepare_dirty_state=prepare_commit_dirty_state,
    )

    raise_if_unpublished_machine_state(
        state,
        instance_id=instance.instance_id,
        invoke_result=current_result,
        attempts=attempts,
        evidence=evidence,
    )
    if deferred_outcomes:
        assert attempt_id is not None
        attempts[0] = FinalizerAttemptWire(attempt=attempt_id, status="deferred")
        return BuiltinCommitExecution(
            invoke_result=current_result,
            result=deferred_result(
                instance.instance_id,
                deferral=merge_deferrals(deferred_outcomes),
                attempts=attempts,
                evidence=evidence,
                diagnostics=diagnostics,
            ),
        )
    if attempt_id is None:
        success_attempts: Sequence[FinalizerAttemptWire] = ()
        if ledger is not None and ledger.attempts:
            success_attempts = (
                FinalizerAttemptWire(
                    attempt=ledger.allocate_attempt(),
                    status="success",
                ),
            )
        return BuiltinCommitExecution(
            invoke_result=current_result,
            result=success_result(
                instance.instance_id,
                attempts=success_attempts,
                evidence=evidence,
                diagnostics=diagnostics,
            ),
        )
    attempts[0] = FinalizerAttemptWire(attempt=attempt_id, status="success")
    return BuiltinCommitExecution(
        invoke_result=current_result,
        result=success_result(
            instance.instance_id,
            attempts=attempts,
            evidence=evidence,
            diagnostics=diagnostics,
        ),
    )


__all__ = ["execute_commit_finalizer"]
