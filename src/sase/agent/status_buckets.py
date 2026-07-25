"""Shared status bucket semantics for agent lists."""

from __future__ import annotations

AGENT_STATUS_BUCKETS: tuple[str, ...] = (
    "Stopped",
    "Failed",
    "Starting",
    "Running",
    "Queued",
    "Waiting",
    "Done",
)

AGENT_STATUS_BUCKET_GLYPHS: dict[str, str] = {
    "Stopped": "▲",
    "Starting": "◐",
    "Running": "▶",
    "Queued": "…",
    "Waiting": "⏳",
    "Failed": "✗",
    "Done": "✓",
}

QUEUED_STATUS = "QUEUED"
QUEUED_STATUS_BUCKET = "Queued"
QUEUED_STATUS_COLOR = "#5F87FF"
PRE_RUN_WAIT_STATUSES: frozenset[str] = frozenset({"WAITING", QUEUED_STATUS})

PLAN_APPROVED_STATUS = "PLAN APPROVED"
TALE_APPROVED_STATUS = "TALE APPROVED"
EPIC_APPROVED_STATUS = "EPIC APPROVED"
PLAN_COMMITTED_STATUS = "PLAN COMMITTED"
WORKING_PLAN_STATUS = "WORKING PLAN"
WORKING_TALE_STATUS = "WORKING TALE"
FEEDBACK_STATUS = "FEEDBACK"

PENDING_PLAN_STATUS = "PLAN"
PENDING_TALE_STATUS = "TALE"
PENDING_EPIC_STATUS = "EPIC"
#: Pending-review statuses in display-priority order (largest ask first).
PENDING_PLAN_REVIEW_STATUSES: tuple[str, ...] = (
    PENDING_EPIC_STATUS,
    PENDING_TALE_STATUS,
    PENDING_PLAN_STATUS,
)
PENDING_PLAN_REVIEW_STATUS_SET: frozenset[str] = frozenset(PENDING_PLAN_REVIEW_STATUSES)

APPROVED_PLAN_STATUSES: frozenset[str] = frozenset(
    {PLAN_APPROVED_STATUS, TALE_APPROVED_STATUS}
)
WORKING_PLAN_STATUSES: frozenset[str] = frozenset(
    {WORKING_PLAN_STATUS, WORKING_TALE_STATUS}
)
ACTIVE_PLAN_HANDOFF_STATUSES: frozenset[str] = (
    APPROVED_PLAN_STATUSES | WORKING_PLAN_STATUSES
)
AUTO_APPROVE_ELIGIBLE_STATUSES: frozenset[str] = frozenset(
    {
        "STARTING",
        "RUNNING",
        *PENDING_PLAN_REVIEW_STATUSES,
        *ACTIVE_PLAN_HANDOFF_STATUSES,
        "WAITING",
        QUEUED_STATUS,
        "QUESTION",
    }
)
WORKING_PLAN_STATUS_TO_APPROVED: dict[str, str] = {
    WORKING_PLAN_STATUS: PLAN_APPROVED_STATUS,
    WORKING_TALE_STATUS: TALE_APPROVED_STATUS,
}

#: Statuses that mean an agent process is actually in flight.  This is
#: deliberately narrower than the ``Running`` bucket used by filters: sticky
#: approved planner statuses bucket as running for query purposes, but the
#: planner process has finished by the time those labels are displayed.
ACTIVE_AGENT_STATUSES: frozenset[str] = frozenset(
    {
        "STARTING",
        "RUNNING",
        "RETRYING",
        "ANSWERED",
        WORKING_PLAN_STATUS,
        WORKING_TALE_STATUS,
        EPIC_APPROVED_STATUS,
        PLAN_COMMITTED_STATUS,
    }
)

#: Statuses where an agent is paused for explicit human input.  This is
#: intentionally narrower than ``needs:input`` query matching, which also
#: includes execution states such as ``PLAN APPROVED``.
AGENT_ASKING_STATUSES: frozenset[str] = frozenset(
    PENDING_PLAN_REVIEW_STATUS_SET | {"QUESTION", "WAITING INPUT"}
)

# Status mapping for status bucketing.  The semantic line is:
# **Stopped** = the agent has stopped and is waiting for you to act;
# **Failed** = terminal failure; everything else is a state the agent is
# moving through on its own.
#
# Members of Stopped:
#   * ``PLAN`` / ``TALE`` / ``EPIC`` — a submitted plan is waiting for review
#   * ``QUESTION`` — the agent has explicitly paused for an answer
#
# ``FAILED`` statuses are terminal failure states and always land in
# **Failed**, independent of retry-chain lineage.
#
# ``PLAN DONE``, ``TALE DONE``, ``PLAN REJECTED``, and ``EPIC CREATED`` are
# post-plan handoff states: the planning work is finished and any code work
# has been spun off, so they read as **Done**.  ``PLAN APPROVED`` /
# ``TALE APPROVED`` and the coder-specific ``WORKING PLAN`` /
# ``WORKING TALE`` statuses are actively executing states and read as
# **Running**.
#
# ``STOPPED`` is a terminal, non-error state for a repeat-chain slot a
# predecessor's ``STOP`` skipped.  It reads as **Done** (finished, not failed,
# nothing for the user to act on) — it is intentionally *not* a member of
# ``_STOPPED_STATUSES`` (those are actionable input pauses).
_STOPPED_STATUSES: frozenset[str] = frozenset(
    PENDING_PLAN_REVIEW_STATUS_SET | {"QUESTION"}
)

#: Terminal statuses — agents that have finished and have a meaningful
#: ``stop_time``.  Shared by TUI date bucketing (which sorts these by
#: ``stop_time`` rather than ``start_time``) and status bucketing (which maps
#: these into the ``Done`` bucket).
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        "DONE",
        "PLAN DONE",
        "TALE DONE",
        "PLAN REJECTED",
        "EPIC CREATED",
        "STOPPED",
        FEEDBACK_STATUS,
    }
)

# TODO(@user): confirm needs:input mapping. Initial set drawn from
# sdd/tales/202604/agents_tab_query_filters.md — covers the statuses where the
# agent is paused awaiting user input rather than running or terminal.
_NEEDS_INPUT_STATUSES: frozenset[str] = frozenset(
    {"QUESTION", "WAITING INPUT"} | ACTIVE_PLAN_HANDOFF_STATUSES
)


def agent_is_asking(status: str | None) -> bool:
    """Return whether *status* represents a human-input pause."""
    return (status or "") in AGENT_ASKING_STATUSES


def pending_plan_status_for_tier(tier: str | None) -> str:
    """Return the pending-review status for an authored plan tier."""
    normalized = tier.strip().lower() if isinstance(tier, str) else ""
    if normalized == "tale":
        return PENDING_TALE_STATUS
    if normalized == "epic":
        return PENDING_EPIC_STATUS
    return PENDING_PLAN_STATUS


def is_pending_plan_review_status(status: str | None) -> bool:
    """Return whether *status* represents a pending plan review."""
    return (status or "") in PENDING_PLAN_REVIEW_STATUS_SET


def agent_is_active(status: str | None) -> bool:
    """Return whether *status* represents an in-flight agent process."""
    return (status or "") in ACTIVE_AGENT_STATUSES


def runner_slot_display_status(
    status: str | None,
    *,
    globally_queued: bool,
) -> str:
    """Return the reversible display status for runner-slot context.

    ``QUEUED`` is derived only for live agents waiting solely on the global
    runner cap. Persisted and scan-level statuses remain ``WAITING``.
    """
    status_text = status or ""
    if status_text not in PRE_RUN_WAIT_STATUSES:
        return status_text
    return QUEUED_STATUS if globally_queued else "WAITING"


def status_bucket_for_values(
    status: str | None,
    retried_as_timestamp: str | None = None,
) -> str:
    """Map a status string to a status bucket.

    ``retried_as_timestamp`` remains accepted for callers that already have
    retry metadata, but failure bucketing is based on the displayed status.
    """
    del retried_as_timestamp
    status_text = status or ""
    if status_text in _TERMINAL_STATUSES:
        return "Done"
    if status_text in _STOPPED_STATUSES:
        return "Stopped"
    if status_text == "STARTING":
        return "Starting"
    # ``ANSWERED`` is the transient post-answer state: the user replied and the
    # agent is expected to resume, so it buckets with the actively-running rows
    # rather than the input-needed ``Stopped`` group.
    if status_text in ACTIVE_PLAN_HANDOFF_STATUSES or status_text == "ANSWERED":
        return "Running"
    if status_text == QUEUED_STATUS:
        return QUEUED_STATUS_BUCKET
    if status_text == "WAITING":
        return "Waiting"
    if status_text.startswith("FAILED"):
        return "Failed"
    return "Running"
