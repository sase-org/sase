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
        queued_count = len(list_agent_publications(target.project_key))
    except Exception as exc:
        return _CommitPublicationOutcome(
            error=f"could not persist agents publication retry: {exc}"
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
        error = _publish_queued_locked(target, owner, git_runner)
    if error is not None:
        return _record_failure(target, error)

    try:
        from sase.agents_sync.status import rewrite_agents_sync_status_after_sync

        rewrite_agents_sync_status_after_sync((target.project_key,))
    except Exception:
        # Status projection is auxiliary and must not fail a completed publish.
        pass
    return _CommitPublicationOutcome(
        published=True,
        drained=queued_count,
    )


def _publish_queued_locked(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
) -> str | None:
    from sase.agents_sync import git_sync

    requests = list_agent_publications(target.project_key)
    logical_keys = tuple(item.logical_key for item in requests)
    pulled = git_sync.pull_agents_rebase(
        target.sidecar_path, git_runner, "agents_sync.commit_publish_pull"
    )
    if pulled.returncode != 0:
        cleanup = git_sync.abort_agents_rebase(target.sidecar_path, git_runner)
        return git_sync.agents_git_error("git pull --rebase failed", pulled, cleanup)

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

    error = _prepare_publications(
        target,
        owner,
        requests,
        identity,
        inventory,
        git_runner,
    )
    if error is not None:
        return error
    commit_result = git_sync.commit_agents_payload_if_dirty(
        target.sidecar_path, owner, git_runner
    )
    if isinstance(commit_result, str):
        return commit_result
    committed = commit_result
    should_push = (
        committed or git_sync.agents_ahead_count(target.sidecar_path, git_runner) > 0
    )
    if not should_push:
        acknowledge_agent_publications(target.project_key, logical_keys)
        return None

    pushed = git_runner(
        target.sidecar_path,
        ["push"],
        network=True,
        op="agents_sync.commit_publish_push",
    )
    if pushed.returncode == 0:
        acknowledge_agent_publications(target.project_key, logical_keys)
        return None
    if not git_sync.is_agents_non_fast_forward(pushed):
        return git_sync.agents_git_error("git push failed", pushed)

    if committed:
        dropped = git_runner(
            target.sidecar_path,
            ["reset", "--hard", "HEAD^"],
            op="agents_sync.commit_publish_retry_drop",
        )
        if dropped.returncode != 0:
            return git_sync.agents_git_error(
                "could not prepare rejected publication for retry", dropped
            )
    repulled = git_sync.pull_agents_rebase(
        target.sidecar_path, git_runner, "agents_sync.commit_publish_retry_pull"
    )
    if repulled.returncode != 0:
        cleanup = git_sync.abort_agents_rebase(target.sidecar_path, git_runner)
        return git_sync.agents_git_error(
            "git pull --rebase retry failed", repulled, cleanup
        )
    error = _prepare_publications(
        target,
        owner,
        requests,
        identity,
        inventory,
        git_runner,
    )
    if error is not None:
        return error
    retry_commit = git_sync.commit_agents_payload_if_dirty(
        target.sidecar_path, owner, git_runner
    )
    if isinstance(retry_commit, str):
        return retry_commit
    retry_push = git_runner(
        target.sidecar_path,
        ["push"],
        network=True,
        op="agents_sync.commit_publish_retry_push",
    )
    if retry_push.returncode != 0:
        return git_sync.agents_git_error("git push retry failed", retry_push)
    acknowledge_agent_publications(target.project_key, logical_keys)
    return None


def _prepare_publications(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    requests: tuple[AgentPublicationOutboxItem, ...],
    identity: AgentIdentitySnapshot,
    inventory: ProjectHoodInventory,
    git_runner: GitRunner,
) -> str | None:
    repo = target.sidecar_path
    requests_by_hood: dict[str, list[AgentPublicationOutboxItem]] = {}
    for request in requests:
        requests_by_hood.setdefault(request.local_hood, []).append(request)

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
        except Exception as exc:  # noqa: BLE001 - durable auxiliary boundary
            return f"could not publish agent hood {request.local_hood!r}: {exc}"

    manifest = read_owner_manifest(
        repo,
        owner,
        V2ProjectIdentity(target.project_key, target.project),
    )
    entries = manifest.by_hood()
    for hood, hood_requests in requests_by_hood.items():
        entry = entries.get(hood)
        if entry is None:
            return f"published hood {hood!r} is absent from manifest"
        update_agent_publications(
            target.project_key,
            (request.logical_key for request in hood_requests),
            hood_digest=entry.digest,
            error=None,
        )
    return None


def _record_failure(
    target: ProjectTarget,
    error: str,
) -> _CommitPublicationOutcome:
    requests = list_agent_publications(target.project_key)
    update_agent_publications(
        target.project_key,
        (item.logical_key for item in requests),
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
