"""Validation and continuation helpers for commit dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import inspect
from pathlib import Path
from typing import Any, cast

from sase.core.finalizer_wire import (
    ExecutedCommitObligationFactWire,
    FinalizerAttemptWire,
    FinalizerDeferralWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.commit_declaration import repository_decision_id
from sase.finalizers.commit_dispatch_followup import (
    collect_repair_remaining_handoff,
    format_repair_handoff_failure,
)
from sase.finalizers.commit_dispatch_types import (
    PrepareDirtyState,
    ProtectedPathResolver,
    UnexpectedPathResolver,
)
from sase.finalizers.commit_repair import (
    load_latest_stitch_attempt,
    stitch_failure_message,
)
from sase.finalizers.commit_types import StitchCommandResult, StitchRunner
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult


def protected_paths_for_decision(
    repo: DirtyRepo,
    decision: Mapping[str, Any],
    deferral: FinalizerDeferralWire | None,
    *,
    artifacts: Path | None,
    protected_path_resolver: ProtectedPathResolver,
) -> tuple[str, Sequence[str]]:
    """Return the accepted action and protected paths for one repository."""
    action = str(decision.get("action"))
    if deferral is not None:
        return action, ()
    return action, protected_path_resolver(artifacts, repo.path)


def identical_attempt_message(
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
    instance_id: str,
    fingerprint: str,
) -> str | None:
    """Explain why retrying an unchanged failed stitch is not useful."""
    prior_attempt = load_latest_stitch_attempt(context, instance_id, repo.name)
    if prior_attempt is None or prior_attempt.inputs.get("fingerprint") != fingerprint:
        return None
    reason = stitch_failure_message(
        repo,
        StitchCommandResult(
            returncode=1,
            stdout=prior_attempt.stdout,
            stderr=prior_attempt.stderr,
        ),
    )
    return (
        f"sase stitch create for {repo.name} was not retried: attempt "
        f"{prior_attempt.attempt}'s inputs -- repo HEAD, dirty-path fingerprints, "
        "exclude set, and message digest -- are unchanged, so a retry is "
        f"guaranteed to fail identically. {reason}"
    )


def record_executed_repo(
    repo: DirtyRepo,
    repo_id: str,
    *,
    repo_markers: Sequence[Mapping[str, Any]],
    executed_ids: set[str],
    executed_facts: list[ExecutedCommitObligationFactWire],
    landed: list[tuple[str, str]],
) -> None:
    """Record that one declared repository obligation has been handled."""
    executed_ids.add(repo_id)
    sha: str | None = None
    if repo_markers:
        raw = repo_markers[-1].get("commit_sha")
        if isinstance(raw, str) and raw:
            sha = raw
            landed.append((repo.name, sha))
    executed_facts.append(
        ExecutedCommitObligationFactWire(
            obligation_id=repo_id,
            completed=True,
            commit_sha=sha,
        )
    )


def apply_repair_remaining_handoff(
    *,
    pending: list[DirtyRepo],
    index: int,
    sweep_used: bool,
    executed_ids: set[str],
    executed_facts: Sequence[ExecutedCommitObligationFactWire],
    landed: Sequence[tuple[str, str]],
    active_decisions: dict[str, Mapping[str, Any]],
    active_deferrals: dict[str, FinalizerDeferralWire],
    context: FinalizerExecutionContext,
    instance_id: str,
    project_dir: str,
    artifacts: Path | None,
    prepare_dirty_state: PrepareDirtyState,
    current_result: InvokeResult,
    attempts: Sequence[FinalizerAttemptWire],
    evidence: list[FinalizerOutcomeEvidenceWire],
    state: PreparedCommitDirtyState,
    declaration_loader: Callable[..., Any],
) -> tuple[
    list[DirtyRepo],
    int,
    bool,
    dict[str, Mapping[str, Any]],
    dict[str, FinalizerDeferralWire],
    FinalizerExecutionContext,
    PreparedCommitDirtyState,
]:
    """Adopt at most one fresh declaration submitted during conflict repair."""
    handoff = collect_repair_remaining_handoff(
        context=context,
        instance_id=instance_id,
        project_dir=project_dir,
        artifacts=artifacts,
        prepare_dirty_state=prepare_dirty_state,
        executed=executed_facts,
        landed=landed,
        current_result=current_result,
        attempts=attempts,
        evidence=evidence,
        declaration_loader=declaration_loader,
    )
    if handoff is None:
        return (
            pending,
            index,
            sweep_used,
            active_decisions,
            active_deferrals,
            context,
            state,
        )
    evidence.append(
        FinalizerOutcomeEvidenceWire(
            kind="repair_handoff_declaration",
            value=str(
                handoff.context.context_digest or handoff.context.plan_digest or ""
            ),
        )
    )
    rest = [
        repo
        for repo in handoff.repos
        if repository_decision_id(repo) not in executed_ids
    ]
    if sweep_used:
        pending_ids = {repository_decision_id(repo) for repo in pending[index:]}
        extra = [
            repo for repo in rest if repository_decision_id(repo) not in pending_ids
        ]
        if extra:
            message_text = format_repair_handoff_failure(
                "conflict repair introduced further remaining obligations after the continuation sweep",
                landed=landed,
                remaining=extra,
                continuation_bound=True,
            )
            from sase.finalizers.commit_types import (
                BuiltinCommitFinalizerError,
                failed_result,
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
        return (
            pending,
            index,
            sweep_used,
            dict(handoff.decisions),
            dict(handoff.accepted_deferrals),
            handoff.context,
            handoff.state,
        )
    return (
        pending[:index] + rest,
        index,
        True,
        dict(handoff.decisions),
        dict(handoff.accepted_deferrals),
        handoff.context,
        handoff.state,
    )


def decision_bead_action(decision: Mapping[str, Any]) -> str | None:
    value = decision.get("bead_action")
    return value if value in {"close", "keep"} else None


def context_assigned_bead_id(context: FinalizerExecutionContext) -> str | None:
    value = getattr(context, "assigned_bead_id", None)
    return value.strip() if isinstance(value, str) and value.strip() else None


def call_stitch_runner(
    stitch_runner: StitchRunner,
    repo: DirtyRepo,
    message: str,
    protected: Sequence[str],
    context: FinalizerExecutionContext,
    *,
    bead_action: str | None,
) -> StitchCommandResult:
    if _callable_accepts_keyword(stitch_runner, "bead_action"):
        return cast(Callable[..., StitchCommandResult], stitch_runner)(
            repo,
            message,
            protected,
            context,
            bead_action=bead_action,
        )
    return stitch_runner(repo, message, protected, context)


def _callable_accepts_keyword(fn: Callable[..., Any], name: str) -> bool:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    return any(
        param.kind is inspect.Parameter.VAR_KEYWORD
        or (
            param.name == name
            and param.kind
            in {inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
        )
        for param in signature.parameters.values()
    )
