"""Sidecar transaction for draining queued agent publications."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sase._interruptions import PublicationDrainTimedOut
from sase.agent.names._registry import name_registry_load_session
from sase.agents_sync.git import GitRunner
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.deferred import (
    prepare_deferred_prompt_archive,
    prompt_runs_by_request,
)
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.agents_sync.publication_timing import DrainTiming
from sase.agents_sync.v2_io import read_owner_manifest
from sase.agents_sync.v2_models import V2ProjectIdentity
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)


@dataclass(frozen=True, slots=True)
class DrainResult:
    drained: int = 0
    item_errors: tuple[str, ...] = ()
    error: str | None = None
    error_keys: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class PublicationTransactionHooks:
    """Facade-owned operations used by the extracted transaction engine."""

    build_inventory: Callable[..., ProjectHoodInventory]
    publish_hood: Callable[..., object]
    update_publications: Callable[..., object]
    acknowledge_publications: Callable[..., object]
    configured_max_attempts: Callable[[], int]


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
        )

    identity = AgentIdentitySnapshot(owner)
    with name_registry_load_session():
        if timer is not None:
            with timer.record_stage("inventory_build"):
                inventory = hooks.build_inventory(
                    target,
                    identity,
                    git_runner=git_runner,
                )
        else:
            inventory = hooks.build_inventory(
                target,
                identity,
                git_runner=git_runner,
            )
    if timer is not None:
        _record_inventory_counters(timer, inventory)

    if timer is not None:
        with timer.record_stage("prepare"):
            prepared, item_errors = _prepare_publications(
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
        prepared, item_errors = _prepare_publications(
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
            )
    else:
        commit_result = git_sync.commit_agents_payload_if_dirty(
            target.sidecar_path,
            owner,
            git_runner,
            extra_paths=("prompts", "artifacts"),
        )
    if isinstance(commit_result, str):
        return DrainResult(
            item_errors=item_errors,
            error=commit_result,
            error_keys=prepared_keys,
        )
    committed = commit_result
    should_push = (
        committed or git_sync.agents_ahead_count(target.sidecar_path, git_runner) > 0
    )
    if not should_push:
        if timer is not None:
            with timer.record_stage("verify"):
                hooks.acknowledge_publications(target.project_key, prepared_keys)
        else:
            hooks.acknowledge_publications(target.project_key, prepared_keys)
        return DrainResult(drained=len(prepared), item_errors=item_errors)

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
        if timer is not None:
            with timer.record_stage("verify"):
                hooks.acknowledge_publications(target.project_key, prepared_keys)
        else:
            hooks.acknowledge_publications(target.project_key, prepared_keys)
        return DrainResult(drained=len(prepared), item_errors=item_errors)
    if not git_sync.is_agents_non_fast_forward(pushed):
        return DrainResult(
            item_errors=item_errors,
            error=git_sync.agents_git_error("git push failed", pushed),
            error_keys=prepared_keys,
        )

    if committed:
        dropped = git_runner(
            target.sidecar_path,
            ["reset", "--hard", "HEAD^"],
            op="agents_sync.commit_publish_retry_drop",
        )
        if dropped.returncode != 0:
            return DrainResult(
                item_errors=item_errors,
                error=git_sync.agents_git_error(
                    "could not prepare rejected publication for retry", dropped
                ),
                error_keys=prepared_keys,
            )
    cleanup_error = git_sync.clean_publication_worktree(
        target.sidecar_path,
        git_runner,
    )
    if cleanup_error is not None:
        return DrainResult(
            item_errors=item_errors,
            error=cleanup_error,
            error_keys=prepared_keys,
        )
    repulled = git_sync.pull_agents_rebase(
        target.sidecar_path, git_runner, "agents_sync.commit_publish_retry_pull"
    )
    if repulled.returncode != 0:
        cleanup = git_sync.abort_agents_rebase(target.sidecar_path, git_runner)
        return DrainResult(
            item_errors=item_errors,
            error=git_sync.agents_git_error(
                "git pull --rebase retry failed", repulled, cleanup
            ),
            error_keys=prepared_keys,
        )
    if timer is not None:
        with timer.record_stage("retry_prepare"):
            retry_prepared, retry_errors = _prepare_publications(
                target,
                owner,
                prepared,
                identity,
                inventory,
                git_runner,
                hooks=hooks,
                timer=timer,
            )
    else:
        retry_prepared, retry_errors = _prepare_publications(
            target,
            owner,
            prepared,
            identity,
            inventory,
            git_runner,
            hooks=hooks,
        )
    all_item_errors = (*item_errors, *retry_errors)
    retry_keys = tuple(item.logical_key for item in retry_prepared)
    if not retry_prepared:
        return DrainResult(item_errors=all_item_errors)
    if timer is not None:
        with timer.record_stage("retry_commit"):
            retry_commit = git_sync.commit_agents_payload_if_dirty(
                target.sidecar_path,
                owner,
                git_runner,
                extra_paths=("prompts", "artifacts"),
            )
    else:
        retry_commit = git_sync.commit_agents_payload_if_dirty(
            target.sidecar_path,
            owner,
            git_runner,
            extra_paths=("prompts", "artifacts"),
        )
    if isinstance(retry_commit, str):
        return DrainResult(
            item_errors=all_item_errors,
            error=retry_commit,
            error_keys=retry_keys,
        )
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
        return DrainResult(
            item_errors=all_item_errors,
            error=git_sync.agents_git_error("git push retry failed", retry_push),
            error_keys=retry_keys,
        )
    if timer is not None:
        with timer.record_stage("verify"):
            hooks.acknowledge_publications(target.project_key, retry_keys)
    else:
        hooks.acknowledge_publications(target.project_key, retry_keys)
    return DrainResult(
        drained=len(retry_prepared),
        item_errors=all_item_errors,
    )


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


def _prepare_publications(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    requests: tuple[AgentPublicationOutboxItem, ...],
    identity: AgentIdentitySnapshot,
    inventory: ProjectHoodInventory,
    git_runner: GitRunner,
    *,
    hooks: PublicationTransactionHooks,
    timer: DrainTiming | None = None,
) -> tuple[tuple[AgentPublicationOutboxItem, ...], tuple[str, ...]]:
    repo = target.sidecar_path
    requests_by_hood: dict[str, list[AgentPublicationOutboxItem]] = {}
    prepared: list[AgentPublicationOutboxItem] = []
    errors: list[str] = []
    prompt_runs = prompt_runs_by_request(inventory, identity)
    for request in requests:
        requests_by_hood.setdefault(request.local_hood, []).append(request)

    published_by_hood: dict[str, list[AgentPublicationOutboxItem]] = {}
    for hood_requests in requests_by_hood.values():
        request = hood_requests[0]
        try:
            if timer is not None:
                with timer.record_stage(f"hood_publish:{request.local_hood}"):
                    hooks.publish_hood(
                        target,
                        repo,
                        request.local_agent,
                        identity=identity,
                        inventory=inventory,
                        git_runner=git_runner,
                    )
            else:
                hooks.publish_hood(
                    target,
                    repo,
                    request.local_agent,
                    identity=identity,
                    inventory=inventory,
                    git_runner=git_runner,
                )
            if timer is not None:
                with timer.record_stage("prompt_archive_prepare"):
                    for hood_request in hood_requests:
                        prepare_deferred_prompt_archive(
                            target,
                            hood_request,
                            git_runner,
                            prompt_runs=prompt_runs,
                        )
            else:
                for hood_request in hood_requests:
                    prepare_deferred_prompt_archive(
                        target,
                        hood_request,
                        git_runner,
                        prompt_runs=prompt_runs,
                    )
            published_by_hood[request.local_hood] = hood_requests
        except PublicationDrainTimedOut:
            raise
        except Exception as exc:  # noqa: BLE001 - durable auxiliary boundary
            error = f"could not publish agent hood {request.local_hood!r}: {exc}"
            hooks.update_publications(
                target.project_key,
                (item.logical_key for item in hood_requests),
                error=error,
                increment_attempts=True,
                quarantine_threshold=hooks.configured_max_attempts(),
                terminal_reason=error
                if isinstance(exc, AgentsSyncFormatError)
                else None,
            )
            errors.append(error)

    if timer is not None:
        timer.stage = "manifest_verify"
    try:
        if timer is not None:
            with timer.record_stage("manifest_verify"):
                entries = (
                    read_owner_manifest(
                        repo,
                        owner,
                        V2ProjectIdentity(target.project_key, target.project),
                    ).by_hood()
                    if published_by_hood
                    else {}
                )
        else:
            entries = (
                read_owner_manifest(
                    repo,
                    owner,
                    V2ProjectIdentity(target.project_key, target.project),
                ).by_hood()
                if published_by_hood
                else {}
            )
    except PublicationDrainTimedOut:
        raise
    except Exception as exc:  # noqa: BLE001 - durable auxiliary boundary
        for hood, hood_requests in published_by_hood.items():
            error = f"could not publish agent hood {hood!r}: {exc}"
            hooks.update_publications(
                target.project_key,
                (item.logical_key for item in hood_requests),
                error=error,
                increment_attempts=True,
                quarantine_threshold=hooks.configured_max_attempts(),
            )
            errors.append(error)
        return (), tuple(errors)
    for hood, hood_requests in published_by_hood.items():
        request = hood_requests[0]
        try:
            entry = entries.get(hood)
            if entry is None:
                raise RuntimeError(f"published hood {hood!r} is absent from manifest")
            hooks.update_publications(
                target.project_key,
                (item.logical_key for item in hood_requests),
                hood_digest=entry.digest,
                error=None,
            )
            prepared.extend(hood_requests)
        except PublicationDrainTimedOut:
            raise
        except Exception as exc:  # noqa: BLE001 - durable auxiliary boundary
            error = f"could not publish agent hood {request.local_hood!r}: {exc}"
            hooks.update_publications(
                target.project_key,
                (item.logical_key for item in hood_requests),
                error=error,
                increment_attempts=True,
                quarantine_threshold=hooks.configured_max_attempts(),
            )
            errors.append(error)
    prepared_keys = {item.logical_key for item in prepared}
    return (
        tuple(item for item in requests if item.logical_key in prepared_keys),
        tuple(errors),
    )
