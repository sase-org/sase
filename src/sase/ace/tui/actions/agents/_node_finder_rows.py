"""Per-panel row construction for the Node Finder snapshot.

Split from :mod:`_node_finder_snapshot`: walks each panel's grouping
tree and emits panel/group/node rows with hidden-reason classification.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ...models._agent_tree import agent_parent_fold_key, agent_tree_depth
from ...models.agent import AgentType
from ...models.agent_groups import GroupingMode, banner_label_for_group_key
from ...models.node_finder import (
    NodeFinderReason,
    NodeFinderRole,
    NodeFinderRow,
    describe_node_finder_row,
    describe_node_finder_row_from_facts,
    kind_styles,
    node_finder_name,
)
from sase.project_display_names import humanize_cl_name

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panels import AgentPanelGroup

    AgentIdentity = tuple[AgentType, str, str | None]

logger = logging.getLogger(__name__)

#: Shared empty reasons set: most visible rows carry no reason, so reusing
#: one instance skips a per-row ``frozenset`` allocation with equal value.
_NO_REASONS: frozenset[NodeFinderReason] = frozenset()

#: Bitmask positions for :class:`NodeFinderReason` members, used to intern
#: the per-row reason sets below: rows sharing one combination (the common
#: case is a single reason) reuse one ``frozenset`` instead of allocating
#: a set plus a frozenset per row.
_REASON_BITS = (
    NodeFinderReason.PANEL,
    NodeFinderReason.BANNER,
    NodeFinderReason.FOLDED,
    NodeFinderReason.QUERY,
    NodeFinderReason.NON_RUN,
)

#: Shared empty enclosing-group key sequence: avoids one list allocation
#: per row when the agent sits under no group banner.
_NO_ENCLOSING: tuple[tuple[str, ...], ...] = ()


def _reasons_for_mask(
    mask: int, cache: dict[int, frozenset[NodeFinderReason]]
) -> frozenset[NodeFinderReason]:
    """Return the interned reason set for *mask*, building it once."""
    try:
        return cache[mask]
    except KeyError:
        reasons = frozenset(
            reason for bit, reason in enumerate(_REASON_BITS) if mask & (1 << bit)
        )
        cache[mask] = reasons
        return reasons


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


def build_snapshot_rows(
    owner: Any,
    panel_group: AgentPanelGroup,
    expanded: list[Agent],
    expanded_tree_state: tuple[dict[str, Agent], dict[int, Agent]],
    mode: GroupingMode,
    merged: bool,
    no_fold_parents: bool,
    no_banner_collapse: bool,
    collapsed_panels: Any,
    unmet: dict[AgentIdentity, tuple[str, ...]],
    query_set: set[AgentIdentity] | None,
    hidden_by_i: set[AgentIdentity],
    rendered: set[AgentIdentity],
    parents: dict[str, Agent],
    parent_keys: dict[int, str | None],
    depths: dict[int, int],
    identity_of: dict[int, AgentIdentity],
    describe_facts: dict[int, tuple[Any, ...]],
    is_monitor_map: dict[int, bool],
    is_gate_map: dict[int, bool],
) -> tuple[
    list[NodeFinderRow],
    dict[AgentIdentity, int],
    set[AgentIdentity],
    bool,
    bool,
    bool,
    bool,
]:
    """Build panel/group/node rows for every panel in *panel_group*.

    Returns ``(rows, index_by_identity, descendant_of_jumpable,
    all_jumpable, has_bare_unrendered, saw_empty_panel, saw_dupe_skip)``.
    The flags after the index are the clean-keep witnesses the omission
    pass consumes: no row can be omitted when nothing is dismissed, every
    node is jumpable, and no reasonless row is unrendered.
    """
    from ...models.agent_groups import build_agent_tree
    from ...models.agent_panels import agents_for_panel
    from ...models.group_fold import GroupFoldRegistry

    from ._fold_scope import panel_fold_registry

    _describe_styles = kind_styles()

    rows: list[NodeFinderRow] = []
    index_by_identity: dict[AgentIdentity, int] = {}
    # Fold keys repeat across clan members, so the collapsed label for one
    # unmet key tuple serves every row that shares it within this snapshot.
    _nearest_collapsed_memo: dict[tuple[str, ...], str] = {}
    # Reason combinations repeat the same way; one interned frozenset per
    # combination replaces a set plus a frozenset allocation per row.
    _reason_sets: dict[int, frozenset[NodeFinderReason]] = {}
    # Fold ancestors of jumpable rows, collected in the row loop so the
    # omission pass below needs no second walk over every row.
    descendant_of_jumpable: set[AgentIdentity] = set()
    # Clean-keep witnesses for the omission skip below. No row can be
    # omitted when nothing is dismissed, every node is jumpable, and no
    # reasonless row is unrendered. Every header then keeps a kept
    # descendant too: each panel holds at least one appended node, and
    # each group banner was emitted while walking an appended, kept node
    # beneath it — provided no panel came up empty and no duplicate
    # identity was skipped.
    all_jumpable = True
    has_bare_unrendered = False
    saw_empty_panel = False
    saw_dupe_skip = False

    single_panel = len(panel_group.panel_keys) == 1 and not merged
    for panel_key in panel_group.panel_keys:
        if single_panel:
            # The one panel key covers the whole roster by construction
            # (``from_agents`` derived it from these agents), so every
            # rendered agent belongs to it: filter by the shared rendered
            # predicate instead of re-resolving each agent's panel key.
            # The status check is inlined from
            # ``agent_is_rendered_in_agents_panel`` (a ``STARTING`` row
            # never renders); the call overhead dominates the check.
            panel_agents = [agent for agent in expanded if agent.status != "STARTING"]
        else:
            panel_agents = agents_for_panel(
                expanded,
                panel_key,
                merge_tribe_panels=merged,
                tree_state=expanded_tree_state,
            )
        if not panel_agents:
            saw_empty_panel = True
        # The index above already covers this exact roster when the panel
        # kept every row, so the tree reuses it instead of rebuilding the
        # same parent/anchor tables for the same objects in the same order.
        # ``panel_agents`` filters ``expanded`` in order with no
        # transformation, so equal length alone proves elementwise
        # identity — no second pass needed.
        if len(panel_agents) == len(expanded):
            panel_tree_state: tuple[dict[str, Agent], dict[int, Agent]] | None = (
                expanded_tree_state
            )
        else:
            panel_tree_state = None
        tree = build_agent_tree(
            panel_agents,
            fold_registry=GroupFoldRegistry(),
            mode=mode,
            tree_state=panel_tree_state,
            singleton_anchors=no_fold_parents,
            # Banner member indices only feed the enclosing map, which is
            # skipped exactly when no banner is collapsed.
            materialize_indices=not no_banner_collapse,
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
        # The enclosing map only feeds per-row ``is_collapsed`` checks. The
        # fast rendered path above verified every panel registry has no
        # collapsed banner, so those checks would all return False and the
        # map stays empty.
        enclosing: dict[int, list[tuple[str, ...]]] = {}
        if not no_banner_collapse:
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
            try:
                identity = identity_of[agent_key]
            except KeyError:
                identity = agent.identity
            if identity in index_by_identity:
                saw_dupe_skip = True
                continue

            # Reasons accumulate as a bitmask over ``_REASON_BITS`` so rows
            # sharing one combination reuse an interned frozenset instead
            # of allocating a set plus a frozenset per row.
            reason_mask = 0
            if panel_key in collapsed_panels:
                reason_mask |= 1
            collapsed_key: tuple[str, ...] | None = None
            for key in enclosing.get(entry.agent_idx, _NO_ENCLOSING):
                if callable(is_collapsed) and is_collapsed(key):
                    collapsed_key = key
            group_label = ""
            if collapsed_key is not None:
                reason_mask |= 2
                group_label = banner_label_for_group_key(collapsed_key)
            missing = unmet.get(identity, ()) if unmet else ()
            if missing:
                reason_mask |= 4
            if query_set is not None and identity not in query_set:
                reason_mask |= 8
            if identity in hidden_by_i:
                reason_mask |= 16
            if identity in rendered:
                if reason_mask:
                    logger.debug(
                        "node finder contradiction: rendered row %r has reasons %r",
                        identity,
                        sorted(
                            reason.value
                            for bit, reason in enumerate(_REASON_BITS)
                            if reason_mask & (1 << bit)
                        ),
                    )
                reason_mask = 0

            # Batched description consumes the per-open fact tables plus
            # one shared style binding instead of re-reading agent
            # properties per row; agents outside the roster keep the exact
            # single-row contract. Ordinary running rows carry a short
            # fact tuple for the plain describer.
            try:
                facts = describe_facts[agent_key]
            except KeyError:
                facts = None
            if facts is not None and len(facts) == 5:
                # Inlined ``_describe_plain_row``: ordinary running rows
                # are the hot path, and the call plus result packing
                # costs more than the name/title/kind reads themselves.
                # Any other shape uses the full batched describer below;
                # the differential test pins this against the single-row
                # contract.
                _plain_presented = facts[0]
                _plain_agent_name = facts[1]
                _plain_display = facts[2]
                _plain_cl = facts[3]
                name = (
                    _plain_presented
                    or _plain_agent_name
                    or _plain_display
                    or humanize_cl_name(_plain_cl)
                )
                title = (
                    ""
                    if (not _plain_display or _plain_display == name)
                    else _plain_display
                )
                jumpable = not facts[4]
                kind_label = "AGENT TURN"
                kind_accent = _describe_styles["agent_entry"]
            elif facts is not None and len(facts) != 5:
                # The facet pass stores a short 5-tuple exactly for ordinary
                # running rows and a full 19-tuple otherwise, keyed by the
                # same complete-roster ids as the monitor/gate maps — so a
                # non-short tuple is exactly the old three-way condition.
                # Agents outside the roster carry no facts and keep the
                # single-row contract below.
                jumpable, name, title, kind_label, kind_accent = (
                    describe_node_finder_row_from_facts(
                        is_clan=facts[0],
                        is_proc=facts[1],
                        is_wf_step=facts[2],
                        step_type=facts[3],
                        presented=facts[4],
                        agent_name=facts[5],
                        display_name=facts[6],
                        cl_name=facts[7],
                        is_session_container=facts[8],
                        is_monitor=is_monitor_map[agent_key],
                        is_gate=is_gate_map[agent_key],
                        is_agent_entry=facts[9],
                        agent_clan=facts[10],
                        proc_label=facts[11],
                        proc_safe_preview=facts[12],
                        step_name=facts[13],
                        is_session_member_child=facts[14],
                        is_pre_prompt_step=facts[15],
                        agent_type=facts[16],
                        is_workflow_child=facts[17],
                        appears_as_agent=facts[18],
                        styles=_describe_styles,
                    )
                )
            else:
                jumpable, name, title, kind_label, kind_accent = (
                    describe_node_finder_row(agent)
                )

            parent_row = group_stack[-1][1] if group_stack else panel_idx
            try:
                first_key = parent_keys[agent_key]
            except KeyError:
                first_key = agent_parent_fold_key(agent)
            # Without fold parents the climb below would exit immediately
            # and record nothing, so it is skipped outright; with an empty
            # parent map the lookups below would miss the same way.
            if first_key and not no_fold_parents:
                if jumpable:
                    # One climb serves the tree-parent override (first
                    # hop) and the jumpable-descendant marking (every
                    # hop) that the omission pass below consumes. Without
                    # fold parents this walk would exit immediately, so
                    # the gate above already skipped it. A single hop
                    # cannot revisit a key, so the cycle set is only
                    # allocated when the chain continues past it.
                    fold_parent = parents.get(first_key)
                    if fold_parent is not None:
                        fold_parent_id = id(fold_parent)
                        try:
                            _fold_identity = identity_of[fold_parent_id]
                        except KeyError:
                            _fold_identity = fold_parent.identity
                        descendant_of_jumpable.add(_fold_identity)
                        if (
                            _fold_identity in index_by_identity
                            and _fold_identity != identity
                        ):
                            parent_row = index_by_identity[_fold_identity]
                        if fold_parent_id in parent_keys:
                            current_key = parent_keys[fold_parent_id]
                        else:
                            current_key = agent_parent_fold_key(fold_parent)
                        seen_keys: set[str] = {first_key}
                        while current_key and current_key not in seen_keys:
                            seen_keys.add(current_key)
                            fold_parent = parents.get(current_key)
                            if fold_parent is None:
                                break
                            fold_parent_id = id(fold_parent)
                            try:
                                _fold_identity = identity_of[fold_parent_id]
                            except KeyError:
                                _fold_identity = fold_parent.identity
                            descendant_of_jumpable.add(_fold_identity)
                            if fold_parent_id in parent_keys:
                                current_key = parent_keys[fold_parent_id]
                            else:
                                current_key = agent_parent_fold_key(fold_parent)
                else:
                    tree_parent = parents.get(first_key, None)
                    if tree_parent is not None:
                        tree_identity = identity_of.get(id(tree_parent))
                        if tree_identity is None:
                            tree_identity = tree_parent.identity
                        if (
                            tree_identity in index_by_identity
                            and tree_identity != identity
                        ):
                            parent_row = index_by_identity[tree_identity]

            if missing:
                if missing not in _nearest_collapsed_memo:
                    _nearest_collapsed_memo[missing] = _nearest_collapsed_label(
                        missing, parents
                    )
                nearest_collapsed = _nearest_collapsed_memo[missing]
            else:
                # The empty chain labels itself ``""``; skip the memo traffic
                # for the common unhidden row.
                nearest_collapsed = ""
            index_by_identity[identity] = len(rows)
            try:
                row_depth = depths[agent_key]
            except KeyError:
                row_depth = agent_tree_depth(agent)
            rows.append(
                # Positional construction in ``NodeFinderRow`` field order:
                # node rows are the hottest allocation in the snapshot.
                # Keep the order in sync with the dataclass definition.
                NodeFinderRow(
                    NodeFinderRole.NODE,
                    identity,
                    agent,
                    name,
                    title,
                    kind_label,
                    kind_accent,
                    row_depth + 1,
                    panel_key,
                    parent_row,
                    jumpable,
                    (
                        _NO_REASONS
                        if reason_mask == 0
                        # Inlined ``_reasons_for_mask`` hit path: shared
                        # combinations reuse one interned frozenset, and
                        # the call overhead exceeds the dict hit.
                        else _reason_sets.get(reason_mask)
                        or _reasons_for_mask(reason_mask, _reason_sets)
                    ),
                    len(missing),
                    nearest_collapsed,
                    group_label,
                )
            )
            if not jumpable:
                all_jumpable = False
            elif reason_mask == 0 and identity not in rendered:
                has_bare_unrendered = True
            # Fold ancestors of jumpable rows were marked during the
            # fused parent climb above, so the omission pass below needs
            # no second walk over every row.

    return (
        rows,
        index_by_identity,
        descendant_of_jumpable,
        all_jumpable,
        has_bare_unrendered,
        saw_empty_panel,
        saw_dupe_skip,
    )


__all__ = [
    "build_snapshot_rows",
]
