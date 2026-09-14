"""Remote-only family node synthesis for fleet summary rows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from ._agent_clan import aggregate_clan_status
from ._agent_ordering import sort_and_reorder
from ._agent_status_apply import apply_status_overrides
from ._fleet_agents_scalars import int_or_none, mapping, optional_str
from .agent import Agent, AgentType


_NESTED_ROLES = frozenset({"member", "monitor", "gate", "proc", "historical_shell"})
_NESTED_KINDS = frozenset({"monitor", "gate", "proc", "historical_shell"})

_SummaryPair = tuple[Mapping[str, Any], Agent]


def normalize_remote_host_nodes(summary_pairs: list[_SummaryPair]) -> list[Agent]:
    """Select, link, and normalize one host's remote rows into family nodes.

    Membership and instance facts come from the fleet wire. This pass only
    constructs ``Agent`` rows, rewrites host-qualified parent links, and
    reuses the local in-memory family primitives. It does not inspect PIDs,
    the filesystem, or imported archives.
    """
    if not summary_pairs:
        return []
    kept, aliases = _select_renderable_pairs(summary_pairs)
    _resolve_host_parent_lineage(kept, aliases)
    _attach_same_logical_history(kept)
    agents = _materialize_missing_family_containers(kept)
    apply_status_overrides(agents, classify_diff_badges=False)
    return sort_and_reorder(agents, [])


def _is_history_or_nested(summary: Mapping[str, Any]) -> bool:
    kind = optional_str(summary.get("row_kind"))
    role = optional_str(
        summary.get("family_role"),
        summary.get("agent_family_role"),
    )
    if kind in _NESTED_KINDS or role in _NESTED_ROLES:
        return True
    return optional_str(summary.get("parent_timestamp")) is not None


def _revision(summary: Mapping[str, Any]) -> int:
    row_revision = mapping(summary.get("row_revision"))
    value = int_or_none(summary.get("revision"), row_revision.get("revision"))
    return -1 if value is None else value


def _summary_owner_lineage_keys(summary: Mapping[str, Any]) -> tuple[str, ...]:
    """Return owner-local identity tokens that may appear as parent keys."""
    logical_locator = mapping(summary.get("logical_locator"))
    exact_locator = mapping(summary.get("exact_locator"))
    nested_logical = mapping(exact_locator.get("logical"))
    keys = (
        summary.get("raw_suffix"),
        summary.get("timestamp"),
        summary.get("agent_timestamp"),
        summary.get("logical_key"),
        summary.get("exact_key"),
        logical_locator.get("agent_id"),
        nested_logical.get("agent_id"),
        exact_locator.get("run_id"),
        exact_locator.get("shell_id"),
    )
    seen: set[str] = set()
    result: list[str] = []
    for key in keys:
        value = optional_str(key)
        if value is None or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _lineage_keys(summary: Mapping[str, Any], agent: Agent) -> tuple[str, ...]:
    keys = list(_summary_owner_lineage_keys(summary))
    if agent.raw_suffix and agent.raw_suffix not in keys:
        keys.append(agent.raw_suffix)
    return tuple(keys)


def _select_renderable_pairs(
    summary_pairs: list[_SummaryPair],
) -> tuple[list[_SummaryPair], dict[str, str]]:
    nested: list[_SummaryPair] = []
    unkeyed: list[_SummaryPair] = []
    by_logical: dict[str, list[_SummaryPair]] = defaultdict(list)
    for pair in summary_pairs:
        summary, agent = pair
        if _is_history_or_nested(summary):
            nested.append(pair)
            continue
        logical = agent.fleet_logical_key
        if not logical:
            unkeyed.append(pair)
            continue
        by_logical[logical].append(pair)

    referenced: set[str] = set()
    for summary, _agent in nested:
        parent = optional_str(summary.get("parent_timestamp"))
        if parent:
            referenced.add(parent)

    chosen_pairs: list[_SummaryPair] = []
    aliases: dict[str, str] = {}
    for group in by_logical.values():
        chosen = _choose_logical_representation(group, referenced)
        chosen_pairs.append(chosen)
        chosen_suffix = chosen[1].raw_suffix
        if not chosen_suffix:
            continue
        for pair in group:
            if pair is chosen:
                continue
            for key in _lineage_keys(pair[0], pair[1]):
                aliases.setdefault(key, chosen_suffix)

    kept_ids = {id(pair) for pair in (*chosen_pairs, *nested, *unkeyed)}
    ordered = [pair for pair in summary_pairs if id(pair) in kept_ids]
    return ordered, aliases


def _choose_logical_representation(
    group: list[_SummaryPair],
    referenced: set[str],
) -> _SummaryPair:
    if len(group) == 1:
        return group[0]

    def _rank(pair: _SummaryPair) -> tuple[int, str]:
        return (_revision(pair[0]), pair[1].raw_suffix or "")

    referenced_rows = [
        pair
        for pair in group
        if referenced.intersection(_lineage_keys(pair[0], pair[1]))
    ]
    if len(referenced_rows) == 1:
        return referenced_rows[0]

    current = [pair for pair in group if pair[0].get("current_instance") is True]
    pool = referenced_rows or group
    if current:
        concrete = [
            pair
            for pair in current
            if pair[0].get("container_projected_concrete_agent") is not True
            and optional_str(pair[0].get("row_kind")) != "container_header"
        ]
        current_pool = concrete or current
        referenced_current = [pair for pair in current_pool if pair in pool]
        return max(referenced_current or current_pool, key=_rank)

    projected = [
        pair
        for pair in pool
        if pair[0].get("container_projected_concrete_agent") is True
    ]
    if projected:
        return max(projected, key=_rank)
    return max(pool, key=_rank)


def _resolve_host_parent_lineage(
    summary_pairs: list[_SummaryPair],
    aliases: Mapping[str, str],
) -> None:
    """Map owner-local parent tokens to rendered host-qualified row ids."""
    by_owner_key: dict[str, str] = dict(aliases)
    for summary, agent in summary_pairs:
        if not agent.raw_suffix:
            continue
        for key in _lineage_keys(summary, agent):
            by_owner_key.setdefault(key, agent.raw_suffix)

    for _summary, agent in summary_pairs:
        raw_parent = agent.parent_timestamp
        if not raw_parent:
            continue
        resolved = by_owner_key.get(raw_parent)
        if resolved is not None:
            agent.parent_timestamp = resolved


def _attach_same_logical_history(summary_pairs: list[_SummaryPair]) -> None:
    """Nest historical/non-current shells under the same logical agent node."""
    suffixes = {
        agent.raw_suffix for _summary, agent in summary_pairs if agent.raw_suffix
    }
    canonical: dict[str, Agent] = {}
    for _summary, agent in summary_pairs:
        logical = agent.fleet_logical_key
        if (
            not logical
            or agent.parent_timestamp
            or (agent.agent_family_role or "") in _NESTED_ROLES
        ):
            continue
        canonical.setdefault(logical, agent)
    for _summary, agent in summary_pairs:
        if agent is canonical.get(agent.fleet_logical_key or ""):
            continue
        parent = agent.parent_timestamp
        if parent and parent in suffixes:
            continue
        host = canonical.get(agent.fleet_logical_key or "")
        if host is not None and host.raw_suffix:
            agent.parent_timestamp = host.raw_suffix


def _materialize_missing_family_containers(
    summary_pairs: list[_SummaryPair],
) -> list[Agent]:
    """Insert a stable family root when members arrived without their parent."""
    agents = [agent for _summary, agent in summary_pairs]
    suffixes = {agent.raw_suffix for agent in agents if agent.raw_suffix}
    groups: dict[tuple[str, str], list[Agent]] = defaultdict(list)
    for agent in agents:
        parent = agent.parent_timestamp
        if not parent or parent in suffixes:
            continue
        origin = agent.fleet_origin_alias or "remote"
        family_key = agent.agent_family or parent
        groups[(origin, family_key)].append(agent)

    if not groups:
        _clear_unresolved_parents(agents)
        return agents

    containers: dict[tuple[str, str], Agent] = {}
    members_by_id: dict[int, tuple[str, str]] = {}
    for key, members in groups.items():
        container = _remote_family_container(key[0], key[1], members)
        containers[key] = container
        for member in members:
            member.parent_timestamp = container.raw_suffix
            members_by_id[id(member)] = key

    projected: list[Agent] = []
    emitted: set[tuple[str, str]] = set()
    for agent in agents:
        group_key = members_by_id.get(id(agent))
        if group_key is not None and group_key not in emitted:
            emitted.add(group_key)
            projected.append(containers[group_key])
        projected.append(agent)
    for leftover_key, container in containers.items():
        if leftover_key not in emitted:
            projected.append(container)
    _clear_unresolved_parents(projected)
    return projected


def _clear_unresolved_parents(agents: list[Agent]) -> None:
    suffixes = {agent.raw_suffix for agent in agents if agent.raw_suffix}
    for agent in agents:
        parent = agent.parent_timestamp
        if parent and parent not in suffixes:
            agent.parent_timestamp = None


def _remote_family_container(
    origin: str,
    family_key: str,
    members: list[Agent],
) -> Agent:
    anchor = members[0]
    starts = [row.start_time for row in members if row.start_time is not None]
    run_starts = [
        row.run_start_time for row in members if row.run_start_time is not None
    ]
    stops = [row.stop_time for row in members if row.stop_time is not None]
    tribes = {row.tribe for row in members if row.tribe}
    status = aggregate_clan_status(row.status for row in members) or "RUNNING"
    container = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=anchor.cl_name,
        project_file=anchor.project_file,
        status=status,
        start_time=min(starts) if starts else None,
        run_start_time=min(run_starts) if run_starts else None,
        stop_time=max(stops) if stops and len(stops) == len(members) else None,
        raw_suffix=f"fleet:{origin}:family:{family_key}",
        agent_name=family_key,
        agent_family=family_key,
        agent_family_role="root",
        project_display_name=anchor.project_display_name,
        fleet_origin_alias=origin,
        fleet_origin_installation_id=anchor.fleet_origin_installation_id,
        fleet_host_running_count=anchor.fleet_host_running_count,
        fleet_host_total_count=anchor.fleet_host_total_count,
        fleet_host_waiting_count=anchor.fleet_host_waiting_count,
        fleet_host_failed_count=anchor.fleet_host_failed_count,
        fleet_host_done_count=anchor.fleet_host_done_count,
        fleet_host_unknown_count=anchor.fleet_host_unknown_count,
        fleet_row_kind="container_header",
        is_remote_family_container=True,
        agent_clan=anchor.agent_clan,
        agent_clan_generation=anchor.agent_clan_generation,
        tribe=next(iter(tribes)) if len(tribes) == 1 else None,
    )
    container.refresh_presented_agent_name()
    return container


__all__ = [
    "normalize_remote_host_nodes",
]
