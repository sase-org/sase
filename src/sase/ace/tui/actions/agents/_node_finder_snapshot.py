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
from ...models.agent import AgentType, project_file_parent_name
from ...models.agent_groups import GroupingMode, banner_label_for_group_key
from sase.gate_turn.state import is_real_gate_member
from sase.monitor_state import is_monitor_member_role
from sase.project_display_names import humanize_cl_name

from ...models.agent_panels import (
    AgentPanelGroup,
    agent_is_rendered_in_agents_panel,
    agents_for_panel,
)
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


def _evolve(row: NodeFinderRow, **changes: Any) -> NodeFinderRow:
    return replace(row, **changes)


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


#: Position of each :func:`describe_node_finder_row_from_facts` fact inside
#: the per-agent tuple built by :func:`_snapshot_all_facets`. The tuple
#: carries every naming/role fact the batched describer needs, so the row
#: loop never re-reads an agent property the facet pass already covered.
_DESCRIBE_FACT_FIELDS = (
    "is_clan",
    "is_proc",
    "is_wf_step",
    "step_type",
    "presented",
    "agent_name",
    "display_name",
    "cl_name",
    "is_session_container",
    "is_agent_entry",
    "agent_clan",
    "proc_label",
    "proc_safe_preview",
    "step_name",
    "is_session_member_child",
    "is_pre_prompt_step",
    "agent_type",
    "is_workflow_child",
    "appears_as_agent",
)


def _describe_plain_row(
    presented: str | None,
    agent_name: str | None,
    display_name: str,
    cl_name: str,
    is_pre_prompt_step: bool,
    styles: dict[str, Any],
) -> tuple[bool, str, str, str, str]:
    """Return ``(jumpable, name, title, kind_label, kind_accent)`` for plain rows.

    Exact fast path through :func:`describe_node_finder_row_from_facts`
    for ordinary running agents (no clan/proc/workflow-step/session shape
    and no monitor/gate/session-child role): the name, title, jumpable,
    and kind branches collapse to these reads, and a running non-shell
    row is always an agent entry. Any other shape uses the full batched
    describer; the differential test pins this against the single-row
    contract.
    """
    name = presented or agent_name or display_name or humanize_cl_name(cl_name)
    raw_title = display_name or None
    title = "" if (not raw_title or raw_title == name) else raw_title
    return (
        not is_pre_prompt_step,
        name,
        title,
        "AGENT SHELL",
        styles["agent_entry"],
    )


def _snapshot_all_facets(
    complete: list[Agent],
) -> tuple[
    dict[int, str | None],
    dict[int, str | None],
    dict[int, int],
    dict[int, AgentIdentity],
    set[int],
    dict[int, bool],
    dict[int, bool],
    dict[int, bool],
    dict[int, tuple[Any, ...]],
]:
    """Read every per-open facet once, including role facts.

    Beyond the base tables, each agent pays once for the monitor/gate role
    booleans and child linkage that the fold filter otherwise recomputes
    per pass via repeated plan-chain suffix parses. The child linkage enum
    answers ``is_child_row`` for the filter and the workflow-step, session
    child, and workflow-child flags for the row describer from one read.
    The row loop reuses the same facts plus one shared kind-style binding
    when calling the batched describer, instead of re-parsing suffixes per
    property per row. Every table is local to this snapshot; live owner
    state is still read afresh on every open. The shell/child maps stay
    sparse: ordinary running rows are never shells or child rows, so only
    other shapes populate them, and every consumer falls back to the same
    live read for a missing id.
    """
    from ...models._agent_tree import agent_fold_key
    from ...models.agent import AgentChildLinkage
    from ...models.agent_types import AgentType

    parent_keys: dict[int, str | None] = {}
    fold_keys: dict[int, str | None] = {}
    depths: dict[int, int] = {}
    identity_of: dict[int, AgentIdentity] = {}
    hidden_steps: set[int] = set()
    is_monitor_map: dict[int, bool] = {}
    is_gate_map: dict[int, bool] = {}
    is_child_row_map: dict[int, bool] = {}
    describe_facts: dict[int, tuple[Any, ...]] = {}
    for agent in complete:
        key = id(agent)
        # ``agent_parent_fold_key`` is the first truthy link (a falsy
        # ``tree_parent_key`` falls through exactly like the ``if`` does);
        # ``agent_fold_key`` is the clan key for clan containers and the
        # raw suffix otherwise. Inlining both skips two calls per agent.
        parent_keys[key] = agent.tree_parent_key or agent.parent_timestamp or None
        if agent.is_clan_container and agent.agent_clan:
            fold_keys[key] = agent_fold_key(agent)
        else:
            fold_keys[key] = agent.raw_suffix or None
        linkage = agent.child_linkage
        is_child_row = linkage is not AgentChildLinkage.ROOT
        # ``agent_tree_depth`` prefers the stored depth and falls back to
        # child-row detection; the linkage read above already answers it.
        tree_depth = agent.tree_depth
        depths[key] = tree_depth if tree_depth > 0 else (1 if is_child_row else 0)
        identity_of[key] = agent.identity
        if agent.is_hidden_step:
            hidden_steps.add(key)
        # The monitor/gate predicates stay the single implementation in
        # their state modules; reading the three metadata fields once here
        # skips two property indirections per agent.
        agent_session_role = agent.agent_session_role
        is_monitor = is_monitor_member_role(agent_session_role, agent.role_suffix)
        is_gate = is_real_gate_member(agent_session_role, agent.gate_id)
        is_clan = agent.is_clan_container
        is_proc = agent.is_proc_shell
        is_wf_step = linkage is AgentChildLinkage.WORKFLOW_STEP
        is_session_child = linkage is AgentChildLinkage.AGENT_SESSION_MEMBER
        # ``is_agent_session_root_entry`` is ``not is_workflow_child``
        # (``is_workflow_child`` is exactly ``linkage is not ROOT``: session
        # members and workflow steps both count as children) plus root
        # metadata; inlining the two attribute reads avoids re-deriving the
        # linkage through the property. The container flag adds the member
        # check from its body.
        is_root_entry = (linkage is AgentChildLinkage.ROOT) and (
            agent.plan_chain_root or agent.agent_session_role == "root"
        )
        if (
            not is_clan
            and not is_proc
            and not is_wf_step
            and not is_monitor
            and not is_gate
            and not is_session_child
            and not (is_root_entry and bool(agent.followup_agents))
            and agent.agent_type is AgentType.RUNNING
        ):
            # Ordinary running row: the plain describer needs only the
            # naming facts plus the pre-prompt flag. All other shapes
            # record the full fact tuple for the batched describer.
            # The display name inlines ``display_name``'s tail: the plain
            # condition already excluded clan/proc/gate shapes and
            # non-RUNNING types, so only the project-agent branch can still
            # apply; anything else humanizes the cl name.
            project_display = agent.project_display_name
            if (
                project_display
                and agent.project_file
                and agent.cl_name == project_file_parent_name(agent.project_file)
            ):
                plain_display = project_display
            else:
                plain_display = humanize_cl_name(agent.cl_name)
            describe_facts[key] = (
                agent.presented_agent_name,
                agent.agent_name,
                plain_display,
                agent.cl_name,
                agent.is_pre_prompt_step,
            )
            continue
        # Only non-plain rows populate the shell/child maps: the plain
        # branch above already proved its rows are never shells or child
        # rows, and every map consumer (the fold filter, the keep-all fast
        # path, and the row describer) falls back to the same live read
        # for a missing id.
        is_monitor_map[key] = is_monitor
        is_gate_map[key] = is_gate
        is_child_row_map[key] = is_child_row
        describe_facts[key] = (
            is_clan,
            is_proc,
            is_wf_step,
            agent.step_type,
            agent.presented_agent_name,
            agent.agent_name,
            agent.display_name,
            agent.cl_name,
            agent.is_agent_session_container_row,
            agent.is_agent_entry,
            agent.agent_clan,
            agent.proc_label,
            agent.proc_safe_preview,
            agent.step_name,
            is_session_child,
            agent.is_pre_prompt_step,
            agent.agent_type,
            is_child_row,
            agent.appears_as_agent,
        )
    return (
        parent_keys,
        fold_keys,
        depths,
        identity_of,
        hidden_steps,
        is_monitor_map,
        is_gate_map,
        is_child_row_map,
        describe_facts,
    )


def _unmet_with_facets(
    complete: list[Agent],
    fold_manager: Any,
    parents: dict[str, Agent],
    parent_keys: dict[int, str | None],
    hidden_steps: set[int],
) -> dict[AgentIdentity, tuple[str, ...]]:
    """Return each row's unmet ancestor fold keys, nearest first.

    Facet-driven equivalent of :func:`unmet_ancestor_folds` for one
    snapshot: parent keys and hidden-step flags come from the single
    per-open facet read instead of re-deriving plan-chain predicates once
    per row. Cycle, bound, and missing-parent guards match the reveal
    preflight exactly, so rows with invalid ancestry are omitted the same
    way; any agent missing from the tables falls back to a direct read.

    Ancestor chains are deterministic (each agent resolves to one parent),
    so one agent's requirement list is its own edge plus its parent's
    already-resolved list. Shared clan/session ancestors resolve once per
    snapshot instead of once per member; per-pair fold-level checks memoize
    the same way. Results match the historical per-row walk exactly.
    """
    from ...models._agent_tree import agent_parent_fold_key
    from ...models.fold_state import FoldLevel
    from ..navigation._agent_reveal import fold_requirement_is_met

    bound = len(complete) + 1
    get_level = fold_manager.get
    # ``memo`` maps ``id(agent)`` to ``(requirements, valid)`` where
    # requirements lists ``(fold_key, level)`` nearest-first exactly as the
    # historical walk. ``met`` memoizes the fold-level check per distinct
    # ``(fold_key, level)`` pair.
    memo: dict[int, tuple[tuple[tuple[str, FoldLevel], ...], bool]] = {}
    met: dict[tuple[str, FoldLevel], bool] = {}

    def _met(fold_key: str, level: FoldLevel) -> bool:
        try:
            return met[(fold_key, level)]
        except KeyError:
            result = fold_requirement_is_met(get_level(fold_key), level)
            met[(fold_key, level)] = result
            return result

    def _edge(
        agent: Agent, agent_id: int
    ) -> tuple[str | None, FoldLevel, Agent | None]:
        if agent_id in parent_keys:
            parent_key = parent_keys[agent_id]
        else:
            parent_key = agent_parent_fold_key(agent)
        if parent_key is None:
            return None, FoldLevel.EXPANDED, None
        parent = parents.get(parent_key)
        if parent is None:
            return parent_key, FoldLevel.EXPANDED, None
        if agent_id in hidden_steps:
            is_hidden = True
        elif agent_id in parent_keys:
            # Roster members use the table: ``hidden_steps`` holds
            # exactly the hidden ones.
            is_hidden = False
        else:
            is_hidden = agent.is_hidden_step
        return (
            parent_key,
            (
                FoldLevel.FULLY_EXPANDED
                if is_hidden and not parent_key.startswith("clan:")
                else FoldLevel.EXPANDED
            ),
            parent,
        )

    def _resolve(
        agent: Agent,
    ) -> tuple[tuple[tuple[str, FoldLevel], ...], bool]:
        """Resolve one agent's chain iteratively with cycle detection.

        The explicit stack mirrors the historical ``visited`` walk: an edge
        back into the current stack marks the whole stack invalid, a
        missing parent marks it invalid, and a memoized ancestor splices
        its already-resolved requirements in. Bound accounting matches the
        historical ``range(bound)`` loop: a chain terminates validly only
        when its total edge count stays under ``bound``.
        """
        stack: list[tuple[Agent, int, str, FoldLevel, Agent]] = []
        stack_ids: set[int] = set()
        current = agent
        while True:
            current_id = id(current)
            hit = memo.get(current_id)
            if hit is not None:
                parent_reqs, parent_valid = hit
                break
            if current_id in stack_ids:
                for _, stale_id, _, _, _ in stack:
                    memo[stale_id] = ((), False)
                return (), False
            parent_key, level, parent = _edge(current, current_id)
            if parent is None:
                if parent_key is None:
                    parent_reqs, parent_valid = (), True
                else:
                    for _, stale_id, _, _, _ in stack:
                        memo[stale_id] = ((), False)
                    memo[current_id] = ((), False)
                    return (), False
                break
            assert parent_key is not None
            stack.append((current, current_id, parent_key, level, parent))
            stack_ids.add(current_id)
            current = parent
        if not parent_valid:
            for _, stale_id, _, _, _ in stack:
                memo[stale_id] = ((), False)
            memo[id(current)] = (parent_reqs, False)
            return (), False
        # Splice the stack back out: each frame's requirements are its own
        # edge plus everything beneath it, exactly as a standalone walk
        # from that frame would collect.
        suffix: tuple[tuple[str, FoldLevel], ...] = parent_reqs
        for _, frame_id, frame_key, frame_level, _ in reversed(stack):
            if len(suffix) + 1 >= bound:
                for _, stale_id, _, _, _ in stack:
                    memo[stale_id] = ((), False)
                memo[id(current)] = (parent_reqs, False)
                return (), False
            suffix = ((frame_key, frame_level),) + suffix
            memo[frame_id] = (suffix, True)
        memo[id(current)] = (parent_reqs, True)
        requirements = list(suffix)
        return tuple(requirements), True

    unmet: dict[AgentIdentity, tuple[str, ...]] = {}
    for agent in complete:
        requirements, valid = _resolve(agent)
        if not valid:
            continue
        missing = tuple(
            fold_key for fold_key, level in requirements if not _met(fold_key, level)
        )
        if missing:
            unmet[agent.identity] = missing
    return unmet


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


def _expanded_roster_keep_all(
    complete: list[Agent],
    projection: Any,
    parent_keys: dict[int, str | None],
    fold_keys: dict[int, str | None],
    hidden_steps: set[int],
    is_monitor_map: dict[int, bool],
    is_gate_map: dict[int, bool],
    is_child_row_map: dict[int, bool],
) -> list[Agent] | None:
    """Return ``list(complete)`` when the fold filter would keep every row.

    Snapshot-local fast path for :func:`filter_agents_by_fold_state`, whose
    fold counts this caller discards. With no hidden step, no monitor/gate
    shell, every parent key owned, and no collapsed level on any owner's
    chain, every row is visible: hidden-only parents need a hidden child,
    shell gating needs a shell, and the remaining visibility rule is one
    non-collapsed owner chain per row. Owner chains resolve over distinct
    fold keys with memoization; a cycle falls back to the exact filter.
    ``None`` means the fast path does not apply. The facet tables cover
    every roster id by construction, except the shell/child maps, which
    only hold non-plain rows and fall back to the same live read for a
    missing id (a plain row is never a shell or a child row).
    """
    from ...models.fold_state import FoldLevel

    if hidden_steps:
        return None
    if any(is_monitor_map.values()) or any(is_gate_map.values()):
        return None
    # Owner index built exactly like the filter's: a non-child row wins a
    # repeated key, uniquely-keyed child rows still register, and legacy
    # children repeating their parent's key never own it.
    owners_by_key: dict[str, Agent] = {}
    owners_child_row: dict[str, bool] = {}
    for agent in complete:
        agent_id = id(agent)
        key = fold_keys[agent_id]
        if key is None:
            continue
        existing = owners_by_key.get(key)
        if existing is not None and (
            not owners_child_row.get(key, existing.is_child_row)
            or is_child_row_map.get(agent_id, agent.is_child_row)
        ):
            continue
        if (
            is_child_row_map.get(agent_id, agent.is_child_row)
            and parent_keys[agent_id] == key
        ):
            continue
        owners_by_key[key] = agent
        owners_child_row[key] = is_child_row_map.get(agent_id, agent.is_child_row)
    get_level = projection.get
    visible: dict[str, bool] = {}
    visiting: set[str] = set()

    def _owner_chain_visible(key: str) -> bool | None:
        hit = visible.get(key)
        if hit is not None:
            return hit
        if key in visiting:
            return None
        owner = owners_by_key.get(key)
        if owner is None:
            visible[key] = False
            return False
        if get_level(key) is FoldLevel.COLLAPSED:
            visible[key] = False
            return False
        visiting.add(key)
        owner_parent_key = parent_keys.get(id(owner))
        if owner_parent_key is None:
            result = True
        else:
            sub = _owner_chain_visible(owner_parent_key)
            if sub is None:
                return None
            result = sub
        visiting.discard(key)
        visible[key] = result
        return result

    for parent_key in parent_keys.values():
        if parent_key is None:
            continue
        if _owner_chain_visible(parent_key) is not True:
            return None
    return list(complete)


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
    from ._fold_scope import panel_fold_registry
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
    ) = _snapshot_all_facets(complete)

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
        # hidden steps, shells, gaps, collapsed levels, and cycles.
        keep_all = _expanded_roster_keep_all(
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
    collapsed_panels = effective_panel_collapses(owner, tree_state=collapse_state)

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
        unmet = _unmet_with_facets(
            complete, fold_manager, parents, parent_keys, hidden_steps
        )
    else:
        # Without fold parents every chain resolves valid with no
        # requirements (each edge returns ``(None, ...)`` up front), so no
        # row ever records a missing fold: the walk would return ``{}``.
        unmet = {}

    from ...models.node_finder import (
        describe_node_finder_row_from_facts,
        kind_styles,
    )

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
            panel_agents = [
                agent for agent in expanded if agent_is_rendered_in_agents_panel(agent)
            ]
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
        if len(panel_agents) == len(expanded) and all(
            new is old for new, old in zip(panel_agents, expanded, strict=True)
        ):
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
                jumpable, name, title, kind_label, kind_accent = _describe_plain_row(
                    facts[0],
                    facts[1],
                    facts[2],
                    facts[3],
                    facts[4],
                    _describe_styles,
                )
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
                parent_key = parent_keys[agent_key]
            except KeyError:
                parent_key = agent_parent_fold_key(agent)
            tree_parent = parents.get(parent_key, None) if parent_key else None
            if tree_parent is not None:
                tree_identity = identity_of.get(id(tree_parent))
                if tree_identity is None:
                    tree_identity = tree_parent.identity
                if tree_identity in index_by_identity and tree_identity != identity:
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
                        else _reasons_for_mask(reason_mask, _reason_sets)
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
            # Jumpable rows mark their fold ancestors while the agent is
            # live here, instead of a second pass re-reading every row.
            # Without fold parents the walk below would exit immediately
            # and record nothing, so it is skipped outright.
            if jumpable and not no_fold_parents:
                if agent_key in parent_keys:
                    current_key = parent_keys[agent_key]
                else:
                    current_key = agent_parent_fold_key(agent)
                seen_keys: set[str] = set()
                while current_key and current_key not in seen_keys:
                    seen_keys.add(current_key)
                    fold_parent = parents.get(current_key)
                    if fold_parent is None:
                        break
                    _fold_identity = identity_of.get(id(fold_parent))
                    descendant_of_jumpable.add(
                        _fold_identity
                        if _fold_identity is not None
                        else fold_parent.identity
                    )
                    fold_parent_id = id(fold_parent)
                    if fold_parent_id in parent_keys:
                        current_key = parent_keys[fold_parent_id]
                    else:
                        current_key = agent_parent_fold_key(fold_parent)

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
        # Omission pass: dismissed rows, rows whose hider is unknown (not
        # rendered and no computed reason), and non-jumpable steps without a
        # jumpable descendant never get a hint, so they stay out.
        # ``descendant_of_jumpable`` was collected in the row loop above.
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
        counts_chains = chains
        if len(kept_positions) != len(rows):
            # Remapping renumbers positions, so the header-count pass resolves
            # its own chains over the final row set.
            counts_chains = None
            remapped: list[NodeFinderRow] = []
            for old in kept_positions:
                row = rows[old]
                parent_pos = row.parent_row
                while parent_pos is not None and parent_pos not in new_index:
                    parent_pos = (
                        rows[parent_pos].parent_row
                        if 0 <= parent_pos < len(rows)
                        else None
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
                                new_index[parent_pos]
                                if parent_pos is not None
                                else None
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
    # nodes once per header. On the clean-keep path positions never moved,
    # so one reverse pass accumulates each subtree total into its parent
    # with no chain memo: rows are in preorder (every parent precedes its
    # children, including node-to-node tree parents, which must already be
    # indexed to become a parent), so visiting children first propagates
    # each node's own jumpable/hidden unit up through every header above
    # it — the same sums the chain walks produce.
    node_count = 0
    hidden = 0
    query_hidden = 0
    hidden_by_i_count = 0
    if clean_keep:
        jumpable_subtree = [0] * len(rows)
        hidden_subtree = [0] * len(rows)
        for pos in range(len(rows) - 1, -1, -1):
            row = rows[pos]
            if row.role is NodeFinderRole.NODE and row.jumpable:
                node_count += 1
                row_reasons = row.reasons
                if row_reasons:
                    hidden += 1
                    if NodeFinderReason.QUERY in row_reasons:
                        query_hidden += 1
                    if NodeFinderReason.NON_RUN in row_reasons:
                        hidden_by_i_count += 1
                    jumpable_subtree[pos] += 1
                    hidden_subtree[pos] += 1
                else:
                    jumpable_subtree[pos] += 1
            parent_pos = row.parent_row
            if parent_pos is not None and 0 <= parent_pos < len(rows):
                jumpable_subtree[parent_pos] += jumpable_subtree[pos]
                hidden_subtree[parent_pos] += hidden_subtree[pos]
        header_counts = {
            pos: (jumpable_subtree[pos], hidden_subtree[pos])
            for pos, row in enumerate(rows)
            if row.role is not NodeFinderRole.NODE
        }
    else:
        header_counts = _accumulate_header_counts(rows, counts_chains)

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
            rows[pos] = _evolve(
                row,
                jumpable_count=counts[0],
                hidden_count=counts[1],
            )
        if here_row is not None:
            rows[here_row] = _evolve(rows[here_row], is_here=True)

    if not clean_keep:
        # The clean-keep linear pass above already tallied the node totals
        # alongside the header counts; other paths count here.
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
