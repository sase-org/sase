"""Recover a rejected publication push and make one bounded retry."""

from __future__ import annotations

import subprocess

from sase.agents_sync.git import GitRunner
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.agents_sync.publication_planning import invalidate_shared_targeted_planning
from sase.agents_sync.publication_timing import DrainTiming
from sase.agents_sync._commit_publication_transaction_steps import (
    acknowledge_completed,
    prepare_publications,
    protection_scope,
)
from sase.agents_sync._commit_publication_transaction_types import (
    DrainResult,
    PublicationTransactionHooks,
    REPOSITORY_FAILURE_SCOPE,
)
from sase.agents_sync.publication_diverged_replay import (
    PUBLICATION_REBASE_FAILURE_STAGE,
    pull_agents_rebase_with_recovery,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity


def _affected_request_identities(
    keys: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    """Render outbox logical keys as ledger-safe request identities."""

    return tuple(f"{global_agent}@{revision}" for global_agent, revision in keys)


def retry_rejected_publication(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
    identity: AgentIdentitySnapshot,
    inventory: ProjectHoodInventory,
    prepared: tuple[AgentPublicationOutboxItem, ...],
    committed: bool,
    commit_parent: str,
    pushed: subprocess.CompletedProcess[str],
    item_errors: tuple[str, ...],
    *,
    hooks: PublicationTransactionHooks,
    timer: DrainTiming | None = None,
) -> DrainResult:
    from sase.agents_sync import git_sync

    from sase.agents_sync.publication_recovery import (
        RECOVERY_REBUILD_CLEAN,
        RECOVERY_RETRY_DIVERGENCE,
        REJECTED_REPOSITORY_RULE,
        REJECTED_SECRET_SCAN,
        recover_publication_push,
        sanitized_push_error,
    )

    prepared_keys = tuple(item.logical_key for item in prepared)
    push_recovery = recover_publication_push(
        target.sidecar_path,
        git_runner,
        project_key=target.project_key,
        repository_identity=target.remote_url,
        returncode=pushed.returncode,
        stdout=pushed.stdout or "",
        stderr=pushed.stderr or "",
        affected_requests=_affected_request_identities(prepared_keys),
    )
    if push_recovery.action == RECOVERY_REBUILD_CLEAN:
        # Secret-scanning recovery already reset the managed clone to the
        # fetched upstream tip and blocked the offending bytes. Rebuild from
        # sources without dropping another commit; protection state keeps
        # the blocked bytes out of the retry.
        already_reset = True
    elif push_recovery.action != RECOVERY_RETRY_DIVERGENCE or not (
        git_sync.is_agents_non_fast_forward(pushed)
    ):
        if push_recovery.rejection.classification in (
            REJECTED_SECRET_SCAN,
            REJECTED_REPOSITORY_RULE,
        ):
            push_message = sanitized_push_error(
                "git push failed",
                push_recovery.rejection,
                blocked_paths=push_recovery.blocked_paths,
            )
        else:
            push_message = git_sync.agents_git_error("git push failed", pushed)
        if committed:
            drop_error = _drop_unacknowledged_pass_commit(
                target,
                git_runner,
                commit_parent,
                op_prefix="agents_sync.commit_publish_drop_failed_push",
            )
            if drop_error is not None:
                push_message = f"{push_message}; {drop_error}"
        if timer is not None and (not committed or drop_error is None):
            timer.pass_commit_parent = None
        return DrainResult(
            item_errors=item_errors,
            error=push_message,
            error_keys=prepared_keys,
            failure_scope=REPOSITORY_FAILURE_SCOPE,
            failure_stage="push",
        )
    else:
        already_reset = False

    if committed and not already_reset:
        drop_error = _drop_unacknowledged_pass_commit(
            target,
            git_runner,
            commit_parent,
            op_prefix="agents_sync.commit_publish_retry_drop",
        )
        if drop_error is not None:
            return DrainResult(
                item_errors=item_errors,
                error=f"could not prepare rejected publication for retry: {drop_error}",
                error_keys=prepared_keys,
                failure_scope=REPOSITORY_FAILURE_SCOPE,
                failure_stage="push",
            )
    if timer is not None:
        timer.pass_commit_parent = None
    cleanup_error = git_sync.clean_publication_worktree(
        target.sidecar_path,
        git_runner,
    )
    if cleanup_error is not None:
        return DrainResult(
            item_errors=item_errors,
            error=cleanup_error,
            error_keys=prepared_keys,
            failure_scope=REPOSITORY_FAILURE_SCOPE,
            failure_stage="cleanup",
        )
    pull_result = pull_agents_rebase_with_recovery(
        target.sidecar_path,
        git_runner,
        "agents_sync.commit_publish_retry_pull",
        project_key=target.project_key,
    )
    repulled = pull_result.process
    if repulled.returncode != 0:
        cleanup = (
            None
            if pull_result.failure_stage == PUBLICATION_REBASE_FAILURE_STAGE
            else git_sync.abort_agents_rebase(target.sidecar_path, git_runner)
        )
        return DrainResult(
            item_errors=item_errors,
            error=git_sync.agents_git_error(
                "git pull --rebase retry failed", repulled, cleanup
            ),
            error_keys=prepared_keys,
            failure_scope=REPOSITORY_FAILURE_SCOPE,
            failure_stage=pull_result.failure_stage or "pull_rebase",
        )
    # Upstream may have changed: rebuild shared indexes from fresh upstream
    # plus the local selected snapshots instead of reusing stale validation.
    invalidate_shared_targeted_planning(target.sidecar_path)
    if timer is not None:
        with timer.record_stage("retry_prepare"):
            retry_prepared, retry_errors, withheld_runs, withheld_hoods = (
                prepare_publications(
                    target,
                    owner,
                    prepared,
                    identity,
                    inventory,
                    git_runner,
                    hooks=hooks,
                    timer=timer,
                )
            )
    else:
        retry_prepared, retry_errors, withheld_runs, withheld_hoods = (
            prepare_publications(
                target,
                owner,
                prepared,
                identity,
                inventory,
                git_runner,
                hooks=hooks,
            )
        )
    all_item_errors = (*item_errors, *retry_errors)
    retry_keys = tuple(item.logical_key for item in retry_prepared)
    if not retry_prepared:
        return DrainResult(item_errors=all_item_errors)
    retry_parent = git_runner(
        target.sidecar_path,
        ["rev-parse", "HEAD"],
        op="agents_sync.commit_publish_retry_parent",
    )
    if retry_parent.returncode != 0 or not retry_parent.stdout.strip():
        return DrainResult(
            item_errors=all_item_errors,
            error=git_sync.agents_git_error(
                "could not identify retry publication commit parent", retry_parent
            ),
            error_keys=retry_keys,
            failure_scope=REPOSITORY_FAILURE_SCOPE,
            failure_stage="retry_commit",
        )
    if timer is not None:
        timer.pass_commit_parent = retry_parent.stdout.strip()
    if timer is not None:
        with timer.record_stage("retry_commit"):
            retry_commit = git_sync.commit_agents_payload_if_dirty(
                target.sidecar_path,
                owner,
                git_runner,
                extra_paths=("prompts", "artifacts"),
                protection_scope=protection_scope(target),
            )
    else:
        retry_commit = git_sync.commit_agents_payload_if_dirty(
            target.sidecar_path,
            owner,
            git_runner,
            extra_paths=("prompts", "artifacts"),
            protection_scope=protection_scope(target),
        )
    if isinstance(retry_commit, str):
        return DrainResult(
            item_errors=all_item_errors,
            error=retry_commit,
            error_keys=retry_keys,
            failure_scope=REPOSITORY_FAILURE_SCOPE,
            failure_stage="retry_commit",
        )
    retry_committed = retry_commit
    if timer is not None:
        with timer.record_stage("retry_push"):
            retry_push = git_runner(
                target.sidecar_path,
                ["push"],
                network=True,
                op="agents_sync.commit_publish_retry_push",
            )
    else:
        retry_push = git_runner(
            target.sidecar_path,
            ["push"],
            network=True,
            op="agents_sync.commit_publish_retry_push",
        )
    if retry_push.returncode != 0:
        # A second failure is classified once more (recording any newly
        # attributed blocks) and then stops; pushes stay bounded at two.
        from sase.agents_sync.publication_recovery import (
            REJECTED_REPOSITORY_RULE,
            REJECTED_SECRET_SCAN,
            recover_publication_push,
            sanitized_push_error,
        )

        second = recover_publication_push(
            target.sidecar_path,
            git_runner,
            project_key=target.project_key,
            repository_identity=target.remote_url,
            returncode=retry_push.returncode,
            stdout=retry_push.stdout or "",
            stderr=retry_push.stderr or "",
            affected_requests=_affected_request_identities(retry_keys),
        )
        retry_drop_error: str | None = None
        if second.rejection.classification in (
            REJECTED_SECRET_SCAN,
            REJECTED_REPOSITORY_RULE,
        ):
            prior_blocked = (
                push_recovery.blocked_paths
                if push_recovery.action == RECOVERY_REBUILD_CLEAN
                else ()
            )
            retry_message = sanitized_push_error(
                "git push retry failed",
                second.rejection,
                blocked_paths=tuple(
                    dict.fromkeys((*prior_blocked, *second.blocked_paths))
                ),
            )
        else:
            retry_message = git_sync.agents_git_error(
                "git push retry failed", retry_push
            )
            if retry_committed:
                retry_drop_error = _drop_unacknowledged_pass_commit(
                    target,
                    git_runner,
                    retry_parent.stdout.strip(),
                    op_prefix="agents_sync.commit_publish_retry_drop_failed_push",
                )
                if retry_drop_error is not None:
                    retry_message = f"{retry_message}; {retry_drop_error}"
        if timer is not None and (not retry_committed or retry_drop_error is None):
            timer.pass_commit_parent = None
        return DrainResult(
            item_errors=all_item_errors,
            error=retry_message,
            error_keys=retry_keys,
            failure_scope=REPOSITORY_FAILURE_SCOPE,
            failure_stage="retry_push",
        )
    if timer is not None:
        timer.pass_commit_parent = None
    acked_retry_keys, gate_errors, parked_keys, newly_parked_keys, newly_details = (
        acknowledge_completed(
            target,
            owner,
            git_runner,
            identity,
            inventory,
            retry_prepared,
            hooks=hooks,
            timer=timer,
            withheld_runs=withheld_runs,
            withheld_hoods=withheld_hoods,
        )
    )
    from sase.agents_sync._commit_publication_transaction_engine import (
        park_notice_error,
    )

    return DrainResult(
        drained=len(acked_retry_keys),
        item_errors=(
            *all_item_errors,
            *gate_errors,
            *(park_notice_error(newly_details) or ()),
        ),
        parked_keys=parked_keys,
        newly_parked_keys=newly_parked_keys,
    )


def _drop_unacknowledged_pass_commit(
    target: ProjectTarget,
    git_runner: GitRunner,
    expected_parent: str,
    *,
    op_prefix: str,
) -> str | None:
    from sase.agents_sync import git_sync

    error = git_sync.drop_unacknowledged_agents_commit(
        target.sidecar_path,
        expected_parent,
        git_runner,
        op_prefix=op_prefix,
    )
    if error is not None:
        return error
    return git_sync.clean_publication_worktree(target.sidecar_path, git_runner)
