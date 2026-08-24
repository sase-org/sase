"""Per-repository stitch dispatch for the built-in commit finalizer."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDeferralWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.commit_declaration import repository_decision_id
from sase.finalizers.commit_repair import (
    load_commit_results,
    marker_evidence,
    marker_matches_repo,
    new_commit_markers,
    record_stitch_artifacts,
    resolve_commit_conflict,
    stitch_failure_message,
)
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    ResumeRunner,
    StitchRunner,
    failed_result,
)
from sase.finalizers.commit_validation import reconcile_commit_file_hooks
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.ledger import FinalizerBudgetError, InstanceLedger
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult, LLMInvocationOptions, ModelTier
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT

PrepareDirtyState = Callable[[str, Path | None], PreparedCommitDirtyState]
ProtectedPathResolver = Callable[[Path | None, str], Sequence[str]]
UnexpectedPathResolver = Callable[[str, Sequence[str]], list[str]]


@dataclass(frozen=True)
class _DeferredRepoOutcome:
    """One repository whose accepted deferral skipped its stitch."""

    repo: DirtyRepo
    deferral: FinalizerDeferralWire


@dataclass(frozen=True)
class _CommitDispatchResult:
    """State accumulated while dispatching accepted repository decisions."""

    invoke_result: InvokeResult
    state: PreparedCommitDirtyState
    attempt_id: int | None
    attempts: list[FinalizerAttemptWire]
    evidence: list[FinalizerOutcomeEvidenceWire]
    deferred: tuple[_DeferredRepoOutcome, ...] = ()


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
    deferred: list[_DeferredRepoOutcome] = []
    current_result = invoke_result

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
        if attempt_id is None:
            try:
                attempt_id = (
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
            attempts = [FinalizerAttemptWire(attempt=attempt_id, status="failed")]

        deferral = accepted_deferrals.get(repository_decision_id(repo))
        if deferral is not None:
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
        consumed_attempt = attempt_id

        message = str(decision.get("message", "")).strip()
        protected = protected_path_resolver(artifacts, repo.path)
        before_markers = load_commit_results(artifacts)
        stitch = stitch_runner(repo, message, protected, context)
        record_stitch_artifacts(
            context,
            instance_id,
            consumed_attempt,
            stitch,
            label=repo.name,
        )
        if stitch.timed_out or stitch.stdout_truncated or stitch.stderr_truncated:
            code = "stitch_timeout" if stitch.timed_out else "stitch_output_cap"
            message_text = f"sase stitch create {code} for {repo.name}"
            attempts[0] = FinalizerAttemptWire(
                attempt=consumed_attempt,
                status="failed",
                diagnostic_code=code,
            )
            result = failed_result(
                instance_id,
                code,
                message_text,
                attempts=attempts,
                evidence=evidence,
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=result,
                invoke_result=current_result,
            )
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
    )


def merge_deferrals(
    deferred: Sequence[_DeferredRepoOutcome],
) -> FinalizerDeferralWire:
    """Combine one dispatch's deferred repositories into one wire record.

    The result wire carries a single typed reason, so a mixed-reason dispatch
    keeps the first repository's reason; every deferred path across every
    repository is still recorded, and the full per-repository detail lives in
    the ``deferred_repo`` evidence entries.
    """

    reason = deferred[0].deferral.reason
    paths: list[str] = []
    seen: set[str] = set()
    for item in deferred:
        for path in item.deferral.paths:
            if path not in seen:
                seen.add(path)
                paths.append(path)
    return FinalizerDeferralWire(reason=reason, paths=paths)


def preflight_attempt(ledger: InstanceLedger | None) -> int:
    if ledger is None:
        return 1
    return ledger.allocate_attempt()


def peek_attempt(ledger: InstanceLedger | None) -> int:
    if ledger is None:
        return 1
    return ledger.next_attempt
