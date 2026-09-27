"""Clan container projection for the agent tree."""

from __future__ import annotations

from collections.abc import Iterable

from sase.core.agent_clan_context import (
    effective_clan_attributes,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity

from ._agent_clan import apply_clan_container_status, clan_member_status_priority
from ._agent_tree_fold import clan_fold_key
from .agent import Agent, AgentType

ClanKey = tuple[str, str | None]


def _reset_tree_projection(agent: Agent) -> None:
    agent.tree_parent_key = None
    agent.tree_depth = 0
    agent.clan_tribes = ()


def _rows_by_suffix(rows: Iterable[Agent]) -> dict[str, Agent]:
    """Index rows by ``raw_suffix``, preferring a non-child on collision."""
    lookup: dict[str, Agent] = {}
    for row in rows:
        suffix = row.raw_suffix
        if not suffix:
            continue
        existing = lookup.get(suffix)
        if existing is None or (existing.is_child_row and not row.is_child_row):
            lookup[suffix] = row
    return lookup


def _clan_for_row(
    agent: Agent,
    parent_by_suffix: dict[str, Agent],
) -> tuple[str, str | None] | None:
    seen: set[int] = set()
    current: Agent | None = agent
    while current is not None:
        current_id = id(current)
        if current_id in seen:
            return None
        seen.add(current_id)
        if current.agent_clan:
            return (
                current.presented_clan_reference_name() or current.agent_clan,
                current.agent_clan_generation,
            )
        parent_timestamp = current.parent_timestamp
        if not parent_timestamp:
            return None
        current = parent_by_suffix.get(parent_timestamp)
    return None


def _assign_clan_tree_links(
    rows: list[Agent],
    fold_key: str,
    parent_by_suffix: dict[str, Agent],
) -> None:
    """Assign ``tree_parent_key`` / ``tree_depth`` in parent-before-child order."""
    row_ids = {id(row) for row in rows}
    assigned: set[int] = set()

    def assign(row: Agent, visiting: set[int]) -> None:
        row_id = id(row)
        if row_id in assigned:
            return
        if row_id in visiting:
            row.tree_depth = 1
            row.tree_parent_key = fold_key
            assigned.add(row_id)
            return
        parent = parent_by_suffix.get(row.parent_timestamp or "")
        if parent is None or id(parent) not in row_ids:
            row.tree_depth = 1
            row.tree_parent_key = fold_key
            assigned.add(row_id)
            return
        visiting.add(row_id)
        assign(parent, visiting)
        visiting.discard(row_id)
        row.tree_parent_key = parent.raw_suffix
        row.tree_depth = parent.tree_depth + 1
        assigned.add(row_id)

    for row in rows:
        assign(row, set())


def _nearest_direct_clan_unit(
    row: Agent,
    fold_key: str,
    unit_by_parent_key: dict[str, list[Agent]],
    row_by_suffix: dict[str, Agent],
) -> list[Agent] | None:
    """Return the unit of *row*'s nearest direct clan member, if any."""
    current_key = row.tree_parent_key
    seen: set[str] = set()
    while current_key and current_key != fold_key:
        if current_key in seen:
            return None
        seen.add(current_key)
        unit = unit_by_parent_key.get(current_key)
        if unit is not None:
            return unit
        parent = row_by_suffix.get(current_key)
        if parent is None:
            return None
        current_key = parent.tree_parent_key
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
    context = next(
        (
            row.clan_context
            for row in rows
            if row.clan_context is not None
            and row.presented_clan_reference_name() == clan_name
            and row.clan_context.agent_clan_generation == generation
        ),
        None,
    )
    tribes: tuple[str, ...]
    if explicit_clan_tribe or explicit_clan_summary:
        from sase.core.agent_clan_tribe import (
            ClanTribeMemberWire,
            resolve_clan_summary,
            resolve_clan_tribe,
        )

        member_wires = [
            ClanTribeMemberWire(
                agent_clan=clan_name,
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

    resolved_clan_tribe, resolved_clan_summary = effective_clan_attributes(
        declared_tribe=resolved_clan_tribe,
        declared_summary=resolved_clan_summary,
        context=context,
    )

    # A new-style declaration is authoritative. Only generations with no
    # declaration use standalone per-member tribe aggregation.
    if explicit_clan_tribe or resolved_clan_tribe:
        tribes = (resolved_clan_tribe,) if resolved_clan_tribe else ()
    else:
        tribes = tuple(sorted({row.tribe for row in rows if row.tribe}, key=str.lower))
    starts = [row.start_time for row in runtime_members if row.start_time is not None]
    run_starts = [
        row.run_start_time for row in runtime_members if row.run_start_time is not None
    ]
    stops = [row.stop_time for row in runtime_members if row.stop_time is not None]
    source_machine = _common_source_machine(runtime_members)
    imported_owner = _common_imported_source_owner(runtime_members)
    fleet_origin_alias = _common_fleet_origin_alias(runtime_members)
    fleet_origin_installation_id = _common_fleet_origin_installation_id(runtime_members)

    container = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=clan_name,
        project_file=anchor.project_file,
        status="RUNNING",
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
        clan_context=context,
        is_clan_container=True,
        clan_tribes=tribes,
        tribe=tribes[0] if len(tribes) == 1 else None,
        source_machine=source_machine,
        imported_source_owner=imported_owner,
        fleet_origin_alias=fleet_origin_alias,
        fleet_origin_installation_id=fleet_origin_installation_id,
    )
    container.runtime_children.extend(runtime_members)
    apply_clan_container_status(container, runtime_members, fallback="RUNNING")
    return container


def _common_source_machine(rows: list[Agent]) -> str | None:
    machines = {
        machine
        for row in rows
        for machine in (
            row.source_machine,
            row.imported_source_owner.machine_name
            if row.imported_source_owner is not None
            else None,
        )
        if machine
    }
    if len(machines) == 1:
        return next(iter(machines))
    return None


def _common_imported_source_owner(rows: list[Agent]) -> AgentOwnerIdentity | None:
    owners = {row.imported_source_owner for row in rows if row.imported_source_owner}
    if len(owners) == 1:
        return next(iter(owners))
    return None


def _common_fleet_origin_alias(rows: list[Agent]) -> str | None:
    aliases = {row.fleet_origin_alias for row in rows if row.fleet_origin_alias}
    if len(aliases) == 1:
        return next(iter(aliases))
    return None


def _common_fleet_origin_installation_id(rows: list[Agent]) -> str | None:
    installation_ids = {
        row.fleet_origin_installation_id
        for row in rows
        if row.fleet_origin_installation_id
    }
    if len(installation_ids) == 1:
        return next(iter(installation_ids))
    return None


def _sort_clan_member_units(rows: list[Agent], fold_key: str) -> list[Agent]:
    """Stable-sort direct clan-member subtrees by their anchor status."""
    units: list[list[Agent]] = []
    unit_by_parent_key: dict[str, list[Agent]] = {}
    row_by_suffix = _rows_by_suffix(rows)

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
        parent_unit = _nearest_direct_clan_unit(
            row, fold_key, unit_by_parent_key, row_by_suffix
        )
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
        (
            agent.presented_clan_reference_name() or agent.agent_clan,
            agent.agent_clan_generation,
        ): [child.identity for child in agent.runtime_children]
        for agent in agents
        if agent.is_clan_container and agent.agent_clan
    }
    real_agents = [agent for agent in agents if not agent.is_clan_container]
    for agent in real_agents:
        _reset_tree_projection(agent)

    parent_by_suffix = _rows_by_suffix(real_agents)
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
        fold_key = clan_fold_key(clan_name, generation)
        _assign_clan_tree_links(rows, fold_key, parent_by_suffix)
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


def project_mixed_agent_tree(
    local_agents: list[Agent],
    remote_agents: list[Agent],
) -> list[Agent]:
    """Project concatenated local and remote rows through the clan tree.

    Fleet refresh reprojection and query refiltering share this helper so a
    mixed list always has the same clan-container shape.
    """
    return project_clan_tree([*local_agents, *remote_agents])
