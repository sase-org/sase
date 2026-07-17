"""Rust-backed cleanup planning helpers for TUI agent kills."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from sase.core.agent_cleanup_wire import AgentCleanupPlanWire


def plan_bulk_kill_cleanup_side_effects(
    agents: list[Agent],
    agents_with_children_snapshot: list[Agent],
) -> AgentCleanupPlanWire:
    from sase.core.agent_cleanup_facade import (
        agents_to_cleanup_targets,
        plan_agent_cleanup,
    )
    from sase.core.agent_cleanup_wire import (
        AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        CLEANUP_MODE_KILL_AND_DISMISS,
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
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=identities,
    )
    return plan_agent_cleanup(
        agents_to_cleanup_targets(
            [a for a in agents_with_children_snapshot if not a.is_clan_container]
        ),
        request,
    )


def plan_single_agent_kill_cleanup(
    agent: Agent,
    agents_with_children_snapshot: list[Agent],
) -> AgentCleanupPlanWire:
    from sase.core.agent_cleanup_facade import (
        agents_to_cleanup_targets,
        plan_agent_cleanup,
    )
    from sase.core.agent_cleanup_wire import (
        AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        CLEANUP_MODE_KILL_AND_DISMISS,
        CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        AgentCleanupIdentityWire,
        AgentCleanupRequestWire,
    )

    request = AgentCleanupRequestWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_KILL_AND_DISMISS,
        identities=(
            AgentCleanupIdentityWire(
                agent_type=agent.agent_type.value,
                cl_name=agent.cl_name,
                raw_suffix=agent.raw_suffix,
            ),
        ),
        include_pidless_as_dismissable=True,
    )
    return plan_agent_cleanup(
        agents_to_cleanup_targets(
            [a for a in agents_with_children_snapshot if not a.is_clan_container]
        ),
        request,
    )
