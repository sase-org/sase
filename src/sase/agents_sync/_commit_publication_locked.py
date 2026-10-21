"""Run the selected publication transaction while holding the sidecar lock."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.agents_sync._commit_publication_outbox import active_agent_publications
from sase.agents_sync._commit_publication_types import REPOSITORY_FAILURE_SCOPE
from sase.agents_sync.commit_publication_transaction import (
    DrainResult,
    PublicationTransactionHooks,
    publish_queued_transaction,
)
from sase.core.agent_publication_recovery import (
    PublicationDrainSelection,
    select_publication_drain,
)
from sase.agents_sync.git import GitRunner
from sase.agents_sync.inventory import build_project_hood_inventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication import publish_agent_hood
from sase.agents_sync.publication_outbox import (
    acknowledge_agent_publications,
    configured_publication_max_attempts,
    update_agent_publications,
)
from sase.agents_sync.publication_timing import DrainTiming
from sase.core.agent_identity_facade import AgentOwnerIdentity

DEFAULT_COMMIT_DRAIN_BATCH_LIMIT = 25


def _counting_git_runner(base: GitRunner, timer: DrainTiming) -> GitRunner:
    """Wrap a git runner to count per-op subprocesses on the drain timer."""

    def _run(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "agents_sync.git",
    ) -> subprocess.CompletedProcess[str]:
        timer.git_op_counts[op] = timer.git_op_counts.get(op, 0) + 1
        return base(cwd, args, network=network, op=op)

    return _run


def publish_queued_locked(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
    timer: DrainTiming | None = None,
    preferred_key: tuple[str, str] | None = None,
    selected_keys: tuple[tuple[str, str], ...] | None = None,
) -> DrainResult:
    from sase.agents_sync import git_sync

    requests = active_agent_publications(target.project_key)
    if selected_keys is not None:
        selected = frozenset(selected_keys)
        requests = tuple(item for item in requests if item.logical_key in selected)
    if timer is not None:
        timer.active_requests = len(requests)
        timer.distinct_hoods = len({request.local_hood for request in requests})
    if not requests:
        return DrainResult()
    rows = tuple(
        {
            "global_agent": item.global_agent,
            "primary_revision": item.primary_revision,
            "terminal": item.terminal,
            "quarantined": item.quarantined,
            "last_error": item.last_error,
            "terminal_reason": item.terminal_reason,
            "created_at": item.created_at,
        }
        for item in requests
    )
    if selected_keys is None:
        selection: PublicationDrainSelection | None
        try:
            selection = select_publication_drain(
                rows,
                limit=DEFAULT_COMMIT_DRAIN_BATCH_LIMIT,
                preferred_key=(
                    {
                        "global_agent": preferred_key[0],
                        "primary_revision": preferred_key[1],
                    }
                    if preferred_key is not None
                    else None
                ),
            )
        except Exception:
            selection = None
        if selection is not None:
            selected = frozenset(
                item.logical_key for item in (*selection.active, *selection.revive)
            )
            if not selected:
                return DrainResult()
            requests = tuple(item for item in requests if item.logical_key in selected)
            if not requests:
                return DrainResult()
    elif not requests:
        return DrainResult()
    logical_keys = tuple(item.logical_key for item in requests)
    if timer is not None:
        timer.active_keys = logical_keys
    runner = (
        _counting_git_runner(git_runner, timer) if timer is not None else git_runner
    )
    if timer is not None:
        with timer.record_stage("payload_clean"):
            cleanup_error = git_sync.clean_publication_worktree(
                target.sidecar_path,
                runner,
            )
    else:
        cleanup_error = git_sync.clean_publication_worktree(
            target.sidecar_path,
            runner,
        )
    if cleanup_error is not None:
        return DrainResult(
            error=cleanup_error,
            error_keys=logical_keys,
            failure_scope=REPOSITORY_FAILURE_SCOPE,
            failure_stage="payload_clean",
        )
    result: DrainResult
    try:
        result = publish_queued_transaction(
            target,
            owner,
            runner,
            requests,
            hooks=PublicationTransactionHooks(
                build_inventory=build_project_hood_inventory,
                publish_hood=publish_agent_hood,
                update_publications=update_agent_publications,
                acknowledge_publications=acknowledge_agent_publications,
                configured_max_attempts=configured_publication_max_attempts,
            ),
            timer=timer,
        )
    except BaseException as exc:
        try:
            if timer is not None:
                with timer.record_stage("cleanup"):
                    cleanup_error = git_sync.clean_publication_worktree(
                        target.sidecar_path, runner
                    )
            else:
                cleanup_error = git_sync.clean_publication_worktree(
                    target.sidecar_path, runner
                )
        except BaseException as cleanup_exc:
            cleanup_error = (
                f"cleanup raised {type(cleanup_exc).__name__}: {cleanup_exc}"
            )
        if cleanup_error is not None:
            exc.add_note(f"publication cleanup also failed: {cleanup_error}")
        raise
    else:
        if timer is not None:
            with timer.record_stage("cleanup"):
                cleanup_error = git_sync.clean_publication_worktree(
                    target.sidecar_path, runner
                )
        else:
            cleanup_error = git_sync.clean_publication_worktree(
                target.sidecar_path, runner
            )
    if cleanup_error is None:
        return result
    if result.error is not None:
        return DrainResult(
            drained=result.drained,
            item_errors=result.item_errors,
            error=(f"{result.error}; publication cleanup also failed: {cleanup_error}"),
            error_keys=result.error_keys or logical_keys,
            failure_scope=result.failure_scope or REPOSITORY_FAILURE_SCOPE,
            failure_stage=result.failure_stage or "cleanup",
        )
    # A cleanup failure after a successful acknowledged push must not resurrect
    # or falsely charge completed rows: completed keys are already gone, so
    # report the cleanup as repository evidence with no chargeable keys.
    return DrainResult(
        drained=result.drained,
        item_errors=result.item_errors,
        error=cleanup_error,
        error_keys=(),
        failure_scope=REPOSITORY_FAILURE_SCOPE,
        failure_stage="cleanup",
    )
