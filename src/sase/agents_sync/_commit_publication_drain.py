"""Coordinate bounded publication drains and account for failed attempts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
import signal
import threading
import time

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync._commit_publication_locked import publish_queued_locked
from sase.agents_sync._commit_publication_outbox import (
    quarantined_count,
    retired_count,
)
from sase.agents_sync._commit_publication_types import (
    HOOD_FAILURE_SCOPE,
    REPOSITORY_FAILURE_SCOPE,
    CommitPublicationOutcome,
)
from sase.agents_sync.commit_publication_transaction import hood_timeout_stage
from sase.core.agent_publication_recovery import (
    PublicationFailureAccounting,
    PublicationFailureCharge,
    decide_publication_failure_accounting,
)
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.git_sync_ops import lock_holder_diagnostic
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import (
    configured_publication_max_attempts,
    list_agent_publications,
    update_agent_publications,
)
from sase.agents_sync.publication_timing import DrainTiming, emit_drain_timing
from sase.agents_sync import _commit_publication_support as publication_support

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


def drain_agent_publications(
    project_key: str,
    *,
    git_runner: GitRunner = run_git,
    preferred_key: tuple[str, str] | None = None,
    selected_keys: tuple[tuple[str, str], ...] | None = None,
) -> CommitPublicationOutcome:
    """Drain active agent-hood requests for one project under its sidecar lock."""

    timer = DrainTiming(project_key=project_key)
    selection = publication_support.resolve_sync_targets((project_key,))
    if len(selection.targets) != 1:
        outcome = selection.outcomes[0] if selection.outcomes else None
        detail = (
            (outcome.skip_reason or outcome.error) if outcome is not None else None
        ) or "agents target is unavailable"
        timer.stage = "resolve_target"
        timer.outcome = "target_unavailable"
        timer.error = detail
        emit_drain_timing(timer)
        return CommitPublicationOutcome(
            skip_reason=f"project {project_key!r} has no usable agents target: {detail}"
        )
    target = selection.targets[0]
    try:
        owner = publication_support.require_agent_owner_identity()
    except Exception as exc:
        timer.stage = "resolve_owner"
        timer.outcome = "owner_unavailable"
        timer.error = f"owner identity is unavailable: {exc}"
        emit_drain_timing(timer)
        return CommitPublicationOutcome(error=f"owner identity is unavailable: {exc}")

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
        timer.failure_scope = REPOSITORY_FAILURE_SCOPE
        timer.failure_stage = "ensure_clone"
        emit_drain_timing(timer)
        return _record_failure(
            target,
            clone_error,
            scope=REPOSITORY_FAILURE_SCOPE,
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
            timer.failure_scope = REPOSITORY_FAILURE_SCOPE
            timer.failure_stage = "acquire_lock"
            emit_drain_timing(timer)
            return _record_failure(
                target,
                error,
                scope=REPOSITORY_FAILURE_SCOPE,
                stage="acquire_lock",
                timer=timer,
            )
        try:
            with _bounded_publication_drain(
                _configured_publication_drain_timeout(), timer=timer
            ):
                result = publish_queued_locked(
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
                scope = HOOD_FAILURE_SCOPE
                keys = (
                    tuple(timer.alarm_keys)
                    if timer.alarm_keys is not None
                    else tuple(timer.active_keys)
                )
            else:
                scope = REPOSITORY_FAILURE_SCOPE
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
            result.failure_scope == REPOSITORY_FAILURE_SCOPE
            or result.failure_scope is None
        ):
            timer.outcome = "published_with_cleanup_error"
            timer.error = result.error
            timer.failure_scope = result.failure_scope or REPOSITORY_FAILURE_SCOPE
            timer.failure_stage = result.failure_stage or "cleanup"
            emit_drain_timing(timer)
            remaining = list_agent_publications(target.project_key)
            return CommitPublicationOutcome(
                published=True,
                queued=bool(remaining),
                drained=result.drained,
                quarantined=quarantined_count(remaining),
                retired=retired_count(remaining),
                error=result.error,
            )
        timer.outcome = "failed_with_item_errors" if result.drained else "failed"
        timer.error = result.error
        timer.failure_scope = result.failure_scope or REPOSITORY_FAILURE_SCOPE
        timer.failure_stage = result.failure_stage or timer.stage or "drain"
        emit_drain_timing(timer)
        return _record_failure(
            target,
            result.error,
            result.error_keys,
            scope=result.failure_scope or REPOSITORY_FAILURE_SCOPE,
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
    return CommitPublicationOutcome(
        published=result.drained > 0,
        queued=bool(remaining),
        drained=result.drained,
        quarantined=quarantined_count(remaining),
        retired=retired_count(remaining),
        error="; ".join(result.item_errors) if result.item_errors else None,
    )


def _record_failure(
    target: ProjectTarget,
    error: str,
    logical_keys: tuple[tuple[str, str], ...] | None = None,
    *,
    scope: str | None = None,
    stage: str | None = None,
    timer: DrainTiming | None = None,
) -> CommitPublicationOutcome:
    failure_scope = scope or REPOSITORY_FAILURE_SCOPE
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
        return CommitPublicationOutcome(
            queued=bool(remaining),
            quarantined=quarantined_count(remaining),
            retired=retired_count(remaining),
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
        return CommitPublicationOutcome(
            queued=bool(remaining),
            quarantined=quarantined_count(remaining),
            retired=retired_count(remaining),
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
    return CommitPublicationOutcome(
        queued=True,
        quarantined=quarantined_count(updated),
        retired=retired_count(updated),
        error=error,
    )
