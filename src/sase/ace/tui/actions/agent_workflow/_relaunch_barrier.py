"""Ordering barrier between a ``,x`` cleanup proc and the launch that follows it.

The prompt bar/stack for a kill-and-edit (``,x``) relaunch mounts immediately,
without waiting for the kill/dismiss persistence proc to settle. What still
must wait is the *launch* that prompt eventually submits: a late bundle write
from the old cleanup must not resurrect a name the replacement agent is about
to reuse. A :class:`_RelaunchCleanupBarrier` records one such in-flight
cleanup; :func:`hold_launch_for_relaunch_cleanup` parks a launch until every
open barrier settles.

An in-flight ``,X`` deferred kill is an additional hold: the replacement
launch must wait through the T0→T4 window until the pending kill is
abandoned or the ordinary cleanup barrier opened at T4 takes over.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from ._types import PromptSessionId, RelaunchOperation, prompt_session_is_live

log = logging.getLogger(__name__)

RELAUNCH_CLEANUP_BARRIER_TIMEOUT_SECONDS = 30.0
PENDING_LAUNCH_KILL_TIMEOUT_SECONDS = 180.0


@dataclass
class _RelaunchCleanupBarrier:
    """One in-flight kill-and-edit cleanup a replacement launch must follow."""

    label: str
    operation: RelaunchOperation | None = None
    settled: bool = False
    _timer: object | None = None


@dataclass
class _RelaunchParkedLaunch:
    """One accepted launch parked behind its owning relaunch cleanup."""

    resume: Callable[[], None]
    owner_id: PromptSessionId | None = None
    operation: RelaunchOperation | None = None
    replayed: bool = False


def open_relaunch_cleanup_barrier(
    app: object,
    label: str,
    *,
    operation: RelaunchOperation | None = None,
) -> _RelaunchCleanupBarrier:
    """Register one in-flight cleanup a replacement launch must wait on."""
    barrier = _RelaunchCleanupBarrier(label=label, operation=operation)
    barriers = getattr(app, "_relaunch_cleanup_barriers", None)
    if barriers is None:
        barriers = []
        app._relaunch_cleanup_barriers = barriers  # type: ignore[attr-defined]
    barriers.append(barrier)

    set_timer = getattr(app, "set_timer", None)
    if callable(set_timer):
        barrier._timer = set_timer(
            RELAUNCH_CLEANUP_BARRIER_TIMEOUT_SECONDS,
            lambda: _settle_on_timeout(app, barrier),
            name="relaunch-cleanup-barrier-timeout",
        )
    return barrier


def settle_relaunch_cleanup_barrier(
    app: object, barrier: _RelaunchCleanupBarrier
) -> None:
    """Settle *barrier*; idempotent since a timeout can race the real settle."""
    if barrier.settled:
        return
    barrier.settled = True

    timer, barrier._timer = barrier._timer, None
    if timer is not None:
        stop = getattr(timer, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass

    barriers = getattr(app, "_relaunch_cleanup_barriers", None)
    if barriers is not None:
        barriers[:] = [candidate for candidate in barriers if candidate is not barrier]
        if _barriers_pending_for_operation(app, barrier.operation):
            return

    _drain_relaunch_cleanup_launch_waiters(app, barrier.operation)


def _relaunch_cleanup_is_pending(
    app: object,
    *,
    operation: RelaunchOperation | None = None,
    legacy_global: bool = False,
) -> bool:
    """Return whether a replacement launch must wait on cleanup or a pending kill."""
    if legacy_global:
        if getattr(app, "_relaunch_cleanup_barriers", None):
            return True
    elif _barriers_pending_for_operation(app, operation):
        return True

    from ._launch_records import has_pending_launch_kill

    if legacy_global:
        return has_pending_launch_kill(app)
    if operation is None:
        return False
    return has_pending_launch_kill(app, operation=operation)


def hold_launch_for_relaunch_cleanup(
    app: object,
    resume: Callable[[], None],
    *,
    owner_id: PromptSessionId | None = None,
    operation: RelaunchOperation | None = None,
) -> bool:
    """Park *resume* until every pending relaunch cleanup barrier settles.

    Returns ``True`` when the launch was held (nothing else to do here) or
    ``False`` when nothing was pending and the caller should proceed with the
    launch immediately.
    """
    legacy_global = owner_id is None and operation is None
    if not _relaunch_cleanup_is_pending(
        app, operation=operation, legacy_global=legacy_global
    ):
        return False

    waiters = getattr(app, "_relaunch_cleanup_launch_waiters", None)
    if waiters is None:
        waiters = []
        app._relaunch_cleanup_launch_waiters = waiters  # type: ignore[attr-defined]
    waiters.append(
        _RelaunchParkedLaunch(
            resume=resume,
            owner_id=owner_id,
            operation=operation,
        )
    )

    notify = getattr(app, "notify", None)
    if callable(notify):
        if _barriers_pending_for_operation(app, operation, legacy_global=legacy_global):
            notify("Waiting for kill/dismiss cleanup to finish before launching...")
        else:
            notify("Waiting for the last launch to finish so it can be killed...")
    return True


def release_relaunch_holds_if_idle(
    app: object,
    *,
    operation: RelaunchOperation | None = None,
) -> None:
    """Replay parked launches when no cleanup barrier or pending kill remains."""
    legacy_global = operation is None
    if not _relaunch_cleanup_is_pending(
        app, operation=operation, legacy_global=legacy_global
    ):
        _drain_relaunch_cleanup_launch_waiters(app, operation)


def _drain_relaunch_cleanup_launch_waiters(
    app: object,
    operation: RelaunchOperation | None = None,
) -> None:
    waiters = getattr(app, "_relaunch_cleanup_launch_waiters", None)
    if not waiters:
        return
    # Swap the list out before replaying so a thunk that re-parks (a second
    # ``,x`` mid-drain) appends to a fresh list instead of looping forever.
    app._relaunch_cleanup_launch_waiters = []  # type: ignore[attr-defined]
    kept: list[_RelaunchParkedLaunch] = []
    for waiter in waiters:
        if not isinstance(waiter, _RelaunchParkedLaunch):
            if operation is None:
                waiter()
            else:
                kept.append(_RelaunchParkedLaunch(resume=waiter))
            continue
        if waiter.operation is not operation and operation is not None:
            if waiter.owner_id is None and waiter.operation is None:
                if _relaunch_cleanup_is_pending(app, legacy_global=True):
                    kept.append(waiter)
                    continue
            else:
                kept.append(waiter)
                continue
        if waiter.replayed:
            continue
        # The prompt bar was cancelled or replaced while the launch was held.
        # Requiring the original owner prevents an old callback from borrowing
        # a later prompt context.
        if not prompt_session_is_live(app, waiter.owner_id):
            log.debug("Dropping parked relaunch: prompt owner was retired")
            continue
        if _relaunch_cleanup_is_pending(
            app,
            operation=waiter.operation,
            legacy_global=waiter.owner_id is None and waiter.operation is None,
        ):
            kept.append(waiter)
            continue
        waiter.replayed = True
        waiter.resume()
    if kept:
        current = getattr(app, "_relaunch_cleanup_launch_waiters", None)
        if current:
            kept.extend(current)
        app._relaunch_cleanup_launch_waiters = kept  # type: ignore[attr-defined]


def _barriers_pending_for_operation(
    app: object,
    operation: RelaunchOperation | None,
    *,
    legacy_global: bool = False,
) -> bool:
    barriers = getattr(app, "_relaunch_cleanup_barriers", None) or ()
    if legacy_global:
        return bool(barriers)
    return any(
        isinstance(barrier, _RelaunchCleanupBarrier)
        and barrier.operation is operation
        and not barrier.settled
        for barrier in barriers
    )


def _settle_on_timeout(app: object, barrier: _RelaunchCleanupBarrier) -> None:
    if barrier.settled:
        return
    log.warning(
        "Relaunch cleanup barrier %r timed out after %.1fs; releasing held launches",
        barrier.label,
        RELAUNCH_CLEANUP_BARRIER_TIMEOUT_SECONDS,
    )
    settle_relaunch_cleanup_barrier(app, barrier)
    notify = getattr(app, "notify", None)
    if callable(notify):
        notify(
            "Kill/dismiss cleanup did not settle in time; launching without "
            "waiting for it.",
            severity="warning",
        )
