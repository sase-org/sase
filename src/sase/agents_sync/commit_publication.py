"""Checkpoint-friendly targeted publication after a primary commit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.agent.names._registry import name_registry_load_session
from sase.agent_lanes import lane_ref_for_agent
from sase.agents_sync.bundles import repository_root
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.incoming_integration import (
    integrate_agent_imports_with_receipts,
)
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.inventory import (
    ProjectHoodInventory,
    build_project_hood_inventory,
)
from sase.agents_sync.inventory_models import InventoryRun
from sase.agents_sync.io import AgentsSyncFormatError
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
    normalize_agent_archive_name,
    normalize_owned_agent_name,
)
from sase.core.prompt_artifact_staging import mark_prompt_archive_published
from sase.repo_inventory import collect_repo_inventory
from sase.sdd.plan_header_refresh import (
    PlanHeaderRefreshOutcome,
    refresh_committed_plan_header,
)

_REPO_KIND_ORDER = {
    "primary": 0,
    "sidecar": 1,
    "linked": 2,
    "external": 3,
}


@dataclass(frozen=True, slots=True)
class _CommitPublicationOutcome:
    published: bool = False
    queued: bool = False
    drained: int = 0
    quarantined: int = 0
    retired: int = 0
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
    commit_cwd: Path | str | None = None,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> _CommitPublicationOutcome:
    """Publish this commit's exact hood and drain older project requests."""

    selector = project
    if selector is None and commit_cwd is not None:
        selector = resolve_publication_project_key(
            commit_cwd,
            git_runner=git_runner,
        )
    selector = selector or _current_project()
    if not selector:
        repository = _display_repository(commit_cwd)
        return _CommitPublicationOutcome(
            skip_reason=f"repository {repository!r} does not map to a SASE project"
        )
    selection = resolve_sync_targets((selector,))
    if len(selection.targets) != 1:
        outcome = selection.outcomes[0] if selection.outcomes else None
        detail = (
            (outcome.skip_reason or outcome.error) if outcome is not None else None
        ) or "agents target is unavailable"
        return _CommitPublicationOutcome(
            skip_reason=f"project {selector!r} has no usable agents target: {detail}",
        )
    target = selection.targets[0]
    owner = require_agent_owner_identity()
    identity = AgentIdentitySnapshot(owner)
    normalized = normalize_agent_archive_name(
        normalize_owned_agent_name(local_agent, identity)
    )
    # The request's identity is the committing agent's *lane*: a family member
    # publishes as its family, a solo agent as itself.  The publication scope is
    # unchanged either way -- it was already whole-hood, and a member and its
    # lane share a hood -- but the recorded identity flows into the request's
    # logical key and notification subject.
    lane = lane_ref_for_agent(normalized, identity)
    item = AgentPublicationOutboxItem(
        project_key=target.project_key,
        project=target.project,
        local_agent=lane.local_name,
        global_agent=lane.global_name,
        primary_revision=primary_revision,
        local_hood=agent_local_hood(lane.local_name),
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
        requests = list_agent_publications(target.project_key)
        stopped = next(
            (
                request
                for request in requests
                if request.logical_key == item.logical_key
            ),
            None,
        )
        return _CommitPublicationOutcome(
            queued=True,
            quarantined=_quarantined_count(requests),
            retired=_retired_count(requests),
            error=(
                (stopped.terminal_reason or stopped.last_error)
                if stopped is not None
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
        quarantined=_quarantined_count(remaining),
        retired=_retired_count(remaining),
        error="; ".join(result.item_errors) if result.item_errors else None,
    )


def _quarantined_count(items: tuple[AgentPublicationOutboxItem, ...]) -> int:
    return sum(item.quarantined and not item.terminal for item in items)


def _retired_count(items: tuple[AgentPublicationOutboxItem, ...]) -> int:
    return sum(item.terminal for item in items)


def resolve_publication_project_key(
    commit_cwd: Path | str,
    *,
    git_runner: GitRunner = run_git,
) -> str | None:
    """Resolve the host project for the repository containing *commit_cwd*."""

    cwd = Path(commit_cwd).expanduser()
    try:
        root = repository_root(cwd, git_runner, {})
    except Exception:
        return None
    if root is None:
        return None
    try:
        inventory = collect_repo_inventory()
    except Exception:
        return None

    normalized_root = root.resolve(strict=False)
    matches = []
    for record in inventory.records:
        paths = (record.path, *(clone.path for clone in record.clones))
        if any(
            path and Path(path).expanduser().resolve(strict=False) == normalized_root
            for path in paths
        ):
            matches.append(record)
    if not matches:
        return None
    selected = min(
        matches,
        key=lambda record: (
            _REPO_KIND_ORDER[record.kind],
            record.project_key,
            record.name.casefold(),
        ),
    )
    return selected.project_key


def _display_repository(commit_cwd: Path | str | None) -> str:
    if commit_cwd is None:
        return "the current checkout"
    return str(Path(commit_cwd).expanduser().resolve(strict=False))


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
    cleanup_error = git_sync.clean_agents_payload_worktree(
        target.sidecar_path,
        git_runner,
    )
    if cleanup_error is not None:
        return _DrainResult(error=cleanup_error, error_keys=logical_keys)
    result: _DrainResult
    try:
        result = _publish_queued_transaction(
            target,
            owner,
            git_runner,
            requests,
        )
    finally:
        cleanup_error = git_sync.clean_agents_payload_worktree(
            target.sidecar_path,
            git_runner,
        )
    return (
        _DrainResult(error=cleanup_error, error_keys=logical_keys)
        if cleanup_error is not None
        else result
    )


def _publish_queued_transaction(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
    requests: tuple[AgentPublicationOutboxItem, ...],
) -> _DrainResult:
    from sase.agents_sync import git_sync

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
        target.sidecar_path,
        owner,
        git_runner,
        extra_paths=("prompts", "artifacts"),
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
        marker_error = _mark_prompt_archives_published(
            prepared,
            inventory,
            identity,
        )
        if marker_error is not None:
            return _DrainResult(error=marker_error, error_keys=prepared_keys)
        acknowledge_agent_publications(target.project_key, prepared_keys)
        return _DrainResult(drained=len(prepared), item_errors=item_errors)

    pushed = git_runner(
        target.sidecar_path,
        ["push"],
        network=True,
        op="agents_sync.commit_publish_push",
    )
    if pushed.returncode == 0:
        marker_error = _mark_prompt_archives_published(
            prepared,
            inventory,
            identity,
        )
        if marker_error is not None:
            return _DrainResult(
                item_errors=item_errors,
                error=marker_error,
                error_keys=prepared_keys,
            )
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
    cleanup_error = git_sync.clean_agents_payload_worktree(
        target.sidecar_path,
        git_runner,
    )
    if cleanup_error is not None:
        return _DrainResult(
            item_errors=item_errors,
            error=cleanup_error,
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
        target.sidecar_path,
        owner,
        git_runner,
        extra_paths=("prompts", "artifacts"),
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
    marker_error = _mark_prompt_archives_published(
        retry_prepared,
        inventory,
        identity,
    )
    if marker_error is not None:
        return _DrainResult(
            item_errors=all_item_errors,
            error=marker_error,
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
    prompt_runs = _prompt_runs_by_request(inventory, identity)
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
            for hood_request in hood_requests:
                _prepare_prompt_archive_retry(
                    target,
                    hood_request,
                    git_runner,
                    prompt_runs=prompt_runs,
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
                terminal_reason=(
                    error
                    if isinstance(exc, AgentsSyncFormatError)
                    and str(exc)
                    == f"hood {request.local_hood!r} has no publishable runs"
                    else None
                ),
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


def _prepare_prompt_archive_retry(
    target: ProjectTarget,
    request: AgentPublicationOutboxItem,
    git_runner: GitRunner,
    *,
    prompt_runs: dict[tuple[str, str], InventoryRun],
) -> None:
    """Regenerate one queued prompt archive in the active sidecar transaction."""

    matching = prompt_runs.get((request.local_agent, request.primary_revision))
    if matching is None or matching.source_label is None:
        return
    artifacts_dir = Path(matching.source_label)
    if not (artifacts_dir / "raw_xprompt.md").is_file():
        return
    from sase.agents_sync.prompt_archive.publish import prepare_prompt_archive

    prepare_prompt_archive(
        target=target,
        repo=target.sidecar_path,
        agent_name=matching.local_name,
        global_agent=matching.global_name,
        primary_revision=request.primary_revision,
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
        git_runner=git_runner,
    )


def _mark_prompt_archives_published(
    requests: tuple[AgentPublicationOutboxItem, ...],
    inventory: ProjectHoodInventory,
    identity: AgentIdentitySnapshot,
) -> str | None:
    """Mark queued prompt inputs safe to reclaim after archive publication."""

    prompt_runs = _prompt_runs_by_request(inventory, identity)
    try:
        for request in requests:
            matching = prompt_runs.get((request.local_agent, request.primary_revision))
            if matching is None or matching.source_label is None:
                continue
            artifacts_dir = Path(matching.source_label)
            if not (artifacts_dir / "raw_xprompt.md").is_file():
                continue
            mark_prompt_archive_published(
                artifacts_dir,
                primary_revision=request.primary_revision,
            )
    except Exception as exc:  # noqa: BLE001 - durable retry boundary.
        return f"could not record prompt archive publication: {exc}"
    return None


def _prompt_runs_by_request(
    inventory: ProjectHoodInventory,
    identity: AgentIdentitySnapshot,
) -> dict[tuple[str, str], InventoryRun]:
    indexed: dict[tuple[str, str], InventoryRun] = {}
    for run in inventory.runs:
        local_name = getattr(run, "local_name", None)
        if not isinstance(local_name, str):
            continue
        lane = lane_ref_for_agent(local_name, identity).local_name
        for commit in getattr(run, "commits", ()):
            sha = getattr(commit, "sha", None)
            if isinstance(sha, str):
                indexed.setdefault((lane, sha), run)
    return indexed


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
    updated = update_agent_publications(
        target.project_key,
        selected,
        error=error,
        increment_attempts=True,
    )
    return _CommitPublicationOutcome(
        queued=True,
        quarantined=_quarantined_count(updated),
        retired=_retired_count(updated),
        error=error,
    )


def _current_project() -> str | None:
    try:
        from sase.workflows.utils import get_project_from_workspace

        return get_project_from_workspace()
    except Exception:
        return None


__all__ = [
    "PlanHeaderRefreshOutcome",
    "publish_committed_agent_hood",
    "refresh_committed_plan_header",
    "resolve_publication_project_key",
]
