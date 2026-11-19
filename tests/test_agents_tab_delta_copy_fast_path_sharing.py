"""Graph closure and identity sharing behavior for exact deltas."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import threading

import pytest

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplySnapshot,
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.actions.agents._loading_compute_types import PreparedApplyBoundary
from sase.ace.tui.actions.agents._loading_graph import share_back_boundary_fast
from sase.ace.tui.models._agent_graph import AGENT_RELINK_FIELDS
from sase.ace.tui.models.agent import Agent, AgentType
from tests._agents_tab_delta_copy_fast_path_support import (
    agent_state,
    annotated_snapshot,
    hundred_row_cache,
    replace_status,
)
from tests._agents_tab_graph_isolation_helpers import (
    agent_session_graph,
    clan_graph,
    delta_load_state,
    unrelated_delta,
)
from tests._agents_tab_incomplete_merge_helpers import incomplete_tier1_snapshot
from tests._agents_tab_query_helpers import make_agent


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


def test_terminal_transition_shares_unrelated_rows() -> None:
    live = hundred_row_cache()
    snapshot = annotated_snapshot(live)
    before = [agent_state(agent) for agent in live]
    target = next(agent for agent in live if agent.status == "DONE")
    incoming = replace_status(target, "FAILED")
    boundary = prepare_loaded_agents_worker_boundary(
        [incoming], [], set(), False, snapshot
    )
    assert [agent_state(agent) for agent in live] == before
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
    snapshot = annotated_snapshot(live)
    before = [agent_state(agent) for agent in live]
    target = next(agent for agent in live if not agent.is_clan_container)
    incoming = deepcopy(target)
    if change == "scalar":
        incoming.llm_provider = value
    else:
        incoming.status = value

    boundary = prepare_loaded_agents_worker_boundary(
        [incoming], [], set(), False, snapshot
    )
    assert [agent_state(agent) for agent in live] == before
    shared = share_back_boundary_fast(boundary, snapshot)
    assert [agent_state(agent) for agent in live] == before
    _assert_boundary_graph_closed(shared, snapshot)
    published_fold = {agent.identity: agent for agent in shared.fold.unfiltered_agents}
    clan_container_row = next(agent for agent in live if agent.is_clan_container)
    assert published_fold[clan_container_row.identity] is not clan_container_row
    assert published_fold[target.identity] is not target


def test_agent_session_child_change_keeps_one_published_graph() -> None:
    live = agent_session_graph()
    snapshot = annotated_snapshot(live)
    before = [agent_state(agent) for agent in live]
    child = next(agent for agent in live if agent.agent_session_role == "code")
    incoming = deepcopy(child)
    incoming.llm_provider = "openai"
    boundary = prepare_loaded_agents_worker_boundary(
        [incoming], [], set(), False, snapshot
    )

    shared = share_back_boundary_fast(boundary, snapshot)

    assert [agent_state(agent) for agent in live] == before
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
    snapshot = annotated_snapshot(live)
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
    snapshot = annotated_snapshot(live)
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
            if agent_state(agent) == agent_state(live_agent):
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
    snapshot = annotated_snapshot(live)
    boundary = prepare_loaded_agents_worker_boundary([], [], set(), False, snapshot)
    worked = {agent.identity: agent for agent in boundary.fold.unfiltered_agents}
    worked_referrer = worked[referrer.identity]
    worked_referenced = worked[referenced.identity]
    worked_referrer.status_display_source = worked_referenced
    worked_referenced.status = "FAILED"
    before_referrer = agent_state(referrer)
    before_referenced = agent_state(referenced)

    shared = share_back_boundary_fast(boundary, snapshot)

    published = _published_by_identity(shared)
    assert published[referrer.identity] is not referrer
    assert published[referenced.identity] is not referenced
    assert (
        published[referrer.identity].status_display_source
        is published[referenced.identity]
    )
    assert agent_state(referrer) == before_referrer
    assert agent_state(referenced) == before_referenced
    _assert_boundary_graph_closed(shared, snapshot)


@pytest.mark.asyncio
async def test_share_back_comparisons_run_once_per_row_on_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.actions.agents import _loading_graph as graph_module
    from sase.ace.tui.actions.agents._loading_disk_delta import (
        _finalize_delta_boundary_worker,
    )

    live = hundred_row_cache()
    snapshot = annotated_snapshot(live)
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
    snapshot = annotated_snapshot(live)
    boundary = prepare_loaded_agents_worker_boundary(
        [unrelated_delta()], [], set(), False, snapshot
    )
    before = [agent_state(agent) for agent in live]

    def fail_comparison(_: Agent, __: Agent) -> bool:
        raise RuntimeError("comparison probe")

    monkeypatch.setattr(graph_module, "_same_share_back_fields", fail_comparison)
    with pytest.raises(RuntimeError, match="comparison probe"):
        share_back_boundary_fast(boundary, snapshot)

    assert [agent_state(agent) for agent in live] == before


def test_share_back_boundary_shares_unchanged_rows() -> None:
    live = [make_agent(cl_name="a", raw_suffix="20260918090000", status="DONE")]
    snapshot = annotated_snapshot(live)
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
    live = hundred_row_cache() + named
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


def test_fleet_rows_stay_owned_and_shared() -> None:
    live = hundred_row_cache()
    fleet_row = make_agent(
        cl_name="fleet-remote",
        raw_suffix="20260918999999",
        status="RUNNING",
    )
    snapshot = annotated_snapshot(live)
    from dataclasses import replace

    snapshot = replace(snapshot, fleet_rows=(fleet_row,))
    target = live[7]
    incoming = replace_status(target, "DONE")
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
