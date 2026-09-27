"""Grouped banner + agent tree builder."""

from __future__ import annotations

from datetime import datetime

from sase.core.time import local_now

from ..agent import Agent
from .._agent_tree import TreeIndex
from ..group_fold import GroupFoldRegistry, GroupFoldView, GroupKey
from ._buckets import GroupingMode
from ._tree_rows import GroupRow, TreeEntry
from ._tree_walk import grouped_walk, should_emit_subgroup_banner


def rendered_group_keys(
    agents: list[Agent],
    mode: GroupingMode = GroupingMode.STANDARD,
    now: datetime | None = None,
) -> tuple[GroupKey, ...]:
    """Return the visible banner keys emitted by the grouped tree builder."""
    return tuple(
        entry.group.group_key
        for entry in build_agent_tree(agents, mode=mode, now=now)
        if entry.kind == "group" and entry.group is not None
    )


def build_agent_tree(
    agents: list[Agent],
    fold_registry: GroupFoldView | None = None,
    mode: GroupingMode = GroupingMode.STANDARD,
    now: datetime | None = None,
    tree_state: TreeIndex | None = None,
    *,
    singleton_anchors: bool = False,
    materialize_indices: bool = True,
) -> list[TreeEntry]:
    """Build the grouped tree of banner + agent entries.

    Args:
        agents: The flat agent list (as filtered/sorted for display).
            Treated as a single panel's worth of agents — the panel's
            layout (2- vs 3-level) is chosen from this list alone.
        fold_registry: Optional per-group collapse registry.  ``None``
            (or an empty registry) renders every group expanded.
        mode: How to bucket agents at L0.  Defaults to ``STANDARD``
            (existing project / Patch hierarchy).  ``BY_DATE``, ``BY_STATUS``,
            and ``BY_MACHINE`` drop the Patch level entirely; L0 becomes
            the bucket.  ``BY_DATE`` uses date-aware subgroup banners under
            the bucket (1-hour under Today/Yesterday, calendar day under
            This Week, Monday-start week under Earlier); ``BY_STATUS``
            uses the name-root layer and optional dotted-name prefix
            subgroups.  ``BY_MACHINE`` sub-groups each machine bucket by
            status (reusing the same priority-ordered buckets as
            ``BY_STATUS``), then applies the name-root / name-prefix layers
            within each status subgroup.
        now: Reference time for ``BY_DATE`` bucketing.  Defaults to
            ``datetime.now()``; only consulted when *mode* is ``BY_DATE``.
        tree_state: Optional caller-built roster index over the same agents
            (see :data:`TreeIndex`); reuses it instead of rebuilding one.
        singleton_anchors: Pass ``True`` only when every agent is its own
            presentation anchor; skips the per-anchor key cache and the
            cluster expansion, which are both identities then.
        materialize_indices: Pass ``False`` only when the caller cannot
            consume banner member indices (no enclosing map, no collapse
            pruning over this tree); banner rows then carry ``()`` instead
            of per-banner member tuples.

    Returns:
        A list of :class:`TreeEntry` rows, ready to be walked by the
        renderer in order.
    """
    registry = fold_registry if fold_registry is not None else GroupFoldRegistry()
    reference = now if now is not None else local_now()
    panel_walk = grouped_walk(
        agents, mode, reference, tree_state, singleton_anchors=singleton_anchors
    )
    keys_per_agent = panel_walk.keys_per_agent
    use_cs = panel_walk.use_patch_level
    walk = panel_walk.indices

    proj_indices: dict[str, list[int]] = {}
    cs_indices: dict[tuple[str, str], list[int]] = {}
    subgroup_indices: dict[tuple[str, str], list[int]] = {}
    root_indices: dict[tuple[tuple[str, ...], str], list[int]] = {}
    prefix_indices: dict[tuple[tuple[str, ...], str, str], list[int]] = {}
    cs_counts: dict[tuple[str, str], int] = {}
    subgroup_counts: dict[tuple[str, str], int] = {}
    root_counts: dict[tuple[tuple[str, ...], str], int] = {}
    prefix_counts: dict[tuple[tuple[str, ...], str, str], int] = {}
    if materialize_indices:
        for i in walk:
            k = keys_per_agent[i]
            proj_indices.setdefault(k.project, []).append(i)
            if use_cs:
                cs_indices.setdefault((k.project, k.patch), []).append(i)
                parent: tuple[str, ...] = (k.project, k.patch)
            elif mode is GroupingMode.BY_MACHINE:
                parent = (k.project, k.subgroup)
            else:
                parent = (k.project,)
            if mode in {GroupingMode.BY_DATE, GroupingMode.BY_MACHINE} and k.subgroup:
                subgroup_indices.setdefault((k.project, k.subgroup), []).append(i)
            if k.name_root:
                root_indices.setdefault((parent, k.name_root), []).append(i)
            if k.name_root and k.name_prefix:
                prefix_indices.setdefault(
                    (parent, k.name_root, k.name_prefix), []
                ).append(i)
    else:
        # Counts only: banner emission decisions read membership sizes,
        # and no caller on this path consumes member index tuples, so
        # the per-agent index lists (and their append traffic) are
        # skipped. Key derivation per agent is identical to the branch
        # above, so the same banners emit.
        for i in walk:
            k = keys_per_agent[i]
            if use_cs:
                cs_key = (k.project, k.patch)
                cs_counts[cs_key] = cs_counts.get(cs_key, 0) + 1
                parent = (k.project, k.patch)
            elif mode is GroupingMode.BY_MACHINE:
                parent = (k.project, k.subgroup)
            else:
                parent = (k.project,)
            if mode in {GroupingMode.BY_DATE, GroupingMode.BY_MACHINE} and k.subgroup:
                sg_key = (k.project, k.subgroup)
                subgroup_counts[sg_key] = subgroup_counts.get(sg_key, 0) + 1
            if k.name_root:
                root_key = (parent, k.name_root)
                root_counts[root_key] = root_counts.get(root_key, 0) + 1
            if k.name_root and k.name_prefix:
                prefix_count_key = (parent, k.name_root, k.name_prefix)
                prefix_counts[prefix_count_key] = (
                    prefix_counts.get(prefix_count_key, 0) + 1
                )

    entries: list[TreeEntry] = []
    cur_proj: str | None = None
    cur_cs: str | None = None  # only meaningful when use_cs
    cur_subgroup: str = ""  # only meaningful under BY_DATE
    cur_root: str = ""
    cur_prefix: str = ""
    cur_proj_collapsed = False
    cur_cs_collapsed = False
    cur_subgroup_collapsed = False
    cur_root_collapsed = False
    cur_prefix_collapsed = False

    def root_has_prefix_groups(
        parent_key: tuple[str, ...],
        name_root: str,
        prefix_sizes: dict[tuple[tuple[str, ...], str, str], int] | None = None,
    ) -> bool:
        if prefix_sizes is not None:
            return any(
                p_parent == parent_key and p_root == name_root and count >= 2
                for (p_parent, p_root, _prefix), count in prefix_sizes.items()
            )
        return any(
            p_parent == parent_key and p_root == name_root and len(indices) >= 2
            for (p_parent, p_root, _prefix), indices in prefix_indices.items()
        )

    def subgroup_has_root_groups(
        l0: str,
        subgroup: str,
        root_sizes: dict[tuple[tuple[str, ...], str], int] | None = None,
    ) -> bool:
        parent_key = (l0, subgroup)
        if root_sizes is not None:
            return any(
                p_parent == parent_key and count >= 2
                for (p_parent, _root), count in root_sizes.items()
            )
        return any(
            p_parent == parent_key and len(indices) >= 2
            for (p_parent, _root), indices in root_indices.items()
        )

    for i in walk:
        k = keys_per_agent[i]
        if cur_proj is None or k.project != cur_proj:
            l0_key: GroupKey = (k.project,)
            cur_proj_collapsed = registry.is_collapsed(l0_key)
            entries.append(
                TreeEntry(
                    kind="group",
                    group=GroupRow(
                        level=0,
                        group_key=l0_key,
                        agent_indices=(
                            tuple(proj_indices[k.project])
                            if materialize_indices
                            else ()
                        ),
                        is_collapsed=cur_proj_collapsed,
                        has_child_groups=True,
                    ),
                )
            )
            cur_proj = k.project
            cur_cs = None
            cur_subgroup = ""
            cur_root = ""
            cur_prefix = ""
            cur_cs_collapsed = False
            cur_subgroup_collapsed = False
            cur_root_collapsed = False
            cur_prefix_collapsed = False
        if cur_proj_collapsed:
            continue

        if use_cs:
            if cur_cs is None or k.patch != cur_cs:
                l1_key: GroupKey = (k.project, k.patch)
                cur_cs_collapsed = registry.is_collapsed(l1_key)
                entries.append(
                    TreeEntry(
                        kind="group",
                        group=GroupRow(
                            level=1,
                            group_key=l1_key,
                            agent_indices=(
                                tuple(cs_indices[(k.project, k.patch)])
                                if materialize_indices
                                else ()
                            ),
                            is_collapsed=cur_cs_collapsed,
                            has_child_groups=True,
                        ),
                    )
                )
                cur_cs = k.patch
                cur_root = ""
                cur_prefix = ""
                cur_root_collapsed = False
                cur_prefix_collapsed = False
            if cur_cs_collapsed:
                continue
            parent_key: tuple[str, ...] = (k.project, k.patch)
            deep_level = 2
        elif mode is GroupingMode.BY_MACHINE:
            parent_key = (k.project, k.subgroup)
            deep_level = 2
        else:
            parent_key = (k.project,)
            deep_level = 1

        if (
            mode in {GroupingMode.BY_DATE, GroupingMode.BY_MACHINE}
            and k.subgroup != cur_subgroup
        ):
            cur_subgroup = k.subgroup
            cur_subgroup_collapsed = False
            cur_root = ""
            cur_prefix = ""
            cur_root_collapsed = False
            cur_prefix_collapsed = False
            if materialize_indices:
                subgroup_count = len(subgroup_indices.get((k.project, k.subgroup), []))
            else:
                subgroup_count = subgroup_counts.get((k.project, k.subgroup), 0)
            if should_emit_subgroup_banner(mode, k.subgroup, subgroup_count):
                subgroup_key: GroupKey = (k.project, k.subgroup)
                cur_subgroup_collapsed = registry.is_collapsed(subgroup_key)
                entries.append(
                    TreeEntry(
                        kind="group",
                        group=GroupRow(
                            level=1,
                            group_key=subgroup_key,
                            agent_indices=(
                                tuple(subgroup_indices[(k.project, k.subgroup)])
                                if materialize_indices
                                else ()
                            ),
                            is_collapsed=cur_subgroup_collapsed,
                            has_child_groups=(
                                subgroup_has_root_groups(
                                    k.project,
                                    k.subgroup,
                                    None if materialize_indices else root_counts,
                                )
                                if mode is GroupingMode.BY_MACHINE
                                else False
                            ),
                        ),
                    )
                )
        if cur_subgroup_collapsed:
            continue

        if k.name_root != cur_root:
            cur_root = k.name_root
            cur_prefix = ""
            cur_root_collapsed = False
            cur_prefix_collapsed = False
            if (
                k.name_root
                and (
                    root_counts[(parent_key, k.name_root)]
                    if not materialize_indices
                    else len(root_indices[(parent_key, k.name_root)])
                )
                >= 2
            ):
                deep_key: GroupKey = (*parent_key, k.name_root)
                cur_root_collapsed = registry.is_collapsed(deep_key)
                entries.append(
                    TreeEntry(
                        kind="group",
                        group=GroupRow(
                            level=deep_level,
                            group_key=deep_key,
                            agent_indices=(
                                tuple(root_indices[(parent_key, k.name_root)])
                                if materialize_indices
                                else ()
                            ),
                            is_collapsed=cur_root_collapsed,
                            has_child_groups=root_has_prefix_groups(
                                parent_key,
                                k.name_root,
                                None if materialize_indices else prefix_counts,
                            ),
                        ),
                    )
                )
        if cur_root_collapsed:
            continue

        if k.name_prefix != cur_prefix:
            cur_prefix = k.name_prefix
            cur_prefix_collapsed = False
            if (
                k.name_root
                and k.name_prefix
                and (
                    prefix_counts[(parent_key, k.name_root, k.name_prefix)]
                    if not materialize_indices
                    else len(prefix_indices[(parent_key, k.name_root, k.name_prefix)])
                )
                >= 2
            ):
                prefix_key: GroupKey = (*parent_key, k.name_root, k.name_prefix)
                cur_prefix_collapsed = registry.is_collapsed(prefix_key)
                entries.append(
                    TreeEntry(
                        kind="group",
                        group=GroupRow(
                            level=deep_level + 1,
                            group_key=prefix_key,
                            agent_indices=(
                                tuple(
                                    prefix_indices[
                                        (parent_key, k.name_root, k.name_prefix)
                                    ]
                                )
                                if materialize_indices
                                else ()
                            ),
                            is_collapsed=cur_prefix_collapsed,
                            has_child_groups=False,
                        ),
                    )
                )
        if cur_prefix_collapsed:
            continue
        # Positional construction in field order: agent entries are the
        # hottest allocation in the tree build. Keep the order in sync
        # with the dataclass definition.
        entries.append(TreeEntry("agent", None, i))

    return entries
