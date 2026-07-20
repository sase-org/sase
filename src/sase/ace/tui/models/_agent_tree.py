"""Pure in-memory tree projection for rootless agent clans."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ._agent_clan import aggregate_clan_status, clan_member_status_priority
from .agent import Agent, AgentType

ClanKey = tuple[str, str | None]


def _clan_fold_key(clan_name: str, generation: str | None = None) -> str:
    """Return the stable :class:`FoldStateManager` key for a clan row."""
    suffix = f":{generation}" if generation else ""
    return f"clan:{clan_name}{suffix}"


def agent_fold_key(agent: Agent) -> str | None:
    """Return the fold key owned by *agent* for its visible descendants."""
    if agent.is_clan_container and agent.agent_clan:
        return _clan_fold_key(agent.agent_clan, agent.agent_clan_generation)
    if agent.raw_suffix:
        return agent.raw_suffix
    return None


def agent_parent_fold_key(agent: Agent) -> str | None:
    """Return the fold key controlling *agent* as an immediate child row."""
    if agent.tree_parent_key:
        return agent.tree_parent_key
    if agent.is_child_row and agent.parent_timestamp:
        return agent.parent_timestamp
    return None


def agent_tree_depth(agent: Agent) -> int:
    """Return an Agents-tab indentation depth without reading external state."""
    if agent.tree_depth > 0:
        return agent.tree_depth
    return 1 if agent.is_child_row else 0


def agent_is_tree_child(agent: Agent) -> bool:
    """Return whether *agent* nests beneath another rendered agent row."""
    return agent_tree_depth(agent) > 0


def tree_parent_lookup(agents: Iterable[Agent]) -> dict[str, Agent]:
    """Index artifact parents and synthetic clan parents by their tree keys."""
    lookup: dict[str, Agent] = {}
    for agent in agents:
        if agent.is_clan_container and agent.agent_clan:
            lookup[_clan_fold_key(agent.agent_clan, agent.agent_clan_generation)] = (
                agent
            )
        if agent.raw_suffix and (
            not agent.is_child_row or agent.raw_suffix not in lookup
        ):
            # Some legacy workflow children repeat their parent's suffix.
            # Prefer the root row while still indexing uniquely-keyed child
            # rows for complete immediate-parent traversal.
            lookup[agent.raw_suffix] = agent
    return lookup


def _tree_parent(agent: Agent, lookup: dict[str, Agent]) -> Agent | None:
    """Resolve *agent*'s immediate rendered parent from an existing index."""
    if agent.tree_parent_key:
        return lookup.get(agent.tree_parent_key)
    if agent.is_child_row and agent.parent_timestamp:
        return lookup.get(agent.parent_timestamp)
    return None


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
    input_positions = {id(agent): i for i, agent in enumerate(agents)}
    resolved: dict[int, Agent] = {}

    for agent in agents:
        if id(agent) in resolved:
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
                cycle = path[cycle_start:]
                anchor = min(
                    cycle,
                    key=lambda row: (
                        agent_tree_depth(row),
                        input_positions.get(id(row), len(agents)),
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


def _reset_tree_projection(agent: Agent) -> None:
    agent.tree_parent_key = None
    agent.tree_depth = 0
    agent.clan_tribes = ()


def _clan_for_row(
    agent: Agent,
    parent_by_suffix: dict[str, Agent],
) -> tuple[str, str | None] | None:
    if agent.agent_clan:
        return (agent.agent_clan, agent.agent_clan_generation)
    if agent.parent_timestamp:
        parent = parent_by_suffix.get(agent.parent_timestamp)
        if parent is not None and parent.agent_clan:
            return (parent.agent_clan, parent.agent_clan_generation)
    return None


def _container_for_clan(
    clan_name: str,
    rows: list[Agent],
    *,
    prior_runtime_order: list[tuple[AgentType, str, str | None]] | None = None,
) -> Agent:
    direct = [row for row in rows if row.tree_depth == 1]
    runtime_members = direct or rows
    if direct and prior_runtime_order:
        prior_positions = {
            identity: index for index, identity in enumerate(prior_runtime_order)
        }
        current_positions = {id(row): index for index, row in enumerate(direct)}
        runtime_members = sorted(
            direct,
            key=lambda row: (
                prior_positions.get(row.identity, len(prior_positions)),
                current_positions[id(row)],
            ),
        )
    anchor = runtime_members[0]
    generations = [
        row.agent_clan_generation for row in rows if row.agent_clan_generation
    ]
    generation = generations[0] if generations else None
    explicit_clan_tribe = any(row.clan_tribe for row in rows)
    explicit_clan_summary = any(row.clan_summary for row in rows)
    resolved_clan_tribe: str | None = None
    resolved_clan_summary: str | None = None
    tribes: tuple[str, ...]
    if explicit_clan_tribe or explicit_clan_summary:
        from sase.core.agent_clan_tribe import (
            ClanTribeMemberWire,
            resolve_clan_summary,
            resolve_clan_tribe,
        )

        member_wires = [
            ClanTribeMemberWire(
                agent_clan=row.agent_clan or clan_name,
                agent_clan_generation=row.agent_clan_generation,
                clan_tribe=row.clan_tribe,
                clan_summary=row.clan_summary,
                launch_timestamp=row.raw_suffix or "",
                identity=(
                    f"{row.agent_type.value}:{row.cl_name}:"
                    f"{row.raw_suffix or ''}:{row.agent_name or ''}"
                ),
            )
            for row in rows
        ]
        if explicit_clan_tribe:
            resolved_clan_tribe = resolve_clan_tribe(
                clan_name,
                generation,
                member_wires,
            ).tribe
        if explicit_clan_summary:
            resolved_clan_summary = resolve_clan_summary(
                clan_name,
                generation,
                member_wires,
            ).summary

    # A new-style declaration is authoritative. Only generations with no
    # declaration use standalone per-member tribe aggregation.
    if explicit_clan_tribe:
        tribes = (resolved_clan_tribe,) if resolved_clan_tribe else ()
    else:
        tribes = tuple(sorted({row.tribe for row in rows if row.tribe}, key=str.lower))
    starts = [row.start_time for row in runtime_members if row.start_time is not None]
    run_starts = [
        row.run_start_time for row in runtime_members if row.run_start_time is not None
    ]
    stops = [row.stop_time for row in runtime_members if row.stop_time is not None]
    status = aggregate_clan_status(row.status for row in runtime_members) or "RUNNING"

    container = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=clan_name,
        project_file=anchor.project_file,
        status=status,
        start_time=min(starts) if starts else None,
        run_start_time=min(run_starts) if run_starts else None,
        stop_time=(
            max(stops) if stops and len(stops) == len(runtime_members) else None
        ),
        raw_suffix=None,
        agent_clan=clan_name,
        agent_clan_generation=generation,
        clan_tribe=resolved_clan_tribe,
        clan_summary=resolved_clan_summary,
        is_clan_container=True,
        clan_tribes=tribes,
        tribe=tribes[0] if len(tribes) == 1 else None,
    )
    container.runtime_children.extend(runtime_members)
    return container


def _sort_clan_member_units(rows: list[Agent], fold_key: str) -> list[Agent]:
    """Stable-sort direct clan-member subtrees by their anchor status."""
    units: list[list[Agent]] = []
    unit_by_parent_key: dict[str, list[Agent]] = {}

    # Create every direct-member unit first so descendants remain attached
    # even when a compatibility payload does not place them after the anchor.
    for row in rows:
        if row.tree_parent_key != fold_key:
            continue
        direct_unit = [row]
        units.append(direct_unit)
        if row.raw_suffix:
            unit_by_parent_key[row.raw_suffix] = direct_unit

    for row in rows:
        if row.tree_parent_key == fold_key:
            continue
        parent_unit = unit_by_parent_key.get(row.tree_parent_key or "")
        if parent_unit is None:
            # Projection makes rows with missing parents direct members. Keep
            # this defensive fallback atomic if a future tree shape reaches
            # the helper without that normalization.
            units.append([row])
        else:
            parent_unit.append(row)

    units.sort(
        key=lambda unit: clan_member_status_priority(
            unit[0].status,
            unit[0].retried_as_timestamp,
        )
    )
    return [row for unit in units for row in unit]


def project_clan_tree(agents: list[Agent]) -> list[Agent]:
    """Return *agents* with one synthetic container per loaded clan.

    Existing containers are discarded first, making this safe after Tier-1
    patch merges and optimistic kill/dismiss mutations. Real rows retain their
    artifact relationships; only the presentation-only tree fields mutate.
    """
    prior_runtime_orders = {
        (agent.agent_clan, agent.agent_clan_generation): [
            child.identity for child in agent.runtime_children
        ]
        for agent in agents
        if agent.is_clan_container and agent.agent_clan
    }
    real_agents = [agent for agent in agents if not agent.is_clan_container]
    for agent in real_agents:
        _reset_tree_projection(agent)

    parent_by_suffix = {
        agent.raw_suffix: agent
        for agent in real_agents
        if agent.raw_suffix and not agent.is_child_row
    }
    row_clans: dict[int, ClanKey] = {}
    for agent in real_agents:
        clan = _clan_for_row(agent, parent_by_suffix)
        if clan is not None:
            row_clans[id(agent)] = clan
    if not row_clans:
        return real_agents

    rows_by_clan: dict[ClanKey, list[Agent]] = {}
    for agent in real_agents:
        clan = row_clans.get(id(agent))
        if clan is not None:
            rows_by_clan.setdefault(clan, []).append(agent)

    containers: dict[ClanKey, Agent] = {}
    for clan_key, rows in rows_by_clan.items():
        clan_name, generation = clan_key
        fold_key = _clan_fold_key(clan_name, generation)
        row_ids = {id(row) for row in rows}
        for row in rows:
            parent = parent_by_suffix.get(row.parent_timestamp or "")
            if parent is not None and id(parent) in row_ids:
                row.tree_depth = 2
                row.tree_parent_key = parent.raw_suffix
            else:
                row.tree_depth = 1
                row.tree_parent_key = fold_key
        containers[clan_key] = _container_for_clan(
            clan_name,
            rows,
            prior_runtime_order=prior_runtime_orders.get(clan_key),
        )
        rows_by_clan[clan_key] = _sort_clan_member_units(rows, fold_key)

    projected: list[Agent] = []
    emitted: set[ClanKey] = set()
    for agent in real_agents:
        clan = row_clans.get(id(agent))
        if clan is None:
            projected.append(agent)
            continue
        if clan in emitted:
            continue
        emitted.add(clan)
        projected.append(containers[clan])
        projected.extend(rows_by_clan[clan])
    return projected


def filter_tree_rows(
    agents: list[Agent],
    predicate: Callable[[Agent], bool],
) -> list[Agent]:
    """Filter rows while retaining matched ancestors and their descendants."""
    lookup = tree_parent_lookup(agents)
    matched = {id(agent) for agent in agents if predicate(agent)}
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


__all__ = [
    "agent_fold_key",
    "agent_is_tree_child",
    "agent_parent_fold_key",
    "agent_tree_depth",
    "filter_tree_rows",
    "presentation_anchor",
    "presentation_anchor_lookup",
    "project_clan_tree",
    "tree_parent_lookup",
]
