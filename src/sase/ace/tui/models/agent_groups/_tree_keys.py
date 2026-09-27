"""Banner-key enumeration for the grouped agent tree."""

from __future__ import annotations

from datetime import datetime

from sase.core.time import local_now

from ..agent import Agent
from ..agent_panels import panel_key_per_agent
from ..group_fold import GroupKey
from ._buckets import GroupingMode
from ._tree_walk import grouped_walk, should_emit_subgroup_banner


def enumerate_group_keys(
    agents: list[Agent],
    mode: GroupingMode = GroupingMode.STANDARD,
    now: datetime | None = None,
) -> list[GroupKey]:
    """Return the deduplicated list of all banner keys present in *agents*.

    Partitions *agents* by panel key so each panel's mode (2- vs 3-level)
    is decided independently, mirroring :func:`build_agent_tree`.  The
    name-root and name-prefix banners are only included when their group
    has 2+ entries; BY_DATE subgroup keys mirror the visible banner
    predicate (synthetic ``(no time)`` only emits with 2+ agents).
    """
    if not agents:
        return []
    panel_keys = panel_key_per_agent(agents)
    panel_to_indices: dict[str | None, list[int]] = {}
    for i, pk in enumerate(panel_keys):
        panel_to_indices.setdefault(pk, []).append(i)

    reference = now if now is not None else local_now()
    seen: set[GroupKey] = set()
    out: list[GroupKey] = []
    for indices in panel_to_indices.values():
        panel_agents = [agents[i] for i in indices]
        panel_walk = grouped_walk(panel_agents, mode, reference)
        keys_per_agent = panel_walk.keys_per_agent
        use_cs = panel_walk.use_patch_level
        walk = panel_walk.indices
        root_counts: dict[tuple[tuple[str, ...], str], int] = {}
        prefix_counts: dict[tuple[tuple[str, ...], str, str], int] = {}
        subgroup_counts: dict[tuple[str, str], int] = {}
        for k in keys_per_agent:
            if use_cs:
                parent: tuple[str, ...] = (k.project, k.patch)
            elif mode is GroupingMode.BY_MACHINE:
                parent = (k.project, k.subgroup)
            else:
                parent = (k.project,)
            if k.name_root:
                root_counts[(parent, k.name_root)] = (
                    root_counts.get((parent, k.name_root), 0) + 1
                )
            if k.name_root and k.name_prefix:
                prefix_counts[(parent, k.name_root, k.name_prefix)] = (
                    prefix_counts.get((parent, k.name_root, k.name_prefix), 0) + 1
                )
            if mode in {GroupingMode.BY_DATE, GroupingMode.BY_MACHINE} and k.subgroup:
                subgroup_counts[(k.project, k.subgroup)] = (
                    subgroup_counts.get((k.project, k.subgroup), 0) + 1
                )
        for i in walk:
            k = keys_per_agent[i]
            l0: GroupKey = (k.project,)
            if l0 not in seen:
                seen.add(l0)
                out.append(l0)
            if use_cs:
                l1: GroupKey = (k.project, k.patch)
                if l1 not in seen:
                    seen.add(l1)
                    out.append(l1)
                parent = l1
            elif mode is GroupingMode.BY_MACHINE:
                parent = (k.project, k.subgroup)
            else:
                parent = l0
            if mode in {
                GroupingMode.BY_DATE,
                GroupingMode.BY_MACHINE,
            } and should_emit_subgroup_banner(
                mode,
                k.subgroup,
                subgroup_counts.get((k.project, k.subgroup), 0),
            ):
                subgroup_key: GroupKey = (k.project, k.subgroup)
                if subgroup_key not in seen:
                    seen.add(subgroup_key)
                    out.append(subgroup_key)
            if k.name_root and root_counts.get((parent, k.name_root), 0) >= 2:
                deep: GroupKey = (*parent, k.name_root)
                if deep not in seen:
                    seen.add(deep)
                    out.append(deep)
                if (
                    k.name_prefix
                    and prefix_counts.get((parent, k.name_root, k.name_prefix), 0) >= 2
                ):
                    prefix_key: GroupKey = (*parent, k.name_root, k.name_prefix)
                    if prefix_key not in seen:
                        seen.add(prefix_key)
                        out.append(prefix_key)
    return out
