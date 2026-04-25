"""Three-level grouping tree for the Agents tab.

Builds a flat sequence of banner + agent entries from a list of agents,
grouped by:

1. **Primary tag** (``Agent.tags[0]``; empty string for untagged agents).
2. **Project / changespec** (derived from ``Agent.project_file`` and
   ``Agent.cl_name``).
3. **Name root** — the part of the agent's name before the first ``.``.

Workflow children inherit grouping identity from their parent so that
banners are never emitted between a parent and its child steps.

Phase 3 always renders groups expanded; ``GroupRow.is_collapsed`` is
present for forward compatibility with Phase 4.
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
    tag = target.tags[0] if target.tags else UNTAGGED
    return _GroupingKeys(
        tag=tag, project=_project_key(target), name_root=_name_root(target)
    )


def build_agent_tree(agents: list[Agent]) -> list[TreeEntry]:
    """Build the grouped tree of banner + agent entries.

    Banners are emitted whenever the active group key changes from the
    previous row, in the order agents appear in *agents*.  Each
    :class:`GroupRow` carries the **full** set of agent indices that share
    its key (across the entire input), so a non-contiguous group (the same
    primary tag broken up by intervening agents with a different tag) will
    produce repeated banners that nonetheless reference the complete index
    set — preserving today's most-recent-activity ordering.

    Args:
        agents: The flat agent list (as filtered/sorted for display).

    Returns:
        A list of :class:`TreeEntry` rows, ready to be walked by the
        renderer in order.
    """
    parent_lookup: dict[str, Agent] = {
        a.raw_suffix: a for a in agents if a.raw_suffix and not a.is_workflow_child
    }
    keys_per_agent = [_grouping_keys_for(a, parent_lookup) for a in agents]

    tag_indices: dict[str, list[int]] = {}
    proj_indices: dict[tuple[str, tuple[str, str]], list[int]] = {}
    root_indices: dict[tuple[str, tuple[str, str], str], list[int]] = {}
    for i, k in enumerate(keys_per_agent):
        tag_indices.setdefault(k.tag, []).append(i)
        proj_indices.setdefault((k.tag, k.project), []).append(i)
        if k.name_root:
            root_indices.setdefault((k.tag, k.project, k.name_root), []).append(i)

    entries: list[TreeEntry] = []
    cur_tag: str | None = None
    cur_proj: tuple[str, str] | None = None
    cur_root: str = ""

    for i, k in enumerate(keys_per_agent):
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
            if k.name_root:
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
