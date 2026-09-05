"""Single-project pull/integrate/export/commit/push transaction."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.agents_sync.git import GitRunner
from sase.agents_sync.git_sync_ops import (
    abort_agents_rebase,
    agents_ahead_count,
    agents_git_error,
    clean_agents_payload_worktree,
    commit_agents_payload_if_dirty,
    is_agents_non_fast_forward,
    pull_agents_rebase,
)
from sase.agents_sync.models import (
    ExportCounts,
    ProjectTarget,
    SyncOutcome,
)
from sase.agents_sync.prompt_archive.git_ops import clean_prompt_archive_worktree
from sase.core.agent_identity_facade import AgentOwnerIdentity

_PROMPT_ARCHIVE_PATHS = ("prompts", "artifacts")

IntegrateExportPass = Callable[
    [ProjectTarget, Path, AgentOwnerIdentity, GitRunner],
    ExportCounts,
]


def sync_project_locked(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
    integrate_export_pass: IntegrateExportPass,
) -> SyncOutcome:
    repo = target.sidecar_path
    cleanup_error = _clean_sync_worktree(repo, git_runner)
    if cleanup_error is not None:
        return _error(target, cleanup_error)
    outcome: SyncOutcome
    try:
        outcome = _sync_project_transaction(
            target,
            owner,
            git_runner,
            integrate_export_pass,
        )
    finally:
        cleanup_error = _clean_sync_worktree(repo, git_runner)
    return _error(target, cleanup_error) if cleanup_error is not None else outcome


def _clean_sync_worktree(repo: Path, git_runner: GitRunner) -> str | None:
    """Restore both the payload and the regenerable prompt archive to ``HEAD``.

    The export pass rebuilds prompt archives owed by queued publication
    requests, so this transaction owns those paths for the same reasons it owns
    the agents payload: everything under them is regenerated from the local
    artifact pool on every pass.
    """

    return clean_agents_payload_worktree(repo, git_runner) or (
        clean_prompt_archive_worktree(repo, git_runner)
    )


def _sync_project_transaction(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
    integrate_export_pass: IntegrateExportPass,
) -> SyncOutcome:
    repo = target.sidecar_path
    pulled = pull_agents_rebase(repo, git_runner, "agents_sync.pull")
    if pulled.returncode != 0:
        cleanup = abort_agents_rebase(repo, git_runner)
        return _error(
            target,
            agents_git_error("git pull --rebase failed", pulled, cleanup),
        )

    try:
        exported = integrate_export_pass(target, repo, owner, git_runner)
    except Exception as exc:  # noqa: BLE001 - project-scoped publication error
        return _error(target, str(exc), pulled=True)

    committed_result = commit_agents_payload_if_dirty(
        repo,
        owner,
        git_runner,
        extra_paths=_PROMPT_ARCHIVE_PATHS,
    )
    if isinstance(committed_result, str):
        return _error(target, committed_result, pulled=True)
    committed = committed_result
    should_push = committed or agents_ahead_count(repo, git_runner) > 0
    if not should_push:
        return SyncOutcome(
            target.project_key,
            target.project,
            pulled=True,
            exported=exported.exported,
            export_refreshed=exported.refreshed,
            hoods_published=exported.hoods_published,
            hoods_refreshed=exported.hoods_refreshed,
            hoods_unchanged=exported.hoods_unchanged,
            families_published=exported.families_published,
            runs_published=exported.runs_published,
            committed=False,
            diagnostics=exported.diagnostics,
        )

    pushed = git_runner(
        repo,
        ["push"],
        network=True,
        op="agents_sync.push",
    )
    if pushed.returncode == 0:
        return SyncOutcome(
            target.project_key,
            target.project,
            pulled=True,
            exported=exported.exported,
            export_refreshed=exported.refreshed,
            hoods_published=exported.hoods_published,
            hoods_refreshed=exported.hoods_refreshed,
            hoods_unchanged=exported.hoods_unchanged,
            families_published=exported.families_published,
            runs_published=exported.runs_published,
            committed=committed,
            pushed=True,
            push_attempts=1,
            diagnostics=exported.diagnostics,
        )
    if not is_agents_non_fast_forward(pushed):
        return _error(
            target,
            agents_git_error("git push failed", pushed),
            pulled=True,
            exported=exported.exported,
            export_refreshed=exported.refreshed,
            hoods_published=exported.hoods_published,
            hoods_refreshed=exported.hoods_refreshed,
            hoods_unchanged=exported.hoods_unchanged,
            families_published=exported.families_published,
            runs_published=exported.runs_published,
            committed=committed,
            push_attempts=1,
            diagnostics=exported.diagnostics,
        )

    if committed:
        dropped = git_runner(
            repo,
            ["reset", "--hard", "HEAD^"],
            op="agents_sync.retry_drop_commit",
        )
        if dropped.returncode != 0:
            return _error(
                target,
                agents_git_error(
                    "could not prepare rejected sync commit for retry", dropped
                ),
                pulled=True,
                push_attempts=1,
            )

    cleanup_error = _clean_sync_worktree(repo, git_runner)
    if cleanup_error is not None:
        return _error(
            target,
            cleanup_error,
            pulled=True,
            push_attempts=1,
        )
    repulled = pull_agents_rebase(repo, git_runner, "agents_sync.retry_pull")
    if repulled.returncode != 0:
        cleanup = abort_agents_rebase(repo, git_runner)
        return _error(
            target,
            agents_git_error("git pull --rebase retry failed", repulled, cleanup),
            pulled=True,
            push_attempts=1,
        )
    try:
        retry_exported = integrate_export_pass(target, repo, owner, git_runner)
    except Exception as exc:  # noqa: BLE001 - project-scoped retry error
        return _error(
            target,
            f"sync recompute after push rejection failed: {exc}",
            pulled=True,
            push_attempts=1,
        )
    retry_commit_result = commit_agents_payload_if_dirty(
        repo,
        owner,
        git_runner,
        extra_paths=_PROMPT_ARCHIVE_PATHS,
    )
    if isinstance(retry_commit_result, str):
        return _error(
            target,
            retry_commit_result,
            pulled=True,
            push_attempts=1,
        )
    retry_committed = retry_commit_result
    retry_push = git_runner(
        repo,
        ["push"],
        network=True,
        op="agents_sync.retry_push",
    )
    all_diagnostics = tuple(
        dict.fromkeys((*exported.diagnostics, *retry_exported.diagnostics))
    )
    if retry_push.returncode != 0:
        return _error(
            target,
            agents_git_error("git push retry failed", retry_push),
            pulled=True,
            exported=max(exported.exported, retry_exported.exported),
            export_refreshed=max(exported.refreshed, retry_exported.refreshed),
            hoods_published=max(
                exported.hoods_published, retry_exported.hoods_published
            ),
            hoods_refreshed=max(
                exported.hoods_refreshed, retry_exported.hoods_refreshed
            ),
            hoods_unchanged=max(
                exported.hoods_unchanged, retry_exported.hoods_unchanged
            ),
            families_published=max(
                exported.families_published,
                retry_exported.families_published,
            ),
            runs_published=max(exported.runs_published, retry_exported.runs_published),
            committed=retry_committed,
            push_attempts=2,
            diagnostics=all_diagnostics,
        )
    return SyncOutcome(
        target.project_key,
        target.project,
        pulled=True,
        exported=max(exported.exported, retry_exported.exported),
        export_refreshed=max(exported.refreshed, retry_exported.refreshed),
        hoods_published=max(exported.hoods_published, retry_exported.hoods_published),
        hoods_refreshed=max(exported.hoods_refreshed, retry_exported.hoods_refreshed),
        hoods_unchanged=max(exported.hoods_unchanged, retry_exported.hoods_unchanged),
        families_published=max(
            exported.families_published, retry_exported.families_published
        ),
        runs_published=max(exported.runs_published, retry_exported.runs_published),
        committed=retry_committed,
        pushed=True,
        push_attempts=2,
        diagnostics=all_diagnostics,
    )


def _error(target: ProjectTarget, error: str, **kwargs: Any) -> SyncOutcome:
    return SyncOutcome(target.project_key, target.project, error=error, **kwargs)


__all__ = ["IntegrateExportPass", "sync_project_locked"]
