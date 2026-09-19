"""Reconstruct the remaining commit work after a conflict-repair turn."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.core.finalizer_facade import (
    RemainingCommitWorkError,
    select_remaining_commit_obligations,
)
from sase.core.finalizer_wire import (
    ExecutedCommitObligationFactWire,
    FinalizerAttemptWire,
    FinalizerOutcomeEvidenceWire,
    RemainingCommitObligationFactWire,
    RemainingCommitWorkRequestWire,
)
from sase.finalizers import declaration as finalizer_declaration
from sase.finalizers.commit_declaration import (
    accepted_deferrals_for_instance,
    accepted_repos_from_host,
    commit_decisions_for_instance,
    load_accepted_commit_declaration,
    repository_decision_id,
)
from sase.finalizers.commit_dispatch_types import (
    PrepareDirtyState,
    RepairRemainingHandoff,
)
from sase.finalizers.commit_types import BuiltinCommitFinalizerError, failed_result
from sase.finalizers.executor import FinalizerExecutionContext
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult


def format_repair_handoff_failure(
    reason: str,
    *,
    landed: Sequence[tuple[str, str]],
    remaining: Sequence[DirtyRepo],
    continuation_bound: bool = False,
) -> str:
    """Describe a repair-handoff failure without implying a replay of landed work."""
    parts = [reason.rstrip(".") + "."]
    if landed:
        parts.append(
            "Already landed: "
            + ", ".join(f"{name} {sha}" for name, sha in landed)
            + "."
        )
    if remaining:
        described = []
        for repo in remaining:
            paths = ", ".join(repo.changed_files)
            described.append(f"{repo.name} ({paths})" if paths else repo.name)
        parts.append("Remaining: " + ", ".join(described) + ".")
    if continuation_bound:
        parts.append(
            "The conflict-repair continuation bound forbids another repair turn."
        )
    return " ".join(parts)


def collect_repair_remaining_handoff(
    *,
    context: FinalizerExecutionContext,
    instance_id: str,
    project_dir: str,
    artifacts: Path | None,
    prepare_dirty_state: PrepareDirtyState,
    executed: Sequence[ExecutedCommitObligationFactWire],
    landed: Sequence[tuple[str, str]],
    current_result: InvokeResult,
    attempts: Sequence[FinalizerAttemptWire],
    evidence: Sequence[FinalizerOutcomeEvidenceWire],
    declaration_loader: Any | None = None,
) -> RepairRemainingHandoff | None:
    """Load the repair declaration and select remaining host-ordered work."""
    state = prepare_dirty_state(project_dir, artifacts)
    completed_ids = {item.obligation_id for item in executed if item.completed}
    remaining_dirty = tuple(
        repo
        for repo in state.dirty_state.repos
        if repository_decision_id(repo) not in completed_ids
    )
    if not remaining_dirty:
        return None
    try:
        loader = declaration_loader or load_accepted_commit_declaration
        envelope, accepted_context, host_records, accepted_deferrals_raw = loader(
            context.artifacts_dir
        )
        if accepted_context is None:
            raise RuntimeError("accepted repair context is missing")
    except Exception as exc:
        _raise_handoff_failure(
            instance_id,
            "missing_commit_declaration",
            f"commit finalizer requires a current accepted declaration: {exc}",
            landed,
            remaining_dirty,
            attempts,
            evidence,
            current_result,
            cause=exc,
        )

    decisions = commit_decisions_for_instance(envelope, instance_id)
    accepted_deferrals = accepted_deferrals_for_instance(
        accepted_deferrals_raw, instance_id
    )
    obligation_by_id = {
        obligation.obligation_id
        for obligation in accepted_context.obligations
        if obligation.kind == "repository"
    }
    current_by_id = {repository_decision_id(repo): repo for repo in remaining_dirty}
    extra_dirty = sorted(set(current_by_id) - obligation_by_id)
    if extra_dirty:
        extra_repos = tuple(current_by_id[repo_id] for repo_id in extra_dirty)
        _raise_handoff_failure(
            instance_id,
            "stale_commit_declaration",
            "commit declaration is stale; unexpected dirty repository obligation(s): "
            + ", ".join(extra_dirty),
            landed,
            extra_repos,
            attempts,
            evidence,
            current_result,
        )

    host_by_id = {record.obligation_id: record for record in host_records}
    facts = [
        RemainingCommitObligationFactWire(
            obligation_id=obligation.obligation_id,
            kind="repository",
            current_digest=finalizer_declaration.repository_state_digest(
                obligation.obligation_id, repo, list(repo.changed_files)
            ),
            submitted_digest=obligation.digest,
            has_host_identity=(record := host_by_id.get(obligation.obligation_id))
            is not None,
            host_identity_matches=_host_identity_matches(record, repo),
            has_valid_decision=_has_valid_current_decision(
                obligation.obligation_id, decisions, accepted_deferrals
            ),
        )
        for obligation in accepted_context.obligations
        if obligation.kind == "repository"
        and (repo := current_by_id.get(obligation.obligation_id)) is not None
    ]
    request = RemainingCommitWorkRequestWire(
        current_run_id=str(context.run_id or ""),
        current_agent_id=str(context.agent_id or ""),
        current_turn_nonce=str(context.turn_nonce or ""),
        current_plan_digest=str(context.plan_digest or ""),
        declaration_run_id=accepted_context.run_id,
        declaration_agent_id=accepted_context.agent_id,
        declaration_turn_nonce=accepted_context.turn_nonce,
        declaration_plan_digest=accepted_context.plan_digest,
        current_obligations=facts,
        executed_obligations=list(executed),
    )
    try:
        outcome = select_remaining_commit_obligations(request)
    except RemainingCommitWorkError as exc:
        _raise_handoff_failure(
            instance_id,
            exc.code,
            str(exc),
            landed,
            tuple(
                current_by_id[item.obligation_id]
                for item in facts
                if item.obligation_id in current_by_id
            ),
            attempts,
            evidence,
            current_result,
            cause=exc,
        )

    remaining_repos = tuple(
        current_by_id[repo_id]
        for repo_id in outcome.obligation_ids
        if repo_id in current_by_id
    )
    if not remaining_repos:
        return None
    accepted_repos_from_host(accepted_context, host_records, instance_id=instance_id)
    assigned_bead = accepted_context.assigned_bead
    return RepairRemainingHandoff(
        repos=remaining_repos,
        decisions=decisions,
        accepted_deferrals=accepted_deferrals,
        state=state,
        context=replace(
            context,
            assigned_bead_id=assigned_bead.bead_id
            if assigned_bead is not None
            else None,
            assigned_bead_primary_repo_id=(
                assigned_bead.primary_repo_obligation_id
                if assigned_bead is not None
                else None
            ),
            run_id=accepted_context.run_id,
            agent_id=accepted_context.agent_id,
            turn_nonce=accepted_context.turn_nonce,
            plan_digest=accepted_context.plan_digest,
            context_digest=accepted_context.context_digest,
        ),
    )


def _raise_handoff_failure(
    instance_id: str,
    code: str,
    reason: str,
    landed: Sequence[tuple[str, str]],
    remaining: Sequence[DirtyRepo],
    attempts: Sequence[FinalizerAttemptWire],
    evidence: Sequence[FinalizerOutcomeEvidenceWire],
    current_result: InvokeResult,
    *,
    cause: Exception | None = None,
) -> None:
    message = format_repair_handoff_failure(reason, landed=landed, remaining=remaining)
    error = BuiltinCommitFinalizerError(
        message,
        result=failed_result(
            instance_id, code, message, attempts=attempts, evidence=evidence
        ),
        invoke_result=current_result,
    )
    if cause is not None:
        raise error from cause
    raise error


def _host_identity_matches(record: Any, repo: DirtyRepo) -> bool:
    return (
        record is not None
        and record.kind == repo.kind
        and record.name == repo.name
        and record.path == repo.path
    )


def _has_valid_current_decision(
    repo_id: str,
    decisions: Mapping[str, Mapping[str, Any]],
    accepted_deferrals: Mapping[str, Any],
) -> bool:
    if repo_id in accepted_deferrals:
        return True
    decision = decisions.get(repo_id)
    return (
        isinstance(decision, Mapping)
        and str(decision.get("action")) == "commit"
        and bool(str(decision.get("message", "")).strip())
    )
