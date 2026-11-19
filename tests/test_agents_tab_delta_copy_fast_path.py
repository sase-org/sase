"""Conservative exact-delta copy-on-write preparation path tests.

Covers the delta-copy phase: a fast ownership path that isolates cached
rows with shallow copies, runs the full merge/slot/tree pipeline without
mutating live rows, then shares back untouched presentation rows by
non-link field comparison and graph closure. Full loads and bounded-history semantics fall back to the
existing deep-detach safe path with an explicit trace reason.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import fields, is_dataclass, replace
from datetime import datetime
import threading

import pytest

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplySnapshot,
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.actions.agents._loading_graph import (
    classify_exact_delta_fast_path,
    share_back_boundary_fast,
)
from sase.ace.tui.actions.agents._loading_compute_types import PreparedApplyBoundary
from sase.ace.tui.models._agent_graph import (
    AGENT_RELINK_FIELDS,
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


def _agent_state(agent: Agent) -> object:
    return tuple(
        (field.name, _state_value(getattr(agent, field.name)))
        for field in fields(agent)
    )


def _boundary_lists(boundary: PreparedApplyBoundary) -> list[list[Agent]]:
    lists = [
        boundary.prep.filtered_agents,
        boundary.prep.hideable_agents,
        boundary.prep.capacity_agents,
        boundary.prep.dismissed_agent_objects,
        boundary.fold.unfiltered_agents,
        boundary.fold.visible_agents,
        boundary.fold.local_unfiltered_agents,
        boundary.fold.local_visible_agents,
    ]
    if boundary.finalize is not None:
        lists.extend(
            (
                boundary.finalize.query.filtered_agents,
                boundary.finalize.agents_query_result,
                boundary.finalize.scoped_agents,
            )
        )
    return lists


def _reachable_rows(rows: list[Agent]) -> dict[int, Agent]:
    found: dict[int, Agent] = {}
    pending = list(rows)
    while pending:
        agent = pending.pop()
        if id(agent) in found:
            continue
        found[id(agent)] = agent
        for name in AGENT_RELINK_FIELDS:
            value = getattr(agent, name)
            if isinstance(value, Agent):
                pending.append(value)
            elif isinstance(value, (list, tuple)):
                pending.extend(item for item in value if isinstance(item, Agent))
    return found


def _assert_boundary_graph_closed(
    boundary: PreparedApplyBoundary,
    snapshot: PreparedApplySnapshot,
) -> None:
    """Assert published aliases point at published rows or stable live rows."""
    lists = _boundary_lists(boundary)
    published = [agent for agents in lists for agent in agents]
    ids_by_identity: dict[object, set[int]] = {}
    for agent in published:
        ids_by_identity.setdefault(agent.identity, set()).add(id(agent))
    published_ids = {id(agent) for agent in published}
    live_ids = {
        id(agent)
        for agent in (
            *snapshot.cached_agents_with_children,
            *snapshot.capacity_agents_with_children,
            *snapshot.fleet_rows,
        )
    }
    for agent in published:
        for name in AGENT_RELINK_FIELDS:
            value = getattr(agent, name)
            refs = (
                [value]
                if isinstance(value, Agent)
                else [item for item in value if isinstance(item, Agent)]
                if isinstance(value, (list, tuple))
                else []
            )
            for ref in refs:
                if ref.identity in ids_by_identity:
                    assert id(ref) in ids_by_identity[ref.identity], (
                        f"{name} on {agent.identity!r} does not point at the "
                        "published row"
                    )
                else:
                    assert id(ref) in published_ids | live_ids, (
                        f"{name} on {agent.identity!r} points at an orphan row"
                    )


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
    ``refresh_runner_slot_context`` entry point the worker uses keeps copied
    rows comparable so share-back can prove identity for untouched rows. The
    capacity roster mirrors the visible roster, as the app does.
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


def _clan_fixture(member_count: int) -> list[Agent]:
    members = [
        make_agent(
            cl_name=f"clan-member-{index}",
            raw_suffix=f"2026091809{index:02d}00",
            status="RUNNING" if index < 2 else "DONE",
            llm_provider="codex" if index % 2 else "claude",
            agent_clan="share-back-clan",
            agent_clan_generation="g1",
            tribe="share-back",
            start_time=datetime(2026, 9, 18, 9, index, 0),
            run_start_time=datetime(2026, 9, 18, 9, index, 0),
        )
        for index in range(member_count)
    ]
    from tests._agents_tab_graph_isolation_helpers import normalize_agent_graph

    return normalize_agent_graph(members)


def _published_by_identity(boundary: PreparedApplyBoundary) -> dict[object, Agent]:
    result: dict[object, Agent] = {}
    for agents in _boundary_lists(boundary):
        for agent in agents:
            result.setdefault(agent.identity, agent)
    return result


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
    before_states = [_agent_state(agent) for agent in live]
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
    assert [_agent_state(agent) for agent in live] == before_states


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
        assert _agent_state(fast_rows[identity]) == _agent_state(
            fallback_rows[identity]
        )


def test_terminal_transition_shares_unrelated_rows() -> None:
    live = _hundred_row_cache()
    snapshot = _annotated_snapshot(live)
    before = [_agent_state(agent) for agent in live]
    target = next(agent for agent in live if agent.status == "DONE")
    incoming = _replace_status(target, "FAILED")
    boundary = prepare_loaded_agents_worker_boundary(
        [incoming], [], set(), False, snapshot
    )
    assert [_agent_state(agent) for agent in live] == before
    shared = share_back_boundary_fast(boundary, snapshot)
    live_ids = {id(agent) for agent in live}
    published = shared.fold.unfiltered_agents  # type: ignore[union-attr]
    assert len(published) == len(live)
    shared_count = sum(1 for agent in published if id(agent) in live_ids)
    # Only the terminal row plus its derived containers/remirrors stay new.
    assert shared_count >= len(live) - 5
    unrelated = next(agent for agent in live if agent.cl_name == "cached-001")
    assert any(agent is unrelated for agent in published)


@pytest.mark.parametrize("member_count", [2, 4])
@pytest.mark.parametrize(
    ("change", "value"),
    [("scalar", "openai"), ("status", "WAITING"), ("terminal", "FAILED")],
)
def test_clan_share_back_is_alias_closed(
    member_count: int,
    change: str,
    value: str,
) -> None:
    live = _clan_fixture(member_count)
    snapshot = _annotated_snapshot(live)
    before = [_agent_state(agent) for agent in live]
    target = next(agent for agent in live if not agent.is_clan_container)
    incoming = deepcopy(target)
    if change == "scalar":
        incoming.llm_provider = value
    else:
        incoming.status = value

    boundary = prepare_loaded_agents_worker_boundary(
        [incoming], [], set(), False, snapshot
    )
    assert [_agent_state(agent) for agent in live] == before
    shared = share_back_boundary_fast(boundary, snapshot)
    assert [_agent_state(agent) for agent in live] == before
    _assert_boundary_graph_closed(shared, snapshot)
    published_fold = {agent.identity: agent for agent in shared.fold.unfiltered_agents}
    clan_container_row = next(agent for agent in live if agent.is_clan_container)
    assert published_fold[clan_container_row.identity] is not clan_container_row
    assert published_fold[target.identity] is not target


def test_agent_session_child_change_keeps_one_published_graph() -> None:
    live = agent_session_graph()
    snapshot = _annotated_snapshot(live)
    before = [_agent_state(agent) for agent in live]
    child = next(agent for agent in live if agent.agent_session_role == "code")
    incoming = deepcopy(child)
    incoming.llm_provider = "openai"
    boundary = prepare_loaded_agents_worker_boundary(
        [incoming], [], set(), False, snapshot
    )

    shared = share_back_boundary_fast(boundary, snapshot)

    assert [_agent_state(agent) for agent in live] == before
    _assert_boundary_graph_closed(shared, snapshot)


@pytest.mark.parametrize("operation", ["add", "remove", "reparent"])
def test_child_graph_changes_keep_one_published_graph(operation: str) -> None:
    parent = make_agent(
        cl_name="parent-a",
        raw_suffix="20260918080000",
        status="RUNNING",
    )
    second_parent = make_agent(
        cl_name="parent-b",
        raw_suffix="20260918081000",
        status="RUNNING",
    )
    child = make_agent(
        cl_name="child",
        raw_suffix="20260918082000",
        status="RUNNING",
        parent_timestamp=parent.raw_suffix,
    )
    from tests._agents_tab_graph_isolation_helpers import normalize_agent_graph

    live = normalize_agent_graph([parent, second_parent, child])
    snapshot = _annotated_snapshot(live)
    incoming: list[Agent] = []
    if operation == "add":
        incoming = [
            make_agent(
                cl_name="added-child",
                raw_suffix="20260918083000",
                status="RUNNING",
                parent_timestamp=parent.raw_suffix,
            )
        ]
    elif operation == "remove":
        snapshot = replace(snapshot, dismissed_agents={child.identity})
    else:
        moved_child = deepcopy(child)
        moved_child.parent_timestamp = second_parent.raw_suffix
        incoming = [moved_child]
    boundary = prepare_loaded_agents_worker_boundary(
        incoming, [], set(), False, snapshot
    )

    shared = share_back_boundary_fast(boundary, snapshot)

    _assert_boundary_graph_closed(shared, snapshot)


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
            if _agent_state(agent) == _agent_state(live_agent):
                assert agent is live_agent


def test_unchanged_referrer_does_not_keep_a_stale_live_reference() -> None:
    referrer = make_agent(
        cl_name="referrer",
        raw_suffix="20260918110000",
        status="RUNNING",
    )
    referenced = make_agent(
        cl_name="referenced",
        raw_suffix="20260918110100",
        status="RUNNING",
    )
    referrer.status_display_source = referenced
    live = [referrer, referenced]
    snapshot = _annotated_snapshot(live)
    boundary = prepare_loaded_agents_worker_boundary([], [], set(), False, snapshot)
    worked = {agent.identity: agent for agent in boundary.fold.unfiltered_agents}
    worked_referrer = worked[referrer.identity]
    worked_referenced = worked[referenced.identity]
    worked_referrer.status_display_source = worked_referenced
    worked_referenced.status = "FAILED"
    before_referrer = _agent_state(referrer)
    before_referenced = _agent_state(referenced)

    shared = share_back_boundary_fast(boundary, snapshot)

    published = _published_by_identity(shared)
    assert published[referrer.identity] is not referrer
    assert published[referenced.identity] is not referenced
    assert (
        published[referrer.identity].status_display_source
        is published[referenced.identity]
    )
    assert _agent_state(referrer) == before_referrer
    assert _agent_state(referenced) == before_referenced
    _assert_boundary_graph_closed(shared, snapshot)


@pytest.mark.asyncio
async def test_share_back_comparisons_run_once_per_row_on_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.actions.agents import _loading_graph as graph_module
    from sase.ace.tui.actions.agents._loading_disk_delta import (
        _finalize_delta_boundary_worker,
    )

    live = _hundred_row_cache()
    snapshot = _annotated_snapshot(live)
    boundary = prepare_loaded_agents_worker_boundary(
        [unrelated_delta()], [], set(), False, snapshot
    )
    distinct_worked = len(
        graph_module._reachable_boundary_agents(_boundary_lists(boundary))
    )
    comparison_threads: list[int] = []
    compare = graph_module._same_share_back_fields

    def comparison_spy(working: Agent, original: Agent) -> bool:
        comparison_threads.append(threading.get_ident())
        return compare(working, original)

    monkeypatch.setattr(graph_module, "_same_share_back_fields", comparison_spy)
    event_loop_thread = threading.get_ident()
    finalized = await asyncio.to_thread(
        _finalize_delta_boundary_worker,
        boundary,
        snapshot,
        content_index=None,
    )

    assert comparison_threads
    assert all(thread_id != event_loop_thread for thread_id in comparison_threads)
    assert len(comparison_threads) <= distinct_worked
    assert finalized.share_back_seconds >= 0.0
    _assert_boundary_graph_closed(finalized.boundary, snapshot)


def test_share_back_comparison_exception_leaves_live_rows_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.actions.agents import _loading_graph as graph_module

    live = clan_graph()
    snapshot = _annotated_snapshot(live)
    boundary = prepare_loaded_agents_worker_boundary(
        [unrelated_delta()], [], set(), False, snapshot
    )
    before = [_agent_state(agent) for agent in live]

    def fail_comparison(_: Agent, __: Agent) -> bool:
        raise RuntimeError("comparison probe")

    monkeypatch.setattr(graph_module, "_same_share_back_fields", fail_comparison)
    with pytest.raises(RuntimeError, match="comparison probe"):
        share_back_boundary_fast(boundary, snapshot)

    assert [_agent_state(agent) for agent in live] == before


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


def test_named_proc_rows_keep_aliases_consistent() -> None:
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
    shared = share_back_boundary_fast(boundary, snapshot)
    published_named = [
        agent for agent in shared.prep.filtered_agents if agent.is_named_proc
    ]
    assert published_named
    assert len({id(agent) for agent in published_named}) == len(published_named)
    _assert_boundary_graph_closed(shared, snapshot)


def test_exact_delta_deletion_equivalence() -> None:
    from dataclasses import replace as _replace

    live = _hundred_row_cache()
    snapshot = _annotated_snapshot(live)
    removed = live[20]
    snapshot = _replace(snapshot, dismissed_agents={removed.identity})
    live_before = [_agent_state(agent) for agent in live]
    boundary = prepare_loaded_agents_worker_boundary([], [], set(), False, snapshot)
    assert removed.identity not in {
        agent.identity for agent in boundary.prep.filtered_agents
    }
    # Worker preparation never mutates the live graph, even for deletions.
    assert [_agent_state(agent) for agent in live] == live_before


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
    _assert_boundary_graph_closed(shared, snapshot)
    assert all(
        left is right
        for left, right in zip(
            shared.fleet_source_rows, snapshot.fleet_rows, strict=True
        )
    )


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
