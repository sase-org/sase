"""TUI wrappers for inferring bead metadata from agent records."""

from __future__ import annotations

from sase.agent.bead_display import (
    derive_agent_bead_id_from_name,
    format_agent_bead_display_for_name,
)

from .agent import Agent


def derive_agent_bead_id(agent: Agent) -> str | None:
    """Infer a bead id from an agent name written by ``sase bead work``."""
    return derive_agent_bead_id_from_name(agent.agent_name)


def format_agent_bead_display(
    agent: Agent, *, include_description: bool = True
) -> str | None:
    """Format the bead metadata value for an agent details header."""
    return format_agent_bead_display_for_name(
        agent.agent_name, include_description=include_description
    )
