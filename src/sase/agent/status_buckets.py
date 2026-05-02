"""Shared status bucket semantics for agent lists."""

from __future__ import annotations

AGENT_STATUS_BUCKETS: tuple[str, ...] = (
    "Needs Attention",
    "Failed",
    "Running",
    "Waiting",
    "Done",
)

AGENT_STATUS_BUCKET_GLYPHS: dict[str, str] = {
    "Needs Attention": "▲",
    "Running": "▶",
    "Waiting": "⏳",
    "Failed": "✗",
    "Done": "✓",
}

# Status mapping for status bucketing.  The semantic line is:
# **Needs Attention** = "you need to act right now"; **Failed** = terminal
# failure; everything else is a state the agent is moving through on its own.
#
# Members of Needs Attention:
#   * ``PLANNING`` — a plan is being drafted and the user is expected to
#     review/answer questions as they arise
#   * ``QUESTION`` — the agent has explicitly paused for an answer
#
# ``FAILED`` statuses are terminal failure states and always land in
# **Failed**, independent of retry-chain lineage.
#
# ``PLAN DONE``, ``PLAN REJECTED``, and ``EPIC CREATED`` are post-plan handoff
# states: the planning work is finished and any code work has been spun off,
# so they read as **Done**.  ``PLAN APPROVED`` is an actively executing state
# and reads as **Running**.
_NEEDS_ATTENTION_STATUSES: frozenset[str] = frozenset({"PLANNING", "QUESTION"})

#: Terminal statuses — agents that have finished and have a meaningful
#: ``stop_time``.  Shared by TUI date bucketing (which sorts these by
#: ``stop_time`` rather than ``start_time``) and status bucketing (which maps
#: these into the ``Done`` bucket).
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"DONE", "PLAN DONE", "PLAN REJECTED", "EPIC CREATED"}
)

# TODO(@user): confirm needs:input mapping. Initial set drawn from
# sdd/tales/202604/agents_tab_query_filters.md — covers the statuses where the
# agent is paused awaiting user input rather than running or terminal.
_NEEDS_INPUT_STATUSES: frozenset[str] = frozenset(
    {"QUESTION", "WAITING INPUT", "PLAN APPROVED"}
)


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
    if status_text in _NEEDS_ATTENTION_STATUSES:
        return "Needs Attention"
    if status_text == "PLAN APPROVED":
        return "Running"
    if status_text == "WAITING":
        return "Waiting"
    if status_text.startswith("FAILED"):
        return "Failed"
    return "Running"
