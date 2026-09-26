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

from ...models._agent_tree import (
    agent_parent_fold_key,
    presentation_anchor_lookup,
)
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
    describe_node_finder_row,
    node_finder_name,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panels import PanelKey

    AgentIdentity = tuple[AgentType, str, str | None]

logger = logging.getLogger(__name__)

#: Shared empty reasons set: most visible rows carry no reason, so reusing
#: one instance skips a per-row ``frozenset`` allocation with equal value.
_NO_REASONS: frozenset[NodeFinderReason] = frozenset()


def _evolve(row: NodeFinderRow, **changes: Any) -> NodeFinderRow:
    return replace(row, **changes)


def _snapshot_facets(
    complete: list[Agent],
) -> tuple[
    dict[int, str | None],
    dict[int, str | None],
    dict[int, int],
    dict[int, AgentIdentity],
    set[int],
]:
    """Read per-agent facets once for one snapshot build.

    Parent and fold keys, tree depth, identity, and the hidden-step flag
    re-derive plan-chain role state, so they are read once per agent here
    and reused by the fold-filter check, levels fill, descendant walk, and
    row construction below instead of once per pass. Every table is local
    to this snapshot; live owner state is still read afresh on every open.
    """
    from ...models._agent_tree import agent_fold_key, agent_tree_depth

    parent_keys: dict[int, str | None] = {}
    fold_keys: dict[int, str | None] = {}
    depths: dict[int, int] = {}
    identity_of: dict[int, AgentIdentity] = {}
    hidden_steps: set[int] = set()
    for agent in complete:
        key = id(agent)
        parent_keys[key] = agent_parent_fold_key(agent)
        fold_keys[key] = agent_fold_key(agent)
        depths[key] = agent_tree_depth(agent)
        identity_of[key] = agent.identity
        if agent.is_hidden_step:
            hidden_steps.add(key)
    return (parent_keys, fold_keys, depths, identity_of, hidden_steps)


def _roster_needs_no_fold_filter(
    parent_keys: dict[int, str | None],
    hidden_steps: set[int],
) -> bool:
    """Return whether the fold filter would return the roster unchanged.

    With no fold parent on any agent, :func:`is_visible` succeeds before
    consulting any level; with no hidden step, the hidden-only-parents
    exclusion is empty. The facet tables already hold one read per agent,
    so this check re-scans values instead of re-deriving predicates.
    """
    if hidden_steps:
        return False
    return all(parent_key is None for parent_key in parent_keys.values())


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
    from ...models._agent_tree import agent_tree_depth, tree_parent_lookup
    from ...models.agent_groups import build_agent_tree
    from ..navigation._agent_reveal import unmet_ancestor_folds
    from ._fold_scope import panel_fold_registry
    from ._panel_fold_intent import effective_panel_collapses
    from ._prospective_clan import FoldStateProjection, apply_active_agent_query

    complete, hidden_by_i = _complete_roster_for_snapshot(owner)
    parents = tree_parent_lookup(complete)
    parent_keys, fold_keys, depths, identity_of, hidden_steps = _snapshot_facets(
        complete
    )

    fold_manager = getattr(owner, "_fold_manager", None)
    if fold_manager is not None:
        levels: dict[str, object] = dict(fold_manager.snapshot())
    else:
        levels = {}
    from ...models.fold_state import FoldLevel

    for fold_key in fold_keys.values():
        if fold_key is not None:
            levels[fold_key] = FoldLevel.FULLY_EXPANDED
    if _roster_needs_no_fold_filter(parent_keys, hidden_steps):
        # No agent has a fold parent and no hidden step exists, so the
        # fold filter would return the roster unchanged: skip its
        # per-agent walk. The discarded fold counts are unused here.
        expanded = list(complete)
    else:
        expanded, _ = filter_agents_by_fold_state(complete, FoldStateProjection(levels))  # type: ignore[arg-type]

    merged = bool(getattr(owner, "_agent_panels_grouped", False))
    mode: GroupingMode = getattr(owner, "_grouping_mode", GroupingMode.STANDARD)
    # One roster index shared by every panel query below: panel grouping
    # filters the same expanded roster once per panel key. When the fold
    # filter kept every row, the expanded roster holds the same objects as
    # the complete roster, so the index built above is reused as is.
    if len(expanded) == len(complete) and all(
        new is old for new, old in zip(expanded, complete, strict=True)
    ):
        expanded_lookup = parents
        expanded_anchors = presentation_anchor_lookup(complete, parents)
    else:
        expanded_lookup = tree_parent_lookup(expanded)
        expanded_anchors = presentation_anchor_lookup(expanded, expanded_lookup)
    expanded_tree_state = (expanded_lookup, expanded_anchors)
    panel_group = AgentPanelGroup.from_agents(
        expanded, merge_tribe_panels=merged, tree_state=expanded_tree_state
    )

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
        unmet = unmet_ancestor_folds(complete, fold_manager, parent_lookup=parents)
    else:
        unmet = {}

    rows: list[NodeFinderRow] = []
    index_by_identity: dict[AgentIdentity, int] = {}
    # Fold keys repeat across clan members, so the collapsed label for one
    # unmet key tuple serves every row that shares it within this snapshot.
    _nearest_collapsed_memo: dict[tuple[str, ...], str] = {}

    for panel_key in panel_group.panel_keys:
        panel_agents = agents_for_panel(
            expanded,
            panel_key,
            merge_tribe_panels=merged,
            tree_state=expanded_tree_state,
        )
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
            agent_key = id(agent)
            # Panel rows are the same objects as the complete roster, so the
            # one-per-open facet read above applies; fall back to a direct
            # read for any object outside that roster.
            identity = identity_of.get(agent_key, agent.identity)
            if identity in index_by_identity:
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
            missing = unmet.get(identity, ())
            if missing:
                reasons.add(NodeFinderReason.FOLDED)
            if query_set is not None and identity not in query_set:
                reasons.add(NodeFinderReason.QUERY)
            if identity in hidden_by_i:
                reasons.add(NodeFinderReason.NON_RUN)
            if identity in rendered:
                if reasons:
                    logger.debug(
                        "node finder contradiction: rendered row %r has reasons %r",
                        identity,
                        sorted(reason.value for reason in reasons),
                    )
                reasons = set()

            jumpable, name, title, kind_label, kind_accent = describe_node_finder_row(
                agent
            )

            parent_row = group_stack[-1][1] if group_stack else panel_idx
            if agent_key in parent_keys:
                parent_key = parent_keys[agent_key]
            else:
                parent_key = agent_parent_fold_key(agent)
            tree_parent = parents.get(parent_key, None) if parent_key else None
            if tree_parent is not None:
                tree_identity = identity_of.get(id(tree_parent), tree_parent.identity)
                if tree_identity in index_by_identity and tree_identity != identity:
                    parent_row = index_by_identity[tree_identity]

            if missing not in _nearest_collapsed_memo:
                _nearest_collapsed_memo[missing] = _nearest_collapsed_label(
                    missing, parents
                )
            index_by_identity[identity] = len(rows)
            rows.append(
                NodeFinderRow(
                    role=NodeFinderRole.NODE,
                    identity=identity,
                    agent=agent,
                    name=name,
                    title=title,
                    kind_label=kind_label,
                    kind_accent=kind_accent,
                    depth=depths.get(agent_key, agent_tree_depth(agent)) + 1,
                    panel_key=panel_key,
                    parent_row=parent_row,
                    jumpable=jumpable,
                    reasons=frozenset(reasons) if reasons else _NO_REASONS,
                    unmet_fold_count=len(missing),
                    nearest_collapsed=_nearest_collapsed_memo[missing],
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
        row_key = id(row_agent)
        if row_key in parent_keys:
            current_key = parent_keys[row_key]
        else:
            current_key = agent_parent_fold_key(row_agent)
        seen_keys: set[str] = set()
        while current_key and current_key not in seen_keys:
            seen_keys.add(current_key)
            fold_parent = parents.get(current_key)
            if fold_parent is None:
                break
            descendant_of_jumpable.add(
                identity_of.get(id(fold_parent), fold_parent.identity)
            )
            fold_parent_id = id(fold_parent)
            if fold_parent_id in parent_keys:
                current_key = parent_keys[fold_parent_id]
            else:
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
    # One memoized ancestor chain per node shared with the header-count
    # pass below; positions are stable when nothing is omitted.
    chains: dict[int, list[int]] = {}
    headers_with_nodes = _headers_with_kept_descendants(rows, kept_nodes, chains)
    for pos, row in enumerate(rows):
        if not keep[pos] or row.role is NodeFinderRole.NODE:
            continue
        if pos not in headers_with_nodes:
            keep[pos] = False

    kept_positions = [pos for pos, kept in enumerate(keep) if kept]
    new_index = {old: new for new, old in enumerate(kept_positions)}
    counts_chains: dict[int, list[int]] | None = chains
    if len(kept_positions) == len(rows):
        # Nothing was omitted, so every parent index still resolves to
        # itself: reuse the rows as built instead of copying each one.
        rows = list(rows)
    else:
        # Remapping renumbers positions, so the header-count pass resolves
        # its own chains over the final row set.
        counts_chains = None
        remapped: list[NodeFinderRow] = []
        for old in kept_positions:
            row = rows[old]
            parent_pos = row.parent_row
            while parent_pos is not None and parent_pos not in new_index:
                parent_pos = (
                    rows[parent_pos].parent_row if 0 <= parent_pos < len(rows) else None
                )
            if parent_pos == row.parent_row and (
                parent_pos is None or new_index[parent_pos] == parent_pos
            ):
                # The parent resolved to itself in the same slot: the row
                # already points at the right target, so reuse it as is.
                remapped.append(row)
            else:
                remapped.append(
                    _evolve(
                        row,
                        parent_row=(
                            new_index[parent_pos] if parent_pos is not None else None
                        ),
                    )
                )
        rows = remapped
    index_by_identity = {
        row.identity: pos
        for pos, row in enumerate(rows)
        if row.role is NodeFinderRole.NODE and row.identity is not None
    }

    # Header counts over the final row set. Each jumpable node contributes
    # to every header above it in one ancestor walk instead of scanning all
    # nodes once per header.
    header_counts: dict[int, tuple[int, int]] = _accumulate_header_counts(
        rows, counts_chains
    )
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

    node_count = 0
    hidden = 0
    query_hidden = 0
    hidden_by_i_count = 0
    for row in rows:
        if row.role is not NodeFinderRole.NODE or not row.jumpable:
            continue
        node_count += 1
        row_reasons = row.reasons
        if not row_reasons:
            continue
        hidden += 1
        if NodeFinderReason.QUERY in row_reasons:
            query_hidden += 1
        if NodeFinderReason.NON_RUN in row_reasons:
            hidden_by_i_count += 1

    load_state = getattr(owner, "_agent_load_state", None)
    panel_group_live = getattr(owner, "_panel_group", None)
    focused_panel_key: PanelKey = (
        panel_group_live.focused_key if panel_group_live is not None else None
    )

    return NodeFinderSnapshot(
        rows=tuple(rows),
        here_row=here_row,
        node_count=node_count,
        hidden_count=hidden,
        query_hidden_count=query_hidden,
        query=raw_query,
        query_incomplete=bool(getattr(load_state, "query_incomplete", False)),
        hidden_by_i_count=hidden_by_i_count,
        hint_overflow=node_count > NODE_FINDER_HINT_CAPACITY,
        focused_panel_key=focused_panel_key,
    )


def _ancestor_chain(
    rows: list[NodeFinderRow], pos: int, chains: dict[int, list[int]]
) -> list[int]:
    """Return *pos*'s strict ancestor positions, memoized in *chains*.

    Each row has a single ``parent_row``, so the walk is one deterministic
    chain; a resolved suffix splices in instead of re-walking. Cycle
    (stop at the first repeated position) and bounds guards match the
    historical per-node walks exactly, so header sets and counts are
    unchanged.
    """
    cached = chains.get(pos)
    if cached is not None:
        return cached
    chain: list[int] = []
    seen: set[int] = set()
    total = len(rows)
    current = rows[pos].parent_row
    while current is not None and current not in seen:
        if not 0 <= current < total:
            break
        seen.add(current)
        chain.append(current)
        tail = chains.get(current)
        if tail is not None:
            for node in tail:
                if node in seen:
                    break
                seen.add(node)
                chain.append(node)
            break
        current = rows[current].parent_row
    chains[pos] = chain
    return chain


def _headers_with_kept_descendants(
    rows: list[NodeFinderRow],
    kept_nodes: set[int],
    chains: dict[int, list[int]] | None = None,
) -> set[int]:
    """Return header positions that have at least one kept node beneath them."""
    if chains is None:
        chains = {}
    headers: set[int] = set()
    for node_pos in kept_nodes:
        headers.update(_ancestor_chain(rows, node_pos, chains))
    return headers


def _accumulate_header_counts(
    rows: list[NodeFinderRow],
    chains: dict[int, list[int]] | None = None,
) -> dict[int, tuple[int, int]]:
    """Count jumpable/hidden nodes beneath each header in one linear pass."""
    if chains is None:
        chains = {}
    jumpable_counts: dict[int, int] = {}
    hidden_counts: dict[int, int] = {}
    headers: list[int] = []
    for pos, row in enumerate(rows):
        if row.role is NodeFinderRole.NODE:
            continue
        headers.append(pos)
        jumpable_counts[pos] = 0
        hidden_counts[pos] = 0
    header_set = set(headers)
    for node_pos, node in enumerate(rows):
        if node.role is not NodeFinderRole.NODE or not node.jumpable:
            continue
        hidden = bool(node.reasons)
        if node_pos in header_set:
            jumpable_counts[node_pos] += 1
            if hidden:
                hidden_counts[node_pos] += 1
        for ancestor in _ancestor_chain(rows, node_pos, chains):
            if ancestor in header_set:
                jumpable_counts[ancestor] += 1
                if hidden:
                    hidden_counts[ancestor] += 1
    return {pos: (jumpable_counts[pos], hidden_counts[pos]) for pos in headers}


__all__ = [
    "build_node_finder_snapshot",
]
