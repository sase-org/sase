"""TUI-facing agent status predicates."""

from __future__ import annotations

from sase.agent.status_buckets import status_bucket_for_values

# Shared semantic colors for agent-status presentation.
RUNNING_COLOR = "#FFD700"
STOPPED_STATUS = "STOPPED"
STOPPED_COLOR = "#8787AF"
# U+2298 (circled division slash) renders as a missing-glyph box in the
# pinned Fira Code visual snapshots; Ø preserves the slashed-circle identity.
STOPPED_GLYPH = "Ø"

# Statuses that indicate an agent is dismissable (shows "x dismiss" in footer).
DISMISSABLE_STATUSES = {
    "DONE",
    "FAILED",
    "PLAN COMMITTED",
    "PLAN DONE",
    "TALE DONE",
    "PLAN REJECTED",
    "EPIC CREATED",
    STOPPED_STATUS,
}

RESUMABLE_DONE_STATUSES = frozenset({"DONE", "PLAN DONE", "TALE DONE"})


def is_resumable_done_status(status: str) -> bool:
    """Return True for terminal agent rows that can resume a chat."""
    return status in RESUMABLE_DONE_STATUSES


def is_unread_completed_status(status: str) -> bool:
    """Return True for terminal statuses that can be surfaced as unread."""
    return status in DISMISSABLE_STATUSES


def is_stopped_agent_status(status: str) -> bool:
    """Return True for statuses displayed in the Stopped agent bucket."""
    return status_bucket_for_values(status) == "Stopped"


def is_failed_agent_status(status: str) -> bool:
    """Return True for displayed statuses that represent failed agents."""
    return status.startswith("FAILED")


def is_revertable_agent_status(status: str) -> bool:
    """Return True for terminal/done agent rows whose commits can be reverted.

    Accepts every status that means the agent finished work that could have
    produced commits: the :data:`DISMISSABLE_STATUSES` set plus any displayed
    ``FAILED*`` status (e.g. ``FAILED (RETRIED)``). Active/input states such as
    ``RUNNING``, ``STARTING``, ``WAITING``, ``PLAN``, and ``QUESTION`` are
    rejected.

    ``STOPPED`` is dismissable but never revertable: a repeat slot skipped by a
    predecessor's ``STOP`` never executed, so it has no commits to revert.
    """
    if status == STOPPED_STATUS:
        return False
    return status in DISMISSABLE_STATUSES or is_failed_agent_status(status)
