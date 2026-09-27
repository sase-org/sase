"""Orchestration for the owner-aware Node Finder snapshot.

Split from :mod:`_node_finder_snapshot`: projects every reachable node
row and classifies why each is hidden. Facet reads, fold walks, row
construction, and finalization live in sibling modules; this module only
wires them together.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...models.agent_groups import GroupingMode
from ...models.node_finder import NODE_FINDER_HINT_CAPACITY, NodeFinderSnapshot

from ._node_finder_facets import snapshot_all_facets
from ._node_finder_finalize import (
    apply_snapshot_omission,
    count_snapshot_headers,
    evolve_row,
)
from ._node_finder_folds import expanded_roster_keep_all, unmet_with_facets
from ._node_finder_rows import build_snapshot_rows

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey

    AgentIdentity = tuple[AgentType, str, str | None]


def _snapshot_has_banner_collapse(owner: Any, panel_keys: list[Any]) -> bool:
    """Return whether any panel grouping registry currently collapses a banner.

    The snapshot's fast rendered path skips the full jump-target tree walks
    when no panel or banner is collapsed; any collapsed state falls back to
    the exact ``_jump_candidate_targets`` walk so hidden rows stay hidden.
    """
    from ._fold_scope import panel_fold_registry

    for panel_key in panel_keys:
        try:
            registry = panel_fold_registry(owner, panel_key)
        except Exception:
            return True
        if registry is None:
            continue
        collapsed = getattr(registry, "collapsed", None)
        if isinstance(collapsed, (set, frozenset)):
            if collapsed:
                return True
            continue
        snapshot = getattr(registry, "snapshot", None)
        if callable(snapshot):
            try:
                if snapshot():
                    return True
            except Exception:
                return True
            continue
        # Unknown registry shape: stay exact via the slow path.
        return True
    return False


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
    from ...models._agent_tree import presentation_anchor_lookup, tree_parent_lookup
    from ...models.agent_panels import AgentPanelGroup
    from ._panel_fold_intent import effective_panel_collapses
    from ._prospective_clan import FoldStateProjection, apply_active_agent_query

    complete, hidden_by_i = _complete_roster_for_snapshot(owner)
    (
        parent_keys,
        fold_keys,
        depths,
        identity_of,
        hidden_steps,
        is_monitor_map,
        is_gate_map,
        is_child_row_map,
        describe_facts,
    ) = snapshot_all_facets(complete)

    # A roster with no fold parent on any agent has no rendered tree edges:
    # every agent anchors to itself, no fold chain can be unmet, and the
    # parent index below is never consulted (every use is guarded by a
    # truthy parent key or an empty ``missing`` tuple). Such rosters skip
    # the parent index, the anchor resolution, and the unmet walk.
    no_fold_parents = True
    for _parent_key in parent_keys.values():
        if _parent_key is not None:
            no_fold_parents = False
            break
    if no_fold_parents:
        parents = {}
    else:
        parents = tree_parent_lookup(complete)

    fold_manager = getattr(owner, "_fold_manager", None)
    if _roster_needs_no_fold_filter(parent_keys, hidden_steps):
        # No agent has a fold parent and no hidden step exists, so the
        # fold filter would return the roster unchanged: skip its
        # per-agent walk. The discarded fold counts are unused here, and
        # no fold projection is needed on this path.
        expanded = list(complete)
    else:
        # The fold projection exists only for the filter paths below.
        from ...models.fold_state import FoldLevel

        if fold_manager is not None:
            levels: dict[str, object] = dict(fold_manager.snapshot())
        else:
            levels = {}
        for fold_key in fold_keys.values():
            if fold_key is not None:
                levels[fold_key] = FoldLevel.FULLY_EXPANDED
        projection = FoldStateProjection(levels)
        # Same keep-all outcome through distinct owner chains instead of
        # the filter's per-agent walk; falls back to the exact filter for
        # hidden steps, turns, gaps, collapsed levels, and cycles.
        keep_all = expanded_roster_keep_all(
            complete,
            projection,
            parent_keys,
            fold_keys,
            hidden_steps,
            is_monitor_map,
            is_gate_map,
            is_child_row_map,
        )
        if keep_all is None:
            expanded, _ = filter_agents_by_fold_state(
                complete,
                projection,  # type: ignore[arg-type]
                fold_keys=fold_keys,
                parent_keys=parent_keys,
                hidden_steps=hidden_steps,
                is_monitor_map=is_monitor_map,
                is_gate_map=is_gate_map,
                is_child_row_map=is_child_row_map,
            )
        else:
            expanded = keep_all

    merged = bool(getattr(owner, "_agent_panels_grouped", False))
    mode: GroupingMode = getattr(owner, "_grouping_mode", GroupingMode.STANDARD)
    # One roster index shared by every panel query below: panel grouping
    # filters the same expanded roster once per panel key. The tree state
    # is only ever consumed through its anchors
    # (``presentation_anchor`` with a provided anchor map never consults
    # the parent index), so the edgeless path reuses the empty parent map.
    if no_fold_parents:
        # With no rendered edges each agent anchors to itself, exactly what
        # the full anchor resolution would produce for this roster.
        expanded_lookup = parents
        expanded_anchors = {id(agent): agent for agent in expanded}
    elif len(expanded) == len(complete) and all(
        new is old for new, old in zip(expanded, complete, strict=True)
    ):
        # When the fold filter kept every row, the expanded roster holds
        # the same objects as the complete roster, so the index built above
        # is reused as is.
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
    if len(current_agents) == len(expanded) and all(
        current is kept for current, kept in zip(current_agents, expanded, strict=True)
    ):
        # The live list holds the same objects in the same order as the
        # roster the anchors above were resolved over, so the collapse
        # check reuses that index instead of rebuilding one: panel keys
        # resolve through the anchor map alone.
        collapse_state = expanded_tree_state
    else:
        collapse_state = None
    # Only live panels can hide a row (``panel_key in collapsed_panels``
    # below) or decide the fast rendered path: config-default collapses
    # for absent panels (e.g. ``chop``) must not defeat it. This matches
    # ``_jump_candidate_targets``, which already passes its live keys.
    collapsed_panels = effective_panel_collapses(
        owner, list(panel_group.panel_keys), tree_state=collapse_state
    )

    jump_targets = getattr(owner, "_jump_candidate_targets", None)
    no_banner_collapse = False
    if (
        callable(jump_targets)
        and not collapsed_panels
        and not _snapshot_has_banner_collapse(owner, list(panel_group.panel_keys))
    ):
        # No panel or banner is collapsed, so the jump-target walk would
        # return every rendered agent in order: reuse the live list
        # directly without rebuilding grouping trees per panel. STARTING
        # rows never render (see ``agent_is_rendered_in_agents_panel``),
        # matching the jump walk's own exclusion.
        no_banner_collapse = True
        rendered = set()
        for _agent in current_agents:
            if _agent.status == "STARTING":
                continue
            _identity = identity_of.get(id(_agent))
            if _identity is None:
                _identity = _agent.identity
            rendered.add(_identity)
    elif callable(jump_targets):
        rendered = set()
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

    dismissed = set(getattr(owner, "_dismissed_agents", set()) or ())

    if fold_manager is not None and not no_fold_parents:
        unmet = unmet_with_facets(
            complete,
            fold_manager,
            parents,
            parent_keys,
            hidden_steps,
            identity_of,
        )
    else:
        # Without fold parents every chain resolves valid with no
        # requirements (each edge returns ``(None, ...)`` up front), so no
        # row ever records a missing fold: the walk would return ``{}``.
        unmet = {}

    from ._agent_tab_jump import off_tab_labels_for_owner

    try:
        off_tab_labels = off_tab_labels_for_owner(owner)
    except Exception:
        off_tab_labels = {}
    (
        rows,
        index_by_identity,
        descendant_of_jumpable,
        all_jumpable,
        has_bare_unrendered,
        saw_empty_panel,
        saw_dupe_skip,
    ) = build_snapshot_rows(
        owner,
        panel_group,
        expanded,
        expanded_tree_state,
        mode,
        merged,
        no_fold_parents,
        no_banner_collapse,
        collapsed_panels,
        unmet,
        query_set,
        hidden_by_i,
        rendered,
        parents,
        parent_keys,
        depths,
        identity_of,
        describe_facts,
        is_monitor_map,
        is_gate_map,
        off_tab_labels,
    )

    clean_keep = (
        not dismissed
        and all_jumpable
        and not has_bare_unrendered
        and not saw_empty_panel
        and not saw_dupe_skip
    )
    if clean_keep:
        # The row loop witnessed clean-keep (see the flag proof above): every
        # row stays, every parent index still resolves to itself, and the
        # row-loop identity index stays valid.
        counts_chains = None
    else:
        rows, index_by_identity, counts_chains = apply_snapshot_omission(
            rows, dismissed, rendered, descendant_of_jumpable
        )

    header_counts, node_count, hidden, query_hidden, hidden_by_i_count = (
        count_snapshot_headers(rows, counts_chains, clean_keep)
    )

    here_row: int | None = None
    if (
        getattr(owner, "current_tab", None) == "agents"
        and getattr(owner, "_current_group_key", None) is None
    ):
        get_selected = getattr(owner, "_get_selected_agent", None)
        selected = get_selected() if callable(get_selected) else None
        if selected is not None and selected.identity in index_by_identity:
            here_row = index_by_identity[selected.identity]
    if header_counts or here_row is not None:
        # Only headers and the here row change, so evolve them in place
        # instead of rebuilding the whole list: positions and every other
        # row object are untouched, and the identity index stays valid.
        for pos, counts in header_counts.items():
            row = rows[pos]
            rows[pos] = evolve_row(
                row,
                jumpable_count=counts[0],
                hidden_count=counts[1],
            )
        if here_row is not None:
            rows[here_row] = evolve_row(rows[here_row], is_here=True)

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


__all__ = [
    "build_node_finder_snapshot",
]
