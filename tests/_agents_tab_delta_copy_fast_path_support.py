"""Shared fixtures for exact-delta copy-on-write tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields, is_dataclass
from datetime import datetime

from sase.ace.tui.actions.agents._loading_compute import PreparedApplySnapshot
from sase.ace.tui.models.agent import Agent
from tests._agents_tab_graph_isolation_helpers import agent_session_graph
from tests._agents_tab_incomplete_merge_helpers import incomplete_tier1_snapshot
from tests._agents_tab_graph_isolation_helpers import delta_load_state
from tests._agents_tab_query_helpers import make_agent


def _state_value(value: object, seen: set[int] | None = None) -> object:
    """Test-only structural state with Agent references represented by identity."""
    if isinstance(value, Agent):
        return ("agent", value.identity)
    if seen is None:
        seen = set()
    if isinstance(value, (list, tuple, set, frozenset, dict)) or is_dataclass(value):
        key = id(value)
        if key in seen:
            return ("cycle", type(value).__name__)
        seen.add(key)
        try:
            if isinstance(value, (list, tuple)):
                return (
                    type(value).__name__,
                    tuple(_state_value(item, seen) for item in value),
                )
            if isinstance(value, (set, frozenset)):
                items = [_state_value(item, seen) for item in value]
                return (type(value).__name__, tuple(sorted(items, key=repr)))
            if isinstance(value, dict):
                items = [
                    (_state_value(key, seen), _state_value(item, seen))
                    for key, item in value.items()
                ]
                return ("dict", tuple(sorted(items, key=repr)))
            return (
                type(value).__name__,
                tuple(
                    (field.name, _state_value(getattr(value, field.name), seen))
                    for field in fields(value)
                ),
            )
        finally:
            seen.remove(key)
    return deepcopy(value)


def agent_state(agent: Agent) -> object:
    return tuple(
        (field.name, _state_value(getattr(agent, field.name)))
        for field in fields(agent)
    )


def hundred_row_cache() -> list[Agent]:
    rows = [
        make_agent(
            cl_name=f"cached-{index:03d}",
            raw_suffix=f"20260918{index:04d}",
            status="DONE",
            start_time=datetime(2026, 9, 18, 9, index % 60, 0),
        )
        for index in range(100)
    ]
    root, child = agent_session_graph()[0], agent_session_graph()[1]
    return [*rows, root, child]


def annotated_snapshot(
    live: list[Agent],
    *,
    cache_query_matches: bool = True,
) -> PreparedApplySnapshot:
    """Wrap live rows in a delta snapshot with realistic slot context."""
    from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context
    from sase.config.core import get_max_running_agents

    refresh_runner_slot_context(
        live,
        effective_limit=get_max_running_agents(),
        capacity_agents=list(live),
    )
    return incomplete_tier1_snapshot(
        live,
        load_state=delta_load_state(),
        capacity_agents_with_children=list(live),
        cache_query_matches=cache_query_matches,
    )


def replace_status(agent: Agent, status: str) -> Agent:
    clone = deepcopy(agent)
    clone.status = status
    return clone
