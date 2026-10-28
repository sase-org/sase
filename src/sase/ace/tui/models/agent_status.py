"""TUI-facing agent status predicates."""

from __future__ import annotations

from sase.agent.status_buckets import status_bucket_for_values, valid_status_bucket

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

# Terminal rows whose finished chats can be opened or forked.  PLAN REJECTED
# remains excluded because its outcome never releases the implied #fork wait;
# STOPPED never ran, so it has no chat.
RESUMABLE_DONE_STATUSES = frozenset(
    {"DONE", "PLAN COMMITTED", "PLAN DONE", "TALE DONE", "EPIC CREATED"}
)


def is_resumable_done_status(status: str) -> bool:
    """Return True for terminal agent rows whose chats can be opened or forked."""
    return status in RESUMABLE_DONE_STATUSES


def is_unread_completed_status(status: str) -> bool:
    """Return True for terminal statuses that can be surfaced as unread."""
    return status in DISMISSABLE_STATUSES


def is_stopped_agent_status(status: str) -> bool:
    """Return True for statuses displayed in the Stopped agent bucket."""
    return status_bucket_for_values(status) == "Stopped"


def is_stopped_agent(agent: object) -> bool:
    """Return True for rows displayed in the Stopped agent bucket.

    Honors an explicit ``status_bucket`` override exactly like the grouping
    and header counts (``agent_status_bucket``), so a pending custom gate
    whose display label is free-form (``CONFIRM``) counts as stopped and a
    settling gate still labeled ``PLAN`` does not.
    """
    override = valid_status_bucket(getattr(agent, "status_bucket", None))
    if override is not None:
        return override == "Stopped"
    status = getattr(agent, "status", None)
    return isinstance(status, str) and is_stopped_agent_status(status)


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
