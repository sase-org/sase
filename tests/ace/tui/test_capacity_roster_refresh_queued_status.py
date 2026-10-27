"""Roster-refresh regression for queued agent sessions and their clans."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.ace.tui.models.agent_runner_slots import (
    RunnerCapacitySnapshot,
    refresh_runner_slot_context,
)
from tests._agents_tab_query_helpers import FakeAgentApp

from ._agent_runner_slots_helpers import (
    _agent,
    _machine_capacity_report_for_waiter,
)


def _queued_clan_projected():
    root = _agent(
        "clan.root",
        status="DONE",
        pid=None,
        agent_clan="research",
        agent_clan_generation="20260712120000",
    )
    turn = _agent(
        "clan.code",
        status="WAITING",
        start_time=datetime(2026, 7, 12, 12, 1),
        parent_timestamp="clan.root",
        slot_requested_at="2026-07-12T12:00:00Z",
        agent_clan="research",
        agent_clan_generation="20260712120000",
    )
    sibling = _agent(
        "clan.sib",
        start_time=datetime(2026, 7, 12, 12, 2),
        agent_clan="research",
        agent_clan_generation="20260712120000",
    )
    rows = [root, turn, sibling]
    _apply_status_overrides(rows)
    refresh_runner_slot_context(rows, effective_limit=8)
    projected = project_clan_tree(rows)
    container = projected[0]
    assert container.is_clan_container
    live_root = next(agent for agent in projected if agent.raw_suffix == "clan.root")
    live_turn = next(
        agent for agent in projected if agent.parent_timestamp == "clan.root"
    )
    assert (container.status, live_root.status, live_turn.status) == (
        "QUEUED",
        "QUEUED",
        "QUEUED",
    )
    assert live_root.wait_display_source is live_turn
    return projected, container, live_root, live_turn


@pytest.mark.asyncio
@pytest.mark.parametrize("use_report", [True, False])
async def test_roster_refresh_keeps_queued_session_and_clan(
    monkeypatch: pytest.MonkeyPatch,
    use_report: bool,
) -> None:
    projected, container, root, turn = _queued_clan_projected()
    app = FakeAgentApp(query="")
    app.current_tab = "agents"
    app._agents = projected
    app._agents_with_children = projected
    app._agents_capacity_with_children = projected
    app._agent_runner_capacity = RunnerCapacitySnapshot()
    app._agents_capacity_generation = 1
    app._agents_capacity_applied_generation = 0
    if use_report:
        app._machine_capacity_report = _machine_capacity_report_for_waiter(turn)
    else:
        app._machine_capacity_report = None

    monkeypatch.setattr("sase.config.core.get_max_running_agents", lambda: 8)
    monkeypatch.setattr(
        "sase.core.agent_hold_facade.active_agent_hold_records",
        lambda: [],
    )

    await app._run_agents_capacity_refresh_from_roster(
        generation=1,
        source="test",
    )
    assert (container.status, root.status, turn.status) == (
        "QUEUED",
        "QUEUED",
        "QUEUED",
    )
    assert root.wait_display_source is turn

    app._agents_capacity_generation = 2
    await app._run_agents_capacity_refresh_from_roster(
        generation=2,
        source="test",
    )
    assert (container.status, root.status, turn.status) == (
        "QUEUED",
        "QUEUED",
        "QUEUED",
    )
    assert root.wait_display_source is turn
