"""TUI-facing agent status predicates."""

from __future__ import annotations

from sase.agent.status_buckets import status_bucket_for_values

# Statuses that indicate an agent is dismissable (shows "x dismiss" in footer).
DISMISSABLE_STATUSES = {
    "DONE",
    "FAILED",
    "PLAN COMMITTED",
    "PLAN DONE",
    "TALE DONE",
    "PLAN REJECTED",
    "EPIC CREATED",
}


def is_unread_completed_status(status: str) -> bool:
    """Return True for terminal statuses that can be surfaced as unread."""
    return status in DISMISSABLE_STATUSES


def is_stopped_agent_status(status: str) -> bool:
    """Return True for statuses displayed in the Stopped agent bucket."""
    return status_bucket_for_values(status) == "Stopped"
