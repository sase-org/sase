"""Worker/UI ownership isolation for Agents-tab row graphs."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    merge_incomplete_load_after_complete_history,
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.actions.agents._loading_refresh import (
    ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S,
    TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S,
)
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.widgets._agent_list_helpers import ordered_row_providers

from tests._agents_tab_graph_isolation_helpers import (
    clan_container,
    clan_graph,
    delta_load_state,
    agent_session_graph,
    agent_session_root,
    row_observation,
    row_prefix,
    unrelated_delta,
)
from tests._agents_tab_incomplete_merge_helpers import (
    _authoritative_load_state,
    _bounded_prefix_load_state,
    _incomplete_tier1_snapshot,
)
from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent
from tests.ace.tui._lazy_tier2_reconcile_helpers import FakeRefreshApp


@contextmanager
def _pause_runtime_clear(
    monkeypatch: pytest.MonkeyPatch,
    *,
    error: BaseException | None = None,
) -> Iterator[tuple[threading.Event, threading.Event]]:
    started = threading.Event()
    release = threading.Event()
    from sase.ace.tui.models import _agent_ordering

    real_clear = _agent_ordering._clear_runtime_children

    def pausing_clear(*args: Any, **kwargs: Any) -> None:
        real_clear(*args, **kwargs)
        started.set()
        if not release.wait(timeout=5.0):
            raise TimeoutError("normalization barrier was not released")
        if error is not None:
            raise error

    monkeypatch.setattr(_agent_ordering, "_clear_runtime_children", pausing_clear)
    try:
        yield started, release
    finally:
        release.set()


def _run_worker(
    live: list[Agent],
    incoming: list[Agent],
    started: threading.Event,
) -> tuple[threading.Thread, list[Any], list[Exception]]:
    app = FakeAgentApp()
    app._agents_with_children = live
    app._agents = list(live)
    app._agents_seen_complete_history = True
    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=False,
        selected_identity=None,
        load_state=delta_load_state(),
    )
    result: list[Any] = []
    failed: list[Exception] = []

    def worker() -> None:
        try:
            result.append(
                prepare_loaded_agents_worker_boundary(
                    incoming,
                    [],
                    set(),
                    False,
                    snapshot,
                )
            )
        except Exception as exc:
            failed.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    assert started.wait(timeout=5.0)
    return thread, result, failed


def test_worker_pause_does_not_clear_live_clan_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = clan_graph()
    container = clan_container(live)
    before = row_observation(container)
    prefix = row_prefix(container)
    assert "🎭" in prefix and "🤖" in prefix

    with _pause_runtime_clear(monkeypatch) as (started, release):
        thread, result, failed = _run_worker(live, [unrelated_delta()], started)
        assert row_observation(container) == before
        assert row_prefix(container) == prefix
        release.set()
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        assert failed == []
        assert row_observation(container) == before
        assert row_prefix(container) == prefix
        prepared = clan_container(result[0].fold.unfiltered_agents)
        assert prepared is not container
        assert row_prefix(prepared) == prefix
        assert ordered_row_providers(prepared) == ("claude", "codex")


def test_worker_pause_does_not_clear_live_agent_session_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = agent_session_graph()
    root = agent_session_root(live)
    before = row_observation(root)
    prefix = row_prefix(root)
    assert root.is_agent_session_container_row
    assert "🎭" in prefix and "🤖" in prefix

    with _pause_runtime_clear(monkeypatch) as (started, release):
        thread, result, failed = _run_worker(live, [unrelated_delta()], started)
        assert row_observation(root) == before
        assert row_prefix(root) == prefix
        release.set()
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        assert failed == []
        assert row_observation(root) == before
        prepared = agent_session_root(result[0].fold.unfiltered_agents)
        assert prepared is not root
        assert prepared.is_agent_session_container_row
        assert row_prefix(prepared) == prefix


def test_worker_exception_does_not_damage_live_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = clan_graph()
    container = clan_container(live)
    before = row_observation(container)
    prefix = row_prefix(container)
    boom = RuntimeError("normalize failed")

    with _pause_runtime_clear(monkeypatch, error=boom) as (started, release):
        thread, result, failed = _run_worker(live, [unrelated_delta()], started)
        assert row_prefix(container) == prefix
        release.set()
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        assert result == []
        assert failed and "normalize failed" in str(failed[0])
        assert row_observation(container) == before
        assert row_prefix(container) == prefix


def test_abandoned_worker_thread_cannot_mutate_live_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling the await does not stop the thread; isolation still holds."""
    live = clan_graph()
    container = clan_container(live)
    before = row_observation(container)
    prefix = row_prefix(container)

    with _pause_runtime_clear(monkeypatch) as (started, release):
        thread, result, failed = _run_worker(live, [unrelated_delta()], started)
        # Simulate asyncio.to_thread cancellation: drop the waiter, thread continues.
        assert row_observation(container) == before
        release.set()
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        assert failed == []
        assert result
        assert row_observation(container) == before
        assert row_prefix(container) == prefix


def test_apply_publishes_legitimate_provider_and_child_updates() -> None:
    live = clan_graph()
    container = clan_container(live)
    prefix = row_prefix(container)
    new_member = _make_agent(
        cl_name="epic-grok",
        raw_suffix="20260918090300",
        status="RUNNING",
        llm_provider="grok",
        agent_clan="epic-clan",
        agent_clan_generation="g1",
        tribe="epic",
        start_time=datetime(2026, 9, 18, 9, 3, 0),
        run_start_time=datetime(2026, 9, 18, 9, 3, 0),
    )
    incoming = [agent for agent in live if not agent.is_clan_container] + [new_member]
    app = FakeAgentApp()
    app._agents_with_children = live
    app._agents = list(live)
    app._agents_seen_complete_history = True
    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=incoming,
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=delta_load_state(),
        persist_dismissed_changes=False,
    )
    assert row_prefix(container) == prefix
    published = clan_container(app._agents_with_children)
    assert published is not container
    published_prefix = row_prefix(published)
    assert "🎭" in published_prefix and "🤖" in published_prefix
    assert "🚀" in published_prefix


def test_incomplete_merge_does_not_alias_live_cached_rows() -> None:
    live = clan_graph()
    container = clan_container(live)
    before = row_observation(container)
    other = unrelated_delta()
    prep = PreparedApplyData(
        filtered_agents=[other],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[other],
        dismissed_agent_objects=[],
    )
    snapshot = _incomplete_tier1_snapshot(
        live,
        artifact_source="artifact_delta",
        used_artifact_index=False,
        capacity_agents_with_children=live,
    )

    merge_incomplete_load_after_complete_history(prep, snapshot)

    assert row_observation(container) == before
    assert all(agent is not container for agent in prep.filtered_agents)
    published = clan_container(prep.filtered_agents)
    assert published is not container
    assert ordered_row_providers(published) == ("claude", "codex")
    assert all(agent is not live[0] for agent in prep.capacity_agents)


def test_bounded_prefix_then_completion_keeps_discovered_rows() -> None:
    first = _make_agent(
        cl_name="startup-first",
        raw_suffix="20260918070100",
        status="RUNNING",
        llm_provider="claude",
    )
    second = _make_agent(
        cl_name="startup-second",
        raw_suffix="20260918070200",
        status="RUNNING",
        llm_provider="codex",
    )
    app = FakeAgentApp()
    prefix_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
        bounded_prefix=True,
        requested_limit=1,
        returned_count=1,
        has_more=True,
    )
    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[first],
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=prefix_state,
        persist_dismissed_changes=False,
    )
    assert [agent.identity for agent in app._agents_with_children] == [first.identity]
    live_first = app._agents_with_children[0]
    live_prefix = row_prefix(live_first)

    completion = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
        bounded_prefix=True,
        requested_limit=2,
        returned_count=2,
        has_more=False,
    )
    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[first, second],
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=completion,
        persist_dismissed_changes=False,
    )
    identities = {agent.identity for agent in app._agents_with_children}
    assert first.identity in identities
    assert second.identity in identities
    assert row_prefix(live_first) == live_prefix


def test_exact_delta_deletion_and_dismissal_apply_on_publish() -> None:
    kept = _make_agent(
        cl_name="kept",
        raw_suffix="20260918110100",
        status="RUNNING",
        artifacts_dir="/tmp/artifacts/ace-run/20260918110100",
    )
    removed = _make_agent(
        cl_name="removed",
        raw_suffix="20260918110200",
        status="DONE",
        artifacts_dir="/tmp/artifacts/ace-run/20260918110200",
    )
    app = FakeAgentApp()
    app._agents_with_children = [kept, removed]
    app._agents = [kept, removed]
    app._agents_seen_complete_history = True
    app._dismissed_agents.add(removed.identity)
    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[kept],
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_delta",
            used_artifact_index=False,
            deleted_artifact_dirs=frozenset({"/tmp/artifacts/ace-run/20260918110200"}),
        ),
        persist_dismissed_changes=False,
    )
    assert [agent.identity for agent in app._agents_with_children] == [kept.identity]


def test_query_reconcile_then_tier1_does_not_retreat() -> None:
    historical = _make_agent(
        cl_name="history-row",
        raw_suffix="20260917010100",
        status="DONE",
    )
    live = _make_agent(
        cl_name="live-row",
        raw_suffix="20260918010100",
        status="RUNNING",
        llm_provider="claude",
    )
    app = FakeAgentApp(query="status:RUNNING")
    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[historical, live],
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=AgentLoadState(
            tier="tier2",
            complete_history=True,
            artifact_source="artifact_index",
            used_artifact_index=True,
        ),
        persist_dismissed_changes=False,
    )
    discovered = {agent.identity for agent in app._agents_with_children}
    assert historical.identity in discovered
    assert live.identity in discovered

    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[live],
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
            bounded_prefix=True,
            requested_limit=1,
            returned_count=1,
            has_more=True,
        ),
        persist_dismissed_changes=False,
    )
    retained = {agent.identity for agent in app._agents_with_children}
    assert historical.identity in retained
    assert live.identity in retained


def test_ten_unrelated_deltas_keep_live_clan_providers() -> None:
    live = clan_graph()
    container = clan_container(live)
    before = row_observation(container)
    prefix = row_prefix(container)
    app = FakeAgentApp()
    app._agents_with_children = live
    app._agents = list(live)
    app._agents_seen_complete_history = True
    for tick in range(10):
        other = _make_agent(
            cl_name=f"delta-{tick}",
            raw_suffix=f"2026091811{tick:02d}00",
            status="DONE",
            start_time=datetime(2026, 9, 18, 11, tick, 0),
        )
        snapshot = app._make_prepared_apply_snapshot(
            on_agents_tab=False,
            selected_identity=None,
            load_state=delta_load_state(),
        )
        prepare_loaded_agents_worker_boundary(
            [other],
            [],
            set(),
            False,
            snapshot,
        )
        assert row_observation(container) == before
        assert row_prefix(container) == prefix


def test_quiet_thresholds_fire_roster_completion_then_tier2_with_fake_time() -> None:
    app = FakeRefreshApp()
    app._last_input_mono = 10.0
    app._arm_agents_history_reconcile(
        quiet_s=ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S,
        now_mono=10.0,
    )

    assert (
        app._maybe_trigger_input_quiet_tier2_reconcile(
            now_mono=10.0 + ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S - 0.1
        )
        is False
    )
    assert (
        app._maybe_trigger_input_quiet_tier2_reconcile(
            now_mono=10.0 + ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S + 0.1
        )
        is True
    )

    app._agents_refresh_scheduled = False
    app._last_input_mono = 10.0
    app._arm_agents_history_reconcile(
        quiet_s=TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S,
        now_mono=10.0,
    )
    assert (
        app._maybe_trigger_input_quiet_tier2_reconcile(
            now_mono=10.0 + ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S + 0.1
        )
        is False
    )
    assert (
        app._maybe_trigger_input_quiet_tier2_reconcile(
            now_mono=10.0 + TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S + 0.1
        )
        is True
    )


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
        _make_agent(
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
        _make_agent(
            cl_name=f"fresh-{index:03d}",
            raw_suffix=f"20260919{index:04d}",
            status="RUNNING",
            llm_provider="claude",
        )
        for index in range(100)
    ]
    snapshot = _incomplete_tier1_snapshot(
        live,
        load_state=_authoritative_load_state(),
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
    from sase.ace.tui.models.agent import AgentType

    counts = _counting_copy_spy(monkeypatch)
    named = [
        _make_agent(
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
    snapshot = _incomplete_tier1_snapshot(
        live,
        load_state=_authoritative_load_state(),
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
    snapshot = _incomplete_tier1_snapshot(
        live,
        load_state=_bounded_prefix_load_state(),
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
        _make_agent(
            cl_name=f"cap-{index:03d}",
            raw_suffix=f"20260920{index:04d}",
            status="RUNNING",
            llm_provider="codex",
        )
        for index in range(10)
    ]
    before_live = [row_observation(agent) for agent in live]
    before_capacity = [row_observation(agent) for agent in capacity]
    snapshot = _incomplete_tier1_snapshot(
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
        _make_agent(
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
        _make_agent(
            cl_name=f"fresh-{index:03d}",
            raw_suffix=f"20260919{index:04d}",
            status="RUNNING",
            llm_provider="claude",
        )
        for index in range(100)
    ]
    snapshot = _incomplete_tier1_snapshot(
        live,
        load_state=_authoritative_load_state(),
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
