"""Wait-dependency status aggregation for agent completion targets."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from sase.ace.tui._agent_completion_candidates import (
    agent_prompt_name,
    visible_clan_completion_groups,
)
from sase.agent.status_buckets import status_bucket_for_values

if TYPE_CHECKING:
    from sase.ace.tui.models import Agent

# When a family wait resolves to multiple agents, active work takes precedence
# over terminal states, and a successful terminal attempt satisfies the family.
_WAIT_DEPENDENCY_BUCKET_PRECEDENCE: tuple[str, ...] = (
    "Running",
    "Starting",
    "Waiting",
    "Done",
    "Stopped",
    "Failed",
)
_WAIT_DEPENDENCY_BUCKET_RANK = {
    bucket: index for index, bucket in enumerate(_WAIT_DEPENDENCY_BUCKET_PRECEDENCE)
}


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
    buckets, _clan_member_statuses = collect_agent_wait_status_maps(agents)
    return buckets


def collect_agent_wait_status_maps(
    agents: Iterable[Agent],
) -> tuple[dict[str, str], dict[str, tuple[tuple[str, str], ...]]]:
    """Return aggregate wait buckets and ordered clan-member detail."""
    from sase.ace.tui.models._agent_clan import aggregate_clan_status

    all_agents = list(agents)
    buckets: dict[str, str] = {}
    for agent in all_agents:
        bucket = status_bucket_for_values(agent.status)
        for name in (agent_prompt_name(agent), agent.agent_name):
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
    return buckets, clan_member_statuses


def _clan_wait_member_label(clan_name: str, member: Agent) -> str:
    """Return one clan member's short in-hood wait-display label."""
    name = member.agent_name or member.presented_agent_name or member.display_name
    prefix = f"{clan_name}."
    if name.startswith(prefix):
        return name[len(clan_name) :]
    return name


def agent_status_buckets_for_app(app: object | None) -> dict[str, str] | None:
    """Return known prompt-referenceable agent status buckets for a TUI app."""
    status_maps = agent_wait_status_maps_for_app(app)
    return status_maps[0] if status_maps is not None else None


def agent_wait_status_maps_for_app(
    app: object | None,
) -> tuple[dict[str, str], dict[str, tuple[tuple[str, str], ...]]] | None:
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
    agent: Agent, status_buckets: Mapping[str, str] | None
) -> bool:
    """Return whether every waited-for agent is known done."""
    from sase.ace.tui.models.agent_time import wait_display_agent

    wait_agent = wait_display_agent(agent)
    if not wait_agent.waiting_for:
        return True
    if status_buckets is None:
        return False
    return all(status_buckets.get(name) == "Done" for name in wait_agent.waiting_for)


__all__ = [
    "agent_status_buckets_for_app",
    "agent_wait_status_maps_for_app",
    "collect_agent_status_buckets",
    "collect_agent_wait_status_maps",
    "wait_dependencies_satisfied",
]
