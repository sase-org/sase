"""Reference facade for agent-list composition.

Phase 1 intentionally keeps product behavior on the existing Python loader.
The helpers here expose that loader through the future Rust wire contract so
golden fixtures and benchmarks can compare subsequent implementations against
one stable shape.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.models.agent import Agent
from sase.core.agent_compose_wire import (
    AgentComposeInputWire,
    AgentComposeOptionsWire,
    ComposedAgentListWire,
    agent_to_wire,
)


# pyvision: tests/test_core_agent_compose.py
def compose_python_agents_to_wire(
    agents: list[Agent],
    *,
    workflow_agent_steps: list[Agent] | None = None,
    dismissed_from_loader: list[Agent] | None = None,
) -> ComposedAgentListWire:
    """Project already-composed Python agents into the compose wire shape."""

    return ComposedAgentListWire(
        agents=[agent_to_wire(agent) for agent in agents],
        workflow_agent_steps=[
            agent_to_wire(agent) for agent in (workflow_agent_steps or [])
        ],
        dismissed_from_loader=[
            agent_to_wire(agent) for agent in (dismissed_from_loader or [])
        ],
        dropped=[],
        merge_log=[],
    )


# pyvision: tests/test_core_agent_compose.py
def compose_agent_list_reference(
    input_wire: AgentComposeInputWire | None = None,
    *,
    changespec_snapshot: list[ChangeSpec] | None = None,
) -> ComposedAgentListWire:
    """Run the current Python loader and return the stable compose wire shape.

    ``input_wire`` is accepted to match the future Rust operation signature.
    Phase 1 does not route product code through these data inputs yet; it uses
    the established Python loader as the reference implementation.
    """

    from sase.ace.tui.models.agent_loader import load_all_agents

    agents = load_all_agents(changespec_snapshot=changespec_snapshot)
    if input_wire is not None and not input_wire.options.include_workflow_steps:
        return compose_python_agents_to_wire(agents)
    return compose_python_agents_to_wire(agents)


# pyvision: tests/test_core_agent_compose.py
def with_options(
    base: AgentComposeOptionsWire,
    **overrides: Any,
) -> AgentComposeOptionsWire:
    """Return a copy of *base* with *overrides* applied."""

    return replace(base, **overrides)


__all__ = [
    "compose_agent_list_reference",
    "compose_python_agents_to_wire",
    "with_options",
]
