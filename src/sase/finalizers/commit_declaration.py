"""Accepted-declaration helpers for the built-in commit finalizer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.core.finalizer_facade import validate_finalizer_submission
from sase.core.finalizer_wire import FinalizerAttemptWire, FinalizerContextWire
from sase.finalizers import declaration as finalizer_declaration
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    failed_result as _failed_result,
)
from sase.finalizers.ledger import InstanceLedger
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState


def commit_decisions_for_instance(
    envelope: Mapping[str, Any],
    instance_id: str,
) -> dict[str, Mapping[str, Any]]:
    payloads = envelope.get("payloads")
    if not isinstance(payloads, list):
        return {}
    for item in payloads:
        if not isinstance(item, Mapping) or item.get("instance_id") != instance_id:
            continue
        payload = item.get("payload")
        if not isinstance(payload, Mapping):
            return {}
        repositories = payload.get("repositories")
        if not isinstance(repositories, list):
            return {}
        decisions: dict[str, Mapping[str, Any]] = {}
        for decision in repositories:
            if not isinstance(decision, Mapping):
                continue
            repo_id = decision.get("repo_id")
            if isinstance(repo_id, str):
                decisions[repo_id] = decision
        return decisions
    return {}


def is_missing_declaration(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    return code in {"missing_final_submission", "missing_final_context"}


def load_accepted_commit_declaration(
    artifacts_dir: str | None,
) -> tuple[
    dict[str, Any],
    FinalizerContextWire,
    tuple[finalizer_declaration.HostRepositoryRecord, ...],
]:
    root = finalizer_declaration.require_artifacts_dir(
        artifacts_dir,
        "finalizer declaration load",
    )
    with finalizer_declaration.hold_finalizer_declaration_lock(root):
        plan = finalizer_declaration.load_finalizer_plan(root)
        latest = finalizer_declaration.load_latest_finalizer_context(root)
        submission = finalizer_declaration.load_latest_finalizer_submission(root)
        context = finalizer_declaration.accepted_context_from_submission(
            submission,
            fallback=latest,
        )
        envelope = finalizer_declaration.normalize_submission_envelope(
            submission["submission"]
        )
        validate_finalizer_submission(plan, context, envelope)
        finalizer_declaration.validate_provider_payloads(plan, context, envelope)
        host_records = finalizer_declaration.load_accepted_host_repositories(root)
        return envelope, context, host_records


def accepted_repos_from_host(
    accepted_context: FinalizerContextWire,
    host_records: Sequence[finalizer_declaration.HostRepositoryRecord],
    *,
    instance_id: str,
) -> tuple[DirtyRepo, ...]:
    host_by_id = {record.obligation_id: record for record in host_records}
    repos: list[DirtyRepo] = []
    for obligation in accepted_context.obligations:
        if obligation.kind != "repository":
            continue
        record = host_by_id.get(obligation.obligation_id)
        if record is None:
            raise BuiltinCommitFinalizerError(
                "commit declaration is stale; missing host identity for "
                f"repository obligation {obligation.obligation_id}",
                result=_failed_result(
                    instance_id,
                    "stale_commit_declaration",
                    "commit declaration is stale; missing host identity for "
                    f"repository obligation {obligation.obligation_id}",
                ),
            )
        repos.append(
            DirtyRepo(
                name=record.name,
                path=record.path,
                changed_files=tuple(obligation.paths),
                kind=record.kind,  # type: ignore[arg-type]
            )
        )
    return tuple(repos)


def dirty_repos_in_context_order(
    dirty_state: DirtyState,
    decisions: Mapping[str, Mapping[str, Any]],
    accepted_context: FinalizerContextWire,
    *,
    attempt: int = 1,
    ledger: InstanceLedger | None = None,
) -> list[DirtyRepo]:
    repos_by_id = {repository_decision_id(repo): repo for repo in dirty_state.repos}
    ordered: list[DirtyRepo] = []
    for obligation in accepted_context.obligations:
        if obligation.kind != "repository":
            continue
        repo_id = obligation.obligation_id
        if repo_id not in decisions:
            raise BuiltinCommitFinalizerError(
                "commit declaration is stale; missing decision(s): " + repo_id,
                result=_failed_result(
                    "commit",
                    "stale_commit_declaration",
                    "commit declaration is stale; missing decision(s): " + repo_id,
                ),
            )
        repo = repos_by_id.get(repo_id)
        if repo is not None:
            ordered.append(repo)
    missing = sorted(set(repos_by_id) - set(decisions))
    if missing:
        if ledger is not None:
            attempt = ledger.allocate_attempt()
        raise BuiltinCommitFinalizerError(
            "commit declaration is stale; missing decision(s): " + ", ".join(missing),
            result=_failed_result(
                "commit",
                "stale_commit_declaration",
                "commit declaration is stale; missing decision(s): "
                + ", ".join(missing),
                attempts=[
                    FinalizerAttemptWire(
                        attempt=attempt,
                        status="failed",
                        diagnostic_code="stale_commit_declaration",
                    )
                ],
            ),
        )
    return ordered


def repository_decision_id(repo: DirtyRepo) -> str:
    return finalizer_declaration.repository_obligation_id(repo)


def reject_stale_repository_obligation(
    repo: DirtyRepo,
    obligation_by_id: Mapping[str, Any],
    instance_id: str,
    *,
    attempt: int = 1,
    ledger: InstanceLedger | None = None,
) -> None:
    repo_id = repository_decision_id(repo)
    obligation = obligation_by_id.get(repo_id)
    if obligation is None:
        if ledger is not None:
            attempt = ledger.allocate_attempt()
        raise BuiltinCommitFinalizerError(
            f"commit declaration is stale; repository {repo.name} is not in "
            "the accepted context",
            result=_failed_result(
                instance_id,
                "stale_commit_declaration",
                f"commit declaration is stale; repository {repo.name} is not "
                "in the accepted context",
                attempts=[
                    FinalizerAttemptWire(
                        attempt=attempt,
                        status="failed",
                        diagnostic_code="stale_commit_declaration",
                    )
                ],
            ),
        )
    expected = getattr(obligation, "digest", None)
    if not isinstance(expected, str) or not expected:
        return
    current = finalizer_declaration.repository_state_digest(
        repo_id,
        repo,
        list(repo.changed_files),
    )
    if current != expected:
        if ledger is not None:
            attempt = ledger.allocate_attempt()
        raise BuiltinCommitFinalizerError(
            f"commit declaration is stale; repository {repo.name} changed after submit",
            result=_failed_result(
                instance_id,
                "stale_commit_declaration",
                f"commit declaration is stale; repository {repo.name} changed "
                "after submit",
                attempts=[
                    FinalizerAttemptWire(
                        attempt=attempt,
                        status="failed",
                        diagnostic_code="stale_commit_declaration",
                    )
                ],
            ),
        )
