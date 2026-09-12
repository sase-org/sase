"""Quiet inline queue-capacity badges for agent rows and queue ladders."""

from __future__ import annotations

from rich.text import Text

from sase.feature_flags import FeatureFlag, current_flags

from ..models.agent import Agent, wait_display_agent
from ..models.agent_runner_slots import (
    format_capacity_value,
    format_queue_weight_badge_value,
)

QUEUE_WEIGHT_BADGE_PREFIX_STYLE = "dim"
QUEUE_WEIGHT_BADGE_NUMBER_STYLE = "#87D7D7"
QUEUE_CAPACITY_BADGE_NUMBER_STYLE = "#87AFD7"
QUEUE_CAPACITY_BADGE_OVER_LIMIT_STYLE = "#FFD700"


def queue_capacity_budget_display_enabled() -> bool:
    """Return whether capacity-budget display has replaced threshold display."""
    return current_flags().enabled(FeatureFlag.queue_capacity_budget)


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


def _append_agent_queue_weight_badge(text: Text, agent: Agent) -> bool:
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


def append_queue_capacity_badge(
    text: Text,
    capacity: object,
    *,
    explicit: bool,
    effective_limit: object | None = None,
    pad: bool = True,
) -> bool:
    """Append ``cN`` for an authored queue-capacity budget."""
    value = _format_queue_capacity_badge_value(capacity, explicit=explicit)
    if value is None:
        return False
    if pad:
        text.append(" ")
    text.append("c", style=QUEUE_WEIGHT_BADGE_PREFIX_STYLE)
    number_style = (
        QUEUE_CAPACITY_BADGE_OVER_LIMIT_STYLE
        if _capacity_over_effective_limit(value, effective_limit)
        else QUEUE_CAPACITY_BADGE_NUMBER_STYLE
    )
    text.append(value, style=number_style)
    return True


def append_agent_queue_badges(text: Text, agent: Agent) -> bool:
    """Append authored row badges for agent-bearing rows only."""
    appended = _append_agent_queue_weight_badge(text, agent)
    if (
        agent.is_clan_container
        or agent.is_proc_shell
        or agent.is_gate
        or agent.is_monitor
        or (agent.is_child_row and not agent.agent_family_parallel)
    ):
        return appended
    wait_agent = wait_display_agent(agent)
    if not queue_capacity_budget_display_enabled():
        return appended
    return (
        append_queue_capacity_badge(
            text,
            wait_agent.wait_runners,
            explicit=wait_agent.wait_runners_explicit,
            effective_limit=wait_agent.runner_effective_limit,
        )
        or appended
    )


def _format_queue_capacity_badge_value(
    capacity: object,
    *,
    explicit: bool,
) -> str | None:
    if not explicit:
        return None
    return format_capacity_value(capacity, minimum_decimal=False)


def _capacity_over_effective_limit(value: str, effective_limit: object | None) -> bool:
    if not value.isdigit() or effective_limit is None:
        return False
    limit_text = format_capacity_value(effective_limit, minimum_decimal=False)
    if not limit_text.isdigit():
        return False
    return int(value) > int(limit_text)
