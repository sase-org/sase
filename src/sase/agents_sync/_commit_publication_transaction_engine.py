"""Run the initial publication commit and push transaction."""

from __future__ import annotations

from sase._interruptions import PublicationDrainTimedOut
from sase.agent.names._registry import name_registry_load_session
from sase.agents_sync.git import GitRunner
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.agents_sync.publication_timing import DrainTiming
from sase.agents_sync._commit_publication_transaction_retry import (
    retry_rejected_publication,
)
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
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity


def _record_inventory_counters(
    timer: DrainTiming, inventory: ProjectHoodInventory
) -> None:
    """Record inventory size counters on the drain timer (never raises)."""

    try:
        timer.runs_scanned = len(inventory.runs)
        timer.prompt_bytes = sum(len(run.prompt_bytes or b"") for run in inventory.runs)
        timer.chat_bytes = sum(len(run.chat_bytes or b"") for run in inventory.runs)
        timer.commit_record_calls = timer.git_op_counts.get(
            "agents_sync.commit_record", 0
        )
    except PublicationDrainTimedOut:
        raise
    except Exception:  # noqa: BLE001 - timing must not fail a drain.
        return


def publish_queued_transaction(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
    requests: tuple[AgentPublicationOutboxItem, ...],
    *,
    hooks: PublicationTransactionHooks,
    timer: DrainTiming | None = None,
) -> DrainResult:
    """Publish prepared requests in one pull/commit/push transaction."""

    from sase.agents_sync import git_sync

    if not requests:
        return DrainResult()
    logical_keys = tuple(item.logical_key for item in requests)
    if timer is not None:
        with timer.record_stage("pull_rebase"):
            pulled = git_sync.pull_agents_rebase(
                target.sidecar_path, git_runner, "agents_sync.commit_publish_pull"
            )
    else:
        pulled = git_sync.pull_agents_rebase(
            target.sidecar_path, git_runner, "agents_sync.commit_publish_pull"
        )
    if pulled.returncode != 0:
        cleanup = git_sync.abort_agents_rebase(target.sidecar_path, git_runner)
        return DrainResult(
            error=git_sync.agents_git_error(
                "git pull --rebase failed", pulled, cleanup
            ),
            error_keys=logical_keys,
            failure_scope=REPOSITORY_FAILURE_SCOPE,
            failure_stage="pull_rebase",
        )

    identity = AgentIdentitySnapshot(owner)
    requested_hoods = frozenset(item.local_hood for item in requests)
    with name_registry_load_session():
        if timer is not None:
            with timer.record_stage("inventory_build"):
                inventory = hooks.build_inventory(
                    target,
                    identity,
                    git_runner=git_runner,
                    requested_hoods=requested_hoods,
                )
        else:
            inventory = hooks.build_inventory(
                target,
                identity,
                git_runner=git_runner,
                requested_hoods=requested_hoods,
            )
    if timer is not None:
        _record_inventory_counters(timer, inventory)

    if timer is not None:
        with timer.record_stage("prepare"):
            prepared, item_errors = prepare_publications(
                target,
                owner,
                requests,
                identity,
                inventory,
                git_runner,
                hooks=hooks,
                timer=timer,
            )
    else:
        prepared, item_errors = prepare_publications(
            target,
            owner,
            requests,
            identity,
            inventory,
            git_runner,
            hooks=hooks,
        )
    prepared_keys = tuple(item.logical_key for item in prepared)
    if not prepared:
        return DrainResult(item_errors=item_errors)
    if timer is not None:
        with timer.record_stage("commit"):
            commit_result = git_sync.commit_agents_payload_if_dirty(
                target.sidecar_path,
                owner,
                git_runner,
                extra_paths=("prompts", "artifacts"),
                protection_scope=protection_scope(target),
            )
    else:
        commit_result = git_sync.commit_agents_payload_if_dirty(
            target.sidecar_path,
            owner,
            git_runner,
            extra_paths=("prompts", "artifacts"),
            protection_scope=protection_scope(target),
        )
    if isinstance(commit_result, str):
        return DrainResult(
            item_errors=item_errors,
            error=commit_result,
            error_keys=prepared_keys,
            failure_scope=REPOSITORY_FAILURE_SCOPE,
            failure_stage="commit",
        )
    committed = commit_result
    should_push = (
        committed or git_sync.agents_ahead_count(target.sidecar_path, git_runner) > 0
    )
    if not should_push:
        acked_keys, gate_errors = acknowledge_completed(
            target,
            owner,
            git_runner,
            identity,
            inventory,
            prepared,
            hooks=hooks,
            timer=timer,
        )
        return DrainResult(
            drained=len(acked_keys),
            item_errors=(*item_errors, *gate_errors),
        )

    if timer is not None:
        with timer.record_stage("push"):
            pushed = git_runner(
                target.sidecar_path,
                ["push"],
                network=True,
                op="agents_sync.commit_publish_push",
            )
    else:
        pushed = git_runner(
            target.sidecar_path,
            ["push"],
            network=True,
            op="agents_sync.commit_publish_push",
        )
    if pushed.returncode == 0:
        acked_keys, gate_errors = acknowledge_completed(
            target,
            owner,
            git_runner,
            identity,
            inventory,
            prepared,
            hooks=hooks,
            timer=timer,
        )
        return DrainResult(
            drained=len(acked_keys),
            item_errors=(*item_errors, *gate_errors),
        )
    return retry_rejected_publication(
        target,
        owner,
        git_runner,
        identity,
        inventory,
        prepared,
        committed,
        pushed,
        item_errors,
        hooks=hooks,
        timer=timer,
    )
