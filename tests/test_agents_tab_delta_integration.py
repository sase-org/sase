"""Integrate bounded affected-graph prep into the exact-delta pipeline.

Proves the expanded fast path hits ordinary mixed-roster scalar deltas
(with a live capacity report and unrelated sessions), matches full
preparation on rendered values, keeps copy counts at delta scale, and
preserves exact-delta routing, stale-result rejection, failure fallback,
and discarded-generation isolation.
"""

from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import replace

import pytest

from sase.ace.tui.actions.agents._loading_compute import (
    attach_finalize_plan_to_boundary,
    make_finalize_stale_token,
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.actions.agents._loading_delta_scaled import (
    try_scoped_worker_boundary,
)
from sase.ace.tui.actions.agents._loading_graph import share_back_boundary_fast
from sase.ace.tui.models.agent import Agent
from sase.config.runner_limit_override import EffectiveRunnerLimitSnapshot
from sase.core.runner_slots import MachineCapacityReport
from tests._agents_tab_delta_copy_fast_path_support import annotated_snapshot
from tests._agents_tab_graph_isolation_helpers import row_observation
from tests._agents_tab_query_helpers import make_agent
from tests._agents_tab_realistic_roster import (
    realistic_roster,
    scalar_deltas,
)


def _presentation(agent: Agent) -> dict[str, object]:
    observed = row_observation(agent)
    observed.update(
        {
            "waiting_for": tuple(agent.waiting_for or ()),
            "queue_position": agent.runner_slot_queue_position,
            "slots_in_use": agent.runner_slots_in_use,
            "agent_clan": agent.agent_clan,
            "clan_generation": agent.agent_clan_generation,
            "is_clan_container": agent.is_clan_container,
            "runner_is_live": agent.runner_is_live,
        }
    )
    return observed


def _roster_view(boundary) -> dict[object, dict[str, object]]:
    rows = boundary.prep.filtered_agents
    assert rows
    return {agent.identity: _presentation(agent) for agent in rows}


def _identity_order(boundary) -> list[object]:
    return [agent.identity for agent in boundary.prep.filtered_agents]


def _capacity_report() -> MachineCapacityReport:
    now = time.time()
    raw = {
        "occupied_capacity": 8.0,
        "occupied_lanes": 10,
        "effective_limit": 16.0,
        "claims": [],
        "waiters": [],
        "accounting": [],
        "accounting_valid": True,
    }
    return MachineCapacityReport(
        machine="athena",
        computed_at=now,
        scanned_at=now,
        token="capacity-token-mixed",
        scan_current=True,
        effective_limit=16.0,
        limit=EffectiveRunnerLimitSnapshot(
            configured_limit=16,
            temporary_override=None,
            captured_at=now,
        ),
        occupied_capacity=8.0,
        occupied_lanes=10,
        over_limit=False,
        claims=(),
        waiters=(),
        accounting=(),
        diagnostics=(),
        accounting_valid=True,
        accounting_available=True,
        raw_snapshot=raw,
        record_inputs=(),
    )


def _mixed_snapshot(live: list[Agent], *, query_matches: bool = True):
    from sase.ace.tui.models._agent_tree import project_clan_tree

    # Production live graphs are already tree-projected from the previous
    # apply. Project in place so scoped preparation keeps that order and
    # clan containers match the full path's idempotent re-projection.
    live[:] = project_clan_tree(live)
    snapshot = annotated_snapshot(live, cache_query_matches=query_matches)
    return replace(
        snapshot,
        capacity_report=_capacity_report(),
        unread_agent_ids=frozenset({live[0].identity}),
        agent_search_query="",
        agent_tabs_view_config=snapshot.agent_tabs_view_config,
    )


def test_scoped_path_hits_mixed_roster_with_capacity_report() -> None:
    live = realistic_roster()
    incoming = scalar_deltas(live, 1)
    snapshot = _mixed_snapshot(live)
    before = [_presentation(agent) for agent in live]
    boundary = try_scoped_worker_boundary(incoming, [], set(), False, snapshot)
    assert boundary is not None
    assert _presentation(live[0]) == before[0]
    published = boundary.prep.filtered_agents
    assert len(published) == len(live)
    changed = next(
        agent for agent in published if agent.identity == incoming[0].identity
    )
    assert changed.status == "PLAN DONE"
    assert changed is not incoming[0]
    live_member = next(
        agent for agent in live if agent.identity == incoming[0].identity
    )
    assert changed is not live_member
    unrelated = next(agent for agent in live if agent.cl_name == "fam-11-code")
    published_unrelated = next(
        agent for agent in published if agent.identity == unrelated.identity
    )
    assert published_unrelated is unrelated


@pytest.mark.parametrize("count", [1, 6, 8])
def test_scoped_and_full_prep_match_on_realistic_deltas(count: int) -> None:
    live = realistic_roster()
    fast_snapshot = _mixed_snapshot(live)
    fallback_snapshot = _mixed_snapshot(live, query_matches=False)
    before = [_presentation(agent) for agent in live]

    started = time.perf_counter()
    fast_boundary = prepare_loaded_agents_worker_boundary(
        scalar_deltas(live, count), [], set(), False, fast_snapshot
    )
    fast_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    fallback_boundary = prepare_loaded_agents_worker_boundary(
        scalar_deltas(live, count), [], set(), False, fallback_snapshot
    )
    full_ms = (time.perf_counter() - started) * 1000

    assert [_presentation(agent) for agent in live] == before
    assert (
        try_scoped_worker_boundary(
            scalar_deltas(live, count), [], set(), False, fast_snapshot
        )
        is not None
    )
    assert (
        try_scoped_worker_boundary(
            scalar_deltas(live, count), [], set(), False, fallback_snapshot
        )
        is None
    )

    # Scoped prep keeps the already-projected live order; the full path
    # re-merges and may regroup from fixture order. Production live graphs
    # are previous-apply output, so the scoped contract is preserve-live.
    assert _identity_order(fast_boundary) == [agent.identity for agent in live]
    fast_view = _roster_view(fast_boundary)
    fallback_view = _roster_view(fallback_boundary)
    assert set(fast_view) == set(fallback_view)
    for identity in fast_view:
        assert fast_view[identity] == fallback_view[identity]

    assert fast_boundary.fold.visible_agents
    assert {agent.identity for agent in fast_boundary.fold.visible_agents} == {
        agent.identity for agent in fallback_boundary.fold.visible_agents
    }
    print(
        f"delta-integration equivalence: n={len(live)} delta={count} "
        f"scoped={fast_ms:.1f}ms full={full_ms:.1f}ms"
    )


def test_copy_counts_stay_bounded_as_roster_grows() -> None:
    small = realistic_roster(ordinary_count=400)
    large = realistic_roster(ordinary_count=880)
    small_snapshot = _mixed_snapshot(small)
    large_snapshot = _mixed_snapshot(large)
    small_boundary = prepare_loaded_agents_worker_boundary(
        scalar_deltas(small, 6), [], set(), False, small_snapshot
    )
    large_boundary = prepare_loaded_agents_worker_boundary(
        scalar_deltas(large, 6), [], set(), False, large_snapshot
    )
    small_ids = {id(agent) for agent in small}
    large_ids = {id(agent) for agent in large}
    small_new = sum(
        1 for agent in small_boundary.prep.filtered_agents if id(agent) not in small_ids
    )
    large_new = sum(
        1 for agent in large_boundary.prep.filtered_agents if id(agent) not in large_ids
    )
    assert small_new == large_new
    assert small_new <= 80
    print(
        f"delta-integration copies: n=400 copied={small_new}; "
        f"n={len(large)} copied={large_new}"
    )


@pytest.mark.parametrize("count", [1, 6, 8])
def test_scoped_prep_is_materially_cheaper(count: int) -> None:
    live = realistic_roster()
    fast_snapshot = _mixed_snapshot(live)
    fallback_snapshot = _mixed_snapshot(live, query_matches=False)
    incoming = scalar_deltas(live, count)
    prepare_loaded_agents_worker_boundary(
        scalar_deltas(live, count), [], set(), False, fast_snapshot
    )
    prepare_loaded_agents_worker_boundary(
        scalar_deltas(live, count), [], set(), False, fallback_snapshot
    )
    started = time.perf_counter()
    prepare_loaded_agents_worker_boundary(
        scalar_deltas(live, count), [], set(), False, fast_snapshot
    )
    scoped_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    prepare_loaded_agents_worker_boundary(incoming, [], set(), False, fallback_snapshot)
    full_ms = (time.perf_counter() - started) * 1000
    print(
        f"delta-integration cost: n={len(live)} delta={count} "
        f"scoped={scoped_ms:.1f}ms full={full_ms:.1f}ms"
    )
    assert scoped_ms < full_ms * 0.85 or scoped_ms < 80.0


def test_unrelated_live_rows_are_mutation_sentinels() -> None:
    live = realistic_roster()
    incoming = scalar_deltas(live, 8)
    snapshot = _mixed_snapshot(live)
    sentinel = next(agent for agent in live if agent.cl_name == "ordinary-0100")
    before_sentinel = _presentation(sentinel)
    before_changed = _presentation(
        next(agent for agent in live if agent.identity == incoming[0].identity)
    )
    boundary = prepare_loaded_agents_worker_boundary(
        incoming, [], set(), False, snapshot
    )
    assert any(agent is sentinel for agent in boundary.prep.filtered_agents)
    assert _presentation(sentinel) == before_sentinel
    live_changed = next(
        agent for agent in live if agent.identity == incoming[0].identity
    )
    assert _presentation(live_changed) == before_changed
    published_changed = next(
        agent
        for agent in boundary.prep.filtered_agents
        if agent.identity == incoming[0].identity
    )
    published_changed.waiting_for.append("worker-sentinel")
    assert "worker-sentinel" not in live_changed.waiting_for


def test_relationship_change_falls_back_to_full_path() -> None:
    live = realistic_roster()
    incoming = scalar_deltas(live, 1)
    incoming[0].parent_timestamp = "20260918070000"
    snapshot = _mixed_snapshot(live)
    assert try_scoped_worker_boundary(incoming, [], set(), False, snapshot) is None
    boundary = prepare_loaded_agents_worker_boundary(
        incoming, [], set(), False, snapshot
    )
    assert boundary.prep.filtered_agents


def test_query_mismatch_and_removals_fall_back() -> None:
    live = realistic_roster()
    incoming = scalar_deltas(live, 1)
    mismatch = _mixed_snapshot(live, query_matches=False)
    assert try_scoped_worker_boundary(incoming, [], set(), False, mismatch) is None
    snapshot = _mixed_snapshot(live)
    snapshot = replace(snapshot, dismissed_agents={live[0].identity})
    empty = try_scoped_worker_boundary([], [], set(), False, snapshot)
    assert empty is None


def test_second_delta_does_not_see_first_worker_mutation() -> None:
    live = realistic_roster()
    first = scalar_deltas(live, 1)
    snapshot = _mixed_snapshot(live)
    first_boundary = prepare_loaded_agents_worker_boundary(
        first, [], set(), False, snapshot
    )
    live_member = next(agent for agent in live if agent.identity == first[0].identity)
    assert live_member.status != "DONE"
    second_incoming = [deepcopy(live_member)]
    second_incoming[0].status = "FAILED"
    second_boundary = prepare_loaded_agents_worker_boundary(
        second_incoming, [], set(), False, snapshot
    )
    first_pub = next(
        agent
        for agent in first_boundary.prep.filtered_agents
        if agent.identity == first[0].identity
    )
    second_pub = next(
        agent
        for agent in second_boundary.prep.filtered_agents
        if agent.identity == first[0].identity
    )
    assert first_pub.status == "PLAN DONE"
    assert second_pub.status == "FAILED"
    assert live_member.status != "DONE"
    assert live_member.status != "FAILED"


def test_stale_finalize_token_discards_scoped_plan() -> None:
    live = realistic_roster()
    snapshot = _mixed_snapshot(live)
    boundary = prepare_loaded_agents_worker_boundary(
        scalar_deltas(live, 1), [], set(), False, snapshot
    )
    planned = attach_finalize_plan_to_boundary(boundary, snapshot, content_index=None)
    assert planned.finalize is not None
    drifted = replace(snapshot, agent_search_query="status:running")
    assert make_finalize_stale_token(drifted) != planned.finalize.stale_token


def test_scoped_exception_falls_back_to_full_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = realistic_roster()
    snapshot = _mixed_snapshot(live)

    def boom(*_args, **_kwargs):
        raise RuntimeError("scoped path exploded")

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._loading_delta_scaled.try_scoped_worker_boundary",
        boom,
    )
    boundary = prepare_loaded_agents_worker_boundary(
        scalar_deltas(live, 1), [], set(), False, snapshot
    )
    assert boundary.prep.filtered_agents
    changed = next(
        agent
        for agent in boundary.prep.filtered_agents
        if agent.cl_name == "fam-00-code"
    )
    assert changed.status == "PLAN DONE"


def test_share_back_keeps_unrelated_live_identity() -> None:
    live = realistic_roster()
    snapshot = _mixed_snapshot(live)
    boundary = prepare_loaded_agents_worker_boundary(
        scalar_deltas(live, 1), [], set(), False, snapshot
    )
    shared = share_back_boundary_fast(boundary, snapshot)
    live_ids = {id(agent) for agent in live}
    published = shared.fold.unfiltered_agents
    shared_live = sum(1 for agent in published if id(agent) in live_ids)
    assert shared_live >= len(live) - 80
    unrelated = next(agent for agent in live if agent.cl_name == "ordinary-0200")
    assert any(agent is unrelated for agent in published)


def test_new_identity_is_a_membership_fallback() -> None:
    live = realistic_roster()
    snapshot = _mixed_snapshot(live)
    stranger = make_agent(
        cl_name="brand-new",
        raw_suffix="20260918999990",
        status="RUNNING",
        project_file="/tmp/projects/synthetic/synthetic.sase",
    )
    assert try_scoped_worker_boundary([stranger], [], set(), False, snapshot) is None
