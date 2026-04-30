"""Cleanup plan helpers for agent dismissal."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from sase.core.agent_cleanup_wire import AgentCleanupPlanWire

AgentIdentity = tuple["AgentType", str, str | None]


def agent_wire_identity(agent: Agent) -> tuple[str, str, str | None]:
    return (agent.agent_type.value, agent.cl_name, agent.raw_suffix)


def wire_identity_key(identity: Any) -> tuple[str, str, str | None]:
    return (
        str(identity.agent_type),
        str(identity.cl_name),
        identity.raw_suffix,
    )


def agent_identity_from_wire(identity: Any) -> AgentIdentity:
    from ...models.agent import AgentType

    return (
        AgentType(str(identity.agent_type)),
        str(identity.cl_name),
        identity.raw_suffix,
    )


def plan_dismissal_side_effects(
    agents: list[Agent],
    agents_with_children_snapshot: list[Agent],
    *,
    taken_dismissed_names: set[str] | None = None,
) -> AgentCleanupPlanWire:
    """Return a Rust/Python cleanup plan for dismissal side effects."""
    from sase.core.agent_cleanup_facade import (
        agents_to_cleanup_targets,
        plan_agent_cleanup,
    )
    from sase.core.agent_cleanup_wire import (
        AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        CLEANUP_MODE_DISMISS_COMPLETED,
        CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        AgentCleanupIdentityWire,
        AgentCleanupRequestWire,
    )

    identities = tuple(
        AgentCleanupIdentityWire(
            agent_type=agent.agent_type.value,
            cl_name=agent.cl_name,
            raw_suffix=agent.raw_suffix,
        )
        for agent in agents
    )
    request = AgentCleanupRequestWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_DISMISS_COMPLETED,
        identities=identities,
        taken_dismissed_names=tuple(sorted(taken_dismissed_names or ())),
    )
    return plan_agent_cleanup(
        agents_to_cleanup_targets(agents_with_children_snapshot),
        request,
    )


def apply_dismissal_rename_intents(
    agents_with_children_snapshot: list[Agent],
    plan: object,
) -> dict[str, str]:
    """Mutate agent names according to cleanup rename intents."""
    by_identity = {
        agent_wire_identity(agent): agent for agent in agents_with_children_snapshot
    }
    name_map: dict[str, str] = {}
    side_effects = getattr(plan, "side_effects", None)
    for intent in getattr(side_effects, "dismissal_rename_allocations", ()):
        agent = by_identity.get(wire_identity_key(intent.identity))
        if agent is None:
            continue
        old_name = agent.agent_name
        agent.agent_name = intent.new_name
        if old_name and old_name != intent.new_name:
            name_map[old_name] = intent.new_name
    if not name_map:
        return dict(getattr(side_effects, "wait_reference_rewrite_map", ()) or ())
    return name_map


def dismissed_identities_from_plan(plan: object) -> set[AgentIdentity]:
    side_effects = getattr(plan, "side_effects", None)
    identities = {
        agent_identity_from_wire(identity)
        for identity in getattr(side_effects, "dismissed_index_additions", ())
    }
    return identities


def apply_in_memory_reference_rewrites(
    agents: Iterable[Agent],
    name_map: dict[str, str],
) -> None:
    """Update each agent's ``waiting_for`` list using *name_map* in place."""
    if not name_map:
        return
    for agent in agents:
        if not agent.waiting_for:
            continue
        new_waiting = [name_map.get(n, n) for n in agent.waiting_for]
        if new_waiting != agent.waiting_for:
            agent.waiting_for = new_waiting
