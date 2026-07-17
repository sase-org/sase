"""Cleanup plan helpers for agent dismissal."""

from __future__ import annotations

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
    )
    return plan_agent_cleanup(
        agents_to_cleanup_targets(
            [a for a in agents_with_children_snapshot if not a.is_clan_container]
        ),
        request,
    )


def dismissed_identities_from_plan(plan: object) -> set[AgentIdentity]:
    side_effects = getattr(plan, "side_effects", None)
    identities = {
        agent_identity_from_wire(identity)
        for identity in getattr(side_effects, "dismissed_index_additions", ())
    }
    return identities
