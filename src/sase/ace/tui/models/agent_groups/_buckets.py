"""Sentinels, ``GroupingMode``, and date/status bucket helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from ..agent import Agent

#: Sentinel used as the project key for agents without a ``project_file``.
NO_PROJECT = ""

#: Synthetic ChangeSpec bucket label for agents with no ``cl_name`` in a
#: panel that otherwise has at least one ChangeSpec.
NO_CHANGESPEC_LABEL = "(no ChangeSpec)"

#: Synthetic hour-bucket label for agents with no usable anchor time
#: under :data:`GroupingMode.BY_DATE`.  Sorts last within its date bucket.
NO_HOUR_LABEL = "(no time)"


class GroupingMode(Enum):
    """How the Agents-tab tree is bucketed at L0.

    - ``STANDARD``: existing behavior — L0 is the project; ChangeSpec
      level is added per-panel when at least one agent has a ``cl_name``.
    - ``BY_DATE``: L0 is a date bucket (``Today`` / ``Yesterday`` /
      ``This Week`` / ``Earlier``) derived from each agent's ``start_time``.
    - ``BY_STATUS``: L0 is a status bucket (``Needs Attention`` /
      ``Running`` / ``Failed`` / ``Done``) derived from each agent's
      ``status`` and retry-chain lineage.

    In ``BY_DATE`` and ``BY_STATUS`` modes the project and ChangeSpec
    levels disappear: L0 is the bucket, L1 is the name-root, and the
    same singleton-suppression rule applies as in ``STANDARD`` mode.
    """

    STANDARD = "standard"
    BY_DATE = "by_date"
    BY_STATUS = "by_status"


_DATE_BUCKETS: tuple[str, ...] = ("Today", "Yesterday", "This Week", "Earlier")
_STATUS_BUCKETS: tuple[str, ...] = (
    "Needs Attention",
    "Running",
    "Waiting",
    "Failed",
    "Done",
)

# Status mapping for ``BY_STATUS`` bucketing.  The semantic line is:
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
# ``PLAN DONE``, ``PLAN REJECTED``, and ``EPIC CREATED`` are post-plan handoff states: the
# planning work is finished and any code work has been spun off, so they
# read as **Done**.  ``PLAN APPROVED`` is an actively executing state and
# reads as **Running**.  All ``WAITING`` variants land in **Waiting**
# regardless of timer/dependency presence.
_NEEDS_ATTENTION_STATUSES: frozenset[str] = frozenset({"PLANNING", "QUESTION"})

#: Terminal statuses — agents that have finished and have a meaningful
#: ``stop_time``.  Shared by :func:`status_bucket_for` (which maps these
#: into the ``Done`` bucket) and :func:`walk_anchors` (which sorts these
#: by ``stop_time`` rather than ``start_time``).
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"DONE", "PLAN DONE", "PLAN REJECTED", "EPIC CREATED"}
)

# TODO(@user): confirm needs:input mapping. Initial set drawn from
# plans/202604/agents_tab_query_filters.md — covers the statuses where the
# agent is paused awaiting user input rather than running or terminal.
_NEEDS_INPUT_STATUSES: frozenset[str] = frozenset(
    {"QUESTION", "WAITING INPUT", "PLAN APPROVED"}
)


def date_bucket_for(agent: Agent, now: datetime) -> str:
    """Map ``agent.start_time`` to one of the date buckets.

    Buckets compare on calendar dates in ``now``'s local frame:

    - ``Today``: same calendar date as ``now``.
    - ``Yesterday``: the day before ``now``.
    - ``This Week``: within the prior six days, but not Today/Yesterday.
    - ``Earlier``: anything older, plus agents with no ``start_time``.
    """
    start = agent.start_time
    if start is None:
        return "Earlier"
    today = now.date()
    start_date = start.date()
    if start_date == today:
        return "Today"
    if start_date == today - timedelta(days=1):
        return "Yesterday"
    if start_date > today - timedelta(days=7):
        return "This Week"
    return "Earlier"


def hour_anchor_time(agent: Agent) -> datetime | None:
    """Return the datetime an agent's hour bucket should anchor on.

    Terminal agents (``DONE`` / ``PLAN DONE`` / ``PLAN REJECTED`` /
    ``EPIC CREATED``) anchor on
    ``stop_time`` (falling back to ``start_time`` when missing); everything
    else anchors on ``start_time``.  Mirrors :func:`walk_anchors` so the
    hour banner emitted for an agent always agrees with the anchor used
    to sort it inside its date bucket.
    """
    if (agent.status or "") in _TERMINAL_STATUSES:
        return agent.stop_time or agent.start_time
    return agent.start_time


def hour_bucket_for(agent: Agent) -> str:
    """Map an agent's anchor time to an ``HH:00`` bucket label.

    Uses ``stop_time`` for terminal agents (falling back to ``start_time``
    when missing) and ``start_time`` otherwise — same rule as
    :func:`walk_anchors` so hour banners agree with the sort order inside
    each date bucket.

    Returns :data:`NO_HOUR_LABEL` for agents with no usable anchor; that
    bucket sorts last within its date bucket.

    Note: under ``BY_DATE``'s ``Earlier`` bucket, agents with the same
    hour-of-day on different calendar dates land in the same ``HH:00``
    sub-bucket.  This is intentional for v1 — the design trades calendar
    precision for compactness inside the already-coarse ``Earlier``
    bucket — not a bug.
    """
    anchor = hour_anchor_time(agent)
    if anchor is None:
        return NO_HOUR_LABEL
    return f"{anchor.hour:02d}:00"


def status_bucket_for(agent: Agent) -> str:
    """Map ``agent.status`` (plus retry lineage) to a status bucket.

    See the ``_NEEDS_ATTENTION_STATUSES`` comment above for the mapping
    rules.  All ``WAITING`` variants land in ``Waiting``.  Anything not
    explicitly bucketed lands in ``Running`` (the agent is in flight from
    the user's perspective).
    """
    status = agent.status or ""
    if status in _TERMINAL_STATUSES:
        return "Done"
    if status in _NEEDS_ATTENTION_STATUSES:
        return "Needs Attention"
    if status == "PLAN APPROVED":
        return "Running"
    if status == "WAITING":
        return "Waiting"
    if status.startswith("FAILED"):
        if not agent.retried_as_timestamp:
            return "Needs Attention"
        return "Failed"
    return "Running"


def bucket_sort_index(mode: GroupingMode, bucket: str) -> int:
    """Fixed bucket ordering for ``BY_DATE`` / ``BY_STATUS`` L0 keys.

    Unknown bucket names sort last so a stale bucket label can never
    silently clobber a valid one.
    """
    order = _DATE_BUCKETS if mode is GroupingMode.BY_DATE else _STATUS_BUCKETS
    try:
        return order.index(bucket)
    except ValueError:
        return len(order)
