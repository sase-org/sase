"""Shared anchored walk and subgroup-banner predicate for the agent tree."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..agent import Agent
from .._agent_tree import TreeIndex, presentation_anchor_lookup, tree_parent_lookup
from ._buckets import NO_HOUR_LABEL, GroupingMode
from ._keys import GroupingKeys, grouping_keys_for, walk_anchors, walk_order


@dataclass(frozen=True)
class _GroupedWalk:
    """Anchored grouping metadata and atomic-cluster render order."""

    keys_per_agent: list[GroupingKeys]
    use_patch_level: bool
    indices: list[int]


def grouped_walk(
    agents: list[Agent],
    mode: GroupingMode,
    reference: datetime,
    tree_state: TreeIndex | None = None,
    *,
    singleton_anchors: bool = False,
) -> _GroupedWalk:
    """Build one shared anchored walk for banners and agent rows.

    Pass a caller-built *tree_state* (see :data:`TreeIndex`) over the same
    roster to reuse one parent/anchor index instead of rebuilding it. Pass
    ``singleton_anchors=True`` only when every agent is its own presentation
    anchor (no agent has a rendered parent): per-anchor key caching, the
    identity index, and cluster expansion are all identities then, so they
    are skipped and :func:`walk_order` consumes the plain sorted order.
    """
    if tree_state is None:
        parent_lookup = tree_parent_lookup(agents)
        anchors = presentation_anchor_lookup(agents, parent_lookup)
    else:
        parent_lookup, anchors = tree_state
    # Structural descendants inherit grouping from their outer presentation
    # anchor, so agents sharing one anchor share one key computation.
    keys_per_agent: list[GroupingKeys] = []
    if singleton_anchors:
        for agent in agents:
            keys_per_agent.append(
                grouping_keys_for(
                    agent,
                    parent_lookup,
                    mode,
                    reference,
                    anchors=anchors,
                    target=agent,
                )
            )
    else:
        keys_by_anchor: dict[int, GroupingKeys] = {}
        for agent in agents:
            # Inlined ``presentation_anchor`` hit path (``anchors`` is
            # never ``None`` here): the call overhead exceeds the dict
            # hit on wide rosters.
            anchor = anchors.get(id(agent), agent)
            cached = keys_by_anchor.get(id(anchor))
            if cached is None:
                cached = grouping_keys_for(
                    agent,
                    parent_lookup,
                    mode,
                    reference,
                    anchors=anchors,
                )
                keys_by_anchor[id(anchor)] = cached
            keys_per_agent.append(cached)
    time_anchors = walk_anchors(
        agents,
        parent_lookup,
        mode,
        anchors=anchors,
    )
    # The Patch level is present exactly when some agent's key carries a
    # Patch name; the keys above already hold that predicate per anchor, so
    # re-walking the roster for it would recompute the same values.
    if mode is GroupingMode.STANDARD:
        use_cs = any(key.patch for key in keys_per_agent)
    else:
        use_cs = False
    cluster_roots: list[int] | None
    if singleton_anchors:
        # Every cluster is one agent at its own index, so the cluster
        # expansion below would map the sorted order onto itself.
        cluster_roots = None
    else:
        index_by_identity = {id(agent): i for i, agent in enumerate(agents)}
        cluster_roots = [
            index_by_identity.get(id(anchors.get(id(agent), agent)), i)
            for i, agent in enumerate(agents)
        ]
    indices = walk_order(
        keys_per_agent,
        time_anchors,
        use_patch_level=use_cs,
        mode=mode,
        cluster_roots=cluster_roots,
    )
    return _GroupedWalk(
        keys_per_agent=keys_per_agent,
        use_patch_level=use_cs,
        indices=indices,
    )


def should_emit_subgroup_banner(mode: GroupingMode, subgroup: str, count: int) -> bool:
    """Whether an L1 subgroup bucket should have a visible banner.

    ``BY_DATE`` keeps its existing rule: a real subgroup label always emits
    a banner, while the synthetic ``(no time)`` label only emits when 2+
    agents share it. ``BY_MACHINE`` has no synthetic bucket —
    ``status_bucket_for`` always returns a real label — so it emits
    whenever ``subgroup`` is non-empty.
    """
    if not subgroup:
        return False
    if mode is GroupingMode.BY_DATE and subgroup == NO_HOUR_LABEL:
        return count >= 2
    return True
