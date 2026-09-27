"""Parent lookup, presentation anchors, and tree filtering."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .agent import Agent
from ._agent_tree_fold import agent_is_tree_child, agent_tree_depth, clan_fold_key


def _tree_parent(agent: Agent, lookup: dict[str, Agent]) -> Agent | None:
    """Resolve *agent*'s immediate rendered parent from an existing index."""
    if agent.tree_parent_key:
        return lookup.get(agent.tree_parent_key)
    if agent.is_child_row and agent.parent_timestamp:
        return lookup.get(agent.parent_timestamp)
    return None


def tree_parent_lookup(agents: Iterable[Agent]) -> dict[str, Agent]:
    """Index artifact parents and synthetic clan parents by their tree keys."""
    lookup: dict[str, Agent] = {}
    for agent in agents:
        if agent.is_clan_container and agent.agent_clan:
            lookup[clan_fold_key(agent.agent_clan, agent.agent_clan_generation)] = agent
        if agent.raw_suffix and (
            # Inlined ``is_child_row`` (``child_linkage is not ROOT`` is
            # exactly these two ``None`` checks): the property call per
            # agent dominates this loop on wide rosters.
            (agent.parent_workflow is None and agent.parent_timestamp is None)
            or agent.raw_suffix not in lookup
        ):
            # Some legacy workflow children repeat their parent's suffix.
            # Prefer the root row while still indexing uniquely-keyed child
            # rows for complete immediate-parent traversal.
            lookup[agent.raw_suffix] = agent
    return lookup


#: Shared per-roster tree index: ``(parent_lookup, anchors)`` as built by
#: :func:`tree_parent_lookup` plus :func:`presentation_anchor_lookup` over
#: the same roster. Callers that filter or group one roster several times
#: build it once and pass it down instead of re-walking the tree.
TreeIndex = tuple[dict[str, Agent], dict[int, Agent]]


def presentation_anchor_lookup(
    agents: list[Agent],
    parent_lookup: dict[str, Agent] | None = None,
) -> dict[int, Agent]:
    """Resolve each row to its outermost available rendered-tree root.

    The returned mapping is keyed by object identity because :class:`Agent`
    rows are mutable and intentionally unhashable.  Resolution memoizes every
    traversed path, keeping the batch operation linear for well-formed trees.

    Missing parents terminate a path at the highest row that was actually
    resolved.  Malformed cycles are collapsed onto the shallowest cycle row,
    with input order as a deterministic tiebreak, so otherwise renderable rows
    never disappear or trigger an unbounded ancestry walk.
    """
    lookup = parent_lookup if parent_lookup is not None else tree_parent_lookup(agents)
    # The cycle tiebreak below re-iterates the roster, so normalize
    # one-shot iterables once up front; lists skip the copy.
    if not isinstance(agents, list):
        agents = list(agents)
    # Built lazily on the first cycle only: well-formed rosters never
    # need input positions, and the dict costs a full pass by itself.
    input_positions: dict[int, int] | None = None
    resolved: dict[int, Agent] = {}

    for agent in agents:
        agent_id = id(agent)
        if agent_id in resolved:
            continue

        # The common shape needs no walk: a root anchors to itself and a
        # row whose parent already resolved shares its anchor. Either
        # outcome matches the general walk below exactly (a resolved
        # anchor is final, and a missing parent terminates the path at
        # the row itself); anything else falls through to it.
        # ``_tree_parent`` is inlined (same field reads): the call per
        # agent dominates this loop on wide rosters. A truthy timestamp
        # already implies the child row, so the child check collapses
        # into the timestamp read.
        _tpk = agent.tree_parent_key
        if _tpk:
            parent = lookup.get(_tpk)
        else:
            _pts = agent.parent_timestamp
            parent = lookup.get(_pts) if _pts else None
        if parent is None:
            resolved[agent_id] = agent
            continue
        parent_anchor = resolved.get(id(parent))
        if parent_anchor is not None:
            resolved[agent_id] = parent_anchor
            continue

        path: list[Agent] = []
        path_positions: dict[int, int] = {}
        current = agent
        while True:
            current_id = id(current)
            cached = resolved.get(current_id)
            if cached is not None:
                anchor = cached
                break

            cycle_start = path_positions.get(current_id)
            if cycle_start is not None:
                if input_positions is None:
                    input_positions = {id(row): i for i, row in enumerate(agents)}
                positions = input_positions
                roster_len = len(agents)
                cycle = path[cycle_start:]
                anchor = min(
                    cycle,
                    key=lambda row: (
                        agent_tree_depth(row),
                        positions.get(id(row), roster_len),
                    ),
                )
                for row in cycle:
                    resolved[id(row)] = anchor
                break

            path_positions[current_id] = len(path)
            path.append(current)
            parent = _tree_parent(current, lookup)
            if parent is None:
                anchor = current
                break
            current = parent

        for row in reversed(path):
            resolved.setdefault(id(row), anchor)

    return resolved


def presentation_anchor(
    agent: Agent,
    parent_lookup: dict[str, Agent],
    anchors: dict[int, Agent] | None = None,
) -> Agent:
    """Return *agent*'s outer presentation anchor from an existing tree index."""
    if anchors is not None:
        return anchors.get(id(agent), agent)
    rows: list[Agent] = []
    seen: set[int] = set()
    for row in [*parent_lookup.values(), agent]:
        row_id = id(row)
        if row_id in seen:
            continue
        seen.add(row_id)
        rows.append(row)
    return presentation_anchor_lookup(rows, parent_lookup).get(id(agent), agent)


def filter_tree_rows(
    agents: list[Agent],
    predicate: Callable[[Agent], bool],
) -> list[Agent]:
    """Filter rows while retaining matched ancestors and their descendants."""
    matched = {id(agent) for agent in agents if predicate(agent)}
    if len(matched) == len(agents):
        # Every row matched, so the ancestor/descendant retention below can
        # add nothing: the kept set is the whole roster in input order, which
        # is exactly what the tail comprehension would return. Skipping the
        # parent index, ancestor walks, and child buckets keeps match-all
        # queries (including the finder's per-open query survivor pass) off
        # the tree machinery without changing the result.
        return list(agents)
    lookup = tree_parent_lookup(agents)
    included = set(matched)

    # Older workflow fixtures/archives can identify children only through the
    # shared display name, without a parent timestamp. Preserve that existing
    # parent-match behavior alongside the explicit tree links used by clans.
    matched_parent_names = {
        agent.agent_name or agent.cl_name
        for agent in agents
        if id(agent) in matched and not agent_is_tree_child(agent)
    }
    included.update(
        id(agent)
        for agent in agents
        if agent.is_child_row
        and (agent.agent_name or agent.cl_name) in matched_parent_names
    )

    # Matching a descendant retains its selectable parent chain.
    for agent in agents:
        if id(agent) not in matched:
            continue
        current = agent
        seen: set[int] = set()
        while (parent := _tree_parent(current, lookup)) is not None:
            parent_id = id(parent)
            if parent_id in seen:
                break
            seen.add(parent_id)
            included.add(parent_id)
            current = parent

    # Matching a parent retains the visible tree beneath it. Build immediate
    # child buckets once so the complete clan -> member -> child projection is
    # traversed in linear time.
    children_by_parent: dict[int, list[Agent]] = {}
    for agent in agents:
        parent = _tree_parent(agent, lookup)
        if parent is not None:
            children_by_parent.setdefault(id(parent), []).append(agent)

    pending = list(included)
    while pending:
        parent_id = pending.pop()
        for child in children_by_parent.get(parent_id, ()):
            child_id = id(child)
            if child_id in included:
                continue
            included.add(child_id)
            pending.append(child_id)

    return [agent for agent in agents if id(agent) in included]
