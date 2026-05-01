"""Rust-backed agent composition helpers."""

from sase.core.agent_compose_wire import (
    AgentComposeInputWire,
)

from .agent import Agent


def compose_rust_agent_list_with_dismissed(
    compose_input: AgentComposeInputWire,
) -> tuple[list[Agent], list[Agent]]:
    from sase.core.agent_compose_facade import (
        compose_agent_list,
        composed_agent_list_to_agents,
        composed_agent_list_to_dismissed_agents,
    )

    record = compose_agent_list(compose_input)
    return (
        composed_agent_list_to_agents(record),
        composed_agent_list_to_dismissed_agents(record),
    )
