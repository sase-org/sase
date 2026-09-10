"""Quiet inline queue-weight badges for agent rows and queue ladders."""

from __future__ import annotations

from rich.text import Text

from ..models.agent import Agent, wait_display_agent
from ..models.agent_runner_slots import format_queue_weight_badge_value

QUEUE_WEIGHT_BADGE_PREFIX_STYLE = "dim"
QUEUE_WEIGHT_BADGE_NUMBER_STYLE = "#87D7D7"


def append_queue_weight_badge(text: Text, weight: object, *, pad: bool = True) -> bool:
    """Append ``wN`` for a non-default valid capacity weight."""
    value = format_queue_weight_badge_value(weight)
    if value is None:
        return False
    if pad:
        text.append(" ")
    text.append("w", style=QUEUE_WEIGHT_BADGE_PREFIX_STYLE)
    text.append(value, style=QUEUE_WEIGHT_BADGE_NUMBER_STYLE)
    return True


def append_agent_queue_weight_badge(text: Text, agent: Agent) -> bool:
    """Append a row badge for weighted agent-bearing rows only."""
    if (
        agent.is_clan_container
        or agent.is_proc_shell
        or agent.is_gate
        or agent.is_monitor
        or (agent.is_child_row and not agent.agent_family_parallel)
    ):
        return False
    return append_queue_weight_badge(text, wait_display_agent(agent).queue_weight)
