"""Tree builders, banner row records, and banner-display helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..agent import Agent
from ..agent_group_fold import AgentGroupFoldRegistry, GroupKey
from ..agent_panels import panel_key_per_agent
from ._buckets import (
    NO_CHANGESPEC_LABEL,
    NO_HOUR_LABEL,
    GroupingMode,
    status_bucket_for,
)
from ._keys import (
    grouping_keys_for,
    grouping_keys_for_agents,
    panel_uses_changespec_level,
    walk_anchors,
    walk_order,
)


@dataclass(frozen=True)
class GroupRow:
    """A banner row in the grouped agent tree."""

    level: int  # 0 = project, 1 = changespec / name-root / time window, 2 = name-root
    group_key: tuple[str, ...]
    agent_indices: tuple[int, ...]
    is_collapsed: bool = False


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


def _should_emit_time_window_banner(hour: str, count: int) -> bool:
    """Whether a BY_DATE time-window bucket should have a visible banner."""
    if not hour:
        return False
    if hour == NO_HOUR_LABEL:
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
    name-root banner is only included when its group has 2+ entries;
    BY_DATE time-window keys mirror the visible banner predicate.
    """
    if not agents:
        return []
    panel_keys = panel_key_per_agent(agents)
    panel_to_indices: dict[str | None, list[int]] = {}
    for i, pk in enumerate(panel_keys):
        panel_to_indices.setdefault(pk, []).append(i)

    reference = now if now is not None else datetime.now()
    seen: set[GroupKey] = set()
    out: list[GroupKey] = []
    for indices in panel_to_indices.values():
        panel_agents = [agents[i] for i in indices]
        keys_per_agent = grouping_keys_for_agents(panel_agents, mode, reference)
        use_cs = panel_uses_changespec_level(panel_agents, mode)
        root_counts: dict[tuple[tuple[str, ...], str], int] = {}
        hour_counts: dict[tuple[str, str], int] = {}
        for k in keys_per_agent:
            parent: tuple[str, ...] = (
                (k.project, k.changespec) if use_cs else (k.project,)
            )
            if k.name_root:
                root_counts[(parent, k.name_root)] = (
                    root_counts.get((parent, k.name_root), 0) + 1
                )
            if mode is GroupingMode.BY_DATE and k.hour:
                hour_counts[(k.project, k.hour)] = (
                    hour_counts.get((k.project, k.hour), 0) + 1
                )
        for k in keys_per_agent:
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
            if mode is GroupingMode.BY_DATE and _should_emit_time_window_banner(
                k.hour, hour_counts.get((k.project, k.hour), 0)
            ):
                hour_key: GroupKey = (k.project, k.hour)
                if hour_key not in seen:
                    seen.add(hour_key)
                    out.append(hour_key)
            if k.name_root and root_counts.get((parent, k.name_root), 0) >= 2:
                deep: GroupKey = (*parent, k.name_root)
                if deep not in seen:
                    seen.add(deep)
                    out.append(deep)
    return out


def build_agent_tree(
    agents: list[Agent],
    fold_registry: AgentGroupFoldRegistry | None = None,
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
            the bucket.  ``BY_DATE`` uses time-window banners under the bucket;
            ``BY_STATUS`` uses the name-root layer.
        now: Reference time for ``BY_DATE`` bucketing.  Defaults to
            ``datetime.now()``; only consulted when *mode* is ``BY_DATE``.

    Returns:
        A list of :class:`TreeEntry` rows, ready to be walked by the
        renderer in order.
    """
    registry = fold_registry if fold_registry is not None else AgentGroupFoldRegistry()
    parent_lookup: dict[str, Agent] = {
        a.raw_suffix: a for a in agents if a.raw_suffix and not a.is_workflow_child
    }
    reference = now if now is not None else datetime.now()
    keys_per_agent = [
        grouping_keys_for(a, parent_lookup, mode, reference) for a in agents
    ]
    anchors = walk_anchors(agents, parent_lookup, mode)
    use_cs = panel_uses_changespec_level(agents, mode)
    walk = walk_order(keys_per_agent, anchors, use_changespec_level=use_cs, mode=mode)

    proj_indices: dict[str, list[int]] = {}
    cs_indices: dict[tuple[str, str], list[int]] = {}
    hour_indices: dict[tuple[str, str], list[int]] = {}
    root_indices: dict[tuple[tuple[str, ...], str], list[int]] = {}
    for i in walk:
        k = keys_per_agent[i]
        proj_indices.setdefault(k.project, []).append(i)
        if use_cs:
            cs_indices.setdefault((k.project, k.changespec), []).append(i)
            parent: tuple[str, ...] = (k.project, k.changespec)
        else:
            parent = (k.project,)
        if mode is GroupingMode.BY_DATE and k.hour:
            hour_indices.setdefault((k.project, k.hour), []).append(i)
        if k.name_root:
            root_indices.setdefault((parent, k.name_root), []).append(i)

    entries: list[TreeEntry] = []
    cur_proj: str | None = None
    cur_cs: str | None = None  # only meaningful when use_cs
    cur_hour: str = ""  # only meaningful under BY_DATE
    cur_root: str = ""
    cur_proj_collapsed = False
    cur_cs_collapsed = False
    cur_hour_collapsed = False
    cur_root_collapsed = False

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
                    ),
                )
            )
            cur_proj = k.project
            cur_cs = None
            cur_hour = ""
            cur_root = ""
            cur_cs_collapsed = False
            cur_hour_collapsed = False
            cur_root_collapsed = False
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
                        ),
                    )
                )
                cur_cs = k.changespec
                cur_root = ""
                cur_root_collapsed = False
            if cur_cs_collapsed:
                continue
            parent_key: tuple[str, ...] = (k.project, k.changespec)
            deep_level = 2
        else:
            parent_key = (k.project,)
            deep_level = 1

        if mode is GroupingMode.BY_DATE and k.hour != cur_hour:
            cur_hour = k.hour
            cur_hour_collapsed = False
            cur_root = ""
            cur_root_collapsed = False
            hour_count = len(hour_indices.get((k.project, k.hour), []))
            if _should_emit_time_window_banner(k.hour, hour_count):
                hour_key: GroupKey = (k.project, k.hour)
                cur_hour_collapsed = registry.is_collapsed(hour_key)
                entries.append(
                    TreeEntry(
                        kind="group",
                        group=GroupRow(
                            level=1,
                            group_key=hour_key,
                            agent_indices=tuple(hour_indices[(k.project, k.hour)]),
                            is_collapsed=cur_hour_collapsed,
                        ),
                    )
                )
        if cur_hour_collapsed:
            continue

        if k.name_root != cur_root:
            cur_root = k.name_root
            cur_root_collapsed = False
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
                        ),
                    )
                )
        if cur_root_collapsed:
            continue
        entries.append(TreeEntry(kind="agent", agent_idx=i))

    return entries


def compute_banner_summary(group: GroupRow, agents: list[Agent]) -> _BannerSummary:
    """Aggregate status counts for the agents referenced by *group*.

    Only non-workflow-child agents are counted so the summary mirrors
    the user's mental model of "agents in this group".  Counts are
    derived from :func:`status_bucket_for` so the chip line can never
    disagree with the banner it sits on.
    """
    count = 0
    running = 0
    failed = 0
    awaiting = 0
    for idx in group.agent_indices:
        if idx < 0 or idx >= len(agents):
            continue
        agent = agents[idx]
        if agent.is_workflow_child:
            continue
        count += 1
        bucket = status_bucket_for(agent)
        if bucket == "Running":
            running += 1
        elif bucket == "Failed":
            failed += 1
        elif bucket == "Needs Attention":
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
    * Level 1, BY_DATE mode (2-tuple ``(date_bucket, "8AM-12PM")``) → the
      bare 4-hour window label.
    * Level 2 (3-tuple ``(project, changespec, name_root)``) → the
      bare name-root.

    All non-L0 banners use the ``group_key[-1]`` suffix as their label.
    """
    if len(group.group_key) == 1:
        proj = group.group_key[0]
        return proj if proj else "(no project)"
    suffix = group.group_key[-1]
    if suffix:
        return suffix
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
