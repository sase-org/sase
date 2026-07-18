"""Per-agent grouping keys, sort keys, and walk-order computation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sase.core.time import local_now
from sase.plan_chain import agent_family_base, canonical_plan_chain_suffix

from ..agent import Agent
from .._agent_tree import (
    agent_tree_depth,
    presentation_anchor,
    presentation_anchor_lookup,
    tree_parent_lookup,
)
from ._buckets import (
    NO_PROJECT,
    GroupingMode,
    bucket_sort_index,
    date_bucket_for,
    date_subgroup_bucket_for,
    date_subgroup_sort_key,
    hour_anchor_time,
    status_bucket_for,
)


def _agent_family_base_from_row(agent: Agent, name: str) -> str | None:
    """Infer a family base only for rows carrying known family metadata."""
    if canonical_plan_chain_suffix(agent.role_suffix) is not None:
        return agent_family_base(name, include_legacy_dash=True)
    return None


def _grouping_name(agent: Agent) -> str:
    """Return the effective name used for root/prefix grouping."""
    if agent.is_clan_container:
        return ""
    if agent.agent_family:
        return agent.agent_family

    if agent.agent_name:
        family_base = _agent_family_base_from_row(agent, agent.agent_name)
        return family_base or agent.agent_name

    name = agent.display_name or ""
    family_base = _agent_family_base_from_row(agent, name)
    if family_base:
        return family_base
    if "." in name:
        return name
    return ""


@dataclass(frozen=True)
class GroupingKeys:
    project: str  # project_name (or NO_PROJECT)
    changespec: str  # real ChangeSpec name (may be "")
    name_root: str
    name_prefix: str
    name_prefix_member_rank: int = 1  # exact prefix marker before descendants
    date_subgroup: str = ""  # populated only under BY_DATE; "" otherwise
    anchor: datetime | None = None  # subgroup sort anchor under BY_DATE


def _project_name(agent: Agent) -> str:
    if not agent.project_file:
        return NO_PROJECT
    return agent.project_display_name or Path(agent.project_file).parent.name


def _name_root(agent: Agent) -> str:
    """Return the grouping root for an agent name."""
    name = _grouping_name(agent)
    if "." in name:
        return name.split(".", 1)[0]
    return name


def _name_prefix(agent: Agent) -> str:
    """Return the first two name segments when the grouping name is dotted."""
    name = _grouping_name(agent)
    parts = name.split(".", 2)
    if len(parts) >= 2:
        return ".".join(parts[:2])
    return ""


def _name_prefix_member_rank(agent: Agent) -> int:
    """Sort exact parent-marker names before their dotted descendants."""
    name = _grouping_name(agent)
    prefix = _name_prefix(agent)
    if prefix and name == prefix:
        return 0
    return 1


def status_grouping_signature(agent: Agent) -> tuple[str, str, str, int]:
    """Return the ``BY_STATUS`` grouping determinants for a single agent.

    Captures exactly the fields that decide which status bucket and
    name-root / name-prefix subgroup a row renders under: the status bucket,
    the name root, the name prefix, and the exact-prefix member rank. Used by
    the in-place row-patch guard to confirm a badge-only change (e.g. a
    deferred live-hint pencil) leaves the row in the same group before patching
    its Option in place; any difference means the row moved and the caller must
    rebuild instead.
    """
    return (
        status_bucket_for(agent),
        _name_root(agent),
        _name_prefix(agent),
        _name_prefix_member_rank(agent),
    )


def _changespec_name_for_grouping(agent: Agent) -> str:
    """Return the real ChangeSpec name for grouping, if any.

    Project-scoped agents use their project name in ``Agent.cl_name`` for
    display/identity, but that value is not a ChangeSpec and should not create
    a duplicate project-name bucket under the project banner.
    """
    if agent.is_clan_container:
        return ""
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


def _date_subgroup_sort_key(
    date_bucket: str, subgroup: str, anchor: datetime | None
) -> tuple[int, int]:
    """Sort key for BY_DATE L1 subgroups within a date bucket.

    Empty ``subgroup`` is the non-BY_DATE neutral (``(0, 0)``) so existing
    orderings under STANDARD / BY_STATUS are preserved byte-for-byte.
    """
    if subgroup == "":
        return (0, 0)
    return date_subgroup_sort_key(date_bucket, subgroup, anchor)


def _l0_value_for(agent: Agent, mode: GroupingMode, now: datetime) -> str:
    """Compute the L0 string value for *agent* under *mode*.

    For STANDARD this is the project name; for BY_DATE / BY_STATUS it's
    the bucket name.  Stored in :class:`GroupingKeys.project` so the
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
    *,
    anchors: dict[int, Agent] | None = None,
) -> GroupingKeys:
    """Compute (L0, changespec, name_root, name_prefix) for *agent*.

    Structural descendants inherit grouping from their outer presentation
    anchor so a banner is never inserted inside a rendered subtree.  ``now``
    is only consulted for ``BY_DATE`` (defaults to ``datetime.now()``);
    ``changespec`` is always empty in non-STANDARD modes since the ChangeSpec
    level disappears from the hierarchy.  ``name_root`` and ``name_prefix``
    are additionally suppressed under ``BY_DATE`` — within a date bucket,
    same-base-name agents are not a meaningful sub-unit, so the bucket renders
    as a flat list sorted by root time.
    """
    target = presentation_anchor(agent, parent_lookup, anchors)
    reference = now if now is not None else local_now()
    l0 = _l0_value_for(target, mode, reference)
    return GroupingKeys(
        project=l0,
        changespec=(
            _changespec_name_for_grouping(target)
            if mode is GroupingMode.STANDARD
            else ""
        ),
        name_root="" if mode is GroupingMode.BY_DATE else _name_root(target),
        name_prefix="" if mode is GroupingMode.BY_DATE else _name_prefix(target),
        name_prefix_member_rank=(
            1 if mode is GroupingMode.BY_DATE else _name_prefix_member_rank(target)
        ),
        date_subgroup=(
            date_subgroup_bucket_for(target, l0) if mode is GroupingMode.BY_DATE else ""
        ),
        anchor=(hour_anchor_time(target) if mode is GroupingMode.BY_DATE else None),
    )


def grouping_keys_for_agents(
    agents: list[Agent],
    mode: GroupingMode = GroupingMode.STANDARD,
    now: datetime | None = None,
) -> list[GroupingKeys]:
    """Public-ish helper exposing per-agent grouping keys."""
    parent_lookup = tree_parent_lookup(agents)
    anchors = presentation_anchor_lookup(agents, parent_lookup)
    reference = now if now is not None else local_now()
    return [
        grouping_keys_for(a, parent_lookup, mode, reference, anchors=anchors)
        for a in agents
    ]


def panel_uses_changespec_level(
    panel_agents: list[Agent],
    mode: GroupingMode = GroupingMode.STANDARD,
    *,
    parent_lookup: dict[str, Agent] | None = None,
    anchors: dict[int, Agent] | None = None,
) -> bool:
    """Whether *panel_agents* should use the 3-level layout.

    Only applies to ``STANDARD`` mode — ``BY_DATE`` and ``BY_STATUS``
    drop the ChangeSpec level entirely, so they always render as
    bucket → name-root.
    """
    if mode is not GroupingMode.STANDARD:
        return False
    lookup = (
        parent_lookup if parent_lookup is not None else tree_parent_lookup(panel_agents)
    )
    anchor_lookup = (
        anchors
        if anchors is not None
        else presentation_anchor_lookup(panel_agents, lookup)
    )
    for agent in panel_agents:
        target = presentation_anchor(agent, lookup, anchor_lookup)
        if _changespec_name_for_grouping(target):
            return True
    return False


def walk_anchors(
    agents: list[Agent],
    parent_lookup: dict[str, Agent],
    mode: GroupingMode,
    *,
    anchors: dict[int, Agent] | None = None,
) -> list[tuple[float, int]]:
    """Per-agent ``(-anchor_epoch, is_child)`` tiebreak under ``BY_DATE``.

    Structural descendants adopt their outer root's anchor.  The depth slot
    remains available to legacy callers; clustered walks preserve projected
    preorder directly rather than sorting descendants by depth.

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
    anchor_lookup = (
        anchors
        if anchors is not None
        else presentation_anchor_lookup(agents, parent_lookup)
    )
    out: list[tuple[float, int]] = []
    for agent in agents:
        target = presentation_anchor(agent, parent_lookup, anchor_lookup)
        is_child = agent_tree_depth(agent) if target is not agent else 0
        anchor_time = hour_anchor_time(target)
        if anchor_time is None:
            anchor = float("inf")
        else:
            anchor = -anchor_time.timestamp()
        out.append((anchor, is_child))
    return out


def walk_order(
    keys_per_agent: list[GroupingKeys],
    anchors: list[tuple[float, int]],
    *,
    use_changespec_level: bool,
    mode: GroupingMode = GroupingMode.STANDARD,
    cluster_roots: list[int] | None = None,
) -> list[int]:
    """Return a stable permutation, optionally treating root trees atomically."""
    parent_keys: list[tuple[str, str]] = [
        (k.project, k.changespec) if use_changespec_level else (k.project, "")
        for k in keys_per_agent
    ]
    root_counts: dict[tuple[tuple[str, str], str], int] = {}
    prefix_counts: dict[tuple[tuple[str, str], str, str], int] = {}
    for parent, k in zip(parent_keys, keys_per_agent, strict=True):
        if k.name_root:
            root_counts[(parent, k.name_root)] = (
                root_counts.get((parent, k.name_root), 0) + 1
            )
        if k.name_root and k.name_prefix:
            prefix_counts[(parent, k.name_root, k.name_prefix)] = (
                prefix_counts.get((parent, k.name_root, k.name_prefix), 0) + 1
            )
    cluster_members: dict[int, list[int]] | None = None
    if cluster_roots is not None and len(cluster_roots) == len(keys_per_agent):
        cluster_members = {}
        for i, root_idx in enumerate(cluster_roots):
            cluster_members.setdefault(root_idx, []).append(i)
        sortable_indices = list(cluster_members)
    else:
        sortable_indices = list(range(len(keys_per_agent)))

    ordered = sorted(
        sortable_indices,
        key=lambda i: (
            _project_sort_key(mode, keys_per_agent[i].project),
            (
                _changespec_sort_key(keys_per_agent[i].changespec)
                if use_changespec_level
                else (0, "")
            ),
            _date_subgroup_sort_key(
                keys_per_agent[i].project,
                keys_per_agent[i].date_subgroup,
                keys_per_agent[i].anchor,
            ),
            _name_root_sort_key(
                keys_per_agent[i].name_root,
                in_group=bool(keys_per_agent[i].name_root)
                and root_counts.get((parent_keys[i], keys_per_agent[i].name_root), 0)
                >= 2,
            ),
            _name_root_sort_key(
                keys_per_agent[i].name_prefix,
                in_group=bool(keys_per_agent[i].name_prefix)
                and prefix_counts.get(
                    (
                        parent_keys[i],
                        keys_per_agent[i].name_root,
                        keys_per_agent[i].name_prefix,
                    ),
                    0,
                )
                >= 2,
            ),
            (
                keys_per_agent[i].name_prefix_member_rank
                if keys_per_agent[i].name_prefix
                and prefix_counts.get(
                    (
                        parent_keys[i],
                        keys_per_agent[i].name_root,
                        keys_per_agent[i].name_prefix,
                    ),
                    0,
                )
                >= 2
                else 0
            ),
            anchors[i][0],
            anchors[i][1],
            i,
        ),
    )
    if cluster_members is None:
        return ordered
    return [i for root_idx in ordered for i in cluster_members[root_idx]]
