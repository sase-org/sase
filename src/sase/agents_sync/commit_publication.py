"""Checkpoint-friendly targeted publication after a primary commit."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync.commit_publication_transaction import (
    DrainResult,
    PublicationTransactionHooks,
    hood_timeout_stage,
    publish_queued_transaction,
)
from sase.core.agent_publication_recovery import (
    PublicationDrainSelection,
    PublicationFailureAccounting,
    PublicationFailureCharge,
    decide_publication_failure_accounting,
    select_publication_drain,
)
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.git_sync_ops import lock_holder_diagnostic
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
from sase.agents_sync.publication_timing import (
    DrainTiming,
    emit_drain_timing,
)
from sase.agents_sync.repository_inspection import repository_root
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
from sase.sase_agent import sase_agent_ref_for_turn
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
def _bounded_publication_drain(
    timeout_seconds: float,
    *,
    timer: DrainTiming | None = None,
) -> Iterator[None]:
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
        if timer is not None:
            timer.alarm_fired = True
            if timer.alarm_stage is None:
                timer.alarm_stage = timer.stage or "drain"
            if timer.alarm_keys is None:
                timer.alarm_keys = tuple(timer.active_keys)
        raise PublicationDrainTimedOut(
            f"agent-hood publication did not complete within {timeout_seconds:.0f}s"
        )

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    signal.setitimer(signal.ITIMER_REAL, 0)
    signal.signal(signal.SIGALRM, _on_alarm)
    started = time.monotonic()
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        previous_delay, previous_interval = previous_timer
        if previous_delay > 0:
            remaining = max(previous_delay - (time.monotonic() - started), 1e-6)
            signal.setitimer(signal.ITIMER_REAL, remaining, previous_interval)
        elif previous_interval > 0:
            signal.setitimer(signal.ITIMER_REAL, 0, previous_interval)


DEFAULT_COMMIT_DRAIN_BATCH_LIMIT = 25

_REPOSITORY_FAILURE_SCOPE = "repository"
_HOOD_FAILURE_SCOPE = "hood"


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
    return _drain_agent_publications(
        target.project_key,
        git_runner=git_runner,
        preferred_key=item.logical_key if item is not None else None,
    )


def drain_selected_agent_publications(
    project_key: str,
    selected_keys: tuple[tuple[str, str], ...],
    *,
    git_runner: GitRunner = run_git,
) -> _CommitPublicationOutcome:
    """Drain only the supplied active requests through targeted publication."""

    if not selected_keys:
        return _CommitPublicationOutcome()
    return _drain_agent_publications(
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
    preferred_key: tuple[str, str] | None = None,
    selected_keys: tuple[tuple[str, str], ...] | None = None,
) -> _CommitPublicationOutcome:
    """Drain active agent-hood requests for one project under its sidecar lock."""

    timer = DrainTiming(project_key=project_key)
    selection = resolve_sync_targets((project_key,))
    if len(selection.targets) != 1:
        outcome = selection.outcomes[0] if selection.outcomes else None
        detail = (
            (outcome.skip_reason or outcome.error) if outcome is not None else None
        ) or "agents target is unavailable"
        timer.stage = "resolve_target"
        timer.outcome = "target_unavailable"
        timer.error = detail
        emit_drain_timing(timer)
        return _CommitPublicationOutcome(
            skip_reason=f"project {project_key!r} has no usable agents target: {detail}"
        )
    target = selection.targets[0]
    try:
        owner = require_agent_owner_identity()
    except Exception as exc:
        timer.stage = "resolve_owner"
        timer.outcome = "owner_unavailable"
        timer.error = f"owner identity is unavailable: {exc}"
        emit_drain_timing(timer)
        return _CommitPublicationOutcome(error=f"owner identity is unavailable: {exc}")

    from sase.agents_sync import git_sync

    timeout = git_sync.configured_agents_lock_timeout()
    clone_error = git_sync.ensure_agents_clone(
        target,
        git_runner=git_runner,
        lock_timeout_seconds=timeout,
    )
    if clone_error is not None:
        timer.stage = "ensure_clone"
        timer.outcome = "clone_failed"
        timer.error = clone_error
        timer.failure_scope = _REPOSITORY_FAILURE_SCOPE
        timer.failure_stage = "ensure_clone"
        emit_drain_timing(timer)
        return _record_failure(
            target,
            clone_error,
            scope=_REPOSITORY_FAILURE_SCOPE,
            stage="ensure_clone",
            timer=timer,
        )

    lock_path = (
        git_sync.agents_git_dir(target.sidecar_path, git_runner)
        / "sase-agents-sync.lock"
    )
    lock_wait_start = time.monotonic()
    with git_sync.bounded_agents_lock(
        lock_path, timeout, operation="commit-publication-drain"
    ) as acquired:
        timer.lock_wait_seconds = time.monotonic() - lock_wait_start
        if not acquired:
            error = "agents sync lock is busy"
            holder = lock_holder_diagnostic(lock_path)
            if holder is not None:
                error = f"{error}; {holder}"
            timer.stage = "acquire_lock"
            timer.outcome = "lock_busy"
            timer.error = error
            timer.failure_scope = _REPOSITORY_FAILURE_SCOPE
            timer.failure_stage = "acquire_lock"
            emit_drain_timing(timer)
            return _record_failure(
                target,
                error,
                scope=_REPOSITORY_FAILURE_SCOPE,
                stage="acquire_lock",
                timer=timer,
            )
        try:
            with _bounded_publication_drain(
                _configured_publication_drain_timeout(), timer=timer
            ):
                result = _publish_queued_locked(
                    target,
                    owner,
                    git_runner,
                    timer=timer,
                    preferred_key=preferred_key,
                    selected_keys=selected_keys,
                )
        except PublicationDrainTimedOut as exc:
            timer.alarm_fired = True
            if timer.alarm_stage is None:
                timer.alarm_stage = timer.stage or "drain"
                if timer.alarm_keys is None:
                    timer.alarm_keys = tuple(timer.active_keys)
            timer.outcome = "timeout"
            cleanup_notes = "\n".join(getattr(exc, "__notes__", ()))
            timer.error = str(exc)
            if cleanup_notes:
                timer.error = f"{timer.error}; {cleanup_notes}"
            alarm_stage = timer.alarm_stage or timer.stage or "drain"
            if hood_timeout_stage(alarm_stage):
                scope = _HOOD_FAILURE_SCOPE
                keys = (
                    tuple(timer.alarm_keys)
                    if timer.alarm_keys is not None
                    else tuple(timer.active_keys)
                )
            else:
                scope = _REPOSITORY_FAILURE_SCOPE
                keys = ()
            timer.failure_scope = scope
            timer.failure_stage = alarm_stage
            emit_drain_timing(timer)
            return _record_failure(
                target,
                timer.error,
                keys if keys else None,
                scope=scope,
                stage=alarm_stage,
                timer=timer,
            )
    if result.error is not None:
        if result.drained > 0 and (
            result.failure_scope == _REPOSITORY_FAILURE_SCOPE
            or result.failure_scope is None
        ):
            timer.outcome = "published_with_cleanup_error"
            timer.error = result.error
            timer.failure_scope = result.failure_scope or _REPOSITORY_FAILURE_SCOPE
            timer.failure_stage = result.failure_stage or "cleanup"
            emit_drain_timing(timer)
            remaining = list_agent_publications(target.project_key)
            return _CommitPublicationOutcome(
                published=True,
                queued=bool(remaining),
                drained=result.drained,
                quarantined=_quarantined_count(remaining),
                retired=_retired_count(remaining),
                error=result.error,
            )
        timer.outcome = "failed_with_item_errors" if result.drained else "failed"
        timer.error = result.error
        timer.failure_scope = result.failure_scope or _REPOSITORY_FAILURE_SCOPE
        timer.failure_stage = result.failure_stage or timer.stage or "drain"
        emit_drain_timing(timer)
        return _record_failure(
            target,
            result.error,
            result.error_keys,
            scope=result.failure_scope or _REPOSITORY_FAILURE_SCOPE,
            stage=result.failure_stage or timer.stage or "drain",
            timer=timer,
        )

    timer.outcome = "published" if result.drained else "no_requests"
    if result.item_errors:
        timer.error = "; ".join(result.item_errors)
    emit_drain_timing(timer)
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


def _publish_queued_locked(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
    timer: DrainTiming | None = None,
    preferred_key: tuple[str, str] | None = None,
    selected_keys: tuple[tuple[str, str], ...] | None = None,
) -> DrainResult:
    from sase.agents_sync import git_sync

    requests = _active_agent_publications(target.project_key)
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
            failure_scope=_REPOSITORY_FAILURE_SCOPE,
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
            failure_scope=result.failure_scope or _REPOSITORY_FAILURE_SCOPE,
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
        failure_scope=_REPOSITORY_FAILURE_SCOPE,
        failure_stage="cleanup",
    )


def _record_failure(
    target: ProjectTarget,
    error: str,
    logical_keys: tuple[tuple[str, str], ...] | None = None,
    *,
    scope: str | None = None,
    stage: str | None = None,
    timer: DrainTiming | None = None,
) -> _CommitPublicationOutcome:
    failure_scope = scope or _REPOSITORY_FAILURE_SCOPE
    failure_stage = stage or (timer.stage if timer is not None else None) or "drain"
    if timer is not None:
        timer.failure_scope = failure_scope
        timer.failure_stage = failure_stage
    requests = list_agent_publications(target.project_key)
    if logical_keys is None:
        selected = tuple(item.logical_key for item in requests)
    else:
        selected = tuple(logical_keys)
    if not selected:
        remaining = requests
        return _CommitPublicationOutcome(
            queued=bool(remaining),
            quarantined=_quarantined_count(remaining),
            retired=_retired_count(remaining),
            error=error,
        )
    rows = tuple(
        {
            "global_agent": item.global_agent,
            "primary_revision": item.primary_revision,
            "attempts": item.attempts,
            "last_error": item.last_error,
            "terminal_reason": item.terminal_reason,
        }
        for item in requests
        if item.logical_key in frozenset(selected)
    )
    decision: PublicationFailureAccounting | None
    try:
        decision = decide_publication_failure_accounting(
            scope=failure_scope,
            error=error,
            attempted_keys=[
                {"global_agent": key[0], "primary_revision": key[1]} for key in selected
            ],
            rows=rows,
            quarantine_threshold=configured_publication_max_attempts(),
        )
    except Exception:
        decision = None
    if decision is None or not decision.charge:
        remaining = list_agent_publications(target.project_key)
        return _CommitPublicationOutcome(
            queued=bool(remaining),
            quarantined=_quarantined_count(remaining),
            retired=_retired_count(remaining),
            error=error,
        )
    charges: tuple[PublicationFailureCharge, ...] = decision.charges
    retire_reason: str | None = None
    for charge in charges:
        if charge.retire:
            retire_reason = charge.terminal_reason or error
            break
    updated = update_agent_publications(
        target.project_key,
        tuple(charge.logical_key for charge in charges) or selected,
        error=error,
        increment_attempts=True,
        quarantine_threshold=configured_publication_max_attempts(),
        terminal_reason=retire_reason,
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
    "drain_selected_agent_publications",
    "publish_committed_agent_hood",
    "refresh_committed_plan_header",
    "resolve_publication_project_key",
]
