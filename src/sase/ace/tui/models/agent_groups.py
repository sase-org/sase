"""Two- or three-level grouping tree for an Agents-tab panel.

Builds a flat sequence of banner + agent entries from a list of agents.
Each panel decides independently between two layouts based on whether
any of its agents targets a ChangeSpec (``cl_name != ""``):

* **2-level layout** (no ChangeSpec anywhere in the panel):
    1. **Project** — derived from ``Agent.project_file``.
    2. **Name root** — the part of the agent's name before the first ``.``.

* **3-level layout** (at least one agent has a ChangeSpec):
    1. **Project**
    2. **ChangeSpec** (``Agent.cl_name``); agents lacking one fall into a
       synthetic ``"(no ChangeSpec)"`` bucket sorted last under their
       project.
    3. **Name root**

Tag-level grouping is not part of this tree — tags drive the dynamic
side panels (see :mod:`sase.ace.tui.models.agent_panels`), so each panel
already represents a single tag bucket.

Workflow children inherit grouping identity from their parent so that
banners are never emitted between a parent and its child steps.

Each group has a binary collapsed/expanded state, tracked per-key in an
:class:`AgentGroupFoldRegistry`.  When a group is collapsed its
descendants are suppressed; sibling groups remain unaffected.

Group ordering is deterministic and independent of the input agent
list's order: named projects sort before ``(no project)``; named
ChangeSpecs sort before the ``(no ChangeSpec)`` bucket; ungrouped
agents (dotless and singleton-name-root) sort first within their
ChangeSpec bucket so they render directly under the ChangeSpec banner,
before any name-root banner.  Within each group, members keep their
original input order via a stable sort.

Name-root banners are only emitted when the name-root group contains
two or more entries; a singleton root renders its lone agent directly
under the parent banner without an extra header.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .agent import Agent
from .agent_group_fold import AgentGroupFoldRegistry, GroupKey
from .agent_panels import panel_key_per_agent

#: Sentinel used as the project key for agents without a ``project_file``.
NO_PROJECT = ""

#: Synthetic ChangeSpec bucket label for agents with no ``cl_name`` in a
#: panel that otherwise has at least one ChangeSpec.
NO_CHANGESPEC_LABEL = "(no ChangeSpec)"


@dataclass(frozen=True)
class GroupRow:
    """A banner row in the grouped agent tree."""

    level: int  # 0 = project, 1 = changespec or name-root, 2 = name-root
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


@dataclass(frozen=True)
class _GroupingKeys:
    project: str  # project_name (or NO_PROJECT)
    changespec: str  # cl_name (may be "")
    name_root: str


def _project_name(agent: Agent) -> str:
    if not agent.project_file:
        return NO_PROJECT
    return Path(agent.project_file).parent.name


def _name_root(agent: Agent) -> str:
    """Return the part of the agent's name before the first ``.``.

    Empty string when the name has no ``.`` (such agents render under the
    parent banner with no name-root header).
    """
    name = agent.agent_name or agent.display_name or ""
    if "." in name:
        return name.split(".", 1)[0]
    return ""


def _project_sort_key(project: str) -> tuple[int, str]:
    """Sort key for projects — named projects first, ``(no project)`` last."""
    if project:
        return (0, project.lower())
    return (1, "")


def _changespec_sort_key(changespec: str) -> tuple[int, str]:
    """Sort key for ChangeSpecs — named first, synthetic bucket last."""
    if changespec:
        return (0, changespec.lower())
    return (1, "")


def _name_root_sort_key(name_root: str, in_group: bool) -> tuple[int, str]:
    """Sort key for name-roots — ungrouped (dotless or singleton) sorts first."""
    return (1, name_root.lower()) if in_group else (0, "")


def _grouping_keys_for(agent: Agent, parent_lookup: dict[str, Agent]) -> _GroupingKeys:
    """Compute (project, changespec, name_root) for *agent*.

    Workflow children inherit grouping from their parent so a banner is
    never inserted between a parent and its workflow steps.
    """
    target = agent
    if agent.is_workflow_child and agent.parent_timestamp:
        parent = parent_lookup.get(agent.parent_timestamp)
        if parent is not None:
            target = parent
    return _GroupingKeys(
        project=_project_name(target),
        changespec=target.cl_name or "",
        name_root=_name_root(target),
    )


def _grouping_keys_for_agents(agents: list[Agent]) -> list[_GroupingKeys]:
    """Public-ish helper exposing per-agent grouping keys."""
    parent_lookup: dict[str, Agent] = {
        a.raw_suffix: a for a in agents if a.raw_suffix and not a.is_workflow_child
    }
    return [_grouping_keys_for(a, parent_lookup) for a in agents]


def _panel_uses_changespec_level(panel_agents: list[Agent]) -> bool:
    """Whether *panel_agents* should use the 3-level layout."""
    return any(a.cl_name for a in panel_agents)


def _walk_order(
    keys_per_agent: list[_GroupingKeys],
    *,
    use_changespec_level: bool,
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
            _project_sort_key(keys_per_agent[i].project),
            (
                _changespec_sort_key(keys_per_agent[i].changespec)
                if use_changespec_level
                else (0, "")
            ),
            _name_root_sort_key(
                keys_per_agent[i].name_root,
                in_group=bool(keys_per_agent[i].name_root)
                and root_counts.get((parent_keys[i], keys_per_agent[i].name_root), 0)
                >= 2,
            ),
            i,
        ),
    )


def enumerate_group_keys(agents: list[Agent]) -> list[GroupKey]:
    """Return the deduplicated list of all banner keys present in *agents*.

    Partitions *agents* by panel key so each panel's mode (2- vs 3-level)
    is decided independently, mirroring :func:`build_agent_tree`.  The
    name-root banner is only included when its group has 2+ entries.
    """
    if not agents:
        return []
    panel_keys = panel_key_per_agent(agents)
    panel_to_indices: dict[str | None, list[int]] = {}
    for i, pk in enumerate(panel_keys):
        panel_to_indices.setdefault(pk, []).append(i)

    seen: set[GroupKey] = set()
    out: list[GroupKey] = []
    for indices in panel_to_indices.values():
        panel_agents = [agents[i] for i in indices]
        keys_per_agent = _grouping_keys_for_agents(panel_agents)
        use_cs = _panel_uses_changespec_level(panel_agents)
        root_counts: dict[tuple[tuple[str, ...], str], int] = {}
        for k in keys_per_agent:
            parent: tuple[str, ...] = (
                (k.project, k.changespec) if use_cs else (k.project,)
            )
            if k.name_root:
                root_counts[(parent, k.name_root)] = (
                    root_counts.get((parent, k.name_root), 0) + 1
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
            if k.name_root and root_counts.get((parent, k.name_root), 0) >= 2:
                deep: GroupKey = (*parent, k.name_root)
                if deep not in seen:
                    seen.add(deep)
                    out.append(deep)
    return out


def build_agent_tree(
    agents: list[Agent],
    fold_registry: AgentGroupFoldRegistry | None = None,
) -> list[TreeEntry]:
    """Build the grouped tree of banner + agent entries.

    Args:
        agents: The flat agent list (as filtered/sorted for display).
            Treated as a single panel's worth of agents — the panel's
            layout (2- vs 3-level) is chosen from this list alone.
        fold_registry: Optional per-group collapse registry.  ``None``
            (or an empty registry) renders every group expanded.

    Returns:
        A list of :class:`TreeEntry` rows, ready to be walked by the
        renderer in order.
    """
    registry = fold_registry if fold_registry is not None else AgentGroupFoldRegistry()
    parent_lookup: dict[str, Agent] = {
        a.raw_suffix: a for a in agents if a.raw_suffix and not a.is_workflow_child
    }
    keys_per_agent = [_grouping_keys_for(a, parent_lookup) for a in agents]
    use_cs = _panel_uses_changespec_level(agents)
    walk_order = _walk_order(keys_per_agent, use_changespec_level=use_cs)

    proj_indices: dict[str, list[int]] = {}
    cs_indices: dict[tuple[str, str], list[int]] = {}
    root_indices: dict[tuple[tuple[str, ...], str], list[int]] = {}
    for i in walk_order:
        k = keys_per_agent[i]
        proj_indices.setdefault(k.project, []).append(i)
        if use_cs:
            cs_indices.setdefault((k.project, k.changespec), []).append(i)
            parent: tuple[str, ...] = (k.project, k.changespec)
        else:
            parent = (k.project,)
        if k.name_root:
            root_indices.setdefault((parent, k.name_root), []).append(i)

    entries: list[TreeEntry] = []
    cur_proj: str | None = None
    cur_cs: str | None = None  # only meaningful when use_cs
    cur_root: str = ""
    cur_proj_collapsed = False
    cur_cs_collapsed = False
    cur_root_collapsed = False

    for i in walk_order:
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
            cur_root = ""
            cur_cs_collapsed = False
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


_AWAITING_STATUSES = frozenset({"QUESTION", "PLAN APPROVED"})


def compute_banner_summary(group: GroupRow, agents: list[Agent]) -> _BannerSummary:
    """Aggregate status counts for the agents referenced by *group*.

    Only non-workflow-child agents are counted so the summary mirrors
    the user's mental model of "agents in this group".
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
        status = agent.status or ""
        if status == "RUNNING":
            running += 1
        elif status.startswith("FAILED"):
            failed += 1
        elif status in _AWAITING_STATUSES:
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
    * Level 2 (3-tuple ``(project, changespec, name_root)``) → the
      bare name-root.
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
