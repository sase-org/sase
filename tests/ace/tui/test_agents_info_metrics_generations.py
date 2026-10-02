"""Generation-keyed info-panel metrics cache (phase tick-compare-skip)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents import _unread_bulk_scope as bulk_scope_mod
from sase.ace.tui.actions.agents._display_detail_info import AgentInfoDisplayMixin
from sase.ace.tui.actions.agents._roster_generation import (
    notify_roster_status_mutation,
    set_agents_roster,
)
from sase.ace.tui.actions.agents._unread_set_generation import (
    bump_unread_set_generation,
)

from .widgets.agent_list_runtime_helpers import agent


class _MetricsOwner(AgentInfoDisplayMixin):
    """Minimal owner carrying the roster/unread state metrics reads."""

    def __init__(self, roster: list[Any]) -> None:
        self._agents = list(roster)
        self._agents_query_result = list(roster)
        self._agents_with_children = list(roster)
        self._unread_completed_agent_ids = set()
        self._agents_roster_generation = 0
        self._unread_set_generation = 0
        self._agent_panels_grouped = False
        self._agent_info_metrics_cache = None

    def _agent_panel_index(self) -> SimpleNamespace:
        return SimpleNamespace(
            non_child_indices=list(range(len(self._agents))),
            hidden_starting_indices=[],
        )


def _owner_with_done_row() -> _MetricsOwner:
    rows = [
        agent(status="RUNNING", cl_name="a"),
        agent(status="DONE", cl_name="b"),
    ]
    owner = _MetricsOwner(rows)
    owner._unread_completed_agent_ids = {rows[1].identity}
    return owner


def test_metrics_second_tick_skips_roster_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repeated tick hits the cache without walking the bulk universe."""
    walks: list[int] = []
    real_universe = bulk_scope_mod.bulk_ack_roster_universe

    def _counting(owner):  # type: ignore[no-untyped-def]
        walks.append(1)
        return real_universe(owner)

    monkeypatch.setattr(bulk_scope_mod, "bulk_ack_roster_universe", _counting)
    owner = _owner_with_done_row()
    first = owner._agent_info_metrics()
    assert first[0] == 1  # one unread terminal row in scope
    second = owner._agent_info_metrics()
    assert second == first
    assert len(walks) == 1


def test_metrics_invalidates_on_each_generation_bump() -> None:
    """Roster, status, and unread bumps each force exactly one rebuild."""
    owner = _owner_with_done_row()
    owner._agent_info_metrics()
    assert owner._agent_info_metrics_cache is not None
    first_key = owner._agent_info_metrics_cache[0]

    set_agents_roster(owner, agents=list(owner._agents))
    owner._agent_info_metrics()
    assert owner._agent_info_metrics_cache[0] != first_key
    second_key = owner._agent_info_metrics_cache[0]

    notify_roster_status_mutation(owner)
    owner._agent_info_metrics()
    assert owner._agent_info_metrics_cache[0] != second_key
    third_key = owner._agent_info_metrics_cache[0]

    bump_unread_set_generation(owner)
    owner._agent_info_metrics()
    assert owner._agent_info_metrics_cache[0] != third_key


def test_metrics_reflects_status_change_after_notify() -> None:
    """An in-place status edit + notify changes the reported counts."""
    owner = _owner_with_done_row()
    before = owner._agent_info_metrics()
    assert before[0] == 1
    done_row = owner._agents[1]
    done_row.status = "RUNNING"
    notify_roster_status_mutation(owner)
    after = owner._agent_info_metrics()
    assert after[0] == 0
    assert after != before


def test_metrics_reflects_unread_change_after_bump() -> None:
    """Clearing the unread set changes the header unread count."""
    owner = _owner_with_done_row()
    assert owner._agent_info_metrics()[0] == 1
    owner._unread_completed_agent_ids.clear()
    bump_unread_set_generation(owner)
    assert owner._agent_info_metrics()[0] == 0
