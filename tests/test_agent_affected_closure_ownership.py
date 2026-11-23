"""Bounded affected-graph ownership for realistic agent delta graphs.

Covers the delta-ownership phase: a representative ~1,000-row roster
(session containers with weak backreferences, workflow children, clan
generations, running and queued members, capacity aliases, ordinary
current-view settings), the bounded affected-closure primitive with explicit
fallback reasons, mutation isolation of affected copies, within-result alias
correctness, discarded-generation safety, read-only out-of-closure
references, and equivalence of scoped versus full preparation on 1-, 6-, and
8-row scalar deltas with before/after work counts and elapsed cost.

The expanded production fast path stays disabled: nothing here wires the new
shapes into ``prepare_loaded_agents_worker_boundary``. That wiring belongs
to the delta-integration phase, which also consumes the new public symbols
(kept alive through its epic-symbol rows until it lands).
"""

from __future__ import annotations

import time
from copy import deepcopy
from datetime import datetime

import pytest

from sase.ace.tui.actions.agents._loading_compute import (
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.actions.agents._loading_compute_merge import (
    EXACT_DELTA_RELATIONSHIP_KEYS,
)
from sase.ace.tui.actions.agents._loading_graph import share_back_boundary_fast
from sase.ace.tui.models._agent_graph import (
    _AFFECTED_RELATIONSHIP_KEYS,
    AGENT_RELINK_FIELDS,
    AffectedClosure,
    compute_affected_closure,
    own_affected_delta_rows,
)
from sase.ace.tui.models.agent import Agent
from tests._agents_tab_delta_copy_fast_path_support import (
    agent_state,
    annotated_snapshot,
)
from tests._agents_tab_graph_isolation_helpers import row_observation
from tests._agents_tab_query_helpers import make_agent
from tests._agents_tab_realistic_roster import (
    ordinary_counts,
    realistic_roster,
    scalar_deltas,
)


def _live_states(live: list[Agent]) -> dict[object, object]:
    return {agent.identity: agent_state(agent) for agent in live}


def test_relationship_keys_match_merge_boundary() -> None:
    assert tuple(_AFFECTED_RELATIONSHIP_KEYS) == tuple(EXACT_DELTA_RELATIONSHIP_KEYS)


def test_realistic_fixture_shape() -> None:
    live = realistic_roster()
    counts = ordinary_counts(live)
    assert counts["total"] >= 1000
    assert counts["ordinary"] == 880
    assert counts["session_rows"] >= 48
    assert counts["workflow_steps"] == 12
    assert counts["clan_containers"] == 6
    assert counts["clan_rows"] == 6 + 3 * 2 * 12
    assert counts["running"] >= 24
    # Twelve standalone queued rows plus the queued waiter in family 0.
    assert counts["queued"] == 13
    assert counts["remote_alias"] >= 1
    assert all(
        agent.project_file.startswith("/tmp/projects/synthetic/") for agent in live
    )
    assert all(agent.prompt_step_file_name is None for agent in live)

    containers = [agent for agent in live if agent.is_clan_container]
    assert containers
    for container in containers:
        assert container.runtime_children
        assert all(
            child.agent_clan == container.agent_clan
            for child in container.runtime_children
        )

    members = [agent for agent in live if agent.agent_session_container is not None]
    assert len(members) >= 36
    for member in members:
        container = member.agent_session_container
        assert container is not None
        assert container.agent_session == member.agent_session
        assert any(sibling is member for sibling in container.runtime_children)

    steps = [agent for agent in live if agent.parent_workflow]
    assert steps
    assert all(agent.step_index is not None for agent in steps)


@pytest.mark.parametrize("count", [1, 6, 8])
def test_closure_bounded_for_scalar_deltas(count: int) -> None:
    live = realistic_roster()
    incoming = scalar_deltas(live, count)
    started = time.perf_counter()
    closure = compute_affected_closure(live, incoming)
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert isinstance(closure, AffectedClosure)
    assert closure.eligible
    assert closure.reason == "bounded"
    assert closure.seeds == count
    assert closure.cached_size == len(live)
    assert closure.closure_size <= 6 * count + 8
    print(
        f"affected closure: n={len(live)} delta={count} "
        f"seeds={closure.seeds} closure={closure.closure_size} "
        f"elapsed={elapsed_ms:.2f}ms"
    )


def test_closure_copy_counts_bounded_as_roster_grows() -> None:
    small = realistic_roster(ordinary_count=400)
    large = realistic_roster(ordinary_count=880)
    incoming_small = scalar_deltas(small, 6)
    incoming_large = scalar_deltas(large, 6)
    closure_small = compute_affected_closure(small, incoming_small)
    closure_large = compute_affected_closure(large, incoming_large)
    assert closure_small.eligible and closure_large.eligible
    assert closure_small.closure_size == closure_large.closure_size
    started = time.perf_counter()
    owned_small, _ = own_affected_delta_rows(small, closure_small)
    small_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    owned_large, _ = own_affected_delta_rows(large, closure_large)
    large_ms = (time.perf_counter() - started) * 1000
    copied_small = sum(1 for a, b in zip(small, owned_small, strict=True) if a is not b)
    copied_large = sum(1 for a, b in zip(large, owned_large, strict=True) if a is not b)
    assert copied_small == closure_small.closure_size == copied_large
    print(
        f"affected ownership scales with delta, not roster: "
        f"n=400 copied={copied_small} {small_ms:.2f}ms; "
        f"n={len(large)} copied={copied_large} {large_ms:.2f}ms"
    )


def test_affected_copies_isolate_live_graph() -> None:
    live = realistic_roster()
    incoming = scalar_deltas(live, 8)
    closure = compute_affected_closure(live, incoming)
    before = _live_states(live)
    owned, memo = own_affected_delta_rows(live, closure)
    assert len(owned) == len(live)
    assert len(memo) == closure.closure_size

    for agent in owned:
        if agent.identity not in closure.affected_identities:
            continue
        agent.followup_agents.append(agent)
        agent.runtime_children.clear()
        agent.retry_chain_siblings.clear()
        agent.plan_times.append(datetime(2026, 9, 18, 12, 0, 0))
        agent.waiting_for.append("mutation-sentinel")
        agent.step_output = dict(agent.step_output or {})
        agent.step_output.update({"ownership_test": "value"})
        agent.status = "CHANGED-BY-WORKER"

    assert _live_states(live) == before
    assert all("mutation-sentinel" not in agent.waiting_for for agent in live)


def test_within_result_aliases_stay_correct() -> None:
    live = realistic_roster()
    incoming = scalar_deltas(live, 1)
    closure = compute_affected_closure(live, incoming)
    owned, _ = own_affected_delta_rows(live, closure)
    by_identity = {agent.identity: agent for agent in owned}

    changed = incoming[0]
    assert changed.agent_session_role == "code"
    copied_member = by_identity[changed.identity]
    live_member = next(agent for agent in live if agent.identity == changed.identity)
    container = copied_member.agent_session_container
    assert container is not None
    assert container is not live_member.agent_session_container
    assert container is by_identity[container.identity]
    assert any(sibling is copied_member for sibling in container.runtime_children)
    live_root = live_member.agent_session_container
    assert live_root is not None
    copied_root = by_identity[live_root.identity]
    assert copied_root.runtime_children
    assert copied_member in copied_root.runtime_children
    assert copied_root.retry_chain_siblings == [copied_member]
    assert copied_member.followup_agents == []


def test_out_of_closure_references_stay_read_only() -> None:
    live = realistic_roster()
    incoming = scalar_deltas(live, 6)
    closure = compute_affected_closure(live, incoming)
    owned, _ = own_affected_delta_rows(live, closure)
    live_by_identity = {agent.identity: agent for agent in live}
    by_identity = {agent.identity: agent for agent in owned}

    for agent in owned:
        if agent.identity not in closure.affected_identities:
            continue
        for name in AGENT_RELINK_FIELDS:
            value = getattr(agent, name)
            refs = (
                [value]
                if isinstance(value, Agent)
                else [item for item in value if isinstance(item, Agent)]
                if isinstance(value, list)
                else []
            )
            for ref in refs:
                if ref.identity in closure.affected_identities:
                    assert ref is by_identity[ref.identity]
                else:
                    assert ref is live_by_identity[ref.identity]

    before_containers = {
        agent.identity: [list(agent.followup_agents), list(agent.runtime_children)]
        for agent in live
    }
    for agent in owned:
        if agent.identity not in closure.affected_identities:
            continue
        if isinstance(agent.followup_agents, list):
            agent.followup_agents.append(agent)
        if isinstance(agent.retry_chain_siblings, list):
            agent.retry_chain_siblings.clear()
    for agent in live:
        assert [list(agent.followup_agents), list(agent.runtime_children)] == (
            before_containers[agent.identity]
        )


def test_discarded_generation_leaves_ui_graph_unchanged() -> None:
    live = realistic_roster()
    incoming = scalar_deltas(live, 6)
    closure = compute_affected_closure(live, incoming)
    before = _live_states(live)
    before_ids = [id(agent) for agent in live]
    owned, _ = own_affected_delta_rows(live, closure)
    assert any(a is not b for a, b in zip(live, owned, strict=True))
    del owned
    assert [id(agent) for agent in live] == before_ids
    assert _live_states(live) == before
    for agent in live:
        container = agent.agent_session_container
        if container is not None:
            assert any(sibling is agent for sibling in container.runtime_children)


def test_closure_fallback_reasons() -> None:
    live = realistic_roster()
    incoming = scalar_deltas(live, 8)

    assert compute_affected_closure([], incoming).reason == "empty-cache"

    oversized = compute_affected_closure(live, incoming, max_closure_size=1)
    assert not oversized.eligible
    assert oversized.reason == "oversized-closure"

    reparented = deepcopy(incoming[0])
    reparented.parent_timestamp = "20260918070000"
    structural = compute_affected_closure(live, [reparented])
    assert not structural.eligible
    assert structural.reason == "relationship-change"

    stranger = make_agent(
        cl_name="stranger",
        raw_suffix="20260918999999",
        status="RUNNING",
        agent_session="no-such-session",
        project_file="/tmp/projects/synthetic/synthetic.sase",
    )
    unanchored = compute_affected_closure(live, [stranger])
    assert not unanchored.eligible
    assert unanchored.reason == "unanchored-new-row"

    for bad in (oversized, structural, unanchored):
        with pytest.raises(ValueError, match="not bounded"):
            own_affected_delta_rows(live, bad)


@pytest.mark.parametrize("count", [1, 6, 8])
def test_scalar_delta_equivalence_full_vs_scoped(count: int) -> None:
    live = realistic_roster()
    fast_snapshot = annotated_snapshot(live)
    fallback_snapshot = annotated_snapshot(live, cache_query_matches=False)
    closure = compute_affected_closure(live, scalar_deltas(live, count))
    assert closure.eligible
    before = _live_states(live)

    fast_boundary = prepare_loaded_agents_worker_boundary(
        scalar_deltas(live, count), [], set(), False, fast_snapshot
    )
    fallback_boundary = prepare_loaded_agents_worker_boundary(
        scalar_deltas(live, count), [], set(), False, fallback_snapshot
    )
    assert _live_states(live) == before

    def observed(boundary) -> dict[object, object]:
        rows = boundary.prep.filtered_agents
        assert rows
        return {agent.identity: row_observation(agent) for agent in rows}

    fast_rows = observed(fast_boundary)
    fallback_rows = observed(fallback_boundary)
    assert set(fast_rows) == set(fallback_rows)
    for identity in fast_rows:
        assert fast_rows[identity] == fallback_rows[identity]

    shared = share_back_boundary_fast(fast_boundary, fast_snapshot)
    published = shared.fold.unfiltered_agents  # type: ignore[union-attr]
    live_ids = {id(agent) for agent in live}
    retained_new = sum(1 for agent in published if id(agent) not in live_ids)
    assert retained_new <= closure.closure_size + 8
    print(
        f"equivalence: n={len(live)} delta={count} "
        f"closure={closure.closure_size} retained_new={retained_new}"
    )


@pytest.mark.parametrize("count", [1, 6, 8])
def test_closure_covers_merge_write_set(count: int) -> None:
    live = realistic_roster()
    incoming = scalar_deltas(live, count)
    closure = compute_affected_closure(live, incoming)
    assert closure.eligible
    snapshot = annotated_snapshot(live)
    before_obs = {agent.identity: row_observation(agent) for agent in live}
    boundary = prepare_loaded_agents_worker_boundary(
        incoming, [], set(), False, snapshot
    )
    changed = {
        agent.identity
        for agent in boundary.prep.filtered_agents
        if row_observation(agent) != before_obs.get(agent.identity)
    }
    changed |= {agent.identity for agent in incoming}
    uncovered = changed - closure.affected_identities
    assert not uncovered, f"merge rewrote rows outside the closure: {uncovered}"
