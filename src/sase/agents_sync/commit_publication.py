"""Checkpoint-friendly targeted publication after a primary commit."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import threading

from sase.agents_sync.bundles import repository_root
from sase.agents_sync.commit_publication_transaction import (
    DrainResult,
    PublicationTransactionHooks,
    publish_queued_transaction,
)
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.inventory import (
    build_project_hood_inventory,
)
from sase.agents_sync.models import ProjectTarget
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
from sase.config import require_agent_owner_identity
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    agent_local_hood,
    normalize_agent_archive_name,
    normalize_owned_agent_name,
)
from sase.repo_inventory import collect_repo_inventory
from sase.sase_agent import sase_agent_ref_for_shell
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

_DRAIN_TIMEOUT_ENV = "SASE_AGENTS_PUBLICATION_DRAIN_TIMEOUT"
DEFAULT_PUBLICATION_DRAIN_TIMEOUT_SECONDS = 120.0


class _PublicationDrainTimedOut(Exception):
    """Raised when a synchronous agent-hood drain exceeds its wall-clock bound."""


def _configured_publication_drain_timeout() -> float:
    """Return the configured bound on a synchronous post-push drain attempt."""

    raw = os.environ.get(_DRAIN_TIMEOUT_ENV)
    if raw is None:
        return DEFAULT_PUBLICATION_DRAIN_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_PUBLICATION_DRAIN_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_PUBLICATION_DRAIN_TIMEOUT_SECONDS


@contextmanager
def _bounded_publication_drain(timeout_seconds: float) -> Iterator[None]:
    """Bound a synchronous drain so a stalled render cannot wedge the caller.

    A finalizer that never returns keeps holding ``sase-agents-sync.lock``
    indefinitely (the reported failure mode). ``SIGALRM`` unwinds the *same*
    call stack that is already inside ``bounded_agents_lock``'s ``with``
    block, so the existing ``finally`` there still releases the lock -- no
    second thread or process is left running to mutate the sidecar after
    this function gives up on it.
    """

    can_bound = (
        timeout_seconds > 0
        and hasattr(signal, "SIGALRM")
        and threading.current_thread() is threading.main_thread()
    )
    if not can_bound:
        yield
        return

    def _on_alarm(_signum: int, _frame: object) -> None:
        raise _PublicationDrainTimedOut(
            f"agent-hood publication did not complete within {timeout_seconds:.0f}s"
        )

    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@dataclass(frozen=True, slots=True)
class _CommitPublicationOutcome:
    published: bool = False
    queued: bool = False
    drained: int = 0
    quarantined: int = 0
    retired: int = 0
    skip_reason: str | None = None
    error: str | None = None


def publish_committed_agent_hood(
    local_agent: str,
    primary_revision: str,
    *,
    project: str | None = None,
    commit_cwd: Path | str | None = None,
    git_runner: GitRunner = run_git,
) -> _CommitPublicationOutcome:
    """Enqueue one agent-hood request and drain it before returning.

    The durable outbox stays on the synchronous path so a publication that
    cannot complete right now is still retried later by ``sase agent sync``.
    """

    outcome, target, _item = _enqueue_committed_agent_publication(
        local_agent,
        primary_revision,
        project=project,
        commit_cwd=commit_cwd,
    )
    if outcome.error is not None or outcome.skip_reason is not None:
        return outcome
    if target is None:
        return outcome
    return _drain_agent_publications(target.project_key, git_runner=git_runner)


def _enqueue_committed_agent_publication(
    local_agent: str,
    primary_revision: str,
    *,
    project: str | None,
    commit_cwd: Path | str | None,
) -> tuple[
    _CommitPublicationOutcome,
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
            _CommitPublicationOutcome(
                skip_reason=(
                    target_error
                    or f"repository {repository!r} does not map to a SASE project"
                )
            ),
            None,
            None,
        )
    owner = require_agent_owner_identity()
    identity = AgentIdentitySnapshot(owner)
    normalized = normalize_agent_archive_name(
        normalize_owned_agent_name(local_agent, identity)
    )
    # The request's identity is the committing agent's sase-agent projection:
    # a family member publishes as its family, a solo agent as itself.  The
    # publication scope is unchanged either way -- it was already whole-hood,
    # and a member and its sase agent share a hood -- but the recorded identity
    # flows into the request's logical key and notification subject.
    agent_ref = sase_agent_ref_for_shell(normalized, identity)
    item = AgentPublicationOutboxItem(
        project_key=target.project_key,
        project=target.project,
        local_agent=agent_ref.local_name,
        global_agent=agent_ref.global_name,
        primary_revision=primary_revision,
        local_hood=agent_local_hood(agent_ref.local_name, identity),
    )
    try:
        enqueue_agent_publication(item)
        active_requests = _active_agent_publications(target.project_key)
    except Exception as exc:
        return (
            _CommitPublicationOutcome(
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
            _CommitPublicationOutcome(
                queued=True,
                quarantined=_quarantined_count(requests),
                retired=_retired_count(requests),
                error=(
                    (stopped.terminal_reason or stopped.last_error)
                    if stopped is not None
                    else "agent publication request is quarantined"
                ),
            ),
            target,
            item,
        )
    return _CommitPublicationOutcome(queued=True), target, item


def _drain_agent_publications(
    project_key: str,
    *,
    git_runner: GitRunner = run_git,
) -> _CommitPublicationOutcome:
    """Drain active agent-hood requests for one project under its sidecar lock."""

    selection = resolve_sync_targets((project_key,))
    if len(selection.targets) != 1:
        outcome = selection.outcomes[0] if selection.outcomes else None
        detail = (
            (outcome.skip_reason or outcome.error) if outcome is not None else None
        ) or "agents target is unavailable"
        return _CommitPublicationOutcome(
            skip_reason=f"project {project_key!r} has no usable agents target: {detail}"
        )
    target = selection.targets[0]
    try:
        owner = require_agent_owner_identity()
    except Exception as exc:
        return _CommitPublicationOutcome(error=f"owner identity is unavailable: {exc}")

    from sase.agents_sync import git_sync

    timeout = git_sync.configured_agents_lock_timeout()
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
        try:
            with _bounded_publication_drain(_configured_publication_drain_timeout()):
                result = _publish_queued_locked(target, owner, git_runner)
        except _PublicationDrainTimedOut as exc:
            return _record_failure(target, str(exc))
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


def _active_agent_publications(
    project_key: str,
) -> tuple[AgentPublicationOutboxItem, ...]:
    return list_agent_publications(project_key, include_quarantined=False)


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
    selection = resolve_sync_targets((selector,))
    if len(selection.targets) == 1:
        return selection.targets[0], None
    outcome = selection.outcomes[0] if selection.outcomes else None
    detail = (
        (outcome.skip_reason or outcome.error) if outcome is not None else None
    ) or "agents target is unavailable"
    return None, f"project {selector!r} has no usable publication target: {detail}"


def _publication_project_key_from_path(commit_cwd: Path | str) -> str | None:
    """Resolve a registered checkout by path without invoking git."""

    cwd = Path(commit_cwd).expanduser().resolve(strict=False)
    try:
        inventory = collect_repo_inventory()
    except Exception:
        return None

    matches: list[tuple[int, int, str, str]] = []
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
                )
            )
    if not matches:
        return None
    return min(matches)[2]


def _display_repository(commit_cwd: Path | str | None) -> str:
    if commit_cwd is None:
        return "the current checkout"
    return str(Path(commit_cwd).expanduser().resolve(strict=False))


def _publish_queued_locked(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
) -> DrainResult:
    from sase.agents_sync import git_sync

    requests = _active_agent_publications(target.project_key)
    if not requests:
        return DrainResult()
    logical_keys = tuple(item.logical_key for item in requests)
    cleanup_error = git_sync.clean_agents_payload_worktree(
        target.sidecar_path,
        git_runner,
    )
    if cleanup_error is not None:
        return DrainResult(error=cleanup_error, error_keys=logical_keys)
    result: DrainResult
    try:
        result = publish_queued_transaction(
            target,
            owner,
            git_runner,
            requests,
            hooks=PublicationTransactionHooks(
                build_inventory=build_project_hood_inventory,
                publish_hood=publish_agent_hood,
                update_publications=update_agent_publications,
                acknowledge_publications=acknowledge_agent_publications,
                configured_max_attempts=configured_publication_max_attempts,
            ),
        )
    finally:
        cleanup_error = git_sync.clean_agents_payload_worktree(
            target.sidecar_path,
            git_runner,
        )
    return (
        DrainResult(error=cleanup_error, error_keys=logical_keys)
        if cleanup_error is not None
        else result
    )


def _record_failure(
    target: ProjectTarget,
    error: str,
    logical_keys: tuple[tuple[str, str], ...] | None = None,
) -> _CommitPublicationOutcome:
    requests = _active_agent_publications(target.project_key)
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
        quarantine_threshold=configured_publication_max_attempts(),
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
