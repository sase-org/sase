"""Quiet inline queue-capacity badges for agent rows and queue ladders."""

from __future__ import annotations

import math

from rich.text import Text

from sase.feature_flags import FeatureFlag, current_flags

from ..models.agent import Agent, wait_display_agent
from ..models.agent_runner_slots import (
    format_queue_weight_badge_value,
)

QUEUE_WEIGHT_BADGE_PREFIX_STYLE = "dim"
QUEUE_WEIGHT_BADGE_NUMBER_STYLE = "#87D7D7"
QUEUE_CAPACITY_BADGE_NUMBER_STYLE = "#87AFD7"
QUEUE_CAPACITY_BADGE_OVER_LIMIT_STYLE = "#FFD700"


def queue_capacity_budget_display_enabled() -> bool:
    """Return whether capacity-budget display has replaced threshold display."""
    return current_flags().enabled(FeatureFlag.queue_capacity_budget)


def append_queue_weight_badge(
    text: Text,
    weight: object,
    *,
    explicit: bool = False,
    pad: bool = True,
) -> bool:
    """Append ``wN`` for a non-default valid capacity weight, including ``w0``."""
    value = format_queue_weight_badge_value(weight, explicit=explicit)
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
        or (agent.is_child_row and not agent.agent_session_parallel)
    ):
        return False
    wait_agent = wait_display_agent(agent)
    return append_queue_weight_badge(
        text,
        wait_agent.queue_weight,
        explicit=wait_agent.queue_weight_explicit,
    )


def append_queue_capacity_badge(
    text: Text,
    capacity: object,
    *,
    explicit: bool,
    effective_limit: object | None = None,
    pad: bool = True,
    multiplier: object | None = None,
) -> bool:
    """Append ``cN`` (or ``c<M>x``) for an authored queue-capacity budget."""
    value = format_queue_capacity_badge_value(
        capacity, explicit=explicit, multiplier=multiplier
    )
    if value is None:
        return False
    if pad:
        text.append(" ")
    text.append("c", style=QUEUE_WEIGHT_BADGE_PREFIX_STYLE)
    number_style = queue_capacity_badge_number_style(
        capacity,
        explicit=explicit,
        effective_limit=effective_limit,
        multiplier=multiplier,
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
        or (agent.is_child_row and not agent.agent_session_parallel)
    ):
        return appended
    wait_agent = wait_display_agent(agent)
    if not queue_capacity_budget_display_enabled():
        return appended
    capacity = (
        wait_agent.queue_capacity
        if wait_agent.queue_capacity is not None
        else wait_agent.wait_runners
    )
    return (
        append_queue_capacity_badge(
            text,
            capacity,
            explicit=(
                wait_agent.queue_capacity_explicit or wait_agent.wait_runners_explicit
            ),
            effective_limit=wait_agent.runner_effective_limit,
            multiplier=wait_agent.queue_capacity_multiplier,
        )
        or appended
    )


def format_queue_capacity_badge_value(
    capacity: object,
    *,
    explicit: bool,
    multiplier: object | None = None,
) -> str | None:
    if not explicit:
        return None
    capacity_int = _queue_capacity_int(capacity)
    if capacity_int is not None:
        return str(capacity_int)
    if multiplier is None:
        return None
    from sase.xprompt.queue_directive import format_queue_capacity_multiplier

    return format_queue_capacity_multiplier(multiplier)


def queue_capacity_badge_number_style(
    capacity: object,
    *,
    explicit: bool,
    effective_limit: object | None,
    multiplier: object | None = None,
) -> str:
    """Return the badge number style for an authored capacity value."""
    if _multiplier_over_limit(multiplier if explicit else None):
        return QUEUE_CAPACITY_BADGE_OVER_LIMIT_STYLE
    if _capacity_over_effective_limit(
        capacity if explicit else None,
        effective_limit,
    ):
        return QUEUE_CAPACITY_BADGE_OVER_LIMIT_STYLE
    return QUEUE_CAPACITY_BADGE_NUMBER_STYLE


def _multiplier_over_limit(multiplier: object | None) -> bool:
    """Return whether an authored ``<M>x`` multiplier exceeds unity."""
    if multiplier is None or isinstance(multiplier, bool):
        return False
    try:
        return float(str(multiplier)) > 1.0
    except (TypeError, ValueError):
        return False


def _capacity_over_effective_limit(
    capacity: object,
    effective_limit: object | None,
) -> bool:
    capacity_int = _queue_capacity_int(capacity)
    limit = _finite_float(effective_limit)
    if capacity_int is None or limit is None:
        return False
    return float(capacity_int) > limit


def _queue_capacity_int(capacity: object) -> int | None:
    if type(capacity) is int and capacity >= 0:
        return capacity
    return None


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None
