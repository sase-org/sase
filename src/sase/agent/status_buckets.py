"""Shared status bucket semantics for agent lists."""

from __future__ import annotations

AGENT_STATUS_BUCKETS: tuple[str, ...] = (
    "Stopped",
    "Failed",
    "Starting",
    "Running",
    "Waiting",
    "Done",
)

AGENT_STATUS_BUCKET_GLYPHS: dict[str, str] = {
    "Stopped": "▲",
    "Starting": "◐",
    "Running": "▶",
    "Waiting": "⏳",
    "Failed": "✗",
    "Done": "✓",
}

PLAN_APPROVED_STATUS = "PLAN APPROVED"
TALE_APPROVED_STATUS = "TALE APPROVED"
EPIC_APPROVED_STATUS = "EPIC APPROVED"
LEGEND_APPROVED_STATUS = "LEGEND APPROVED"
PLAN_COMMITTED_STATUS = "PLAN COMMITTED"
WORKING_PLAN_STATUS = "WORKING PLAN"
WORKING_TALE_STATUS = "WORKING TALE"
FEEDBACK_STATUS = "FEEDBACK"

APPROVED_PLAN_STATUSES: frozenset[str] = frozenset(
    {PLAN_APPROVED_STATUS, TALE_APPROVED_STATUS}
)
WORKING_PLAN_STATUSES: frozenset[str] = frozenset(
    {WORKING_PLAN_STATUS, WORKING_TALE_STATUS}
)
ACTIVE_PLAN_HANDOFF_STATUSES: frozenset[str] = (
    APPROVED_PLAN_STATUSES | WORKING_PLAN_STATUSES
)
WORKING_PLAN_STATUS_TO_APPROVED: dict[str, str] = {
    WORKING_PLAN_STATUS: PLAN_APPROVED_STATUS,
    WORKING_TALE_STATUS: TALE_APPROVED_STATUS,
}

#: Statuses where an agent is paused for explicit human input.  This is
#: intentionally narrower than ``needs:input`` query matching, which also
#: includes execution states such as ``PLAN APPROVED``.
AGENT_ASKING_STATUSES: frozenset[str] = frozenset({"PLAN", "QUESTION", "WAITING INPUT"})

# Status mapping for status bucketing.  The semantic line is:
# **Stopped** = the agent has stopped and is waiting for you to act;
# **Failed** = terminal failure; everything else is a state the agent is
# moving through on its own.
#
# Members of Stopped:
#   * ``PLAN`` — a submitted plan is waiting for user review
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
_STOPPED_STATUSES: frozenset[str] = frozenset({"PLAN", "QUESTION"})

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
    if status_text == "WAITING":
        return "Waiting"
    if status_text.startswith("FAILED"):
        return "Failed"
    return "Running"
