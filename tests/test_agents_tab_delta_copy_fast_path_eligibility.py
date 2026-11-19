"""Eligibility and isolated-copy semantics for exact-delta preparation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from sase.ace.tui.actions.agents._loading_graph import classify_exact_delta_fast_path
from sase.ace.tui.models._agent_graph import copy_agent_rows_delta_isolated
from tests._agents_tab_graph_isolation_helpers import clan_graph, delta_load_state
from tests._agents_tab_delta_copy_fast_path_support import (
    agent_state,
    hundred_row_cache,
    replace_status,
)
from tests._agents_tab_incomplete_merge_helpers import incomplete_tier1_snapshot
from tests._agents_tab_query_helpers import make_agent


def test_fast_path_eligible_for_artifact_delta_patch() -> None:
    live = hundred_row_cache()
    snapshot = incomplete_tier1_snapshot(live, load_state=delta_load_state())
    decision = classify_exact_delta_fast_path(snapshot)
    assert decision.eligible
    assert decision.reason == "exact-delta"


def test_fast_path_fallback_reasons() -> None:
    from sase.ace.tui.models.agent_loader import AgentLoadState

    live = hundred_row_cache()
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
    scalar = replace_status(cached, "DONE")
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
    before_states = [agent_state(agent) for agent in live]
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
    assert [agent_state(agent) for agent in live] == before_states


def test_incomplete_history_snapshot_falls_back() -> None:
    live = hundred_row_cache()
    snapshot = incomplete_tier1_snapshot(
        live,
        load_state=delta_load_state(),
        agents_seen_complete_history=False,
    )
    decision = classify_exact_delta_fast_path(snapshot)
    assert not decision.eligible
    assert decision.reason == "no-complete-watermark"
