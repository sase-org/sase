"""Raise and reconcile the one pending gate each live bead may have.

A task bead is either ready — awaiting a ``TaskTriage`` decision — or snoozed,
awaiting a ``BeadSnooze`` wake. A task bead of type ``flag`` whose removal
thresholds have both passed awaits a ``FlagTriage`` decision. All three gate
kinds are reconciled here, in one lane state and under one lock, because
"which gate does this bead have" is a single question: a second chop owning a
second kind could only race this one into giving a bead two pending gates.

A gateable bead is deferred while work is in flight (an active launch proc
**or** a live agent). A pending gate is left in place while the launch proc
is still running — the launch may still fail — and canceled with reason
``bead_work_in_flight`` once a live agent owns the bead.

A pending gate whose rendered presentation drifted is re-presented in place:
its successor generation adopts the pending gate's notification row, and only
then is the superseded gate retired without settling that row. The inbox keeps
one row per bead and gate kind, whose read, dismissed, and snooze state
survive; a row is new and unread only when the gate kind changes or the bead
re-enters a gateable state.

Dismissing a pending triage, snooze, or flag gate's notification cancels it
with reason ``notification_dismissed`` instead of refreshing it. The
cancellation sticks in lane state: no new gate rises for that bead until its
kind changes or it leaves and re-enters a gateable state. Settled bundles of
these kinds older than the configured horizon are reaped under the creation
lock with a per-pass cap; other gate kinds are only counted."""

from __future__ import annotations

from sase.scripts._bead_task_triage_reconcile import (
    AUTOMATION_OWNED_KINDS,
    main,
)

__all__ = ["AUTOMATION_OWNED_KINDS", "main"]

if __name__ == "__main__":
    main()
