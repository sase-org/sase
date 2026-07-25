"""Checkpoint-friendly targeted publication after a primary commit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.agent.names._registry import name_registry_load_session
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.incoming_integration import (
    integrate_agent_imports_with_receipts,
)
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.inventory import (
    ProjectHoodInventory,
    build_project_hood_inventory,
)
from sase.agents_sync.publication import publish_agent_hood
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    acknowledge_agent_publications,
    configured_publication_max_attempts,
    enqueue_agent_publication,
    list_agent_publications,
    update_agent_publications,
)
from sase.agents_sync.targets import resolve_sync_targets
from sase.agents_sync.v2_io import read_owner_manifest
from sase.agents_sync.v2_models import V2ProjectIdentity
from sase.config import require_agent_owner_identity
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    agent_local_hood,
    globalize_owned_agent_name,
    normalize_agent_archive_name,
    normalize_owned_agent_name,
)


@dataclass(frozen=True, slots=True)
class _CommitPublicationOutcome:
    published: bool = False
    queued: bool = False
    drained: int = 0
    skip_reason: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _DrainResult:
    drained: int = 0
    item_errors: tuple[str, ...] = ()
    error: str | None = None
    error_keys: tuple[tuple[str, str], ...] = ()


def publish_committed_agent_hood(
    local_agent: str,
    primary_revision: str,
    *,
    project: str | None = None,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> _CommitPublicationOutcome:
    """Publish this commit's exact hood and drain older project requests."""

    selector = project or _current_project()
    if not selector:
        return _CommitPublicationOutcome(skip_reason="current project is unavailable")
    selection = resolve_sync_targets((selector,))
    if len(selection.targets) != 1:
        outcome = selection.outcomes[0] if selection.outcomes else None
        return _CommitPublicationOutcome(
            skip_reason=outcome.skip_reason if outcome is not None else None,
            error=outcome.error
            if outcome is not None
            else "agents target is unavailable",
        )
    target = selection.targets[0]
    owner = require_agent_owner_identity()
    identity = AgentIdentitySnapshot(owner)
    normalized = normalize_agent_archive_name(
        normalize_owned_agent_name(local_agent, identity)
    )
    item = AgentPublicationOutboxItem(
        project_key=target.project_key,
        project=target.project,
        local_agent=normalized,
        global_agent=globalize_owned_agent_name(normalized, identity),
        primary_revision=primary_revision,
        local_hood=agent_local_hood(normalized),
    )
    try:
        enqueue_agent_publication(item)
        active_requests = list_agent_publications(
            target.project_key,
            include_quarantined=False,
        )
    except Exception as exc:
        return _CommitPublicationOutcome(
            error=f"could not persist agents publication retry: {exc}"
        )
    if not active_requests:
        quarantined = next(
            (
                request
                for request in list_agent_publications(target.project_key)
                if request.logical_key == item.logical_key
            ),
            None,
        )
        return _CommitPublicationOutcome(
            queued=True,
            error=(
                quarantined.last_error
                if quarantined is not None
                else "agent publication request is quarantined"
            ),
        )

    from sase.agents_sync import git_sync

    timeout = (
        git_sync.configured_agents_lock_timeout()
        if lock_timeout_seconds is None
        else max(lock_timeout_seconds, 0.0)
    )
    clone_error = git_sync.ensure_agents_clone(
        target,
        git_runner=git_runner,
        lock_timeout_seconds=timeout,
    )
    if clone_error is not None:
        return _record_failure(target, clone_error)

    lock_path = (
        git_sync.agents_git_dir(target.sidecar_path, git_runner)
        / "sase-agents-sync.lock"
    )
    with git_sync.bounded_agents_lock(lock_path, timeout) as acquired:
        if not acquired:
            return _record_failure(target, "agents sync lock is busy")
        result = _publish_queued_locked(target, owner, git_runner)
    if result.error is not None:
        return _record_failure(target, result.error, result.error_keys)

    try:
        from sase.agents_sync.status import rewrite_agents_sync_status_after_sync

        rewrite_agents_sync_status_after_sync((target.project_key,))
    except Exception:
        # Status projection is auxiliary and must not fail a completed publish.
        pass
    remaining = list_agent_publications(target.project_key)
    return _CommitPublicationOutcome(
        published=result.drained > 0,
        queued=bool(remaining),
        drained=result.drained,
        error="; ".join(result.item_errors) if result.item_errors else None,
    )


def _publish_queued_locked(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
) -> _DrainResult:
    from sase.agents_sync import git_sync

    requests = list_agent_publications(
        target.project_key,
        include_quarantined=False,
    )
    if not requests:
        return _DrainResult()
    logical_keys = tuple(item.logical_key for item in requests)
    pulled = git_sync.pull_agents_rebase(
        target.sidecar_path, git_runner, "agents_sync.commit_publish_pull"
    )
    if pulled.returncode != 0:
        cleanup = git_sync.abort_agents_rebase(target.sidecar_path, git_runner)
        return _DrainResult(
            error=git_sync.agents_git_error(
                "git pull --rebase failed", pulled, cleanup
            ),
            error_keys=logical_keys,
        )

    identity = AgentIdentitySnapshot(owner)
    with name_registry_load_session():
        integrate_agent_imports_with_receipts(
            target,
            target.sidecar_path,
            owner,
            git_runner=git_runner,
        )
        inventory = build_project_hood_inventory(
            target,
            identity,
            git_runner=git_runner,
        )

    prepared, item_errors = _prepare_publications(
        target,
        owner,
        requests,
        identity,
        inventory,
        git_runner,
    )
    prepared_keys = tuple(item.logical_key for item in prepared)
    if not prepared:
        return _DrainResult(item_errors=item_errors)
    commit_result = git_sync.commit_agents_payload_if_dirty(
        target.sidecar_path, owner, git_runner
    )
    if isinstance(commit_result, str):
        return _DrainResult(
            item_errors=item_errors,
            error=commit_result,
            error_keys=prepared_keys,
        )
    committed = commit_result
    should_push = (
        committed or git_sync.agents_ahead_count(target.sidecar_path, git_runner) > 0
    )
    if not should_push:
        acknowledge_agent_publications(target.project_key, prepared_keys)
        return _DrainResult(drained=len(prepared), item_errors=item_errors)

    pushed = git_runner(
        target.sidecar_path,
        ["push"],
        network=True,
        op="agents_sync.commit_publish_push",
    )
    if pushed.returncode == 0:
        acknowledge_agent_publications(target.project_key, prepared_keys)
        return _DrainResult(drained=len(prepared), item_errors=item_errors)
    if not git_sync.is_agents_non_fast_forward(pushed):
        return _DrainResult(
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
            return _DrainResult(
                item_errors=item_errors,
                error=git_sync.agents_git_error(
                    "could not prepare rejected publication for retry", dropped
                ),
                error_keys=prepared_keys,
            )
    repulled = git_sync.pull_agents_rebase(
        target.sidecar_path, git_runner, "agents_sync.commit_publish_retry_pull"
    )
    if repulled.returncode != 0:
        cleanup = git_sync.abort_agents_rebase(target.sidecar_path, git_runner)
        return _DrainResult(
            item_errors=item_errors,
            error=git_sync.agents_git_error(
                "git pull --rebase retry failed", repulled, cleanup
            ),
            error_keys=prepared_keys,
        )
    retry_prepared, retry_errors = _prepare_publications(
        target,
        owner,
        prepared,
        identity,
        inventory,
        git_runner,
    )
    all_item_errors = (*item_errors, *retry_errors)
    retry_keys = tuple(item.logical_key for item in retry_prepared)
    if not retry_prepared:
        return _DrainResult(item_errors=all_item_errors)
    retry_commit = git_sync.commit_agents_payload_if_dirty(
        target.sidecar_path, owner, git_runner
    )
    if isinstance(retry_commit, str):
        return _DrainResult(
            item_errors=all_item_errors,
            error=retry_commit,
            error_keys=retry_keys,
        )
    retry_push = git_runner(
        target.sidecar_path,
        ["push"],
        network=True,
        op="agents_sync.commit_publish_retry_push",
    )
    if retry_push.returncode != 0:
        return _DrainResult(
            item_errors=all_item_errors,
            error=git_sync.agents_git_error("git push retry failed", retry_push),
            error_keys=retry_keys,
        )
    acknowledge_agent_publications(target.project_key, retry_keys)
    return _DrainResult(
        drained=len(retry_prepared),
        item_errors=all_item_errors,
    )


def _prepare_publications(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    requests: tuple[AgentPublicationOutboxItem, ...],
    identity: AgentIdentitySnapshot,
    inventory: ProjectHoodInventory,
    git_runner: GitRunner,
) -> tuple[tuple[AgentPublicationOutboxItem, ...], tuple[str, ...]]:
    repo = target.sidecar_path
    requests_by_hood: dict[str, list[AgentPublicationOutboxItem]] = {}
    prepared: list[AgentPublicationOutboxItem] = []
    errors: list[str] = []
    for request in requests:
        requests_by_hood.setdefault(request.local_hood, []).append(request)

    published_by_hood: dict[str, list[AgentPublicationOutboxItem]] = {}
    for hood_requests in requests_by_hood.values():
        request = hood_requests[0]
        try:
            publish_agent_hood(
                target,
                repo,
                request.local_agent,
                identity=identity,
                inventory=inventory,
                git_runner=git_runner,
            )
            published_by_hood[request.local_hood] = hood_requests
        except Exception as exc:  # noqa: BLE001 - durable auxiliary boundary
            error = f"could not publish agent hood {request.local_hood!r}: {exc}"
            update_agent_publications(
                target.project_key,
                (item.logical_key for item in hood_requests),
                error=error,
                increment_attempts=True,
                quarantine_threshold=configured_publication_max_attempts(),
            )
            errors.append(error)

    try:
        entries = (
            read_owner_manifest(
                repo,
                owner,
                V2ProjectIdentity(target.project_key, target.project),
            ).by_hood()
            if published_by_hood
            else {}
        )
    except Exception as exc:  # noqa: BLE001 - durable auxiliary boundary
        for hood, hood_requests in published_by_hood.items():
            error = f"could not publish agent hood {hood!r}: {exc}"
            update_agent_publications(
                target.project_key,
                (item.logical_key for item in hood_requests),
                error=error,
                increment_attempts=True,
                quarantine_threshold=configured_publication_max_attempts(),
            )
            errors.append(error)
        return (), tuple(errors)
    for hood, hood_requests in published_by_hood.items():
        request = hood_requests[0]
        try:
            entry = entries.get(hood)
            if entry is None:
                raise RuntimeError(f"published hood {hood!r} is absent from manifest")
            update_agent_publications(
                target.project_key,
                (item.logical_key for item in hood_requests),
                hood_digest=entry.digest,
                error=None,
            )
            prepared.extend(hood_requests)
        except Exception as exc:  # noqa: BLE001 - durable auxiliary boundary
            error = f"could not publish agent hood {request.local_hood!r}: {exc}"
            update_agent_publications(
                target.project_key,
                (item.logical_key for item in hood_requests),
                error=error,
                increment_attempts=True,
                quarantine_threshold=configured_publication_max_attempts(),
            )
            errors.append(error)
    prepared_keys = {item.logical_key for item in prepared}
    return (
        tuple(item for item in requests if item.logical_key in prepared_keys),
        tuple(errors),
    )


def _record_failure(
    target: ProjectTarget,
    error: str,
    logical_keys: tuple[tuple[str, str], ...] | None = None,
) -> _CommitPublicationOutcome:
    requests = list_agent_publications(
        target.project_key,
        include_quarantined=False,
    )
    selected = (
        tuple(item.logical_key for item in requests)
        if logical_keys is None
        else logical_keys
    )
    update_agent_publications(
        target.project_key,
        selected,
        error=error,
        increment_attempts=True,
    )
    return _CommitPublicationOutcome(queued=True, error=error)


def _current_project() -> str | None:
    try:
        from sase.workflows.utils import get_project_from_workspace

        return get_project_from_workspace()
    except Exception:
        return None


__all__ = ["publish_committed_agent_hood"]
