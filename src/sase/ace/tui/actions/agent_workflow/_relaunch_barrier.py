"""Ordering barrier between a ``,x`` cleanup proc and the launch that follows it.

The prompt bar/stack for a kill-and-edit (``,x``) relaunch mounts immediately,
without waiting for the kill/dismiss persistence proc to settle. What still
must wait is the *launch* that prompt eventually submits: a late bundle write
from the old cleanup must not resurrect a name the replacement agent is about
to reuse. A :class:`_RelaunchCleanupBarrier` records one such in-flight
cleanup; :func:`hold_launch_for_relaunch_cleanup` parks a launch until every
open barrier settles.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

RELAUNCH_CLEANUP_BARRIER_TIMEOUT_SECONDS = 30.0

_MISSING = object()


@dataclass
class _RelaunchCleanupBarrier:
    """One in-flight kill-and-edit cleanup a replacement launch must follow."""

    label: str
    settled: bool = False
    _timer: object | None = None


def open_relaunch_cleanup_barrier(app: object, label: str) -> _RelaunchCleanupBarrier:
    """Register one in-flight cleanup a replacement launch must wait on."""
    barrier = _RelaunchCleanupBarrier(label=label)
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
        if barriers:
            return

    _drain_relaunch_cleanup_launch_waiters(app)


def _relaunch_cleanup_is_pending(app: object) -> bool:
    """Return whether any relaunch cleanup barrier is still open."""
    return bool(getattr(app, "_relaunch_cleanup_barriers", None))


def hold_launch_for_relaunch_cleanup(app: object, resume: Callable[[], None]) -> bool:
    """Park *resume* until every pending relaunch cleanup barrier settles.

    Returns ``True`` when the launch was held (nothing else to do here) or
    ``False`` when nothing was pending and the caller should proceed with the
    launch immediately.
    """
    if not _relaunch_cleanup_is_pending(app):
        return False

    waiters = getattr(app, "_relaunch_cleanup_launch_waiters", None)
    if waiters is None:
        waiters = []
        app._relaunch_cleanup_launch_waiters = waiters  # type: ignore[attr-defined]
    waiters.append(resume)

    notify = getattr(app, "notify", None)
    if callable(notify):
        notify("Waiting for kill/dismiss cleanup to finish before launching...")
    return True


def _drain_relaunch_cleanup_launch_waiters(app: object) -> None:
    waiters = getattr(app, "_relaunch_cleanup_launch_waiters", None)
    if not waiters:
        return
    # Swap the list out before replaying so a thunk that re-parks (a second
    # ``,x`` mid-drain) appends to a fresh list instead of looping forever.
    app._relaunch_cleanup_launch_waiters = []  # type: ignore[attr-defined]
    for resume in waiters:
        # The prompt bar was cancelled while the launch was held: the base
        # context is gone (its text already saved to prompt history), so
        # replaying would only produce a spurious "cannot launch" toast.
        if getattr(app, "_prompt_context", _MISSING) is None:
            log.debug("Dropping parked relaunch: prompt context was cancelled")
            continue
        resume()


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
