"""Queue committed publication requests and resolve their project targets."""

from __future__ import annotations

from pathlib import Path

from sase.agents_sync._commit_publication_drain import drain_agent_publications
from sase.agents_sync._commit_publication_outbox import (
    active_agent_publications,
    quarantined_count,
    retired_count,
)
from sase.agents_sync import _commit_publication_support as publication_support
from sase.agents_sync._commit_publication_types import CommitPublicationOutcome
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import (
    PUBLICATION_SCOPE_LINKED,
    PUBLICATION_SCOPE_REVISION,
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
    list_agent_publications,
)
from sase.agents_sync.repository_inspection import repository_root
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    agent_local_hood,
    normalize_agent_archive_name,
    normalize_owned_agent_name,
)
from sase.repo_inventory import collect_repo_inventory
from sase.sase_agent import sase_agent_ref_for_turn

_REPO_KIND_ORDER = {
    "primary": 0,
    "sidecar": 1,
    "linked": 2,
    "external": 3,
}


def publish_committed_agent_hood(
    local_agent: str,
    primary_revision: str,
    *,
    project: str | None = None,
    commit_cwd: Path | str | None = None,
    git_runner: GitRunner = run_git,
) -> CommitPublicationOutcome:
    """Enqueue one agent-hood request and drain it before returning.

    The durable outbox stays on the synchronous path so a publication that
    cannot complete right now is still retried later by ``sase agent sync``.
    """

    outcome, target, item = _enqueue_committed_agent_publication(
        local_agent,
        primary_revision,
        project=project,
        commit_cwd=commit_cwd,
    )
    if outcome.error is not None or outcome.skip_reason is not None:
        return outcome
    if target is None:
        return outcome
    return drain_agent_publications(
        target.project_key,
        git_runner=git_runner,
        preferred_key=item.logical_key if item is not None else None,
    )


def drain_selected_agent_publications(
    project_key: str,
    selected_keys: tuple[tuple[str, str], ...],
    *,
    git_runner: GitRunner = run_git,
) -> CommitPublicationOutcome:
    """Drain only the supplied active requests through targeted publication."""

    if not selected_keys:
        return CommitPublicationOutcome()
    return drain_agent_publications(
        project_key,
        git_runner=git_runner,
        selected_keys=selected_keys,
    )


def _enqueue_committed_agent_publication(
    local_agent: str,
    primary_revision: str,
    *,
    project: str | None,
    commit_cwd: Path | str | None,
) -> tuple[
    CommitPublicationOutcome,
    ProjectTarget | None,
    AgentPublicationOutboxItem | None,
]:
    """Resolve and enqueue, returning private context for the compatibility path."""

    target, target_error = _resolve_sidecar_publication_target(
        project=project,
        commit_cwd=commit_cwd,
    )
    if target is None:
        repository = _display_repository(commit_cwd)
        return (
            CommitPublicationOutcome(
                skip_reason=(
                    target_error
                    or f"repository {repository!r} does not map to a SASE project"
                )
            ),
            None,
            None,
        )
    owner = publication_support.require_agent_owner_identity()
    identity = AgentIdentitySnapshot(owner)
    normalized = normalize_agent_archive_name(
        normalize_owned_agent_name(local_agent, identity)
    )
    # The request's identity is the committing agent's sase-agent projection:
    # a session member publishes as its session, a solo agent as itself.  The
    # publication scope is unchanged either way -- it was already whole-hood,
    # and a member and its sase agent share a hood -- but the recorded identity
    # flows into the request's logical key and notification subject.
    agent_ref = sase_agent_ref_for_turn(normalized, identity)
    item = AgentPublicationOutboxItem(
        project_key=target.project_key,
        project=target.project,
        local_agent=agent_ref.local_name,
        global_agent=agent_ref.global_name,
        primary_revision=primary_revision,
        local_hood=agent_local_hood(agent_ref.local_name, identity),
        scope=fulfillment_scope_for_commit_cwd(commit_cwd),
    )
    try:
        enqueue_agent_publication(item)
        active_requests = active_agent_publications(target.project_key)
    except Exception as exc:
        return (
            CommitPublicationOutcome(
                error=f"could not persist agents publication retry: {exc}"
            ),
            target,
            item,
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
        return (
            CommitPublicationOutcome(
                queued=True,
                quarantined=quarantined_count(requests),
                retired=retired_count(requests),
                error=(
                    (stopped.terminal_reason or stopped.last_error)
                    if stopped is not None
                    else "agent publication request is quarantined"
                ),
            ),
            target,
            item,
        )
    return CommitPublicationOutcome(queued=True), target, item


def fulfillment_scope_for_commit_cwd(commit_cwd: Path | str | None) -> str:
    """Return linked-scope for a non-primary checkout, else revision-bound."""

    if commit_cwd is None:
        return PUBLICATION_SCOPE_REVISION
    match = _publication_inventory_match(commit_cwd)
    if match is None or match[1] == "primary":
        return PUBLICATION_SCOPE_REVISION
    return PUBLICATION_SCOPE_LINKED


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


def _resolve_sidecar_publication_target(
    *,
    project: str | None = None,
    commit_cwd: Path | str | None = None,
) -> tuple[ProjectTarget | None, str | None]:
    """Resolve a durable queue target without touching a sidecar repository.

    Enqueue-only callers use the repository inventory rather than ``git`` so
    marking publication cannot accidentally perform sidecar work.
    """

    selector = project
    if selector is None and commit_cwd is not None:
        selector = _publication_project_key_from_path(commit_cwd)
    selector = selector or _current_project()
    if not selector:
        return None, None
    selection = publication_support.resolve_sync_targets((selector,))
    if len(selection.targets) == 1:
        return selection.targets[0], None
    outcome = selection.outcomes[0] if selection.outcomes else None
    detail = (
        (outcome.skip_reason or outcome.error) if outcome is not None else None
    ) or "agents target is unavailable"
    return None, f"project {selector!r} has no usable publication target: {detail}"


def _publication_inventory_match(
    commit_cwd: Path | str,
) -> tuple[str, str] | None:
    """Return ``(project_key, kind)`` for the most specific inventory match."""

    cwd = Path(commit_cwd).expanduser().resolve(strict=False)
    try:
        inventory = collect_repo_inventory()
    except Exception:
        return None

    matches: list[tuple[int, int, str, str, str]] = []
    for record in inventory.records:
        paths = (record.path, *(clone.path for clone in record.clones))
        for raw_path in paths:
            if not raw_path:
                continue
            root = Path(raw_path).expanduser().resolve(strict=False)
            if cwd != root and not cwd.is_relative_to(root):
                continue
            matches.append(
                (
                    -len(root.parts),
                    _REPO_KIND_ORDER[record.kind],
                    record.project_key,
                    record.name.casefold(),
                    record.kind,
                )
            )
    if not matches:
        return None
    selected = min(matches)
    return selected[2], selected[4]


def _publication_project_key_from_path(commit_cwd: Path | str) -> str | None:
    """Resolve a registered checkout by path without invoking git."""

    match = _publication_inventory_match(commit_cwd)
    return None if match is None else match[0]


def _display_repository(commit_cwd: Path | str | None) -> str:
    if commit_cwd is None:
        return "the current checkout"
    return str(Path(commit_cwd).expanduser().resolve(strict=False))


def _current_project() -> str | None:
    try:
        from sase.workflows.utils import get_project_from_workspace

        return get_project_from_workspace()
    except Exception:
        return None
