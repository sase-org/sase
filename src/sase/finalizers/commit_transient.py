"""Transient extra-dirty handling for the built-in commit finalizer."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.finalizers.commit_declaration import repository_decision_id
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.reconciliation import pre_reconciliation_dirty_state
from sase.llm_provider.commit_finalizer_git_status import git_head_commit_id
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState

TRANSIENT_EXTRA_RECHECK_LIMIT = 1


def _describe_extra_repo(repo: DirtyRepo) -> str:
    """Describe one unexpected dirty repo for the stale-declaration error."""

    files = ", ".join(repo.changed_files) if repo.changed_files else "no listed paths"
    return f"{repo.name} ({repo.kind}:{repo.name} at {repo.path}: {files})"


def extra_dirty_message(extra_repos: Sequence[DirtyRepo]) -> str:
    """Build the stale-declaration message for unexpected dirty repos."""

    detail = ", ".join(_describe_extra_repo(repo) for repo in extra_repos)
    return (
        "commit declaration is stale; unexpected dirty repository "
        f"obligation(s): {detail}"
    )


def _extra_dirty_repos(
    dirty_state: DirtyState,
    obligation_by_id: Mapping[str, Any],
) -> list[DirtyRepo]:
    """Return dirty repos absent from the accepted declaration."""

    current_by_id = {repository_decision_id(repo): repo for repo in dirty_state.repos}
    return [
        current_by_id[repo_id]
        for repo_id in sorted(set(current_by_id) - set(obligation_by_id))
    ]


def refresh_state_for_transient_extra_dirty(
    state: Any,
    obligation_by_id: Mapping[str, Any],
    *,
    project_dir: str,
    artifacts: Path | None,
    ledger_after_reconciliation: list[dict[str, Any]],
    prepare_dirty_state: Callable[[str, Path | None], Any],
    load_results: Callable[[Path | None], list[dict[str, Any]]],
) -> tuple[Any, list[dict[str, Any]], DirtyState, DirtyState]:
    """Recheck newly observed dirty repos after machine-owned reconciliation.

    A bead-sidecar sync/rebase can dirty a sidecar between the declaration
    and the finalizer's first scan, then clean it before the next scan. When
    the post-reconciliation state shows repos absent from the accepted
    declaration, refresh once through ``prepare_commit_dirty_state`` (which
    re-runs proven auto-commits) and continue with only the accepted
    decisions when the extra repos prove clean. Persistently dirty repos
    stay dirty and fail closed downstream with their names and paths.
    """

    if not _extra_dirty_repos(state.dirty_state, obligation_by_id):
        return (
            state,
            ledger_after_reconciliation,
            state.dirty_state,
            pre_reconciliation_dirty_state(state),
        )
    refreshed = state
    for _ in range(TRANSIENT_EXTRA_RECHECK_LIMIT):
        refreshed = prepare_dirty_state(project_dir, artifacts)
        if not _extra_dirty_repos(refreshed.dirty_state, obligation_by_id):
            break
    ledger_after = load_results(artifacts)
    return (
        refreshed,
        ledger_after,
        refreshed.dirty_state,
        pre_reconciliation_dirty_state(refreshed),
    )


def already_clean_fingerprint_before(
    already_clean: Sequence[DirtyRepo],
    host_records: Sequence[Any],
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Build declaration-time fingerprints for already-clean repos.

    The HEAD is the one recorded when the declaration context was built.
    Records written before that HEAD was stored fall back to the current
    HEAD, which is exactly today's behaviour.
    """

    head_by_id: dict[str, Any] = {}
    for record in host_records:
        obligation_id = getattr(record, "obligation_id", None)
        if isinstance(obligation_id, str):
            head_by_id[obligation_id] = getattr(record, "head", None)
    entries: list[tuple[str, str, tuple[str, ...]]] = []
    for repo in already_clean:
        head = head_by_id.get(repository_decision_id(repo))
        if not isinstance(head, str):
            head = git_head_commit_id(repo.path)
        entries.append((repo.path, head, tuple(sorted(repo.changed_files))))
    return tuple(entries)


def context_for_accepted_assigned_bead(
    context: FinalizerExecutionContext,
    accepted_context: Any,
) -> FinalizerExecutionContext:
    """Bind the accepted assigned-bead identity onto the execution context."""

    assigned_bead = getattr(accepted_context, "assigned_bead", None)
    return replace(
        context,
        assigned_bead_id=(assigned_bead.bead_id if assigned_bead is not None else None),
        assigned_bead_primary_repo_id=(
            assigned_bead.primary_repo_obligation_id
            if assigned_bead is not None
            else None
        ),
    )


__all__ = [
    "TRANSIENT_EXTRA_RECHECK_LIMIT",
    "already_clean_fingerprint_before",
    "context_for_accepted_assigned_bead",
    "extra_dirty_message",
    "refresh_state_for_transient_extra_dirty",
]
