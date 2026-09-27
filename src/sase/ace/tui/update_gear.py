"""Pure three-state updates-gear model and yellow restart copy.

Precedence is green > yellow > red: live work always wins, a queued
restart (at most 60 s, about to change the process) outranks a sticky
failure, and red waits. All three gears share one slot so the badge
never shifts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

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


def restart_pending_tooltip(pending: PendingUpdateRestart) -> str:
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
    return (
        "New SASE code installed · restart queued\n"
        f"{wait_line}\n"
        f"If they are still running at {restart_at}, ACE restarts anyway.\n"
        "Click to see what it is waiting on."
    )


def _format_hms(epoch: float) -> str:
    """Format *epoch* as local-time ``HH:MM:SS``."""
    return datetime.fromtimestamp(epoch).strftime("%H:%M:%S")


__all__ = [
    "PendingUpdateRestart",
    "UpdateGearState",
    "resolve_update_gear",
    "restart_pending_tooltip",
]
