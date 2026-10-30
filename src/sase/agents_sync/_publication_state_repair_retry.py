"""Recompute a rejected state repair after pulling the upstream change."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from sase.agents_sync.git import GitRunner
from sase.agents_sync.git_sync_ops import agents_git_error
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync._publication_state_repair_types import StateRepairReport


def retry_divergent_repair(
    target: ProjectTarget,
    git_runner: GitRunner,
    base_report: StateRepairReport,
    retry: Callable[[], StateRepairReport],
) -> StateRepairReport:
    """Drop stale work, pull upstream, and recompute the bounded repair."""

    from sase.agents_sync.git_sync_ops import (
        abort_agents_rebase,
        clean_agents_payload_worktree,
        pull_agents_rebase,
    )

    dropped = git_runner(
        target.sidecar_path,
        ["reset", "--hard", "HEAD^"],
        op="agents_state_repair.retry_drop_commit",
    )
    if dropped.returncode != 0:
        return replace(
            base_report,
            error=agents_git_error(
                "could not prepare rejected state repair for retry", dropped
            ),
        )
    # Discard stale planning caches and recompute from the new upstream:
    # the retry never replays a stale precomputed state patch.
    cleanup_error = clean_agents_payload_worktree(target.sidecar_path, git_runner)
    if cleanup_error is not None:
        return replace(base_report, error=cleanup_error)
    from sase.agents_sync.publication_planning import (
        invalidate_shared_targeted_planning,
    )

    invalidate_shared_targeted_planning(target.sidecar_path)
    invalidate_shared_targeted_planning()
    repulled = pull_agents_rebase(
        target.sidecar_path, git_runner, "agents_state_repair.retry_pull"
    )
    if repulled.returncode != 0:
        cleanup = abort_agents_rebase(target.sidecar_path, git_runner)
        return replace(
            base_report,
            error=agents_git_error("git pull --rebase retry failed", repulled, cleanup),
        )
    retry_report = retry()
    return replace(
        retry_report,
        push_attempts=retry_report.push_attempts + 1,
        diagnostics=(*base_report.diagnostics, *retry_report.diagnostics),
    )
