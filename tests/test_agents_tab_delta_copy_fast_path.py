"""Conservative exact-delta copy-on-write preparation path tests.

Covers the delta-copy phase: a fast ownership path that isolates cached
rows with shallow copies, runs the full merge/slot/tree pipeline without
mutating live rows, then shares back untouched presentation rows by
fingerprint. Full loads and bounded-history semantics fall back to the
existing deep-detach safe path with an explicit trace reason.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

import pytest

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplySnapshot,
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.actions.agents._loading_graph import (
    classify_exact_delta_fast_path,
    share_back_boundary_fast,
)
from sase.ace.tui.models._agent_graph import (
    agent_share_fingerprint,
    copy_agent_rows_delta_isolated,
)
from sase.ace.tui.models.agent import Agent, AgentType
from tests._agents_tab_graph_isolation_helpers import (
    agent_session_graph,
    clan_graph,
    delta_load_state,
    row_observation,
    unrelated_delta,
)
from tests._agents_tab_incomplete_merge_helpers import incomplete_tier1_snapshot
from tests._agents_tab_query_helpers import make_agent


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


def _annotated_snapshot(
    live: list[Agent],
    *,
    cache_query_matches: bool = True,
) -> PreparedApplySnapshot:
    """Annotate *live* with slot context and wrap it in a delta snapshot.

    Production live rows carry runner-slot/capacity fields from prior loads;
    fixtures built via ``make_agent`` do not. Annotating with the same
    ``refresh_runner_slot_context`` entry point the worker uses keeps
    fingerprints comparable so share-back can prove identity for untouched
    rows. The capacity roster mirrors the visible roster, as the app does.
    """
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


def _replace_status(agent: Agent, status: str) -> Agent:
    clone = deepcopy(agent)
    clone.status = status
    return clone


def _counting_deep_copy_spy(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
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


def test_fast_path_eligible_for_artifact_delta_patch() -> None:
    live = _hundred_row_cache()
    snapshot = incomplete_tier1_snapshot(live, load_state=delta_load_state())
    decision = classify_exact_delta_fast_path(snapshot)
    assert decision.eligible
    assert decision.reason == "exact-delta"


def test_fast_path_fallback_reasons() -> None:
    from sase.ace.tui.models.agent_loader import AgentLoadState

    live = _hundred_row_cache()
    authoritative = incomplete_tier1_snapshot(
        live,
        load_state=AgentLoadState(
            tier="tier2",
            complete_history=True,
            artifact_source="source_scan",
            used_artifact_index=False,
        ),
    )
    assert classify_exact_delta_fast_path(authoritative).reason == (
        "authoritative-complete"
    )
    bounded = incomplete_tier1_snapshot(
        live,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
            bounded_prefix=True,
            requested_limit=10,
            returned_count=10,
            has_more=True,
        ),
    )
    assert classify_exact_delta_fast_path(bounded).reason == "not-artifact-delta"
    repair = incomplete_tier1_snapshot(
        live,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_delta",
            used_artifact_index=False,
            repair_recommended=True,
            repair_reason="artifact_delta_scan_incomplete",
        ),
    )
    assert classify_exact_delta_fast_path(repair).reason == "repair-recommended"
    mismatch = incomplete_tier1_snapshot(
        live,
        load_state=delta_load_state(),
        cache_query_matches=False,
    )
    assert classify_exact_delta_fast_path(mismatch).reason == "query-mismatch"


def test_scalar_vs_relationship_keys_documented() -> None:
    from sase.ace.tui.actions.agents._loading_compute_merge import (
        EXACT_DELTA_RELATIONSHIP_KEYS,
    )

    # Scalar updates keep every relationship key equal; reparenting does not.
    cached = make_agent(cl_name="row", raw_suffix="20260918090000", status="RUNNING")
    scalar = _replace_status(cached, "DONE")
    assert all(
        getattr(cached, key) == getattr(scalar, key)
        for key in EXACT_DELTA_RELATIONSHIP_KEYS
    )
    reparented = deepcopy(cached)
    reparented.parent_timestamp = "20260918080000"
    assert any(
        getattr(cached, key) != getattr(reparented, key)
        for key in EXACT_DELTA_RELATIONSHIP_KEYS
    )
    assert "parent_timestamp" in EXACT_DELTA_RELATIONSHIP_KEYS


def test_delta_isolated_copy_detaches_mutable_containers() -> None:
    live = clan_graph()
    before_fingerprints = [agent_share_fingerprint(agent) for agent in live]
    copies = copy_agent_rows_delta_isolated(live)
    assert all(
        copy is not original for copy, original in zip(copies, live, strict=True)
    )
    # Mutating the copy's in-place containers must not touch the live row.
    copies[0].followup_agents.append(copies[1])
    copies[0].runtime_children.clear()
    copies[0].plan_times.append(datetime(2026, 9, 18, 12, 0, 0))
    copies[0].step_output = dict(copies[0].step_output or {})
    copies[0].step_output.update({"meta_test": "value"})
    assert [agent_share_fingerprint(agent) for agent in live] == before_fingerprints


def test_scalar_delta_equivalence_fast_vs_fallback() -> None:
    live = _hundred_row_cache()
    before = [row_observation(agent) for agent in live]
    target = live[5]
    incoming = _replace_status(target, "FAILED")
    fast_snapshot = _annotated_snapshot(live)
    fallback_snapshot = _annotated_snapshot(live, cache_query_matches=False)
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
        assert agent_share_fingerprint(fast_rows[identity]) == agent_share_fingerprint(
            fallback_rows[identity]
        )


def test_terminal_transition_shares_unrelated_rows() -> None:
    live = _hundred_row_cache()
    snapshot = _annotated_snapshot(live)
    before = [agent_share_fingerprint(agent) for agent in live]
    target = next(agent for agent in live if agent.status == "DONE")
    incoming = _replace_status(target, "FAILED")
    boundary = prepare_loaded_agents_worker_boundary(
        [incoming], [], set(), False, snapshot
    )
    assert [agent_share_fingerprint(agent) for agent in live] == before
    shared = share_back_boundary_fast(boundary, snapshot)
    live_ids = {id(agent) for agent in live}
    published = shared.fold.unfiltered_agents  # type: ignore[union-attr]
    assert len(published) == len(live)
    shared_count = sum(1 for agent in published if id(agent) in live_ids)
    # Only the terminal row plus its derived containers/remirrors stay new.
    assert shared_count >= len(live) - 5
    unrelated = next(agent for agent in live if agent.cl_name == "cached-001")
    assert any(agent is unrelated for agent in published)


def test_unrelated_delta_preserves_live_identity() -> None:
    live = clan_graph()
    snapshot = _annotated_snapshot(live)
    other = unrelated_delta()
    boundary = prepare_loaded_agents_worker_boundary(
        [other], [], set(), False, snapshot
    )
    shared = share_back_boundary_fast(boundary, snapshot)
    published = shared.fold.unfiltered_agents  # type: ignore[union-attr]
    live_by_identity = {agent.identity: agent for agent in live}
    for agent in published:
        if agent.identity in live_by_identity:
            live_agent = live_by_identity[agent.identity]
            if agent_share_fingerprint(agent) == agent_share_fingerprint(live_agent):
                assert agent is live_agent


def test_fast_path_uses_no_deep_copies_for_small_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = _hundred_row_cache()
    counts = _counting_deep_copy_spy(monkeypatch)
    snapshot = _annotated_snapshot(live)
    target = live[10]
    incoming = _replace_status(target, "FAILED")
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


def test_share_back_boundary_shares_unchanged_rows() -> None:
    live = [make_agent(cl_name="a", raw_suffix="20260918090000", status="DONE")]
    snapshot = _annotated_snapshot(live)
    boundary = prepare_loaded_agents_worker_boundary([], [], set(), False, snapshot)
    shared = share_back_boundary_fast(boundary, snapshot)
    published = shared.fold.unfiltered_agents  # type: ignore[union-attr]
    assert any(agent is live[0] for agent in published)


def test_named_proc_fallback_rows_stay_owned() -> None:
    named = [
        make_agent(
            agent_type=AgentType.NAMED_PROC,
            cl_name="proc-1",
            raw_suffix="proc-1",
            status="RUNNING",
        )
    ]
    live = _hundred_row_cache() + named
    from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context
    from sase.config.core import get_max_running_agents

    refresh_runner_slot_context(
        live,
        effective_limit=get_max_running_agents(),
        capacity_agents=list(live),
    )
    snapshot = incomplete_tier1_snapshot(
        live,
        load_state=delta_load_state(),
        capacity_agents_with_children=list(live),
        proc_projection=None,
    )
    boundary = prepare_loaded_agents_worker_boundary(
        [unrelated_delta()], [], set(), False, snapshot
    )
    published_named = [
        agent for agent in boundary.prep.filtered_agents if agent.is_named_proc
    ]
    assert published_named
    assert all(
        id(agent) not in {id(agent) for agent in live} for agent in published_named
    )


def test_exact_delta_deletion_equivalence() -> None:
    from dataclasses import replace as _replace

    live = _hundred_row_cache()
    snapshot = _annotated_snapshot(live)
    removed = live[20]
    snapshot = _replace(snapshot, dismissed_agents={removed.identity})
    live_before = [agent_share_fingerprint(agent) for agent in live]
    boundary = prepare_loaded_agents_worker_boundary([], [], set(), False, snapshot)
    assert removed.identity not in {
        agent.identity for agent in boundary.prep.filtered_agents
    }
    # Worker preparation never mutates the live graph, even for deletions.
    assert [agent_share_fingerprint(agent) for agent in live] == live_before


def test_child_add_remove_equivalence() -> None:
    live = agent_session_graph()
    snapshot = _annotated_snapshot(live)
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


def test_fleet_rows_stay_owned_and_shared() -> None:
    live = _hundred_row_cache()
    fleet_row = make_agent(
        cl_name="fleet-remote",
        raw_suffix="20260918999999",
        status="RUNNING",
    )
    snapshot = _annotated_snapshot(live)
    from dataclasses import replace

    snapshot = replace(snapshot, fleet_rows=(fleet_row,))
    target = live[7]
    incoming = _replace_status(target, "DONE")
    boundary = prepare_loaded_agents_worker_boundary(
        [incoming], [], set(), False, snapshot
    )
    assert boundary.fleet_source_rows == (fleet_row,)
    shared = share_back_boundary_fast(boundary, snapshot)
    assert shared.fold.unfiltered_agents  # type: ignore[union-attr]


def test_incomplete_history_snapshot_falls_back() -> None:
    live = _hundred_row_cache()
    snapshot = incomplete_tier1_snapshot(
        live,
        load_state=delta_load_state(),
        agents_seen_complete_history=False,
    )
    decision = classify_exact_delta_fast_path(snapshot)
    assert not decision.eligible
    assert decision.reason == "no-complete-watermark"
