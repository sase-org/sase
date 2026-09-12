"""Built-in ``builtin@commit`` finalizer execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDiagnosticWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.config import ConfiguredFinalizerInstance
from sase.finalizers.commit_declaration import (
    accepted_deferrals_for_instance as _accepted_deferrals_for_instance,
    accepted_repos_from_host as _accepted_repos_from_host,
    commit_decisions_for_instance as _commit_decisions_for_instance,
    dirty_repos_in_context_order as _dirty_repos_in_context_order,
    is_missing_declaration as _is_missing_declaration,
    load_accepted_commit_declaration as _load_accepted_commit_declaration,
    reject_stale_repository_obligation as _reject_stale_repository_obligation,
    repository_decision_id as _repository_decision_id,
)
from sase.finalizers.commit_dispatch import (
    dispatch_commit_decisions as _dispatch_commit_decisions,
    merge_deferrals as _merge_deferrals,
    peek_attempt as _peek_attempt,
    preflight_attempt as _preflight_attempt,
)
from sase.finalizers.commit_dispatch_types import DeferredRepoOutcome
from sase.finalizers.commit_checkpoint_recovery import (
    resume_owned_pending_checkpoint as _resume_owned_pending_checkpoint,
)
from sase.finalizers.commit_repair import (
    load_commit_results as _load_commit_results,
    marker_evidence as _marker_evidence,
    marker_is_unpushed as _marker_is_unpushed,
    marker_matches_repo as _marker_matches_repo,
    new_commit_markers as _new_commit_markers,
    record_stitch_artifacts as _record_stitch_artifacts,
    run_stitch_create,
    run_stitch_resume,
    stitch_bounds_failure_message as _stitch_bounds_failure_message,
    stitch_failure_message as _stitch_failure_message,
)
from sase.finalizers.commit_types import (
    BuiltinCommitExecution,
    BuiltinCommitFinalizerError,
    ResumeRunner,
    StitchCommandResult,
    StitchRunner,
    deferred_result as _deferred_result,
    failed_result as _failed_result,
    success_result as _success_result,
)
from sase.finalizers.commit_validation import (
    protected_baseline_paths,
    protected_baseline_record,
    raise_if_unpublished_machine_state as _raise_if_unpublished_machine_state,
    reject_discarded_dirty_work as _reject_discarded_dirty_work,
    unexpected_remaining_paths,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.ledger import FinalizerBudgetError, InstanceLedger
from sase.finalizers.reconciliation import (
    pre_reconciliation_dirty_state,
    pre_reconciliation_fingerprints,
    prepare_commit_dirty_state,
    reject_unproven_reconciliation_transition,
)
from sase.llm_provider.commit_finalizer_artifacts import artifact_root
from sase.llm_provider.commit_finalizer_baseline import FinalizerBaselineRecord
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.llm_provider.commit_finalizer_git import git_changed_files
from sase.llm_provider.commit_finalizer_prompting import failure_message
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult, LLMInvocationOptions, ModelTier

_COMMIT_PROVIDER_REF = "builtin@commit"


def _unpushed_markers_for_repo(
    markers: Sequence[Mapping[str, Any]],
    repo: DirtyRepo,
) -> list[dict[str, Any]]:
    return [
        dict(marker)
        for marker in markers
        if _marker_is_unpushed(marker) and _marker_matches_repo(marker, repo)
    ]


def _consume_unpushed_resume_attempt(
    ledger: InstanceLedger | None,
    instance_id: str,
    current_result: InvokeResult,
) -> int:
    try:
        return ledger.consume_before_execute() if ledger is not None else 1
    except FinalizerBudgetError as exc:
        raise BuiltinCommitFinalizerError(
            str(exc),
            result=_failed_result(
                instance_id,
                "attempt_budget_exhausted",
                str(exc),
                attempts=[
                    FinalizerAttemptWire(
                        attempt=_peek_attempt(ledger),
                        status="failed",
                        diagnostic_code="attempt_budget_exhausted",
                    )
                ],
            ),
            invoke_result=current_result,
        ) from exc


def _unpushed_resume_failure_message(
    repo: DirtyRepo,
    marker: Mapping[str, Any],
    result: StitchCommandResult,
) -> str:
    sha = marker.get("commit_sha")
    commit = sha[:12] if isinstance(sha, str) and sha else "HEAD"
    return (
        f"commit {commit} already exists locally for {repo.name}; "
        "sase stitch create --resume could not push it. "
        + _stitch_failure_message(repo, result)
    )


def _resume_unpushed_already_clean_repos(
    repos: Sequence[DirtyRepo],
    *,
    artifacts: Path | None,
    context: FinalizerExecutionContext,
    instance_id: str,
    resume_runner: ResumeRunner,
    ledger: InstanceLedger | None,
    current_result: InvokeResult,
) -> tuple[int | None, list[FinalizerAttemptWire], list[FinalizerOutcomeEvidenceWire]]:
    markers = _load_commit_results(artifacts)
    work = [
        (repo, repo_markers[-1])
        for repo in repos
        if (repo_markers := _unpushed_markers_for_repo(markers, repo))
    ]
    if not work:
        return (None, [], [])

    attempt_id = _consume_unpushed_resume_attempt(ledger, instance_id, current_result)
    attempts = [FinalizerAttemptWire(attempt=attempt_id, status="failed")]
    evidence: list[FinalizerOutcomeEvidenceWire] = []

    for repo, marker in work:
        evidence.append(
            FinalizerOutcomeEvidenceWire(
                kind="unpushed_commit_resume",
                value=repo.name,
            )
        )
        evidence.extend(_marker_evidence(marker))
        before_markers = _load_commit_results(artifacts)
        resumed = resume_runner(repo, context)
        _record_stitch_artifacts(
            context,
            instance_id,
            attempt_id,
            resumed,
            label=f"{repo.name}-unpushed-resume",
            inputs={
                "resume_unpushed": True,
                "repo_path": repo.path,
                "commit_sha": marker.get("commit_sha"),
                "result": marker.get("result"),
            },
        )
        if resumed.timed_out or resumed.stdout_truncated or resumed.stderr_truncated:
            code = "stitch_timeout" if resumed.timed_out else "stitch_output_cap"
            message_text = _stitch_bounds_failure_message(
                repo,
                resumed,
                code,
                artifacts=artifacts,
                resume=True,
            )
            attempts[0] = FinalizerAttemptWire(
                attempt=attempt_id,
                status="failed",
                diagnostic_code=code,
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=_failed_result(
                    instance_id,
                    code,
                    message_text,
                    attempts=attempts,
                    evidence=evidence,
                ),
                invoke_result=current_result,
            )
        if resumed.returncode != 0:
            message_text = _unpushed_resume_failure_message(repo, marker, resumed)
            attempts[0] = FinalizerAttemptWire(
                attempt=attempt_id,
                status="failed",
                diagnostic_code="stitch_failed",
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=_failed_result(
                    instance_id,
                    "stitch_failed",
                    message_text,
                    attempts=attempts,
                    evidence=evidence,
                ),
                invoke_result=current_result,
            )
        resumed_markers = [
            item
            for item in _new_commit_markers(
                before_markers,
                _load_commit_results(artifacts),
            )
            if _marker_matches_repo(item, repo)
        ]
        if resumed_markers:
            evidence.extend(_marker_evidence(resumed_markers[-1]))
        else:
            latest = _latest_marker_for_repo(_load_commit_results(artifacts), repo)
            if latest is not None:
                evidence.extend(_marker_evidence(latest))

    attempts[0] = FinalizerAttemptWire(attempt=attempt_id, status="success")
    return (attempt_id, attempts, evidence)


def _latest_marker_for_repo(
    markers: Sequence[Mapping[str, Any]],
    repo: DirtyRepo,
) -> Mapping[str, Any] | None:
    for marker in reversed(markers):
        if _marker_matches_repo(marker, repo):
            return marker
    return None


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
            result=_failed_result(
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
    ledger_before_reconciliation = _load_commit_results(artifacts)
    already_clean_ledger_before = (
        ledger_before_already_clean
        if ledger_before_already_clean is not None
        else ledger_before_reconciliation
    )
    state = prepare_commit_dirty_state(project_dir, artifacts)
    ledger_after_reconciliation = _load_commit_results(artifacts)
    dirty_before_decisions = state.dirty_state
    dirty_before_reconciliation = pre_reconciliation_dirty_state(state)
    try:
        (
            envelope,
            accepted_context,
            host_records,
            accepted_deferrals_raw,
        ) = _load_accepted_commit_declaration(context.artifacts_dir)
    except Exception as exc:
        if state.dirty_state.is_clean and _is_missing_declaration(exc):
            _raise_if_unpublished_machine_state(
                state,
                instance_id=instance.instance_id,
                invoke_result=invoke_result,
            )
            return BuiltinCommitExecution(
                invoke_result=invoke_result,
                result=_success_result(
                    instance.instance_id,
                    attempts=(),
                    evidence=(),
                ),
            )
        result = _failed_result(
            instance.instance_id,
            "missing_commit_declaration",
            f"commit finalizer requires a current accepted declaration: {exc}",
            attempts=[
                FinalizerAttemptWire(
                    attempt=_preflight_attempt(ledger),
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

    obligation_by_id = {
        obligation.obligation_id: obligation
        for obligation in accepted_context.obligations
        if obligation.kind == "repository"
    }
    decisions = _commit_decisions_for_instance(envelope, instance.instance_id)
    accepted_deferrals = _accepted_deferrals_for_instance(
        accepted_deferrals_raw, instance.instance_id
    )
    current_result = invoke_result
    for repo in dirty_before_reconciliation.repos:
        _reject_stale_repository_obligation(
            repo,
            obligation_by_id,
            instance.instance_id,
            attempt=_peek_attempt(ledger),
            ledger=ledger,
            fingerprints=pre_reconciliation_fingerprints(state, repo),
        )
    ordered = _dirty_repos_in_context_order(
        state.dirty_state,
        decisions,
        accepted_context,
        attempt=_peek_attempt(ledger),
        ledger=ledger,
    )
    attempts: list[FinalizerAttemptWire] = []
    evidence: list[FinalizerOutcomeEvidenceWire] = []
    diagnostics: Sequence[FinalizerDiagnosticWire] = ()
    attempt_id: int | None = None
    deferred_outcomes: Sequence[DeferredRepoOutcome] = ()
    runner = stitch_runner or run_stitch_create
    resume = resume_runner or run_stitch_resume
    accepted_repos = _accepted_repos_from_host(
        accepted_context,
        host_records,
        instance_id=instance.instance_id,
    )
    current_by_id = {
        _repository_decision_id(repo): repo for repo in state.dirty_state.repos
    }
    extra_dirty = sorted(set(current_by_id) - set(obligation_by_id))
    if extra_dirty:
        raise BuiltinCommitFinalizerError(
            "commit declaration is stale; unexpected dirty repository "
            "obligation(s): " + ", ".join(extra_dirty),
            result=_failed_result(
                instance.instance_id,
                "stale_commit_declaration",
                "commit declaration is stale; unexpected dirty repository "
                "obligation(s): " + ", ".join(extra_dirty),
            ),
            invoke_result=invoke_result,
        )
    checkpoint_recovery = _resume_owned_pending_checkpoint(
        accepted_repos,
        decisions=decisions,
        artifacts=artifacts,
        context=context,
        instance_id=instance.instance_id,
        resume_runner=resume,
        ledger=ledger,
        current_result=current_result,
        repository_decision_id=_repository_decision_id,
        peek_attempt=_peek_attempt,
    )
    resumed_attempt_id = None
    if checkpoint_recovery is not None:
        resumed_attempt_id, resume_attempts, resume_evidence = checkpoint_recovery
        attempts = resume_attempts
        evidence.extend(resume_evidence)
        attempt_id = resumed_attempt_id
        state = prepare_commit_dirty_state(project_dir, artifacts)
        current_by_id = {
            _repository_decision_id(repo): repo for repo in state.dirty_state.repos
        }
        ordered = _dirty_repos_in_context_order(
            state.dirty_state,
            decisions,
            accepted_context,
            attempt=_peek_attempt(ledger),
            ledger=ledger,
        )
    reject_unproven_reconciliation_transition(
        dirty_before_reconciliation,
        state.dirty_state,
        fingerprints_before=state.fingerprints_before,
        artifacts=artifacts,
        ledger_before=ledger_before_reconciliation,
        instance_id=instance.instance_id,
        attempt=_peek_attempt(ledger),
        ledger=ledger,
        invoke_result=invoke_result,
    )

    already_clean = tuple(
        repo
        for repo in accepted_repos
        if _repository_decision_id(repo) not in current_by_id
    )
    if already_clean:
        _reject_discarded_dirty_work(
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
        ) = _resume_unpushed_already_clean_repos(
            already_clean,
            artifacts=artifacts,
            context=context,
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
        ordered = _dirty_repos_in_context_order(
            state.dirty_state,
            decisions,
            accepted_context,
            attempt=_peek_attempt(ledger),
            ledger=ledger,
        )

    if not accepted_repos and state.dirty_state.is_clean:
        _raise_if_unpublished_machine_state(
            state,
            instance_id=instance.instance_id,
            invoke_result=invoke_result,
        )
        return BuiltinCommitExecution(
            invoke_result=invoke_result,
            result=_success_result(
                instance.instance_id,
                attempts=(),
                evidence=(),
            ),
        )

    dispatched = _dispatch_commit_decisions(
        ordered,
        decisions,
        state=state,
        context=context,
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
        protected_path_resolver=_protected_baseline_paths,
        unexpected_path_resolver=_unexpected_remaining_paths,
        baseline_record_resolver=_protected_baseline_record,
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

    _reject_discarded_dirty_work(
        dirty_before_decisions,
        state.dirty_state,
        artifacts=artifacts,
        project_dir=project_dir,
        instance_id=instance.instance_id,
        attempts=attempts,
        evidence=evidence,
        invoke_result=current_result,
        ledger_before=ledger_after_reconciliation,
    )

    deferred_repo_ids = {
        _repository_decision_id(item.repo) for item in deferred_outcomes
    }
    residual_repos = tuple(
        repo
        for repo in state.dirty_state.repos
        if _repository_decision_id(repo) not in deferred_repo_ids
    )
    if residual_repos:
        message_text = failure_message(
            DirtyState(
                project_dir=state.dirty_state.project_dir,
                repos=residual_repos,
                details=state.dirty_state.details,
            ),
            max_passes=1,
            no_progress_passes=0,
        )
        result = _failed_result(
            instance.instance_id,
            "dirty_after_commit_decisions",
            message_text,
            attempts=attempts,
            evidence=evidence,
        )
        raise BuiltinCommitFinalizerError(
            message_text,
            result=result,
            invoke_result=current_result,
        )

    _raise_if_unpublished_machine_state(
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
            result=_deferred_result(
                instance.instance_id,
                deferral=_merge_deferrals(deferred_outcomes),
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
            result=_success_result(
                instance.instance_id,
                attempts=success_attempts,
                evidence=evidence,
                diagnostics=diagnostics,
            ),
        )
    attempts[0] = FinalizerAttemptWire(attempt=attempt_id, status="success")
    return BuiltinCommitExecution(
        invoke_result=current_result,
        result=_success_result(
            instance.instance_id,
            attempts=attempts,
            evidence=evidence,
            diagnostics=diagnostics,
        ),
    )


def _protected_baseline_paths(
    artifacts: Path | None, repo_path: str
) -> tuple[str, ...]:
    return protected_baseline_paths(
        artifacts,
        repo_path,
        get_changed_files=git_changed_files,
    )


def _unexpected_remaining_paths(repo_path: str, protected: Sequence[str]) -> list[str]:
    return unexpected_remaining_paths(
        repo_path,
        protected,
        get_changed_files=git_changed_files,
    )


def _protected_baseline_record(
    artifacts: Path | None, repo_path: str
) -> FinalizerBaselineRecord | None:
    return protected_baseline_record(artifacts, repo_path)


__all__ = [
    "BuiltinCommitExecution",
    "BuiltinCommitFinalizerError",
    "StitchCommandResult",
    "execute_commit_finalizer",
    "run_stitch_create",
    "run_stitch_resume",
]
