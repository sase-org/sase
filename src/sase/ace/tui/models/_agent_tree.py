"""Pure in-memory tree projection for rootless agent clans."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ._agent_clan import aggregate_clan_status
from .agent import Agent, AgentType

ClanKey = tuple[str, str | None]


def _clan_fold_key(clan_name: str, generation: str | None = None) -> str:
    """Return the stable :class:`FoldStateManager` key for a clan row."""
    suffix = f":{generation}" if generation else ""
    return f"clan:{clan_name}{suffix}"


def agent_fold_key(agent: Agent) -> str | None:
    """Return the fold key governing *agent*'s visible descendants."""
    if agent.tree_parent_key:
        return agent.tree_parent_key
    if agent.is_clan_container and agent.agent_clan:
        return _clan_fold_key(agent.agent_clan, agent.agent_clan_generation)
    if agent.is_child_row and agent.parent_timestamp:
        return agent.parent_timestamp
    if agent.raw_suffix:
        return agent.raw_suffix
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
        if agent.raw_suffix and not agent.is_child_row:
            lookup[agent.raw_suffix] = agent
    return lookup


def tree_parent(agent: Agent, lookup: dict[str, Agent]) -> Agent | None:
    """Resolve *agent*'s immediate rendered parent from an existing index."""
    if agent.tree_parent_key:
        return lookup.get(agent.tree_parent_key)
    if agent.is_child_row and agent.parent_timestamp:
        return lookup.get(agent.parent_timestamp)
    return None


def _reset_tree_projection(agent: Agent) -> None:
    agent.tree_parent_key = None
    agent.tree_depth = 0
    agent.clan_tags = ()


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


def _container_for_clan(clan_name: str, rows: list[Agent]) -> Agent:
    direct = [row for row in rows if row.tree_depth == 1]
    runtime_members = direct or rows
    anchor = runtime_members[0]
    generations = [
        row.agent_clan_generation for row in rows if row.agent_clan_generation
    ]
    generation = generations[0] if generations else None
    tags = tuple(sorted({row.tag for row in rows if row.tag}, key=str.lower))
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
        is_clan_container=True,
        clan_tags=tags,
        tag=tags[0] if len(tags) == 1 else None,
    )
    container.runtime_children.extend(runtime_members)
    return container


def project_clan_tree(agents: list[Agent]) -> list[Agent]:
    """Return *agents* with one synthetic container per loaded clan.

    Existing containers are discarded first, making this safe after Tier-1
    patch merges and optimistic kill/dismiss mutations. Real rows retain their
    artifact relationships; only the presentation-only tree fields mutate.
    """
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
            is_descendant = parent is not None and id(parent) in row_ids
            row.tree_depth = 2 if is_descendant else 1
            row.tree_parent_key = fold_key
        containers[clan_key] = _container_for_clan(clan_name, rows)

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
        while (parent := tree_parent(current, lookup)) is not None:
            parent_id = id(parent)
            if parent_id in seen:
                break
            seen.add(parent_id)
            included.add(parent_id)
            current = parent

    # Matching a parent retains the visible tree beneath it.
    changed = True
    while changed:
        changed = False
        for agent in agents:
            if id(agent) in included:
                continue
            parent = tree_parent(agent, lookup)
            if parent is not None and id(parent) in included:
                included.add(id(agent))
                changed = True

    return [agent for agent in agents if id(agent) in included]


__all__ = [
    "agent_fold_key",
    "agent_is_tree_child",
    "agent_tree_depth",
    "filter_tree_rows",
    "project_clan_tree",
    "tree_parent",
    "tree_parent_lookup",
]
