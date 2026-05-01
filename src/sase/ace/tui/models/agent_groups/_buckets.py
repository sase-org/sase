"""Sentinels, ``GroupingMode``, and date/status bucket helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKETS,
    _NEEDS_ATTENTION_STATUSES,
    _NEEDS_INPUT_STATUSES,
    _TERMINAL_STATUSES,
    status_bucket_for_values,
)

from ..agent import Agent
from ..date_subgroups import four_hour_window_label, one_hour_window_label

#: Sentinel used as the project key for agents without a ``project_file``.
NO_PROJECT = ""

#: Synthetic ChangeSpec bucket label for agents with no ``cl_name`` in a
#: panel that otherwise has at least one ChangeSpec.
NO_CHANGESPEC_LABEL = "(no ChangeSpec)"

#: Synthetic time-window label for agents with no usable anchor time
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
    levels disappear.  ``BY_DATE`` renders date bucket → 4-hour window →
    one-hour window, while ``BY_STATUS`` renders status bucket → name-root
    with the same singleton-suppression rule as ``STANDARD`` mode.
    """

    STANDARD = "standard"
    BY_DATE = "by_date"
    BY_STATUS = "by_status"


_DATE_BUCKETS: tuple[str, ...] = ("Today", "Yesterday", "This Week", "Earlier")
_STATUS_BUCKETS: tuple[str, ...] = (*AGENT_STATUS_BUCKETS,)


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
    """Return the datetime an agent's time window should anchor on.

    Terminal agents (``DONE`` / ``PLAN DONE`` / ``PLAN REJECTED`` /
    ``EPIC CREATED``) anchor on
    ``stop_time`` (falling back to ``start_time`` when missing); everything
    else anchors on ``start_time``.  Mirrors :func:`walk_anchors` so the
    time-window banner emitted for an agent always agrees with the anchor used
    to sort it inside its date bucket.
    """
    if (agent.status or "") in _TERMINAL_STATUSES:
        return agent.stop_time or agent.start_time
    return agent.start_time


def time_window_bucket_for(agent: Agent) -> str:
    """Map an agent's anchor time to a 4-hour window label.

    Uses ``stop_time`` for terminal agents (falling back to ``start_time``
    when missing) and ``start_time`` otherwise — same rule as
    :func:`walk_anchors` so time-window banners agree with the sort order
    inside each date bucket.

    Returns :data:`NO_HOUR_LABEL` for agents with no usable anchor; that
    bucket sorts last within its date bucket.

    Note: under ``BY_DATE``'s ``Earlier`` bucket, agents with the same
    4-hour window on different calendar dates land in the same sub-bucket.
    This is intentional — the design trades calendar precision for
    compactness inside the already-coarse ``Earlier`` bucket.
    """
    anchor = hour_anchor_time(agent)
    if anchor is None:
        return NO_HOUR_LABEL
    return four_hour_window_label(anchor)


def one_hour_bucket_for(agent: Agent) -> str:
    """Map an agent's anchor time to a one-hour ``HH:00`` label.

    Returns an empty string when no real anchor exists so callers can keep
    ``(no time)`` as a terminal synthetic bucket.
    """
    anchor = hour_anchor_time(agent)
    if anchor is None:
        return ""
    return one_hour_window_label(anchor)


def hour_bucket_for(agent: Agent) -> str:
    """Compatibility alias for :func:`time_window_bucket_for`."""
    return time_window_bucket_for(agent)


def status_bucket_for(agent: Agent) -> str:
    """Map ``agent.status`` (plus retry lineage) to a status bucket.

    See the ``_NEEDS_ATTENTION_STATUSES`` comment above for the mapping
    rules.  All ``WAITING`` variants land in ``Waiting``.  Anything not
    explicitly bucketed lands in ``Running`` (the agent is in flight from
    the user's perspective).
    """
    return status_bucket_for_values(agent.status, agent.retried_as_timestamp)


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
