"""Two- or three-level grouping tree for an Agents-tab panel.

Builds a flat sequence of banner + agent entries from a list of agents.
Each panel decides independently between two layouts based on whether
any of its non-project-scoped agents targets a ChangeSpec
(``cl_name != ""``):

* **2-level layout** (no ChangeSpec anywhere in the panel):
    1. **Project** — derived from ``Agent.project_file``.
    2. **Name root** — the part of the agent's name before the first ``.``.

* **3-level layout** (at least one non-project agent has a ChangeSpec):
    1. **Project**
    2. **ChangeSpec** (``Agent.cl_name``); project-scoped agents and
       agents lacking one fall into a synthetic ``"(no ChangeSpec)"``
       bucket sorted last under their project.
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
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

from .agent import Agent
from .agent_group_fold import AgentGroupFoldRegistry, GroupKey
from .agent_panels import panel_key_per_agent

#: Sentinel used as the project key for agents without a ``project_file``.
NO_PROJECT = ""

#: Synthetic ChangeSpec bucket label for agents with no ``cl_name`` in a
#: panel that otherwise has at least one ChangeSpec.
NO_CHANGESPEC_LABEL = "(no ChangeSpec)"


class GroupingMode(Enum):
    """How the Agents-tab tree is bucketed at L0.

    - ``STANDARD``: existing behavior — L0 is the project; ChangeSpec
      level is added per-panel when at least one agent has a ``cl_name``.
    - ``BY_DATE``: L0 is a date bucket (``Today`` / ``Yesterday`` /
      ``This Week`` / ``Earlier``) derived from each agent's ``start_time``.
    - ``BY_STATUS``: L0 is a status bucket (``Needs Attention`` /
      ``Running`` / ``Failed`` / ``Done``) derived from each agent's
      ``status`` and retry-chain lineage.

    In ``BY_DATE`` and ``BY_STATUS`` modes the project and ChangeSpec
    levels disappear: L0 is the bucket, L1 is the name-root, and the
    same singleton-suppression rule applies as in ``STANDARD`` mode.
    """

    STANDARD = "standard"
    BY_DATE = "by_date"
    BY_STATUS = "by_status"


_DATE_BUCKETS: tuple[str, ...] = ("Today", "Yesterday", "This Week", "Earlier")
_STATUS_BUCKETS: tuple[str, ...] = (
    "Needs Attention",
    "Running",
    "Waiting",
    "Failed",
    "Done",
)

# Status mapping for ``BY_STATUS`` bucketing.  The semantic line is:
# **Needs Attention** = "you need to act right now"; everything else is a
# state the agent is moving through on its own.
#
# Members of Needs Attention:
#   * ``PLANNING`` — a plan is being drafted and the user is expected to
#     review/answer questions as they arise
#   * ``QUESTION`` — the agent has explicitly paused for an answer
#   * ``FAILED`` without ``retried_as_timestamp`` (handled by the
#     ``startswith("FAILED")`` branch below, not by this frozenset)
#
# ``PLAN DONE`` and ``EPIC CREATED`` are post-plan handoff states: the
# planning work is finished and any code work has been spun off, so they
# read as **Done**.  ``PLAN APPROVED`` is an actively executing state and
# reads as **Running**.  All ``WAITING`` variants land in **Waiting**
# regardless of timer/dependency presence.
_NEEDS_ATTENTION_STATUSES: frozenset[str] = frozenset({"PLANNING", "QUESTION"})

# TODO(@user): confirm needs:input mapping. Initial set drawn from
# plans/202604/agents_tab_query_filters.md — covers the statuses where the
# agent is paused awaiting user input rather than running or terminal.
_NEEDS_INPUT_STATUSES: frozenset[str] = frozenset(
    {"QUESTION", "WAITING INPUT", "PLAN APPROVED"}
)


def _date_bucket_for(agent: Agent, now: datetime) -> str:
    """Map ``agent.start_time`` to one of the date buckets.

    Buckets compare on calendar dates in ``now``'s local frame:

    - ``Today``: same calendar date as ``now``.
    - ``Yesterday``: the day before ``now``.
    - ``This Week``: within the prior six days, but not Today/Yesterday.
    - ``Earlier``: anything older, plus agents with no ``start_time``.
    """
    start = agent.start_time
    if start is None:
        return "Earlier"
    today = now.date()
    start_date = start.date()
    if start_date == today:
        return "Today"
    if start_date == today - timedelta(days=1):
        return "Yesterday"
    if start_date > today - timedelta(days=7):
        return "This Week"
    return "Earlier"


def _status_bucket_for(agent: Agent) -> str:
    """Map ``agent.status`` (plus retry lineage) to a status bucket.

    See the ``_NEEDS_ATTENTION_STATUSES`` comment above for the mapping
    rules.  All ``WAITING`` variants land in ``Waiting``.  Anything not
    explicitly bucketed lands in ``Running`` (the agent is in flight from
    the user's perspective).
    """
    status = agent.status or ""
    if status in {"DONE", "PLAN DONE", "EPIC CREATED"}:
        return "Done"
    if status in _NEEDS_ATTENTION_STATUSES:
        return "Needs Attention"
    if status == "PLAN APPROVED":
        return "Running"
    if status == "WAITING":
        return "Waiting"
    if status.startswith("FAILED"):
        if not agent.retried_as_timestamp:
            return "Needs Attention"
        return "Failed"
    return "Running"


def _bucket_sort_index(mode: GroupingMode, bucket: str) -> int:
    """Fixed bucket ordering for ``BY_DATE`` / ``BY_STATUS`` L0 keys.

    Unknown bucket names sort last so a stale bucket label can never
    silently clobber a valid one.
    """
    order = _DATE_BUCKETS if mode is GroupingMode.BY_DATE else _STATUS_BUCKETS
    try:
        return order.index(bucket)
    except ValueError:
        return len(order)


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
    changespec: str  # real ChangeSpec name (may be "")
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
    return (0, _bucket_sort_index(mode, project))


def _changespec_sort_key(changespec: str) -> tuple[int, str]:
    """Sort key for ChangeSpecs — named first, synthetic bucket last."""
    if changespec:
        return (0, changespec.lower())
    return (1, "")


def _name_root_sort_key(name_root: str, in_group: bool) -> tuple[int, str]:
    """Sort key for name-roots — ungrouped (dotless or singleton) sorts first."""
    return (1, name_root.lower()) if in_group else (0, "")


def _l0_value_for(agent: Agent, mode: GroupingMode, now: datetime) -> str:
    """Compute the L0 string value for *agent* under *mode*.

    For STANDARD this is the project name; for BY_DATE / BY_STATUS it's
    the bucket name.  Stored in :class:`_GroupingKeys.project` so the
    rest of the tree-building plumbing stays unchanged.
    """
    if mode is GroupingMode.STANDARD:
        return _project_name(agent)
    if mode is GroupingMode.BY_DATE:
        return _date_bucket_for(agent, now)
    return _status_bucket_for(agent)


def _grouping_keys_for(
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
    )


def _grouping_keys_for_agents(
    agents: list[Agent],
    mode: GroupingMode = GroupingMode.STANDARD,
    now: datetime | None = None,
) -> list[_GroupingKeys]:
    """Public-ish helper exposing per-agent grouping keys."""
    parent_lookup: dict[str, Agent] = {
        a.raw_suffix: a for a in agents if a.raw_suffix and not a.is_workflow_child
    }
    reference = now if now is not None else datetime.now()
    return [_grouping_keys_for(a, parent_lookup, mode, reference) for a in agents]


def _panel_uses_changespec_level(
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


def _walk_anchors(
    agents: list[Agent],
    parent_lookup: dict[str, Agent],
    mode: GroupingMode,
) -> list[tuple[float, int]]:
    """Per-agent ``(-anchor_start_epoch, is_child)`` tiebreak under ``BY_DATE``.

    Workflow children adopt their parent's ``start_time`` and a ``1`` in
    the ``is_child`` slot so they sort immediately after the parent
    regardless of the child's own ``start_time``.  Non-``BY_DATE`` modes
    return a constant ``(0.0, 0)`` per agent so the sort is unchanged.

    Agents with no ``start_time`` sort last within their bucket
    (``+inf`` in the negated-epoch slot).
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
        if target.start_time is None:
            anchor = float("inf")
        else:
            anchor = -target.start_time.timestamp()
        out.append((anchor, is_child))
    return out


def _walk_order(
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


def enumerate_group_keys(
    agents: list[Agent],
    mode: GroupingMode = GroupingMode.STANDARD,
    now: datetime | None = None,
) -> list[GroupKey]:
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

    reference = now if now is not None else datetime.now()
    seen: set[GroupKey] = set()
    out: list[GroupKey] = []
    for indices in panel_to_indices.values():
        panel_agents = [agents[i] for i in indices]
        keys_per_agent = _grouping_keys_for_agents(panel_agents, mode, reference)
        use_cs = _panel_uses_changespec_level(panel_agents, mode)
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
            the bucket and L1 becomes the name-root.
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
        _grouping_keys_for(a, parent_lookup, mode, reference) for a in agents
    ]
    anchors = _walk_anchors(agents, parent_lookup, mode)
    use_cs = _panel_uses_changespec_level(agents, mode)
    walk_order = _walk_order(
        keys_per_agent, anchors, use_changespec_level=use_cs, mode=mode
    )

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


def compute_banner_summary(group: GroupRow, agents: list[Agent]) -> _BannerSummary:
    """Aggregate status counts for the agents referenced by *group*.

    Only non-workflow-child agents are counted so the summary mirrors
    the user's mental model of "agents in this group".  Counts are
    derived from :func:`_status_bucket_for` so the chip line can never
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
        bucket = _status_bucket_for(agent)
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
