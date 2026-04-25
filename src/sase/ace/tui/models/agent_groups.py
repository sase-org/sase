"""Three-level grouping tree for the Agents tab.

Builds a flat sequence of banner + agent entries from a list of agents,
grouped by:

1. **Tag** (``Agent.tag``; empty string for untagged agents).
2. **Project / changespec** (derived from ``Agent.project_file`` and
   ``Agent.cl_name``).
3. **Name root** — the part of the agent's name before the first ``.``.

Workflow children inherit grouping identity from their parent so that
banners are never emitted between a parent and its child steps.

The tree builder accepts a ``group_fold_level``:

* ``3`` (default) — every banner and agent row is emitted.  Each group
  key renders exactly once, with all of its members contiguous beneath
  the banner.
* ``0``/``1``/``2`` — only banners up to the requested level are
  emitted.  Each unique group key produces exactly one banner row.
  Agent rows are suppressed entirely so that L0/L1/L2 act as a
  "headers-only" view.

Group ordering is deterministic and independent of the input agent
list's order: named tags sort before ``(untagged)``; named projects
sort before ``(no project)``; the empty name-root sorts first within a
project so dotless agents render directly under the project banner.
Within each group, members keep their original input order via a
stable sort.

Level-2 (name-root) banners are only emitted when the name-root group
contains two or more entries; a singleton root renders its lone agent
directly under the project banner without an extra header.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .agent import Agent

#: Sentinel used as the project key for agents without a ``project_file``.
NO_PROJECT = ""

#: Sentinel used as the tag key for agents without any tags.
UNTAGGED = ""


@dataclass(frozen=True)
class GroupRow:
    """A banner row in the grouped agent tree."""

    level: int  # 0 = tag, 1 = project, 2 = name-root
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
    tag: str
    project: tuple[str, str]  # (project_name, changespec)
    name_root: str


def _project_key(agent: Agent) -> tuple[str, str]:
    if not agent.project_file:
        return (NO_PROJECT, agent.cl_name or "")
    return (Path(agent.project_file).parent.name, agent.cl_name or "")


def _name_root(agent: Agent) -> str:
    """Return the part of the agent's name before the first ``.``.

    Empty string when the name has no ``.`` (such agents render under the
    project banner with no name-root header).
    """
    name = agent.agent_name or agent.display_name or ""
    if "." in name:
        return name.split(".", 1)[0]
    return ""


def _tag_sort_key(tag: str) -> tuple[int, str]:
    """Sort key for primary tags — named tags first, ``(untagged)`` last."""
    return (0, tag.lower()) if tag else (1, "")


def _project_sort_key(project: tuple[str, str]) -> tuple[int, str, str]:
    """Sort key for projects — named projects first, ``(no project)`` last."""
    name, cl = project
    if name:
        return (0, name.lower(), cl.lower())
    return (1, "", cl.lower())


def _name_root_sort_key(name_root: str) -> tuple[int, str]:
    """Sort key for name-roots — empty (dotless) sorts first within project."""
    return (0, "") if not name_root else (1, name_root.lower())


def _walk_order(keys_per_agent: list[_GroupingKeys]) -> list[int]:
    """Return a stable permutation of agent indices sorted by grouping keys."""
    return sorted(
        range(len(keys_per_agent)),
        key=lambda i: (
            _tag_sort_key(keys_per_agent[i].tag),
            _project_sort_key(keys_per_agent[i].project),
            _name_root_sort_key(keys_per_agent[i].name_root),
            i,
        ),
    )


def _grouping_keys_for(agent: Agent, parent_lookup: dict[str, Agent]) -> _GroupingKeys:
    """Compute (tag, project, name_root) for *agent*.

    Workflow children inherit grouping from their parent so a banner is
    never inserted between a parent and its workflow steps.
    """
    target = agent
    if agent.is_workflow_child and agent.parent_timestamp:
        parent = parent_lookup.get(agent.parent_timestamp)
        if parent is not None:
            target = parent
    tag = target.tag or UNTAGGED
    return _GroupingKeys(
        tag=tag, project=_project_key(target), name_root=_name_root(target)
    )


def build_agent_tree(agents: list[Agent], group_fold_level: int = 3) -> list[TreeEntry]:
    """Build the grouped tree of banner + agent entries.

    See module docstring for level semantics.

    Args:
        agents: The flat agent list (as filtered/sorted for display).
        group_fold_level: Global expansion level (0–3).

    Returns:
        A list of :class:`TreeEntry` rows, ready to be walked by the
        renderer in order.
    """
    parent_lookup: dict[str, Agent] = {
        a.raw_suffix: a for a in agents if a.raw_suffix and not a.is_workflow_child
    }
    keys_per_agent = [_grouping_keys_for(a, parent_lookup) for a in agents]
    walk_order = _walk_order(keys_per_agent)

    tag_indices: dict[str, list[int]] = {}
    proj_indices: dict[tuple[str, tuple[str, str]], list[int]] = {}
    root_indices: dict[tuple[str, tuple[str, str], str], list[int]] = {}
    for i in walk_order:
        k = keys_per_agent[i]
        tag_indices.setdefault(k.tag, []).append(i)
        proj_indices.setdefault((k.tag, k.project), []).append(i)
        if k.name_root:
            root_indices.setdefault((k.tag, k.project, k.name_root), []).append(i)

    if group_fold_level >= 3:
        return _build_full_tree(
            keys_per_agent, walk_order, tag_indices, proj_indices, root_indices
        )
    return _build_collapsed_tree(
        keys_per_agent,
        walk_order,
        group_fold_level,
        tag_indices,
        proj_indices,
        root_indices,
    )


def _build_full_tree(
    keys_per_agent: list[_GroupingKeys],
    walk_order: list[int],
    tag_indices: dict[str, list[int]],
    proj_indices: dict[tuple[str, tuple[str, str]], list[int]],
    root_indices: dict[tuple[str, tuple[str, str], str], list[int]],
) -> list[TreeEntry]:
    """Full banner + agent rows.

    Members are walked in deterministic grouping order so each group
    key emits exactly one banner with all of its members contiguous
    beneath it.
    """
    entries: list[TreeEntry] = []
    cur_tag: str | None = None
    cur_proj: tuple[str, str] | None = None
    cur_root: str = ""

    for i in walk_order:
        k = keys_per_agent[i]
        if cur_tag is None or k.tag != cur_tag:
            entries.append(
                TreeEntry(
                    kind="group",
                    group=GroupRow(
                        level=0,
                        group_key=(k.tag,),
                        agent_indices=tuple(tag_indices[k.tag]),
                    ),
                )
            )
            cur_tag = k.tag
            cur_proj = None
            cur_root = ""
        if cur_proj is None or k.project != cur_proj:
            entries.append(
                TreeEntry(
                    kind="group",
                    group=GroupRow(
                        level=1,
                        group_key=(k.tag, *k.project),
                        agent_indices=tuple(proj_indices[(k.tag, k.project)]),
                    ),
                )
            )
            cur_proj = k.project
            cur_root = ""
        if k.name_root != cur_root:
            if k.name_root and len(root_indices[(k.tag, k.project, k.name_root)]) >= 2:
                entries.append(
                    TreeEntry(
                        kind="group",
                        group=GroupRow(
                            level=2,
                            group_key=(k.tag, *k.project, k.name_root),
                            agent_indices=tuple(
                                root_indices[(k.tag, k.project, k.name_root)]
                            ),
                        ),
                    )
                )
            cur_root = k.name_root
        entries.append(TreeEntry(kind="agent", agent_idx=i))

    return entries


def _build_collapsed_tree(
    keys_per_agent: list[_GroupingKeys],
    walk_order: list[int],
    group_fold_level: int,
    tag_indices: dict[str, list[int]],
    proj_indices: dict[tuple[str, tuple[str, str]], list[int]],
    root_indices: dict[tuple[str, tuple[str, str], str], list[int]],
) -> list[TreeEntry]:
    """Headers-only tree for fold levels 0/1/2.

    Each unique group at the requested levels appears once in
    deterministic grouping order.  Agent rows are suppressed.
    """
    entries: list[TreeEntry] = []
    seen_tags: set[str] = set()
    seen_projects: set[tuple[str, tuple[str, str]]] = set()
    seen_roots: set[tuple[str, tuple[str, str], str]] = set()

    for i in walk_order:
        k = keys_per_agent[i]
        if k.tag not in seen_tags:
            seen_tags.add(k.tag)
            entries.append(
                TreeEntry(
                    kind="group",
                    group=GroupRow(
                        level=0,
                        group_key=(k.tag,),
                        agent_indices=tuple(tag_indices[k.tag]),
                        is_collapsed=group_fold_level < 1,
                    ),
                )
            )
        if group_fold_level >= 1:
            proj_id = (k.tag, k.project)
            if proj_id not in seen_projects:
                seen_projects.add(proj_id)
                entries.append(
                    TreeEntry(
                        kind="group",
                        group=GroupRow(
                            level=1,
                            group_key=(k.tag, *k.project),
                            agent_indices=tuple(proj_indices[proj_id]),
                            is_collapsed=group_fold_level < 2,
                        ),
                    )
                )
        if group_fold_level >= 2 and k.name_root:
            root_id = (k.tag, k.project, k.name_root)
            if root_id not in seen_roots and len(root_indices[root_id]) >= 2:
                seen_roots.add(root_id)
                entries.append(
                    TreeEntry(
                        kind="group",
                        group=GroupRow(
                            level=2,
                            group_key=(k.tag, *k.project, k.name_root),
                            agent_indices=tuple(root_indices[root_id]),
                            is_collapsed=True,
                        ),
                    )
                )
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

    Tag level: ``"@tag"`` or ``"(untagged)"``.
    Project level: ``"<project> / <changespec>"`` or
    ``"(no project) / <changespec>"``.
    Name-root level: the bare ``"<name>"``.
    """
    if group.level == 0:
        tag = group.group_key[0]
        return f"@{tag}" if tag else "(untagged)"
    if group.level == 1:
        proj = group.group_key[1]
        cl = group.group_key[2] if len(group.group_key) > 2 else ""
        proj_disp = proj if proj else "(no project)"
        return f"{proj_disp} / {cl}" if cl else proj_disp
    if group.level == 2:
        return group.group_key[-1]
    return ""


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

    Used to snap focus back to a group banner when a fold change hides
    the previously focused agent.  Picks the deepest banner whose
    ``agent_indices`` contains *target_agent_idx*; falls back to the
    first banner that contains it, or ``None``.
    """
    best: GroupRow | None = None
    for entry in entries:
        if entry.kind != "group" or entry.group is None:
            continue
        if target_agent_idx in entry.group.agent_indices:
            if best is None or entry.group.level > best.level:
                best = entry.group
    return best
