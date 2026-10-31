"""Cached row graph copy-cost tests for the Agents tab."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    merge_incomplete_load_after_complete_history,
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.models.agent import Agent, AgentType
from tests._agents_tab_graph_isolation_helpers import (
    agent_session_graph,
    delta_load_state,
    row_observation,
    unrelated_delta,
)
from tests._agents_tab_incomplete_merge_helpers import (
    authoritative_load_state,
    bounded_prefix_load_state,
    incomplete_tier1_snapshot,
)
from tests._agents_tab_query_helpers import make_agent


def _counting_copy_spy(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int]:
    """Count rows passed to the worker-ownership copy entry point."""
    from sase.ace.tui.actions.agents import _loading_graph as graph_mod
    from sase.ace.tui.models import _agent_graph as model_graph

    counts = {"rows": 0, "calls": 0}
    real = model_graph.copy_agent_graph

    def spy(
        agents: list[Agent],
        memo: dict[int, Agent] | None = None,
    ) -> list[Agent]:
        counts["rows"] += len(list(agents))
        counts["calls"] += 1
        return real(agents, memo)

    monkeypatch.setattr(graph_mod, "copy_agent_graph", spy)
    return counts


def _hundred_row_cache() -> list[Agent]:
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


def test_authoritative_replacement_copies_no_cached_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An authoritative load with a proc projection must not copy cached history."""
    from sase.ace.tui._proc_observer_models import ProcProjection

    counts = _counting_copy_spy(monkeypatch)
    live = _hundred_row_cache()
    before = [row_observation(agent) for agent in live]
    incoming = [
        make_agent(
            cl_name=f"fresh-{index:03d}",
            raw_suffix=f"20260919{index:04d}",
            status="RUNNING",
            llm_provider="claude",
        )
        for index in range(100)
    ]
    snapshot = incomplete_tier1_snapshot(
        live,
        load_state=authoritative_load_state(),
        proc_projection=ProcProjection(),
    )

    boundary = prepare_loaded_agents_worker_boundary(
        incoming,
        [],
        set(),
        False,
        snapshot,
    )

    assert counts["rows"] == 0
    assert [row_observation(agent) for agent in live] == before
    assert {id(agent) for agent in boundary.prep.filtered_agents} == {
        id(agent) for agent in incoming
    }


def test_authoritative_without_proc_projection_copies_only_named_proc_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a projection, authoritative loads detach only fallback named procs."""

    counts = _counting_copy_spy(monkeypatch)
    named = [
        make_agent(
            agent_type=AgentType.NAMED_PROC,
            cl_name=f"proc-{index}",
            raw_suffix=f"proc-{index}",
            status="RUNNING",
        )
        for index in range(2)
    ]
    live = _hundred_row_cache() + named
    before = [row_observation(agent) for agent in live]
    incoming = [unrelated_delta()]
    snapshot = incomplete_tier1_snapshot(
        live,
        load_state=authoritative_load_state(),
        proc_projection=None,
    )

    boundary = prepare_loaded_agents_worker_boundary(
        incoming,
        [],
        set(),
        False,
        snapshot,
    )

    assert counts["rows"] == len(named)
    assert [row_observation(agent) for agent in live] == before
    published_named = [
        agent for agent in boundary.prep.filtered_agents if agent.is_named_proc
    ]
    assert len(published_named) == len(named)
    live_ids = {id(agent) for agent in live}
    assert all(id(agent) not in live_ids for agent in published_named)


def test_query_change_bounded_prefix_copies_no_cached_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bounded load under a new committed query replaces; it never patches."""
    from sase.ace.tui._proc_observer_models import ProcProjection

    counts = _counting_copy_spy(monkeypatch)
    live = _hundred_row_cache()
    before = [row_observation(agent) for agent in live]
    snapshot = incomplete_tier1_snapshot(
        live,
        load_state=bounded_prefix_load_state(),
        agents_seen_complete_history=False,
        cache_query_matches=False,
        proc_projection=ProcProjection(),
    )

    boundary = prepare_loaded_agents_worker_boundary(
        [unrelated_delta()],
        [],
        set(),
        False,
        snapshot,
    )

    assert counts["rows"] == 0
    assert [row_observation(agent) for agent in live] == before
    assert boundary.prep.filtered_agents


def test_delta_patch_with_empty_incoming_capacity_skips_capacity_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capacity roots are detached only when the capacity merge will run."""
    counts = _counting_copy_spy(monkeypatch)
    live = _hundred_row_cache()
    capacity = [
        make_agent(
            cl_name=f"cap-{index:03d}",
            raw_suffix=f"20260920{index:04d}",
            status="RUNNING",
            llm_provider="codex",
        )
        for index in range(10)
    ]
    before_live = [row_observation(agent) for agent in live]
    before_capacity = [row_observation(agent) for agent in capacity]
    snapshot = incomplete_tier1_snapshot(
        live,
        load_state=delta_load_state(),
        capacity_agents_with_children=capacity,
    )
    prep = PreparedApplyData(
        filtered_agents=[unrelated_delta()],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
        capacity_agents=[],
    )

    merged = merge_incomplete_load_after_complete_history(prep, snapshot)

    assert counts["rows"] == len(live)
    assert [row_observation(agent) for agent in live] == before_live
    assert [row_observation(agent) for agent in capacity] == before_capacity
    live_ids = {id(agent) for agent in live}
    assert all(id(agent) not in live_ids for agent in merged.filtered_agents)


def test_authoritative_with_capacity_report_leaves_cached_history_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authoritative loads with a capacity report must not copy discarded history."""
    import time
    from dataclasses import replace

    from sase.ace.tui._proc_observer_models import ProcProjection
    from sase.config.runner_limit_override import EffectiveRunnerLimitSnapshot
    from sase.core.runner_slots import MachineCapacityReport

    counts = _counting_copy_spy(monkeypatch)
    live = _hundred_row_cache()
    capacity = [
        make_agent(
            cl_name=f"cap-{index:03d}",
            raw_suffix=f"20260920{index:04d}",
            status="RUNNING",
            llm_provider="codex",
        )
        for index in range(10)
    ]
    before_live = [row_observation(agent) for agent in live]
    before_capacity = [row_observation(agent) for agent in capacity]
    incoming = [
        make_agent(
            cl_name=f"fresh-{index:03d}",
            raw_suffix=f"20260919{index:04d}",
            status="RUNNING",
            llm_provider="claude",
        )
        for index in range(100)
    ]
    snapshot = incomplete_tier1_snapshot(
        live,
        load_state=authoritative_load_state(),
        proc_projection=ProcProjection(),
        capacity_agents_with_children=capacity,
    )
    now = time.time()
    raw = {
        "occupied_capacity": 5.0,
        "occupied_lanes": 6,
        "effective_limit": 8.0,
        "claims": [],
        "waiters": [],
        "accounting": [],
        "accounting_valid": True,
    }
    snapshot = replace(
        snapshot,
        capacity_report=MachineCapacityReport(
            machine="athena",
            computed_at=now,
            scanned_at=now,
            token="capacity-token-1",
            scan_current=True,
            effective_limit=8.0,
            limit=EffectiveRunnerLimitSnapshot(
                configured_limit=8,
                temporary_override=None,
                captured_at=now,
            ),
            occupied_capacity=5.0,
            occupied_lanes=6,
            over_limit=False,
            claims=(),
            waiters=(),
            accounting=(),
            diagnostics=(),
            accounting_valid=True,
            accounting_available=True,
            raw_snapshot=raw,
            record_inputs=(),
        ),
    )

    boundary = prepare_loaded_agents_worker_boundary(
        incoming,
        [],
        set(),
        False,
        snapshot,
    )

    assert counts["rows"] == 0
    assert [row_observation(agent) for agent in live] == before_live
    assert [row_observation(agent) for agent in capacity] == before_capacity
    live_ids = {id(agent) for agent in live} | {id(agent) for agent in capacity}
    assert all(id(agent) not in live_ids for agent in boundary.prep.filtered_agents)
