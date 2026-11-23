"""Preparation, equivalence, and copy-count tests for exact deltas."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sase.ace.tui.actions.agents._loading_compute import (
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.actions.agents._loading_graph import share_back_boundary_fast
from sase.ace.tui.models.agent import Agent
from tests._agents_tab_delta_copy_fast_path_support import (
    agent_state,
    annotated_snapshot,
    hundred_row_cache,
    replace_status,
)
from tests._agents_tab_graph_isolation_helpers import (
    agent_session_graph,
    row_observation,
    unrelated_delta,
)
from tests._agents_tab_query_helpers import make_agent


def counting_deep_copy_spy(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
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


def test_scalar_delta_equivalence_fast_vs_fallback() -> None:
    live = hundred_row_cache()
    before = [row_observation(agent) for agent in live]
    target = live[5]
    incoming = replace_status(target, "FAILED")
    fast_snapshot = annotated_snapshot(live)
    fallback_snapshot = annotated_snapshot(live, cache_query_matches=False)
    fast_boundary = prepare_loaded_agents_worker_boundary(
        [incoming], [], set(), False, fast_snapshot
    )
    fallback_boundary = prepare_loaded_agents_worker_boundary(
        [incoming], [], set(), False, fallback_snapshot
    )
    assert [row_observation(agent) for agent in live] == before
    fast_rows = {agent.identity: agent for agent in fast_boundary.prep.filtered_agents}
    fallback_rows = {
        agent.identity: agent for agent in fallback_boundary.prep.filtered_agents
    }
    assert set(fast_rows) == set(fallback_rows)
    for identity in fast_rows:
        assert agent_state(fast_rows[identity]) == agent_state(fallback_rows[identity])


def test_fast_path_uses_no_deep_copies_for_small_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = hundred_row_cache()
    counts = counting_deep_copy_spy(monkeypatch)
    snapshot = annotated_snapshot(live)
    target = live[10]
    incoming = replace_status(target, "FAILED")
    boundary = prepare_loaded_agents_worker_boundary(
        [incoming], [], set(), False, snapshot
    )
    assert counts["rows"] == 0
    shared = share_back_boundary_fast(boundary, snapshot)
    published = shared.fold.unfiltered_agents  # type: ignore[union-attr]
    live_ids = {id(agent) for agent in live}
    retained_new = sum(1 for agent in published if id(agent) not in live_ids)
    assert retained_new <= 8
    assert len(published) >= len(live) - 1


def test_fast_path_without_complete_watermark_uses_no_deep_copies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = hundred_row_cache()
    counts = counting_deep_copy_spy(monkeypatch)
    snapshot = replace(
        annotated_snapshot(live),
        agents_seen_complete_history=False,
    )
    target = live[10]
    incoming = replace_status(target, "FAILED")
    boundary = prepare_loaded_agents_worker_boundary(
        [incoming], [], set(), False, snapshot
    )
    assert counts["rows"] == 0
    shared = share_back_boundary_fast(boundary, snapshot)
    published = shared.fold.unfiltered_agents  # type: ignore[union-attr]
    live_ids = {id(agent) for agent in live}
    retained_new = sum(1 for agent in published if id(agent) not in live_ids)
    assert retained_new <= 8
    assert len(published) >= len(live) - 1


def test_exact_delta_deletion_equivalence() -> None:
    live = hundred_row_cache()
    snapshot = annotated_snapshot(live)
    removed = live[20]
    snapshot = replace(snapshot, dismissed_agents={removed.identity})
    live_before = [agent_state(agent) for agent in live]
    boundary = prepare_loaded_agents_worker_boundary([], [], set(), False, snapshot)
    assert removed.identity not in {
        agent.identity for agent in boundary.prep.filtered_agents
    }
    # Worker preparation never mutates the live graph, even for deletions.
    assert [agent_state(agent) for agent in live] == live_before


def test_child_add_remove_equivalence() -> None:
    live = agent_session_graph()
    snapshot = annotated_snapshot(live)
    parent_suffix = next(
        agent.raw_suffix for agent in live if agent.agent_session_role == "root"
    )
    assert parent_suffix
    child = make_agent(
        cl_name="fam-new",
        raw_suffix="20260918080200",
        status="RUNNING",
        parent_timestamp=parent_suffix,
        agent_session="fam",
        agent_session_role="code",
    )
    boundary = prepare_loaded_agents_worker_boundary(
        [child], [], set(), False, snapshot
    )
    assert any(
        agent.raw_suffix == "20260918080200" for agent in boundary.prep.filtered_agents
    )
    # Removing it again restores the roster identities.
    assert {agent.identity for agent in live} <= {
        agent.identity for agent in boundary.prep.filtered_agents
    }
