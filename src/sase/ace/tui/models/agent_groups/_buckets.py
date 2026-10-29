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
from sase.gate_turn.state import gate_state_is_terminal
from sase.monitor_state import monitor_state_is_terminal
from sase.monitor_status import monitor_status_pair

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
      ``Running`` / ``Monitoring`` / ``Queued`` / ``Waiting`` / ``Done`` /
      ``Starting``) derived from each agent's ``status``.
    - ``BY_MACHINE``: L0 is the fleet machine alias, with local rows under
      ``local``.  Each machine bucket is further sub-grouped by the same
      priority-ordered status bucket used by ``BY_STATUS``, then by
      name-root / name-prefix within each (machine, status) pair.

    In ``BY_DATE``, ``BY_STATUS``, and ``BY_MACHINE`` modes the project and Patch
    levels disappear.  ``BY_DATE`` renders date bucket → date-aware
    subgroup (1-hour under Today/Yesterday, calendar day under This Week,
    Monday-start week under Earlier), while ``BY_STATUS`` renders
    bucket → name-root with the same singleton-suppression rule as
    ``STANDARD`` mode.  ``BY_MACHINE`` renders machine → status subgroup →
    name-root, with every status subgroup banner always visible (no
    singleton suppression, since every real status bucket is meaningful).
    """

    STANDARD = "standard"
    BY_DATE = "by_date"
    BY_STATUS = "by_status"
    BY_MACHINE = "by_machine"


_DATE_BUCKETS: tuple[str, ...] = ("Today", "Yesterday", "This Week", "Earlier")
# User-attention priority: actionable stopped/failed work first, active work
# next (live monitors sit beside Running), then waiting and completed work.
# Keep transient startup rows last.
_STATUS_BUCKETS: tuple[str, ...] = (
    "Stopped",
    "Failed",
    "Running",
    "Monitoring",
    "Queued",
    "Waiting",
    "Done",
    "Starting",
)

#: Grouping-only TUI label for rows displaying a running monitor's start
#: label. Not a shared status bucket: query filters, counts, and integrations
#: keep reading such rows as ``Running``.
MONITORING_STATUS_GROUP = "Monitoring"


def date_anchor_time(agent: Agent) -> datetime | None:
    """Return the shared BY_DATE anchor for an agent.

    Terminal agents anchor on ``stop_time`` (falling back to
    ``start_time`` when missing); everything else anchors on ``start_time``.
    Durable turn rows key terminality on their turn state rather than the
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


def row_displays_live_monitor(agent: Agent) -> bool:
    """Return whether *agent* currently shows a running monitor's start label.

    Row-local: reads only the row's own ``status``, ``monitor_start_status``,
    ``monitor_stop_status``, and ``monitor_state`` so per-row grouping
    signatures stay cheap and consistent. Matches the same
    status-equals-pair-start rule as ``monitor_status_presentation``: a live
    monitor (non-terminal ``monitor_state``) whose ``status`` equals the
    pair's start half. A missing or unknown ``monitor_state`` counts as live,
    following the doctrine that a monitor that has not reported never reads
    as finished.
    """
    start = agent.monitor_start_status
    stop = agent.monitor_stop_status
    if not start and not stop:
        return False
    if monitor_state_is_terminal(agent.monitor_state):
        return False
    pair = monitor_status_pair(start, stop)
    return (agent.status or "").casefold() == pair.start.casefold()


def status_bucket_for(agent: Agent) -> str:
    """Map ``agent.status`` to a status bucket.

    See the ``_STOPPED_STATUSES`` comment above for the mapping
    rules.  ``FAILED`` display statuses land in ``Failed`` and ``WAITING``
    statuses land in ``Waiting``.  Anything not explicitly bucketed lands in
    ``Running`` (the agent is in flight from the user's perspective).

    Rows whose shared bucket is ``Running`` but which display a running
    monitor's start label group under the grouping-only ``Monitoring`` label.
    """
    bucket = agent_status_bucket(agent)
    if bucket == "Running" and row_displays_live_monitor(agent):
        return MONITORING_STATUS_GROUP
    return bucket


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
