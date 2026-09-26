"""Owner-aware Node Finder snapshot builder.

Mirrors :mod:`_prospective_clan`: it projects every fold open, walks each
tribe panel's grouping tree, and classifies why each row stays hidden. The
row model itself lives in ``models.node_finder``; this module only reads
owner state.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ...models.agent import AgentType
from ...models.agent_groups import GroupingMode, banner_label_for_group_key
from ...models.agent_panels import AgentPanelGroup, agents_for_panel
from ...models.group_fold import GroupFoldRegistry
from ...models.node_finder import (
    NODE_FINDER_HINT_CAPACITY,
    NodeFinderReason,
    NodeFinderRole,
    NodeFinderRow,
    NodeFinderSnapshot,
    node_finder_jumpable,
    node_finder_kind,
    node_finder_name,
    node_finder_title,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panels import PanelKey

    AgentIdentity = tuple[AgentType, str, str | None]

logger = logging.getLogger(__name__)


def _evolve(row: NodeFinderRow, **changes: Any) -> NodeFinderRow:
    return replace(row, **changes)


def _kind_word(agent: Agent) -> str:
    if agent.is_clan_container:
        return "clan"
    if agent.is_agent_session_container_row:
        return "session"
    if agent.agent_type == AgentType.WORKFLOW:
        return "workflow"
    return "node"


def _nearest_collapsed_label(
    unmet: tuple[str, ...],
    parents: dict[str, Agent],
) -> str:
    if not unmet:
        return ""
    parent = parents.get(unmet[0])
    if parent is None:
        return ""
    return f"{_kind_word(parent)} {node_finder_name(parent)}"


def _complete_roster_for_snapshot(owner: Any) -> tuple[list[Agent], set[AgentIdentity]]:
    """Return the pre-``I`` roster and identities hidden from the live list.

    The regular Agents caches deliberately contain only the visible roster while
    ``I`` is on.  Node Finder needs the same in-memory source that the next
    reload will project, so it can show those rows in their real tree positions
    without starting a load or changing the live view.
    """
    live_complete = list(getattr(owner, "_agents_with_children", None) or ())
    if not bool(getattr(owner, "hide_non_run_agents", False)):
        return live_complete, set()

    hideable = list(getattr(owner, "_hideable_agents", None) or ())
    if not hideable:
        return live_complete, set()

    local = list(getattr(owner, "_agents_local_with_children", None) or ())
    roster: list[Agent] = []
    seen: set[AgentIdentity] = set()
    for agent in [*local, *hideable]:
        if agent.identity not in seen:
            seen.add(agent.identity)
            roster.append(agent)

    filter_removed = getattr(owner, "filter_explicitly_removed", None)
    if callable(filter_removed):
        roster = list(filter_removed(roster))
    project_current_mode = getattr(owner, "_agents_source_for_current_mode", None)
    complete = (
        list(project_current_mode(roster)) if callable(project_current_mode) else roster
    )
    live_identities = {agent.identity for agent in live_complete}
    hidden_by_i = {
        agent.identity for agent in complete if agent.identity not in live_identities
    }
    return complete, hidden_by_i


def build_node_finder_snapshot(owner: Any) -> NodeFinderSnapshot:
    """Project every reachable node row and classify why each is hidden."""
    from ...models import filter_agents_by_fold_state
    from ...models._agent_tree import (
        agent_fold_key,
        agent_parent_fold_key,
        agent_tree_depth,
        tree_parent_lookup,
    )
    from ...models.agent_groups import build_agent_tree
    from ..navigation._agent_reveal import unmet_ancestor_folds
    from ._fold_scope import panel_fold_registry
    from ._panel_fold_intent import effective_panel_collapses
    from ._prospective_clan import FoldStateProjection, apply_active_agent_query

    complete, hidden_by_i = _complete_roster_for_snapshot(owner)
    parents = tree_parent_lookup(complete)

    fold_manager = getattr(owner, "_fold_manager", None)
    if fold_manager is not None:
        levels: dict[str, object] = dict(fold_manager.snapshot())
    else:
        levels = {}
    from ...models.fold_state import FoldLevel

    for agent in complete:
        fold_key = agent_fold_key(agent)
        if fold_key is not None:
            levels[fold_key] = FoldLevel.FULLY_EXPANDED
    expanded, _ = filter_agents_by_fold_state(complete, FoldStateProjection(levels))  # type: ignore[arg-type]

    merged = bool(getattr(owner, "_agent_panels_grouped", False))
    mode: GroupingMode = getattr(owner, "_grouping_mode", GroupingMode.STANDARD)
    panel_group = AgentPanelGroup.from_agents(expanded, merge_tribe_panels=merged)

    raw_query = getattr(owner, "_agent_search_query", "") or ""
    if raw_query:
        query_set = {
            agent.identity for agent in apply_active_agent_query(owner, expanded)
        }
    else:
        query_set = None

    current_agents: list[Agent] = list(getattr(owner, "_agents", None) or ())
    jump_targets = getattr(owner, "_jump_candidate_targets", None)
    if callable(jump_targets):
        rendered: set[AgentIdentity] = set()
        for target in jump_targets():
            if (
                isinstance(target, tuple)
                and target
                and target[0] == "agent"
                and 0 <= target[1] < len(current_agents)
            ):
                rendered.add(current_agents[target[1]].identity)
    else:
        rendered = {agent.identity for agent in current_agents}

    collapsed_panels = effective_panel_collapses(owner)
    dismissed = set(getattr(owner, "_dismissed_agents", set()) or ())

    if fold_manager is not None:
        unmet = unmet_ancestor_folds(complete, fold_manager)
    else:
        unmet = {}

    rows: list[NodeFinderRow] = []
    index_by_identity: dict[AgentIdentity, int] = {}

    for panel_key in panel_group.panel_keys:
        panel_agents = agents_for_panel(expanded, panel_key, merge_tribe_panels=merged)
        tree = build_agent_tree(
            panel_agents, fold_registry=GroupFoldRegistry(), mode=mode
        )
        panel_idx = len(rows)
        rows.append(
            NodeFinderRow(
                role=NodeFinderRole.PANEL,
                panel_key=panel_key,
                depth=0,
                parent_row=None,
            )
        )

        group_entries = [entry for entry in tree if entry.kind == "group"]
        enclosing: dict[int, list[tuple[str, ...]]] = {}
        for entry in group_entries:
            if entry.group is None:
                continue
            for local_idx in entry.group.agent_indices:
                enclosing.setdefault(local_idx, []).append(entry.group.group_key)

        registry = panel_fold_registry(owner, panel_key)
        is_collapsed = getattr(registry, "is_collapsed", None)

        group_stack: list[tuple[int, int]] = []
        for entry in tree:
            if entry.kind == "group":
                if entry.group is None:
                    continue
                level = entry.group.level
                while group_stack and group_stack[-1][0] >= level:
                    group_stack.pop()
                parent = group_stack[-1][1] if group_stack else panel_idx
                group_stack.append((level, len(rows)))
                rows.append(
                    NodeFinderRow(
                        role=NodeFinderRole.GROUP,
                        panel_key=panel_key,
                        depth=level + 1,
                        parent_row=parent,
                        group_label=banner_label_for_group_key(entry.group.group_key),
                    )
                )
                continue
            if entry.kind != "agent" or entry.agent_idx is None:
                continue
            if not (0 <= entry.agent_idx < len(panel_agents)):
                continue
            agent = panel_agents[entry.agent_idx]
            if agent.identity in index_by_identity:
                continue

            reasons: set[NodeFinderReason] = set()
            if panel_key in collapsed_panels:
                reasons.add(NodeFinderReason.PANEL)
            collapsed_key: tuple[str, ...] | None = None
            for key in enclosing.get(entry.agent_idx, []):
                if callable(is_collapsed) and is_collapsed(key):
                    collapsed_key = key
            group_label = ""
            if collapsed_key is not None:
                reasons.add(NodeFinderReason.BANNER)
                group_label = banner_label_for_group_key(collapsed_key)
            missing = unmet.get(agent.identity, ())
            if missing:
                reasons.add(NodeFinderReason.FOLDED)
            if query_set is not None and agent.identity not in query_set:
                reasons.add(NodeFinderReason.QUERY)
            if agent.identity in hidden_by_i:
                reasons.add(NodeFinderReason.NON_RUN)
            if agent.identity in rendered:
                if reasons:
                    logger.debug(
                        "node finder contradiction: rendered row %r has reasons %r",
                        agent.identity,
                        sorted(reason.value for reason in reasons),
                    )
                reasons = set()

            jumpable = node_finder_jumpable(agent)
            kind_label, kind_accent = node_finder_kind(agent)
            title = node_finder_title(agent) or ""

            parent_row = group_stack[-1][1] if group_stack else panel_idx
            parent_key = agent_parent_fold_key(agent)
            tree_parent = parents.get(parent_key, None) if parent_key else None
            if (
                tree_parent is not None
                and tree_parent.identity in index_by_identity
                and tree_parent.identity != agent.identity
            ):
                parent_row = index_by_identity[tree_parent.identity]

            index_by_identity[agent.identity] = len(rows)
            rows.append(
                NodeFinderRow(
                    role=NodeFinderRole.NODE,
                    identity=agent.identity,
                    agent=agent,
                    name=node_finder_name(agent),
                    title=title,
                    kind_label=kind_label,
                    kind_accent=kind_accent,
                    depth=agent_tree_depth(agent) + 1,
                    panel_key=panel_key,
                    parent_row=parent_row,
                    jumpable=jumpable,
                    reasons=frozenset(reasons),
                    unmet_fold_count=len(missing),
                    nearest_collapsed=_nearest_collapsed_label(missing, parents),
                    group_label=group_label,
                )
            )

    # Omission pass: dismissed rows, rows whose hider is unknown (not
    # rendered and no computed reason), and non-jumpable steps without a
    # jumpable descendant never get a hint, so they stay out.
    descendant_of_jumpable: set[AgentIdentity] = set()
    for row in rows:
        if row.role is not NodeFinderRole.NODE or not row.jumpable:
            continue
        row_agent = row.agent
        if row_agent is None:
            continue
        current_key = agent_parent_fold_key(row_agent)
        seen_keys: set[str] = set()
        while current_key and current_key not in seen_keys:
            seen_keys.add(current_key)
            fold_parent = parents.get(current_key)
            if fold_parent is None:
                break
            descendant_of_jumpable.add(fold_parent.identity)
            current_key = agent_parent_fold_key(fold_parent)

    keep = [True] * len(rows)
    for pos, row in enumerate(rows):
        if row.role is not NodeFinderRole.NODE:
            continue
        if row.identity in dismissed:
            keep[pos] = False
        elif not row.jumpable and row.identity not in descendant_of_jumpable:
            keep[pos] = False
        elif not row.reasons and row.identity not in rendered:
            keep[pos] = False

    kept_nodes = {
        pos
        for pos, row in enumerate(rows)
        if keep[pos] and row.role is NodeFinderRole.NODE
    }
    for pos, row in enumerate(rows):
        if not keep[pos] or row.role is NodeFinderRole.NODE:
            continue
        if not any(_is_descendant(rows, node_pos, pos) for node_pos in kept_nodes):
            keep[pos] = False

    kept_positions = [pos for pos, kept in enumerate(keep) if kept]
    new_index = {old: new for new, old in enumerate(kept_positions)}
    remapped: list[NodeFinderRow] = []
    for old in kept_positions:
        row = rows[old]
        parent_pos = row.parent_row
        while parent_pos is not None and parent_pos not in new_index:
            parent_pos = (
                rows[parent_pos].parent_row if 0 <= parent_pos < len(rows) else None
            )
        remapped.append(
            _evolve(
                row,
                parent_row=new_index[parent_pos] if parent_pos is not None else None,
            )
        )
    rows = remapped
    index_by_identity = {
        row.identity: pos
        for pos, row in enumerate(rows)
        if row.role is NodeFinderRole.NODE and row.identity is not None
    }

    # Header counts over the final row set.
    header_counts: dict[int, tuple[int, int]] = {}
    for pos, row in enumerate(rows):
        if row.role is NodeFinderRole.NODE:
            continue
        jumpable_count = 0
        hidden_count = 0
        for node_pos, node in enumerate(rows):
            if node.role is not NodeFinderRole.NODE or not node.jumpable:
                continue
            if node_pos == pos or _is_descendant(rows, node_pos, pos):
                jumpable_count += 1
                if node.reasons:
                    hidden_count += 1
        header_counts[pos] = (jumpable_count, hidden_count)
    if header_counts:
        rows = [
            _evolve(
                row,
                jumpable_count=header_counts[pos][0],
                hidden_count=header_counts[pos][1],
            )
            if pos in header_counts
            else row
            for pos, row in enumerate(rows)
        ]

    here_row: int | None = None
    if (
        getattr(owner, "current_tab", None) == "agents"
        and getattr(owner, "_current_group_key", None) is None
    ):
        get_selected = getattr(owner, "_get_selected_agent", None)
        selected = get_selected() if callable(get_selected) else None
        if selected is not None and selected.identity in index_by_identity:
            here_row = index_by_identity[selected.identity]
            rows = [
                _evolve(row, is_here=True) if pos == here_row else row
                for pos, row in enumerate(rows)
            ]

    node_rows = [
        row for row in rows if row.role is NodeFinderRole.NODE and row.jumpable
    ]
    hidden = sum(1 for row in node_rows if row.reasons)
    query_hidden = sum(1 for row in node_rows if NodeFinderReason.QUERY in row.reasons)

    load_state = getattr(owner, "_agent_load_state", None)
    panel_group_live = getattr(owner, "_panel_group", None)
    focused_panel_key: PanelKey = (
        panel_group_live.focused_key if panel_group_live is not None else None
    )

    return NodeFinderSnapshot(
        rows=tuple(rows),
        here_row=here_row,
        node_count=len(node_rows),
        hidden_count=hidden,
        query_hidden_count=query_hidden,
        query=raw_query,
        query_incomplete=bool(getattr(load_state, "query_incomplete", False)),
        hidden_by_i_count=sum(
            1 for row in node_rows if NodeFinderReason.NON_RUN in row.reasons
        ),
        hint_overflow=len(node_rows) > NODE_FINDER_HINT_CAPACITY,
        focused_panel_key=focused_panel_key,
    )


def _is_descendant(rows: list[NodeFinderRow], node_pos: int, ancestor_pos: int) -> bool:
    for ancestor in _ancestor_chain(rows, node_pos):
        if ancestor == ancestor_pos:
            return True
    return False


def _ancestor_chain(rows: list[NodeFinderRow], pos: int) -> list[int]:
    chain: list[int] = []
    current = rows[pos].parent_row
    seen: set[int] = set()
    while current is not None and current not in seen:
        seen.add(current)
        chain.append(current)
        current = rows[current].parent_row if 0 <= current < len(rows) else None
    return chain


__all__ = [
    "build_node_finder_snapshot",
]
