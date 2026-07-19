"""Tree builders, banner row records, and banner-display helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sase.core.time import local_now
from sase.project_display_names import humanize_cl_name

from ..agent import Agent
from .._agent_clan import agent_status_projections
from .._agent_tree import (
    agent_is_tree_child,
    presentation_anchor_lookup,
    tree_parent_lookup,
)
from ..agent_panels import panel_key_per_agent
from ..group_fold import GroupFoldRegistry, GroupFoldView, GroupKey
from ._buckets import (
    NO_CHANGESPEC_LABEL,
    NO_HOUR_LABEL,
    GroupingMode,
)
from ._keys import (
    GroupingKeys,
    grouping_keys_for,
    panel_uses_changespec_level,
    walk_anchors,
    walk_order,
)


@dataclass(frozen=True)
class GroupRow:
    """A banner row in the grouped agent tree."""

    # 0 = project/date/status bucket. Deeper levels are structural
    # descendants: ChangeSpec, BY_DATE subgroup, name-root, or dotted
    # name-prefix subgroup depending on the active layout.
    level: int
    group_key: tuple[str, ...]
    agent_indices: tuple[int, ...]
    is_collapsed: bool = False
    has_child_groups: bool = False


@dataclass(frozen=True)
class TreeEntry:
    """One row in the rendered tree — either a banner or an agent."""

    kind: str  # "group" or "agent"
    group: GroupRow | None = None
    agent_idx: int | None = None


@dataclass(frozen=True)
class _BannerSummary:
    """Aggregate counts shown next to a group banner."""

    count: int
    running: int
    failed: int
    awaiting: int


@dataclass(frozen=True)
class _GroupedWalk:
    """Anchored grouping metadata and atomic-cluster render order."""

    keys_per_agent: list[GroupingKeys]
    use_changespec_level: bool
    indices: list[int]


def _grouped_walk(
    agents: list[Agent],
    mode: GroupingMode,
    reference: datetime,
) -> _GroupedWalk:
    """Build one shared anchored walk for banners and agent rows."""
    parent_lookup = tree_parent_lookup(agents)
    anchors = presentation_anchor_lookup(agents, parent_lookup)
    keys_per_agent = [
        grouping_keys_for(
            agent,
            parent_lookup,
            mode,
            reference,
            anchors=anchors,
        )
        for agent in agents
    ]
    time_anchors = walk_anchors(
        agents,
        parent_lookup,
        mode,
        anchors=anchors,
    )
    use_cs = panel_uses_changespec_level(
        agents,
        mode,
        parent_lookup=parent_lookup,
        anchors=anchors,
    )
    index_by_identity = {id(agent): i for i, agent in enumerate(agents)}
    cluster_roots = [
        index_by_identity.get(id(anchors.get(id(agent), agent)), i)
        for i, agent in enumerate(agents)
    ]
    indices = walk_order(
        keys_per_agent,
        time_anchors,
        use_changespec_level=use_cs,
        mode=mode,
        cluster_roots=cluster_roots,
    )
    return _GroupedWalk(
        keys_per_agent=keys_per_agent,
        use_changespec_level=use_cs,
        indices=indices,
    )


def _should_emit_date_subgroup_banner(subgroup: str, count: int) -> bool:
    """Whether a BY_DATE subgroup bucket should have a visible banner.

    A real subgroup label always emits a banner; the synthetic
    ``(no time)`` label only emits when 2+ agents share it.
    """
    if not subgroup:
        return False
    if subgroup == NO_HOUR_LABEL:
        return count >= 2
    return True


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
        grouped_walk = _grouped_walk(panel_agents, mode, reference)
        keys_per_agent = grouped_walk.keys_per_agent
        use_cs = grouped_walk.use_changespec_level
        walk = grouped_walk.indices
        root_counts: dict[tuple[tuple[str, ...], str], int] = {}
        prefix_counts: dict[tuple[tuple[str, ...], str, str], int] = {}
        subgroup_counts: dict[tuple[str, str], int] = {}
        for k in keys_per_agent:
            parent: tuple[str, ...] = (
                (k.project, k.changespec) if use_cs else (k.project,)
            )
            if k.name_root:
                root_counts[(parent, k.name_root)] = (
                    root_counts.get((parent, k.name_root), 0) + 1
                )
            if k.name_root and k.name_prefix:
                prefix_counts[(parent, k.name_root, k.name_prefix)] = (
                    prefix_counts.get((parent, k.name_root, k.name_prefix), 0) + 1
                )
            if mode is GroupingMode.BY_DATE and k.date_subgroup:
                subgroup_counts[(k.project, k.date_subgroup)] = (
                    subgroup_counts.get((k.project, k.date_subgroup), 0) + 1
                )
        for i in walk:
            k = keys_per_agent[i]
            l0: GroupKey = (k.project,)
            if l0 not in seen:
                seen.add(l0)
                out.append(l0)
            if use_cs:
                l1: GroupKey = (k.project, k.changespec)
                if l1 not in seen:
                    seen.add(l1)
                    out.append(l1)
                parent = l1
            else:
                parent = l0
            if mode is GroupingMode.BY_DATE and _should_emit_date_subgroup_banner(
                k.date_subgroup,
                subgroup_counts.get((k.project, k.date_subgroup), 0),
            ):
                subgroup_key: GroupKey = (k.project, k.date_subgroup)
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


def build_agent_tree(
    agents: list[Agent],
    fold_registry: GroupFoldView | None = None,
    mode: GroupingMode = GroupingMode.STANDARD,
    now: datetime | None = None,
) -> list[TreeEntry]:
    """Build the grouped tree of banner + agent entries.

    Args:
        agents: The flat agent list (as filtered/sorted for display).
            Treated as a single panel's worth of agents — the panel's
            layout (2- vs 3-level) is chosen from this list alone.
        fold_registry: Optional per-group collapse registry.  ``None``
            (or an empty registry) renders every group expanded.
        mode: How to bucket agents at L0.  Defaults to ``STANDARD``
            (existing project / ChangeSpec hierarchy).  ``BY_DATE`` and
            ``BY_STATUS`` drop the ChangeSpec level entirely; L0 becomes
            the bucket.  ``BY_DATE`` uses date-aware subgroup banners under
            the bucket (1-hour under Today/Yesterday, calendar day under
            This Week, Monday-start week under Earlier); ``BY_STATUS``
            uses the name-root layer and optional dotted-name prefix
            subgroups.
        now: Reference time for ``BY_DATE`` bucketing.  Defaults to
            ``datetime.now()``; only consulted when *mode* is ``BY_DATE``.

    Returns:
        A list of :class:`TreeEntry` rows, ready to be walked by the
        renderer in order.
    """
    registry = fold_registry if fold_registry is not None else GroupFoldRegistry()
    reference = now if now is not None else local_now()
    grouped_walk = _grouped_walk(agents, mode, reference)
    keys_per_agent = grouped_walk.keys_per_agent
    use_cs = grouped_walk.use_changespec_level
    walk = grouped_walk.indices

    proj_indices: dict[str, list[int]] = {}
    cs_indices: dict[tuple[str, str], list[int]] = {}
    subgroup_indices: dict[tuple[str, str], list[int]] = {}
    root_indices: dict[tuple[tuple[str, ...], str], list[int]] = {}
    prefix_indices: dict[tuple[tuple[str, ...], str, str], list[int]] = {}
    for i in walk:
        k = keys_per_agent[i]
        proj_indices.setdefault(k.project, []).append(i)
        if use_cs:
            cs_indices.setdefault((k.project, k.changespec), []).append(i)
            parent: tuple[str, ...] = (k.project, k.changespec)
        else:
            parent = (k.project,)
        if mode is GroupingMode.BY_DATE and k.date_subgroup:
            subgroup_indices.setdefault((k.project, k.date_subgroup), []).append(i)
        if k.name_root:
            root_indices.setdefault((parent, k.name_root), []).append(i)
        if k.name_root and k.name_prefix:
            prefix_indices.setdefault((parent, k.name_root, k.name_prefix), []).append(
                i
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

    def root_has_prefix_groups(parent_key: tuple[str, ...], name_root: str) -> bool:
        return any(
            p_parent == parent_key and p_root == name_root and len(indices) >= 2
            for (p_parent, p_root, _prefix), indices in prefix_indices.items()
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
                        agent_indices=tuple(proj_indices[k.project]),
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
            if cur_cs is None or k.changespec != cur_cs:
                l1_key: GroupKey = (k.project, k.changespec)
                cur_cs_collapsed = registry.is_collapsed(l1_key)
                entries.append(
                    TreeEntry(
                        kind="group",
                        group=GroupRow(
                            level=1,
                            group_key=l1_key,
                            agent_indices=tuple(cs_indices[(k.project, k.changespec)]),
                            is_collapsed=cur_cs_collapsed,
                            has_child_groups=True,
                        ),
                    )
                )
                cur_cs = k.changespec
                cur_root = ""
                cur_prefix = ""
                cur_root_collapsed = False
                cur_prefix_collapsed = False
            if cur_cs_collapsed:
                continue
            parent_key: tuple[str, ...] = (k.project, k.changespec)
            deep_level = 2
        else:
            parent_key = (k.project,)
            deep_level = 1

        if mode is GroupingMode.BY_DATE and k.date_subgroup != cur_subgroup:
            cur_subgroup = k.date_subgroup
            cur_subgroup_collapsed = False
            cur_root = ""
            cur_prefix = ""
            cur_root_collapsed = False
            cur_prefix_collapsed = False
            subgroup_count = len(subgroup_indices.get((k.project, k.date_subgroup), []))
            if _should_emit_date_subgroup_banner(k.date_subgroup, subgroup_count):
                subgroup_key: GroupKey = (k.project, k.date_subgroup)
                cur_subgroup_collapsed = registry.is_collapsed(subgroup_key)
                entries.append(
                    TreeEntry(
                        kind="group",
                        group=GroupRow(
                            level=1,
                            group_key=subgroup_key,
                            agent_indices=tuple(
                                subgroup_indices[(k.project, k.date_subgroup)]
                            ),
                            is_collapsed=cur_subgroup_collapsed,
                            has_child_groups=False,
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
            if k.name_root and len(root_indices[(parent_key, k.name_root)]) >= 2:
                deep_key: GroupKey = (*parent_key, k.name_root)
                cur_root_collapsed = registry.is_collapsed(deep_key)
                entries.append(
                    TreeEntry(
                        kind="group",
                        group=GroupRow(
                            level=deep_level,
                            group_key=deep_key,
                            agent_indices=tuple(
                                root_indices[(parent_key, k.name_root)]
                            ),
                            is_collapsed=cur_root_collapsed,
                            has_child_groups=root_has_prefix_groups(
                                parent_key, k.name_root
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
                and len(prefix_indices[(parent_key, k.name_root, k.name_prefix)]) >= 2
            ):
                prefix_key: GroupKey = (*parent_key, k.name_root, k.name_prefix)
                cur_prefix_collapsed = registry.is_collapsed(prefix_key)
                entries.append(
                    TreeEntry(
                        kind="group",
                        group=GroupRow(
                            level=deep_level + 1,
                            group_key=prefix_key,
                            agent_indices=tuple(
                                prefix_indices[(parent_key, k.name_root, k.name_prefix)]
                            ),
                            is_collapsed=cur_prefix_collapsed,
                            has_child_groups=False,
                        ),
                    )
                )
        if cur_prefix_collapsed:
            continue
        entries.append(TreeEntry(kind="agent", agent_idx=i))

    return entries


def compute_banner_summary(group: GroupRow, agents: list[Agent]) -> _BannerSummary:
    """Aggregate status counts for the agents referenced by *group*.

    Only non-workflow-child agents are counted so the summary mirrors
    the user's mental model of "agents in this group".  Counts are
    derived from the shared concrete-agent projection so family handoffs and
    container counts agree with the other summary surfaces.
    """
    count = 0
    running = 0
    failed = 0
    awaiting = 0
    roots: list[Agent] = []
    for idx in group.agent_indices:
        if idx < 0 or idx >= len(agents):
            continue
        agent = agents[idx]
        if agent_is_tree_child(agent):
            continue
        roots.append(agent)

    for root in roots:
        for projection in agent_status_projections((root,)):
            count += 1
            bucket = projection.bucket
            if bucket == "Running":
                running += 1
            elif bucket == "Failed":
                failed += 1
            elif bucket == "Stopped":
                awaiting += 1
    return _BannerSummary(
        count=count, running=running, failed=failed, awaiting=awaiting
    )


def banner_label(group: GroupRow) -> str:
    """Compose the human-readable banner label for *group*.

    * Level 0 (1-tuple ``(project,)``) → project name or ``"(no project)"``.
    * Level 1, 3-level mode (2-tuple ``(project, changespec)``) → the
      ChangeSpec name or the synthetic ``"(no ChangeSpec)"`` bucket.
    * Level 1, 2-level mode (2-tuple ``(project, name_root)``) → the
      bare name-root (always non-empty for a real banner).
    * Level 1, BY_DATE mode (2-tuple ``(date_bucket, subgroup)``) → the
      bare subgroup label (1-hour ``HH:00``, calendar day, or week range).
    * Level 2+ dotted-name prefix or name-root descendants use their
      bare suffix.

    All non-L0 banners use the ``group_key[-1]`` suffix as their label.
    """
    if len(group.group_key) == 1:
        proj = group.group_key[0]
        return proj if proj else "(no project)"
    suffix = group.group_key[-1]
    if suffix:
        return humanize_cl_name(suffix)
    return NO_CHANGESPEC_LABEL


def banner_summary_text(summary: _BannerSummary) -> str:
    """Compact ``"N agents · 2 running · 1 failed"``-style label.

    Returns an empty string when the summary is empty (count == 0).
    """
    if summary.count <= 0:
        return ""
    plural = "s" if summary.count != 1 else ""
    parts = [f"{summary.count} agent{plural}"]
    if summary.running:
        parts.append(f"{summary.running} running")
    if summary.failed:
        parts.append(f"{summary.failed} failed")
    if summary.awaiting:
        parts.append(f"{summary.awaiting} awaiting")
    return " · ".join(parts)


def find_visible_ancestor_banner(
    entries: list[TreeEntry], target_agent_idx: int
) -> GroupRow | None:
    """Return the closest ancestor banner of *target_agent_idx* in *entries*.

    Picks the deepest banner whose ``agent_indices`` contains
    *target_agent_idx*; falls back to the first banner that contains
    it, or ``None``.
    """
    best: GroupRow | None = None
    for entry in entries:
        if entry.kind != "group" or entry.group is None:
            continue
        if target_agent_idx in entry.group.agent_indices:
            if best is None or entry.group.level > best.level:
                best = entry.group
    return best
