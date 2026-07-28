"""Orchestration for synchronizing agents sidecars across projects."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.agent.names._registry import name_registry_load_session
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.git_sync_ops import (
    DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS,
    abort_agents_rebase,
    agents_ahead_count,
    agents_git_dir,
    agents_git_error,
    bounded_agents_lock,
    clean_agents_payload_worktree,
    coerce_owner as _coerce_owner,
    commit_agents_payload_if_dirty,
    configured_agents_lock_timeout,
    ensure_agents_clone,
    is_agents_non_fast_forward,
    pull_agents_rebase,
)
from sase.agents_sync.git_sync_transaction import sync_project_locked
from sase.agents_sync.incoming_integration import (
    integrate_agent_imports_with_receipts,
)
from sase.agents_sync.models import (
    ExportCounts,
    IntegrationCounts,
    ProjectTarget,
    SyncOutcome,
)
from sase.agents_sync.publication import reconcile_agent_hoods
from sase.agents_sync.targets import resolve_sync_targets
from sase.config import require_agent_owner_identity
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)


def sync_agents(
    projects: Sequence[str] = (),
    *,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
    retry_quarantined: bool = False,
) -> tuple[SyncOutcome, ...]:
    """Synchronize every selected project without cross-project fail-fast."""

    selection = resolve_sync_targets(projects)
    outcomes = list(selection.outcomes)
    try:
        owner = require_agent_owner_identity()
    except (RuntimeError, ValueError) as exc:
        outcomes.extend(
            SyncOutcome(
                target.project_key,
                target.project,
                error=f"owner identity is not configured: {exc}",
            )
            for target in selection.targets
        )
        return tuple(sorted(outcomes, key=lambda item: item.project_key))

    timeout = (
        configured_agents_lock_timeout()
        if lock_timeout_seconds is None
        else max(lock_timeout_seconds, 0.0)
    )
    for target in selection.targets:
        pending_publications: tuple[Any, ...] = ()
        try:
            from sase.agents_sync.publication_outbox import (
                acknowledge_agent_publications,
                clear_quarantined_agent_publications,
                configured_publication_max_attempts,
                list_agent_publications,
                publication_quarantine_diagnostics,
                update_agent_publications,
            )

            if retry_quarantined:
                clear_quarantined_agent_publications(target.project_key)
            pending_publications = list_agent_publications(
                target.project_key,
                include_quarantined=False,
            )
            outcome = _sync_project(
                target,
                owner,
                git_runner=git_runner,
                lock_timeout_seconds=timeout,
            )
            if outcome.ok and outcome.skip_reason is None and pending_publications:
                materialized = tuple(
                    item
                    for item in pending_publications
                    if _publication_request_materialized(target, item.global_agent)
                )
                if materialized:
                    acknowledge_agent_publications(
                        target.project_key,
                        (item.logical_key for item in materialized),
                    )
                for item in pending_publications:
                    if item in materialized:
                        continue
                    update_agent_publications(
                        target.project_key,
                        (item.logical_key,),
                        error=(
                            f"published agent page for {item.global_agent!r} "
                            "did not materialize during full sync"
                        ),
                        increment_attempts=True,
                        quarantine_threshold=configured_publication_max_attempts(),
                    )
            quarantine_diagnostics = publication_quarantine_diagnostics(
                target.project_key
            )
            if quarantine_diagnostics:
                outcome = replace(
                    outcome,
                    diagnostics=(
                        *outcome.diagnostics,
                        *quarantine_diagnostics,
                    ),
                )
            outcomes.append(outcome)
        except Exception as exc:  # noqa: BLE001 - per-project isolation contract
            outcomes.append(
                SyncOutcome(
                    target.project_key,
                    target.project,
                    error=f"agents sync failed: {exc}",
                )
            )

    result = tuple(sorted(outcomes, key=lambda item: item.project_key))
    try:
        from sase.agents_sync.status import rewrite_agents_sync_status_after_sync

        rewrite_agents_sync_status_after_sync(projects)
    except Exception:
        # A cache write must never turn an already-complete sync into failure.
        pass
    return result


def _publication_request_materialized(
    target: ProjectTarget,
    global_agent: str,
) -> bool:
    agents_root = (target.sidecar_path / "agents").resolve(strict=False)
    page = (agents_root / global_agent / "README.md").resolve(strict=False)
    return page.is_relative_to(agents_root) and page.is_file()


def _sync_project(
    target: ProjectTarget,
    owner: AgentOwnerIdentity | str,
    *,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float = DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS,
) -> SyncOutcome:
    """Run one project's bounded mutation transaction."""

    resolved_owner = _coerce_owner(owner)

    if not target.primary_checkout.is_dir():
        return _error(target, "primary checkout does not exist")
    clone_error = ensure_agents_clone(
        target,
        git_runner=git_runner,
        lock_timeout_seconds=lock_timeout_seconds,
    )
    if clone_error is not None:
        if clone_error == "agents sync clone lock is busy":
            return _skip(target, clone_error)
        return _error(target, clone_error)

    lock_path = (
        agents_git_dir(target.sidecar_path, git_runner) / "sase-agents-sync.lock"
    )
    with bounded_agents_lock(lock_path, lock_timeout_seconds) as acquired:
        if not acquired:
            return _skip(target, "agents sync lock is busy")
        return _sync_project_locked(target, resolved_owner, git_runner)


def _sync_project_locked(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
) -> SyncOutcome:
    return sync_project_locked(
        target,
        owner,
        git_runner,
        _integrate_export_pass,
    )


def _integrate_export_pass(
    target: ProjectTarget,
    repo: Path,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
) -> tuple[IntegrationCounts, ExportCounts]:
    identity = AgentIdentitySnapshot(owner)
    # Import recovery can claim many historical names. Keep one registry
    # snapshot alive across the pass instead of rebuilding the artifact-backed
    # registry for every recovered transaction.
    with name_registry_load_session():
        integrated = integrate_agent_imports_with_receipts(
            target,
            repo,
            owner,
            git_runner=git_runner,
        )
        published = reconcile_agent_hoods(
            target,
            repo,
            identity=identity,
            git_runner=git_runner,
        )
    return integrated, ExportCounts(
        diagnostics=tuple(
            dict.fromkeys((*integrated.diagnostics, *published.diagnostics))
        ),
        hoods_published=published.hoods_published,
        hoods_refreshed=published.hoods_refreshed,
        hoods_unchanged=published.hoods_unchanged,
        families_published=published.families_published,
        runs_published=published.runs_published,
    )


def _error(target: ProjectTarget, error: str, **kwargs: Any) -> SyncOutcome:
    return SyncOutcome(target.project_key, target.project, error=error, **kwargs)


def _skip(target: ProjectTarget, reason: str) -> SyncOutcome:
    return SyncOutcome(target.project_key, target.project, skip_reason=reason)


__all__ = [
    "DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS",
    "abort_agents_rebase",
    "agents_ahead_count",
    "agents_git_dir",
    "agents_git_error",
    "bounded_agents_lock",
    "clean_agents_payload_worktree",
    "commit_agents_payload_if_dirty",
    "configured_agents_lock_timeout",
    "ensure_agents_clone",
    "is_agents_non_fast_forward",
    "pull_agents_rebase",
    "sync_agents",
]
