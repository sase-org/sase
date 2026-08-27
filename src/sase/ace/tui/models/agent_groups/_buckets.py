"""Sentinels, ``GroupingMode``, and date/status bucket helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from sase.agent.status_buckets import (
    _NEEDS_INPUT_STATUSES,
    _STOPPED_STATUSES,
    _TERMINAL_STATUSES,
    agent_status_bucket,
)
from sase.gate_shell.state import gate_state_is_terminal
from sase.monitor_state import monitor_state_is_terminal

from ..agent import Agent
from ..date_subgroups import (
    day_subgroup_label,
    day_subgroup_sort_key,
    one_hour_window_label,
    one_hour_window_sort_key,
    week_subgroup_label,
    week_subgroup_sort_key,
)

#: Sentinel used as the project key for agents without a ``project_file``.
NO_PROJECT = ""

#: Synthetic Patch bucket label for agents with no ``cl_name`` in a
#: panel that otherwise has at least one Patch.
NO_PATCH_LABEL = "(no Patch)"

#: Synthetic subgroup label for agents with no usable anchor time
#: under :data:`GroupingMode.BY_DATE`.  Sorts last within its date bucket.
NO_HOUR_LABEL = "(no time)"


class GroupingMode(Enum):
    """How the Agents-tab tree is bucketed at L0.

    - ``STANDARD``: existing behavior — L0 is the project; Patch
      level is added per-panel when at least one agent has a ``cl_name``.
    - ``BY_DATE``: L0 is a date bucket (``Today`` / ``Yesterday`` /
      ``This Week`` / ``Earlier``) derived from each agent's shared
      BY_DATE anchor.
    - ``BY_STATUS``: L0 is a status bucket (``Stopped`` / ``Failed`` /
      ``Running`` / ``Queued`` / ``Waiting`` / ``Done`` / ``Starting``)
      derived from each agent's ``status``.

    In ``BY_DATE`` and ``BY_STATUS`` modes the project and Patch
    levels disappear.  ``BY_DATE`` renders date bucket → date-aware
    subgroup (1-hour under Today/Yesterday, calendar day under This Week,
    Monday-start week under Earlier), while ``BY_STATUS`` renders status
    bucket → name-root with the same singleton-suppression rule as
    ``STANDARD`` mode.
    """

    STANDARD = "standard"
    BY_DATE = "by_date"
    BY_STATUS = "by_status"


_DATE_BUCKETS: tuple[str, ...] = ("Today", "Yesterday", "This Week", "Earlier")
# User-attention priority: actionable stopped/failed work first, active work
# next, then waiting and completed work. Keep transient startup rows last.
_STATUS_BUCKETS: tuple[str, ...] = (
    "Stopped",
    "Failed",
    "Running",
    "Queued",
    "Waiting",
    "Done",
    "Starting",
)


def date_anchor_time(agent: Agent) -> datetime | None:
    """Return the shared BY_DATE anchor for an agent.

    Terminal agents anchor on ``stop_time`` (falling back to
    ``start_time`` when missing); everything else anchors on ``start_time``.
    Durable shell rows key terminality on their shell state rather than the
    displayed status label, so a custom stop label such as ``TESTED`` still
    anchors on ``stop_time``. The same anchor decides the L0 bucket, L1
    subgroup label, and sort position so the BY_DATE tree remains internally
    consistent.
    """
    if agent.is_monitor:
        return (
            (agent.stop_time or agent.start_time)
            if monitor_state_is_terminal(agent.monitor_state)
            else agent.start_time
        )
    if agent.is_gate:
        return (
            (agent.stop_time or agent.start_time)
            if gate_state_is_terminal(agent.gate_state)
            else agent.start_time
        )
    if (agent.status or "") in _TERMINAL_STATUSES:
        return agent.stop_time or agent.start_time
    return agent.start_time


def date_bucket_for(agent: Agent, now: datetime) -> str:
    """Map an agent's BY_DATE anchor to one of the date buckets.

    Buckets compare on calendar dates in ``now``'s local frame:

    - ``Today``: same calendar date as ``now``.
    - ``Yesterday``: the day before ``now``.
    - ``This Week``: within the prior six days, but not Today/Yesterday.
    - ``Earlier``: anything older, plus agents with no BY_DATE anchor.
    """
    anchor = date_anchor_time(agent)
    if anchor is None:
        return "Earlier"
    today = now.date()
    anchor_date = anchor.date()
    if anchor_date == today:
        return "Today"
    if anchor_date == today - timedelta(days=1):
        return "Yesterday"
    if anchor_date > today - timedelta(days=7):
        return "This Week"
    return "Earlier"


def date_subgroup_bucket_for(agent: Agent, date_bucket: str) -> str:
    """Map an agent's anchor time to a BY_DATE L1 subgroup label.

    The label depends on the L0 *date_bucket*:

    - ``Today`` / ``Yesterday`` → 1-hour ``HH:00`` window.
    - ``This Week`` → calendar-day label (e.g. ``Fri Apr 24``).
    - ``Earlier`` → Monday-start week range (e.g. ``Apr 21-27``).

    Uses :func:`date_anchor_time`, the same rule used for the L0 bucket
    and walk-order anchor, so subgroup banners agree with the bucket and sort
    position.

    Returns :data:`NO_HOUR_LABEL` for agents with no usable anchor; that
    sub-bucket sorts last within its date bucket.
    """
    anchor = date_anchor_time(agent)
    if anchor is None:
        return NO_HOUR_LABEL
    if date_bucket in {"Today", "Yesterday"}:
        return one_hour_window_label(anchor)
    if date_bucket == "This Week":
        return day_subgroup_label(anchor)
    if date_bucket == "Earlier":
        return week_subgroup_label(anchor)
    return ""


def date_subgroup_sort_key(
    date_bucket: str, subgroup: str, anchor: datetime | None
) -> tuple[int, int]:
    """Sort key for BY_DATE L1 subgroups within a date bucket.

    Newest-first within real labels, with ``NO_HOUR_LABEL`` placed last.
    ``anchor`` should be the value from :func:`date_anchor_time`, which also
    decides the L0 bucket. Mirrors the Patches tab's sort rule so both tabs
    agree on subgroup order.
    """
    if not subgroup:
        return (0, 0)
    if subgroup == NO_HOUR_LABEL:
        return (2, 0)
    if anchor is None:
        return (1, 0)
    if date_bucket in {"Today", "Yesterday"}:
        return one_hour_window_sort_key(subgroup)
    if date_bucket == "This Week":
        return day_subgroup_sort_key(anchor)
    if date_bucket == "Earlier":
        return week_subgroup_sort_key(anchor)
    return (1, 0)


def status_bucket_for(agent: Agent) -> str:
    """Map ``agent.status`` to a status bucket.

    See the ``_STOPPED_STATUSES`` comment above for the mapping
    rules.  ``FAILED`` display statuses land in ``Failed`` and ``WAITING``
    statuses land in ``Waiting``.  Anything not explicitly bucketed lands in
    ``Running`` (the agent is in flight from the user's perspective).
    """
    return agent_status_bucket(agent)


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
