"""Per-agent grouping keys, sort keys, and walk-order computation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..agent import Agent
from ..date_subgroups import four_hour_window_sort_key, one_hour_window_sort_key
from ._buckets import (
    NO_HOUR_LABEL,
    NO_PROJECT,
    GroupingMode,
    hour_anchor_time,
    bucket_sort_index,
    date_bucket_for,
    one_hour_bucket_for,
    status_bucket_for,
    time_window_bucket_for,
)


@dataclass(frozen=True)
class _GroupingKeys:
    project: str  # project_name (or NO_PROJECT)
    changespec: str  # real ChangeSpec name (may be "")
    name_root: str
    hour: str = ""  # populated only under BY_DATE; "" otherwise
    one_hour: str = ""  # populated only under real BY_DATE 4-hour windows


def _project_name(agent: Agent) -> str:
    if not agent.project_file:
        return NO_PROJECT
    return Path(agent.project_file).parent.name


def _name_root(agent: Agent) -> str:
    """Return the grouping root for an agent name."""
    if agent.agent_name:
        if "." in agent.agent_name:
            return agent.agent_name.split(".", 1)[0]
        return agent.agent_name

    name = agent.display_name or ""
    if "." in name:
        return name.split(".", 1)[0]
    return ""


def _changespec_name_for_grouping(agent: Agent) -> str:
    """Return the real ChangeSpec name for grouping, if any.

    Project-scoped agents use their project name in ``Agent.cl_name`` for
    display/identity, but that value is not a ChangeSpec and should not create
    a duplicate project-name bucket under the project banner.
    """
    if agent.is_project_agent:
        return ""
    return agent.cl_name or ""


def _project_sort_key(mode: GroupingMode, project: str) -> tuple[int, str | int]:
    """Sort key for L0 banners.

    STANDARD: named projects first, ``(no project)`` last.
    BY_DATE / BY_STATUS: fixed bucket order (newest-first / priority-first).
    """
    if mode is GroupingMode.STANDARD:
        if project:
            return (0, project.lower())
        return (1, "")
    return (0, bucket_sort_index(mode, project))


def _changespec_sort_key(changespec: str) -> tuple[int, str]:
    """Sort key for ChangeSpecs — named first, synthetic bucket last."""
    if changespec:
        return (0, changespec.lower())
    return (1, "")


def _name_root_sort_key(name_root: str, in_group: bool) -> tuple[int, str]:
    """Sort key for name-roots — ungrouped (dotless or singleton) sorts first."""
    return (1, name_root.lower()) if in_group else (0, "")


def _hour_sort_key(hour: str) -> tuple[int, int]:
    """Sort key for time windows — newest window first, ``(no time)`` last.

    Empty ``hour`` is the non-BY_DATE neutral (``(0, 0)``) so existing
    orderings under STANDARD / BY_STATUS are preserved byte-for-byte.
    """
    if hour == "":
        return (0, 0)
    if hour == NO_HOUR_LABEL:
        return (2, 0)
    return four_hour_window_sort_key(hour)


def _one_hour_sort_key(one_hour: str) -> tuple[int, int]:
    """Sort key for hourly BY_DATE subgroups — newest hour first."""
    if one_hour == "":
        return (0, 0)
    return one_hour_window_sort_key(one_hour)


def _l0_value_for(agent: Agent, mode: GroupingMode, now: datetime) -> str:
    """Compute the L0 string value for *agent* under *mode*.

    For STANDARD this is the project name; for BY_DATE / BY_STATUS it's
    the bucket name.  Stored in :class:`_GroupingKeys.project` so the
    rest of the tree-building plumbing stays unchanged.
    """
    if mode is GroupingMode.STANDARD:
        return _project_name(agent)
    if mode is GroupingMode.BY_DATE:
        return date_bucket_for(agent, now)
    return status_bucket_for(agent)


def grouping_keys_for(
    agent: Agent,
    parent_lookup: dict[str, Agent],
    mode: GroupingMode = GroupingMode.STANDARD,
    now: datetime | None = None,
) -> _GroupingKeys:
    """Compute (L0, changespec, name_root) for *agent* under *mode*.

    Workflow children inherit grouping from their parent so a banner is
    never inserted between a parent and its workflow steps.  ``now`` is
    only consulted for ``BY_DATE`` (defaults to ``datetime.now()``);
    ``changespec`` is always empty in non-STANDARD modes since the
    ChangeSpec level disappears from the hierarchy.  ``name_root`` is
    additionally suppressed under ``BY_DATE`` — within a date bucket,
    same-base-name agents are not a meaningful sub-unit, so the bucket
    renders as a flat list sorted by ``start_time``.
    """
    target = agent
    if agent.is_workflow_child and agent.parent_timestamp:
        parent = parent_lookup.get(agent.parent_timestamp)
        if parent is not None:
            target = parent
    reference = now if now is not None else datetime.now()
    return _GroupingKeys(
        project=_l0_value_for(target, mode, reference),
        changespec=(
            _changespec_name_for_grouping(target)
            if mode is GroupingMode.STANDARD
            else ""
        ),
        name_root="" if mode is GroupingMode.BY_DATE else _name_root(target),
        hour=time_window_bucket_for(target) if mode is GroupingMode.BY_DATE else "",
        one_hour=one_hour_bucket_for(target) if mode is GroupingMode.BY_DATE else "",
    )


def grouping_keys_for_agents(
    agents: list[Agent],
    mode: GroupingMode = GroupingMode.STANDARD,
    now: datetime | None = None,
) -> list[_GroupingKeys]:
    """Public-ish helper exposing per-agent grouping keys."""
    parent_lookup: dict[str, Agent] = {
        a.raw_suffix: a for a in agents if a.raw_suffix and not a.is_workflow_child
    }
    reference = now if now is not None else datetime.now()
    return [grouping_keys_for(a, parent_lookup, mode, reference) for a in agents]


def panel_uses_changespec_level(
    panel_agents: list[Agent], mode: GroupingMode = GroupingMode.STANDARD
) -> bool:
    """Whether *panel_agents* should use the 3-level layout.

    Only applies to ``STANDARD`` mode — ``BY_DATE`` and ``BY_STATUS``
    drop the ChangeSpec level entirely, so they always render as
    bucket → name-root.
    """
    if mode is not GroupingMode.STANDARD:
        return False
    parent_lookup: dict[str, Agent] = {
        a.raw_suffix: a
        for a in panel_agents
        if a.raw_suffix and not a.is_workflow_child
    }
    for agent in panel_agents:
        target = agent
        if agent.is_workflow_child and agent.parent_timestamp:
            target = parent_lookup.get(agent.parent_timestamp, agent)
        if _changespec_name_for_grouping(target):
            return True
    return False


def walk_anchors(
    agents: list[Agent],
    parent_lookup: dict[str, Agent],
    mode: GroupingMode,
) -> list[tuple[float, int]]:
    """Per-agent ``(-anchor_epoch, is_child)`` tiebreak under ``BY_DATE``.

    Workflow children adopt their parent's anchor and a ``1`` in the
    ``is_child`` slot so they sort immediately after the parent
    regardless of the child's own timestamps.  Non-``BY_DATE`` modes
    return a constant ``(0.0, 0)`` per agent so the sort is unchanged.

    Terminal agents (``DONE`` / ``PLAN DONE`` / ``EPIC CREATED``) anchor
    on ``stop_time`` so a recently-finished agent floats to the top of
    the Done segment regardless of when it started; they fall back to
    ``start_time`` when ``stop_time`` is missing.  Non-terminal agents
    continue to anchor on ``start_time``.

    Agents with no usable anchor sort last within their bucket (``+inf``
    in the negated-epoch slot).
    """
    if mode is not GroupingMode.BY_DATE:
        return [(0.0, 0)] * len(agents)
    out: list[tuple[float, int]] = []
    for agent in agents:
        target = agent
        is_child = 0
        if agent.is_workflow_child and agent.parent_timestamp:
            parent = parent_lookup.get(agent.parent_timestamp)
            if parent is not None:
                target = parent
                is_child = 1
        anchor_time = hour_anchor_time(target)
        if anchor_time is None:
            anchor = float("inf")
        else:
            anchor = -anchor_time.timestamp()
        out.append((anchor, is_child))
    return out


def walk_order(
    keys_per_agent: list[_GroupingKeys],
    anchors: list[tuple[float, int]],
    *,
    use_changespec_level: bool,
    mode: GroupingMode = GroupingMode.STANDARD,
) -> list[int]:
    """Return a stable permutation of agent indices sorted by grouping keys."""
    parent_keys: list[tuple[str, str]] = [
        (k.project, k.changespec) if use_changespec_level else (k.project, "")
        for k in keys_per_agent
    ]
    root_counts: dict[tuple[tuple[str, str], str], int] = {}
    for parent, k in zip(parent_keys, keys_per_agent, strict=True):
        if k.name_root:
            root_counts[(parent, k.name_root)] = (
                root_counts.get((parent, k.name_root), 0) + 1
            )
    return sorted(
        range(len(keys_per_agent)),
        key=lambda i: (
            _project_sort_key(mode, keys_per_agent[i].project),
            (
                _changespec_sort_key(keys_per_agent[i].changespec)
                if use_changespec_level
                else (0, "")
            ),
            _hour_sort_key(keys_per_agent[i].hour),
            _one_hour_sort_key(keys_per_agent[i].one_hour),
            _name_root_sort_key(
                keys_per_agent[i].name_root,
                in_group=bool(keys_per_agent[i].name_root)
                and root_counts.get((parent_keys[i], keys_per_agent[i].name_root), 0)
                >= 2,
            ),
            anchors[i][0],
            anchors[i][1],
            i,
        ),
    )
