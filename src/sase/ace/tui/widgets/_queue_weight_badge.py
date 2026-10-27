"""Quiet inline queue-capacity badges for agent rows and queue ladders."""

from __future__ import annotations

import math

from rich.text import Text

from sase.agent.status_buckets import agent_status_bucket

from ..models.agent import Agent, wait_display_agent
from ..models.agent_runner_slots import (
    format_capacity_value,
    format_queue_weight_badge_value,
)

QUEUE_WEIGHT_BADGE_PREFIX_STYLE = "dim"

# Occupancy mark family for charged runner capacity. ``▰N`` is what a
# Running-bucket row is charged right now (``▰0`` for an explicit zero-weight
# claim); ``▱`` is a Running row holding nothing (rider, unstarted, or
# pending human); ``▱?`` is unknown (no accounting entry, invalid weight,
# missing process evidence, or accounting unavailable). The ▰/▱ pair renders
# as single-cell text in the Fira Code / DejaVu / Noto Emoji snapshot stack
# with no emoji presentation, and neither glyph is an Agents-tab row token
# today: rows use ● ○ ◐ ▪ ◆ ★ ▲ ▼ ▸ ❯ ⚙ ⚠ ⚑ ⚡ ⚒ ⊛ ◌ ↻ ↺ ⧖ ✗ ✓ ⏳ … ▶ ⋔ ▣
# (the only ▰/▱ in the TUI is the prompt-completion frequency meter, a
# different surface). The filled/hollow pairing reads as a gauge segment, and
# the trailing ``?`` extends the hollow variant for the unknown case.
CAPACITY_MARK_HOLDING_GLYPH = "▰"
CAPACITY_MARK_IDLE_GLYPH = "▱"
CAPACITY_MARK_STYLE = "dim"
QUEUE_WEIGHT_BADGE_NUMBER_STYLE = "#87D7D7"
QUEUE_CAPACITY_BADGE_NUMBER_STYLE = "#87AFD7"
QUEUE_CAPACITY_BADGE_OVER_LIMIT_STYLE = "#FFD700"


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
    if agent.is_monitor:
        if agent.queue_weight == 0 and agent.queue_weight_explicit:
            return append_queue_weight_badge(
                text,
                agent.queue_weight,
                explicit=True,
            )
        return False
    if (
        agent.is_clan_container
        or agent.is_named_proc
        or agent.is_gate
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


def _capacity_mark_text(agent: Agent) -> str | None:
    """Return the occupancy mark for one row, or ``None`` when it shows none.

    Marks draw on every Running-bucket agent row and clan container,
    including collapsed clans. Clan containers carry their summed member
    aggregate (see ``_apply_clan_capacity_aggregates``), so this reads the
    row's own stored fields in both cases. ``None`` capacity state means no
    report has been applied yet, which shows no mark rather than a guess.
    """
    if agent.capacity_state is None:
        return None
    if agent.is_workflow_step_child or agent.is_named_proc:
        return None
    if agent_status_bucket(agent) != "Running":
        return None
    if agent.capacity_state == "holding":
        charged = agent.capacity_charged
        if charged is None:
            return f"{CAPACITY_MARK_HOLDING_GLYPH}?"
        return (
            f"{CAPACITY_MARK_HOLDING_GLYPH}"
            f"{format_capacity_value(charged, minimum_decimal=False)}"
        )
    if agent.capacity_state in ("riding_claim", "waiting", "not_holding"):
        return CAPACITY_MARK_IDLE_GLYPH
    return f"{CAPACITY_MARK_IDLE_GLYPH}?"


def append_capacity_mark(text: Text, agent: Agent) -> bool:
    """Append the occupancy mark for *agent*'s row, if it shows one."""
    mark = _capacity_mark_text(agent)
    if mark is None:
        return False
    text.append(" ")
    text.append(mark, style=CAPACITY_MARK_STYLE)
    return True


def append_agent_queue_badges(text: Text, agent: Agent) -> bool:
    """Append authored row badges for agent-bearing rows only."""
    appended = _append_agent_queue_weight_badge(text, agent)
    if agent.is_clan_container:
        # Clan containers carry the mark after the R/W/D chip instead
        # (see ``format_agent_option``), never beside queue badges.
        return appended
    if (
        agent.is_named_proc
        or agent.is_gate
        or agent.is_monitor
        or (agent.is_child_row and not agent.agent_session_parallel)
    ):
        return append_capacity_mark(text, agent) or appended
    wait_agent = wait_display_agent(agent)
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
        or append_capacity_mark(text, agent)
        or appended
    )


def format_queue_capacity_badge_value(
    capacity: object,
    *,
    explicit: bool,
    multiplier: object | None = None,
) -> str | None:
    capacity_int = _queue_capacity_int(capacity)
    if capacity_int is not None:
        return str(capacity_int) if explicit else None
    if multiplier is None:
        return None
    from sase.macro.queue_directive import format_queue_capacity_multiplier

    return format_queue_capacity_multiplier(multiplier)


def queue_capacity_badge_number_style(
    capacity: object,
    *,
    explicit: bool,
    effective_limit: object | None,
    multiplier: object | None = None,
) -> str:
    """Return the badge number style for an authored capacity value."""
    if _queue_capacity_int(capacity) is not None:
        if _capacity_over_effective_limit(
            capacity if explicit else None,
            effective_limit,
        ):
            return QUEUE_CAPACITY_BADGE_OVER_LIMIT_STYLE
        return QUEUE_CAPACITY_BADGE_NUMBER_STYLE
    if _multiplier_over_limit(multiplier):
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
