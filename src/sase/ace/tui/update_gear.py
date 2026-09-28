"""Pure three-state updates-gear model and yellow restart copy.

Precedence is green > yellow > red: live work always wins, a queued
restart (at most 60 s, about to change the process) outranks a sticky
failure, and red waits. All three gears share one slot so the badge
never shifts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from time import time as unix_time
from typing import TYPE_CHECKING, Literal

from sase.core.time import format_local, parse_local

if TYPE_CHECKING:
    from sase.ace._update_attempts_model import UpdateFailure

UpdateGearState = Literal["updating", "restart_pending", "failed"]


@dataclass(frozen=True, slots=True)
class PendingUpdateRestart:
    """Coalesced in-memory record for one tracked restart wait."""

    blocker_labels: tuple[str, ...]
    blocker_identities: tuple[str, ...]
    queued_at: float
    restart_by: float


def resolve_update_gear(
    *,
    updating: bool,
    restart_pending: bool,
    failed: bool,
) -> UpdateGearState | None:
    """Return the single visible gear for the three inputs."""
    if updating:
        return "updating"
    if restart_pending:
        return "restart_pending"
    if failed:
        return "failed"
    return None


def restart_pending_tooltip(
    pending: PendingUpdateRestart,
    *,
    failure: UpdateFailure | None = None,
) -> str:
    """Return the yellow-gear tooltip with absolute times."""
    labels = tuple(pending.blocker_labels)
    count = len(labels)
    if count == 0:
        wait_line = "ACE and the SASE service restart shortly."
    else:
        noun = "proc" if count == 1 else "procs"
        verb = "finishes" if count == 1 else "finish"
        shown = ", ".join(labels[:3])
        suffix = "" if count <= 3 else f" +{count - 3} more"
        wait_line = (
            f"ACE and the SASE service restart once {count} {noun} "
            f"{verb}: {shown}{suffix}."
        )
    restart_at = _format_hms(pending.restart_by)
    lines = [
        "New SASE code installed · restart queued",
        wait_line,
        f"If they are still running at {restart_at}, ACE restarts anyway.",
    ]
    if failure is not None and failure.finished_at >= pending.queued_at:
        lines.append("The update also reported a failure; details after the restart.")
    lines.append("Click to see what it is waiting on.")
    return "\n".join(lines)


def format_failure_when(epoch: float, *, now: float | None = None) -> str:
    """Return ``today at 14:32`` style copy for a failure timestamp."""
    moment = parse_local(epoch)
    reference = parse_local(now if now is not None else unix_time())
    if moment is None or reference is None:
        return format_local(epoch, "%b %d at %H:%M")
    clock = format_local(epoch, "%H:%M")
    day = moment.date()
    today = reference.date()
    if day == today:
        return f"today at {clock}"
    if day == today - timedelta(days=1):
        return f"yesterday at {clock}"
    return format_local(epoch, "%b %d") + f" at {clock}"


def failure_tooltip(failure: UpdateFailure) -> str:
    """Return the red-gear tooltip with absolute times."""
    when = format_failure_when(failure.finished_at)
    if failure.interrupted:
        return (
            f"Last update was interrupted · {when}\n"
            f'ACE exited before "{failure.label}" finished; '
            "the install may be incomplete.\n"
            "Click for the failure report."
        )
    return (
        f"Last update failed · {when}\n"
        f"{failure.label}: {failure.error}\n"
        "Click for the failure report."
    )


def _format_hms(epoch: float) -> str:
    """Format *epoch* as local-time ``HH:MM:SS``."""
    return format_local(epoch, "%H:%M:%S")


__all__ = [
    "PendingUpdateRestart",
    "UpdateGearState",
    "failure_tooltip",
    "format_failure_when",
    "resolve_update_gear",
    "restart_pending_tooltip",
]
