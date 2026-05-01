"""Shared status bucket semantics for agent lists."""

from __future__ import annotations

AGENT_STATUS_BUCKETS: tuple[str, ...] = (
    "Needs Attention",
    "Running",
    "Waiting",
    "Failed",
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
# **Needs Attention** = "you need to act right now"; everything else is a
# state the agent is moving through on its own.
#
# Members of Needs Attention:
#   * ``PLANNING`` — a plan is being drafted and the user is expected to
#     review/answer questions as they arise
#   * ``QUESTION`` — the agent has explicitly paused for an answer
#   * ``FAILED`` without ``retried_as_timestamp`` (handled by the
#     ``startswith("FAILED")`` branch below, not by this frozenset)
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
# plans/202604/agents_tab_query_filters.md — covers the statuses where the
# agent is paused awaiting user input rather than running or terminal.
_NEEDS_INPUT_STATUSES: frozenset[str] = frozenset(
    {"QUESTION", "WAITING INPUT", "PLAN APPROVED"}
)


def status_bucket_for_values(
    status: str | None,
    retried_as_timestamp: str | None = None,
) -> str:
    """Map a status string plus retry lineage to a status bucket."""
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
        if not retried_as_timestamp:
            return "Needs Attention"
        return "Failed"
    return "Running"
