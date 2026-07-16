"""Shared helpers for single-agent kill tests."""

from __future__ import annotations

from sase.ace.tui.models.agent import Agent


def cleanup_plan(agent: Agent, *, action: str, kind: str = "running") -> object:
    from sase.core.agent_cleanup_wire import (
        AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        AgentCleanupDismissItemWire,
        AgentCleanupIdentityWire,
        AgentCleanupKillItemWire,
        AgentCleanupPlanWire,
        AgentCleanupSideEffectsWire,
    )

    identity = AgentCleanupIdentityWire(
        agent_type=agent.agent_type.value,
        cl_name=agent.cl_name,
        raw_suffix=agent.raw_suffix,
    )
    kill_items = ()
    dismiss_items = ()
    if action == "kill":
        kill_items = (
            AgentCleanupKillItemWire(
                identity=identity,
                kind=kind,
                pid=agent.pid,
                display_name=agent.display_name,
            ),
        )
    elif action == "dismiss":
        dismiss_items = (
            AgentCleanupDismissItemWire(
                identity=identity,
                display_name=agent.display_name,
            ),
        )
    return AgentCleanupPlanWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        selected_identities=(identity,),
        kill_items=kill_items,
        dismiss_items=dismiss_items,
        side_effects=AgentCleanupSideEffectsWire(
            dismissed_index_additions=(identity,),
        ),
    )
