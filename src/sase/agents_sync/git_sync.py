"""Orchestration for synchronizing agents sidecars across projects."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
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
from sase.agents_sync.inventory import build_project_hood_inventory
from sase.agents_sync.models import (
    ExportCounts,
    IntegrationCounts,
    ProjectTarget,
    SyncOutcome,
)
from sase.agents_sync.prompt_archive.deferred import (
    restore_deferred_prompt_archives,
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
    drop_retired: bool = False,
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
                drop_terminal_agent_publications,
                list_agent_publications,
                publication_quarantine_diagnostics,
                update_agent_publications,
            )
            from sase.agents_sync.referenced_by_outbox import (
                clear_quarantined_referenced_by_requests,
                drop_terminal_referenced_by_requests,
                referenced_by_quarantine_diagnostics,
            )
            from sase.agents_sync.referenced_by_publication import (
                drain_referenced_by_requests,
            )

            if retry_quarantined:
                clear_quarantined_agent_publications(target.project_key)
                clear_quarantined_referenced_by_requests(target.project_key)
            drop_diagnostics: tuple[str, ...] = ()
            if drop_retired:
                drop_diagnostics = (
                    *_dropped_publication_diagnostics(
                        drop_terminal_agent_publications(target.project_key)
                    ),
                    *_dropped_referenced_by_diagnostics(
                        drop_terminal_referenced_by_requests(target.project_key)
                    ),
                )
            pending_publications = list_agent_publications(
                target.project_key,
                include_quarantined=False,
            )
            deferred_prompts = _DeferredPromptWork(requests=pending_publications)
            outcome = _sync_project(
                target,
                owner,
                git_runner=git_runner,
                lock_timeout_seconds=timeout,
                deferred_prompts=deferred_prompts,
            )
            if outcome.ok and outcome.skip_reason is None and pending_publications:
                prompt_failures = deferred_prompts.failures
                materialized = tuple(
                    item
                    for item in pending_publications
                    if item.logical_key not in prompt_failures
                    and _publication_request_materialized(target, item.global_agent)
                )
                if materialized:
                    acknowledge_agent_publications(
                        target.project_key,
                        (item.logical_key for item in materialized),
                    )
                for item in pending_publications:
                    if item in materialized:
                        continue
                    # A prompt archive that could not be rebuilt is a transient
                    # failure of a recoverable request, so it stays retryable
                    # instead of being retired as unpublishable.
                    prompt_error = prompt_failures.get(item.logical_key)
                    error = prompt_error or (
                        f"published agent page for {item.global_agent!r} "
                        "did not materialize during full sync"
                    )
                    update_agent_publications(
                        target.project_key,
                        (item.logical_key,),
                        error=error,
                        increment_attempts=True,
                        quarantine_threshold=configured_publication_max_attempts(),
                        terminal_reason=None if prompt_error else error,
                    )
            referenced_by_diagnostics: tuple[str, ...] = ()
            if outcome.ok and outcome.skip_reason is None:
                referenced_by_diagnostics = drain_referenced_by_requests(
                    target,
                    git_runner=git_runner,
                )
            publication_diagnostics = (
                *drop_diagnostics,
                *publication_quarantine_diagnostics(target.project_key),
                *referenced_by_diagnostics,
                *referenced_by_quarantine_diagnostics(target.project_key),
            )
            if publication_diagnostics:
                outcome = replace(
                    outcome,
                    diagnostics=(
                        *outcome.diagnostics,
                        *publication_diagnostics,
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


def _dropped_publication_diagnostics(
    dropped: Sequence[Any],
) -> tuple[str, ...]:
    """Render one line per dropped retired request, plus a count summary."""

    if not dropped:
        return ()
    plural = "" if len(dropped) == 1 else "s"
    return (
        f"dropped {len(dropped)} retired publication request{plural}",
        *(
            f"dropped retired publication request {item.global_agent}@"
            f"{item.primary_revision[:12]}: "
            f"{item.terminal_reason or item.last_error or 'unknown reason'}"
            for item in dropped
        ),
    )


def _dropped_referenced_by_diagnostics(
    dropped: Sequence[Any],
) -> tuple[str, ...]:
    """Render one line per dropped retired referenced-by request."""

    if not dropped:
        return ()
    plural = "" if len(dropped) == 1 else "s"
    return (
        f"dropped {len(dropped)} retired referenced-by request{plural}",
        *(
            f"dropped retired referenced-by request {item.global_agent}@"
            f"{item.primary_revision[:12]} -> {item.sidecar_role}:"
            f"{item.repo_relpath}: "
            f"{item.terminal_reason or item.last_error or 'unknown reason'}"
            for item in dropped
        ),
    )


def _publication_request_materialized(
    target: ProjectTarget,
    global_agent: str,
) -> bool:
    agents_root = (target.sidecar_path / "agents").resolve(strict=False)
    page = (agents_root / global_agent / "README.md").resolve(strict=False)
    return page.is_relative_to(agents_root) and page.is_file()


@dataclass(slots=True)
class _DeferredPromptWork:
    """Queued requests whose prompt archives this sync still owes.

    ``failures`` is filled in by the export pass so the caller can keep a
    request queued instead of acknowledging a publication whose prompt never
    reached the sidecar.
    """

    requests: tuple[Any, ...] = ()
    failures: dict[tuple[str, str], str] = field(default_factory=dict)


def _sync_project(
    target: ProjectTarget,
    owner: AgentOwnerIdentity | str,
    *,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float = DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS,
    deferred_prompts: _DeferredPromptWork | None = None,
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
        return _sync_project_locked(
            target,
            resolved_owner,
            git_runner,
            deferred_prompts,
        )


def _sync_project_locked(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
    deferred_prompts: _DeferredPromptWork | None = None,
) -> SyncOutcome:
    def integrate_export_pass(
        pass_target: ProjectTarget,
        repo: Path,
        pass_owner: AgentOwnerIdentity,
        pass_git_runner: GitRunner,
    ) -> tuple[IntegrationCounts, ExportCounts]:
        return _integrate_export_pass(
            pass_target,
            repo,
            pass_owner,
            pass_git_runner,
            deferred_prompts=deferred_prompts,
        )

    return sync_project_locked(
        target,
        owner,
        git_runner,
        integrate_export_pass,
    )


def _integrate_export_pass(
    target: ProjectTarget,
    repo: Path,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
    *,
    deferred_prompts: _DeferredPromptWork | None = None,
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
        inventory = build_project_hood_inventory(
            target,
            identity,
            git_runner=git_runner,
        )
        published = reconcile_agent_hoods(
            target,
            repo,
            identity=identity,
            inventory=inventory,
            git_runner=git_runner,
        )
    # A queued publication request also owns any prompt archive that was
    # deferred when the primary commit landed. This sync acknowledges the
    # request once the hood materializes, so the prompt has to be regenerated
    # here or it would be dropped with the request.
    prompt_failures = restore_deferred_prompt_archives(
        target,
        deferred_prompts.requests if deferred_prompts is not None else (),
        git_runner,
        identity=identity,
        inventory=inventory,
    )
    if deferred_prompts is not None:
        # A retry pass rebuilds the same archives, so the caller sees only the
        # failures the final pass left behind.
        deferred_prompts.failures.clear()
        deferred_prompts.failures.update(prompt_failures)
    return integrated, ExportCounts(
        diagnostics=tuple(
            dict.fromkeys(
                (
                    *integrated.diagnostics,
                    *published.diagnostics,
                    *prompt_failures.values(),
                )
            )
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
