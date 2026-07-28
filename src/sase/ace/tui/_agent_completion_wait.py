"""Wait-dependency status aggregation for agent completion targets."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.ace.tui._agent_completion_candidates import (
    agent_prompt_name,
    visible_clan_completion_groups,
)
from sase.agent.status_buckets import status_bucket_for_values
from sase.core.agent_tribe import InvalidTribeError, parse_tribe_reference
from sase.core.wait_dependency_resolution import (
    TribeMemberRow,
    TribeWaitBinding,
    resolve_tribe_wait_binding,
)

if TYPE_CHECKING:
    from sase.ace.tui.models import Agent

# When a family wait resolves to multiple agents, active work takes precedence
# over terminal states, and a successful terminal attempt satisfies the family.
_WAIT_DEPENDENCY_BUCKET_PRECEDENCE: tuple[str, ...] = (
    "Running",
    "Starting",
    "Queued",
    "Waiting",
    "Done",
    "Stopped",
    "Failed",
)
_WAIT_DEPENDENCY_BUCKET_RANK = {
    bucket: index for index, bucket in enumerate(_WAIT_DEPENDENCY_BUCKET_PRECEDENCE)
}


@dataclass(frozen=True, slots=True)
class AgentWaitStatusMaps:
    """Wait-display state derived from one already-loaded agent snapshot."""

    buckets: dict[str, str]
    clan_member_statuses: dict[str, tuple[tuple[str, str], ...]]
    tribe_bindings: dict[tuple[object, str], TribeWaitBinding]


def _preferred_wait_dependency_bucket(current: str | None, candidate: str) -> str:
    if current is None:
        return candidate
    current_rank = _WAIT_DEPENDENCY_BUCKET_RANK.get(
        current,
        len(_WAIT_DEPENDENCY_BUCKET_RANK),
    )
    candidate_rank = _WAIT_DEPENDENCY_BUCKET_RANK.get(
        candidate,
        len(_WAIT_DEPENDENCY_BUCKET_RANK),
    )
    return candidate if candidate_rank < current_rank else current


def collect_agent_status_buckets(agents: Iterable[Agent]) -> dict[str, str]:
    """Return prompt-referenceable agent names mapped to status buckets."""
    return collect_agent_wait_status_maps(agents).buckets


def collect_agent_wait_status_maps(
    agents: Iterable[Agent],
) -> AgentWaitStatusMaps:
    """Return ordinary and tribe wait state from one in-memory snapshot."""
    from sase.ace.tui.models._agent_clan import aggregate_clan_status
    from sase.ace.tui.models.agent_time import wait_display_agent

    all_agents = list(agents)
    buckets: dict[str, str] = {}
    for agent in all_agents:
        # Synthetic clan rows carry the presented clan name for rendering, but
        # their status must come from the real member aggregate below.
        if agent.is_clan_container:
            continue
        bucket = status_bucket_for_values(agent.status)
        for name in (
            agent_prompt_name(agent),
            agent.presented_agent_name,
            agent.agent_name,
        ):
            if not name or not name.strip():
                continue
            buckets[name] = _preferred_wait_dependency_bucket(
                buckets.get(name),
                bucket,
            )

    clan_member_statuses: dict[str, tuple[tuple[str, str], ...]] = {}
    for group in visible_clan_completion_groups(all_agents):
        # Clan names are reserved in current data. If legacy rows collide,
        # retain the real agent/family wait-target behavior.
        if group.name in buckets:
            continue
        aggregate_status = aggregate_clan_status(
            member.status for member in group.members
        )
        if aggregate_status is None:
            continue
        buckets[group.name] = status_bucket_for_values(aggregate_status)
        clan_member_statuses[group.name] = tuple(
            (
                _clan_wait_member_label(group.name, member),
                status_bucket_for_values(member.status),
            )
            for member in group.members
        )

    tribe_rows = _collect_tribe_member_rows(all_agents)
    tribe_bindings: dict[tuple[object, str], TribeWaitBinding] = {}
    for agent in all_agents:
        wait_agent = wait_display_agent(agent)
        for reference in wait_agent.waiting_for:
            tribe = _parse_tribe_target(reference)
            if tribe is None:
                continue
            key = (wait_agent.identity, reference)
            if key in tribe_bindings:
                continue
            tribe_bindings[key] = resolve_tribe_wait_binding(
                tribe,
                tribe_rows,
                newer_than=wait_agent.raw_suffix,
                exclude_identity=wait_agent.raw_suffix,
            )

    return AgentWaitStatusMaps(
        buckets=buckets,
        clan_member_statuses=clan_member_statuses,
        tribe_bindings=tribe_bindings,
    )


def _collect_tribe_member_rows(agents: list[Agent]) -> tuple[TribeMemberRow, ...]:
    """Project loaded agent rows into the pure tribe-binding input shape."""
    effective_clan_tribes: dict[tuple[str, str], set[str]] = {}
    for agent in agents:
        clan_key = _agent_clan_key(agent)
        if clan_key is None:
            continue
        tribes = effective_clan_tribes.setdefault(clan_key, set())
        if agent.clan_tribe:
            tribes.add(agent.clan_tribe)
        tribes.update(agent.clan_tribes)

    rows: list[TribeMemberRow] = []
    for agent in agents:
        if (
            agent.is_clan_container
            or agent.is_synthetic_planner
            or agent.is_workflow_child
            or not agent.raw_suffix
        ):
            continue
        clan_key = _agent_clan_key(agent)
        effective_tribes = (
            effective_clan_tribes.get(clan_key, set())
            if clan_key is not None
            else set()
        )
        bucket = status_bucket_for_values(agent.status)
        name = agent_prompt_name(agent) or agent.agent_name or agent.display_name
        clan_name = clan_key[0] if clan_key is not None else None
        clan_generation = clan_key[1] if clan_key is not None else None
        effective_values: tuple[str | None, ...] = tuple(sorted(effective_tribes)) or (
            None,
        )
        for effective_tribe in effective_values:
            rows.append(
                TribeMemberRow(
                    tribe=agent.tribe,
                    launch_timestamp=agent.raw_suffix,
                    identity=agent.raw_suffix,
                    name=name,
                    clan_name=clan_name,
                    clan_generation=clan_generation,
                    effective_clan_tribe=effective_tribe,
                    is_complete=bucket == "Done",
                    is_terminal=bucket in {"Done", "Failed"},
                )
            )
    return tuple(rows)


def _agent_clan_key(agent: Agent) -> tuple[str, str] | None:
    if not agent.agent_clan or not agent.agent_clan_generation:
        return None
    return (
        agent.presented_clan_reference_name() or agent.agent_clan,
        agent.agent_clan_generation,
    )


def _parse_tribe_target(reference: str) -> str | None:
    try:
        return parse_tribe_reference(reference)
    except InvalidTribeError:
        return None


def _clan_wait_member_label(clan_name: str, member: Agent) -> str:
    """Return one clan member's short in-hood wait-display label."""
    name = member.presented_agent_name or member.agent_name or member.display_name
    prefix = f"{clan_name}."
    if name.startswith(prefix):
        return name[len(clan_name) :]
    return name


def agent_status_buckets_for_app(app: object | None) -> dict[str, str] | None:
    """Return known prompt-referenceable agent status buckets for a TUI app."""
    status_maps = agent_wait_status_maps_for_app(app)
    return status_maps.buckets if status_maps is not None else None


def agent_wait_status_maps_for_app(
    app: object | None,
) -> AgentWaitStatusMaps | None:
    """Return aggregate and clan-member wait statuses from one app snapshot."""
    if app is None:
        return None

    for attr_name in ("_agents_with_children", "_agents"):
        try:
            agents = getattr(app, attr_name, None)
        except Exception:
            continue
        if agents:
            return collect_agent_wait_status_maps(agents)
    return None


def wait_dependencies_satisfied(
    agent: Agent,
    status_buckets: Mapping[str, str] | None,
    tribe_bindings: Mapping[tuple[object, str], TribeWaitBinding] | None = None,
) -> bool:
    """Return whether every ordinary or tribe wait target is satisfied."""
    from sase.ace.tui.models.agent_time import wait_display_agent

    wait_agent = wait_display_agent(agent)
    if wait_agent.waiting_for_beads:
        return False
    if not wait_agent.waiting_for:
        return True
    for name in wait_agent.waiting_for:
        tribe = _parse_tribe_target(name)
        if tribe is not None:
            binding = (
                tribe_bindings.get((wait_agent.identity, name))
                if tribe_bindings is not None
                else None
            )
            if binding is None or binding.state != "bound":
                return False
        elif status_buckets is None or status_buckets.get(name) != "Done":
            return False
    return True


def has_unresolvable_wait_target(
    agent: Agent,
    tribe_bindings: Mapping[tuple[object, str], TribeWaitBinding] | None,
) -> bool:
    """Return whether any tribe wait target is known to be unresolvable."""
    from sase.ace.tui.models.agent_time import wait_display_agent

    if tribe_bindings is None:
        return False
    wait_agent = wait_display_agent(agent)
    for name in wait_agent.waiting_for:
        if _parse_tribe_target(name) is None:
            continue
        binding = tribe_bindings.get((wait_agent.identity, name))
        if binding is not None and binding.state == "reserved":
            return True
    return False


def missing_wait_dependency_names(
    agent: Agent,
    status_buckets: Mapping[str, str] | None,
) -> tuple[str, ...] | None:
    """Return ordered agent wait targets absent from a usable status snapshot.

    ``None`` preserves the distinction between an unavailable snapshot and a
    usable snapshot where every target is known. Synthetic family, clan, and
    root rows inherit the effective wait source used by the rest of the TUI.
    """
    from sase.ace.tui.models.agent_time import wait_display_agent

    if status_buckets is None:
        return None
    wait_agent = wait_display_agent(agent)
    return tuple(
        name
        for name in wait_agent.waiting_for
        if _parse_tribe_target(name) is None and name not in status_buckets
    )


__all__ = [
    "AgentWaitStatusMaps",
    "agent_status_buckets_for_app",
    "agent_wait_status_maps_for_app",
    "collect_agent_status_buckets",
    "collect_agent_wait_status_maps",
    "has_unresolvable_wait_target",
    "missing_wait_dependency_names",
    "wait_dependencies_satisfied",
]
