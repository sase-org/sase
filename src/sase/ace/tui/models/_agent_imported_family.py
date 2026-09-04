"""Synthesize family-container rows for imported sequential families."""

from __future__ import annotations

from collections import defaultdict
import hashlib

from sase.core.agent_identity_facade import AgentOwnerIdentity

from ._agent_clan import aggregate_clan_status
from .agent import Agent, AgentType


def _imported_family_fold_suffix(
    family_name: str,
    owner: AgentOwnerIdentity,
    cl_name: str,
) -> str:
    """Return a stable synthetic ``raw_suffix`` for one imported family."""
    digest = hashlib.sha256(
        f"{owner.username}\0{owner.machine_name}\0{family_name}\0{cl_name}".encode()
    ).hexdigest()[:20]
    return f"ifam-{digest}"


def materialize_imported_family_containers(agents: list[Agent]) -> list[Agent]:
    """Insert synthetic family roots so imported members fold as one family.

    Existing imported-family containers are discarded first so this is safe
    after incomplete-history merges. Real ``parent_timestamp`` links are left
    alone; only in-memory synthetic parent links are reset.
    """
    real: list[Agent] = []
    for agent in agents:
        if agent.is_imported_family_container:
            continue
        if agent.imported_family_parent_synthetic:
            agent.parent_timestamp = None
            agent.imported_family_parent_synthetic = False
            agent.family_container = None
        real.append(agent)

    groups: dict[tuple[str, str, str, str], list[Agent]] = defaultdict(list)
    roots: set[tuple[str, str, str, str]] = set()
    for agent in real:
        owner = agent.imported_source_owner
        family = agent.agent_family
        if owner is None or not family:
            continue
        key = (family, owner.username, owner.machine_name, agent.cl_name)
        if agent.is_family_root_entry:
            roots.add(key)
            continue
        if agent.parent_timestamp:
            continue
        groups[key].append(agent)

    containers: dict[tuple[str, str, str, str], Agent] = {}
    for key, members in groups.items():
        if key in roots or not members:
            continue
        family, username, machine, cl_name = key
        owner = AgentOwnerIdentity(username, machine)
        suffix = _imported_family_fold_suffix(family, owner, cl_name)
        containers[key] = _imported_family_container(family, owner, members, suffix)

    if not containers:
        return real

    for key, members in groups.items():
        container = containers.get(key)
        if container is None:
            continue
        for member in members:
            member.parent_timestamp = container.raw_suffix
            member.imported_family_parent_synthetic = True

    projected: list[Agent] = []
    emitted: set[tuple[str, str, str, str]] = set()
    for agent in real:
        owner = agent.imported_source_owner
        family = agent.agent_family
        if owner is None or not family:
            projected.append(agent)
            continue
        key = (family, owner.username, owner.machine_name, agent.cl_name)
        container = containers.get(key)
        if container is None:
            projected.append(agent)
            continue
        if key not in emitted:
            emitted.add(key)
            projected.append(container)
        projected.append(agent)
    return projected


def _imported_family_container(
    family_name: str,
    owner: AgentOwnerIdentity,
    members: list[Agent],
    suffix: str,
) -> Agent:
    anchor = members[0]
    starts = [row.start_time for row in members if row.start_time is not None]
    run_starts = [
        row.run_start_time for row in members if row.run_start_time is not None
    ]
    stops = [row.stop_time for row in members if row.stop_time is not None]
    tribes = {row.tribe for row in members if row.tribe}
    status = aggregate_clan_status(row.status for row in members) or "DONE"
    container = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=anchor.cl_name,
        project_file=anchor.project_file,
        status=status,
        start_time=min(starts) if starts else None,
        run_start_time=min(run_starts) if run_starts else None,
        stop_time=max(stops) if stops and len(stops) == len(members) else None,
        raw_suffix=suffix,
        workflow=anchor.workflow,
        agent_name=family_name,
        agent_family=family_name,
        agent_family_role="root",
        imported_source_owner=owner,
        is_imported_family_container=True,
        project_display_name=anchor.project_display_name,
        agent_clan=anchor.agent_clan,
        agent_clan_generation=anchor.agent_clan_generation,
        tribe=next(iter(tribes)) if len(tribes) == 1 else None,
    )
    container.refresh_presented_agent_name()
    return container


__all__ = [
    "materialize_imported_family_containers",
]
