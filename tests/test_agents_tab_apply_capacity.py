"""Integration tests for the agents-tab fold/capacity/proc-shell apply boundary."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pytest

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    prepare_loaded_agents_apply_boundary,
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_runner_slots import RunnerCapacitySnapshot
from sase.ace.tui.models.agent_proc_shells import merge_proc_shell_agents
from sase.feature_flags import override_flags

from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent


@pytest.fixture(autouse=True)
def _pin_legacy_agent_query_dialect() -> Iterator[None]:
    """sase-zf.2: these tests exercise the legacy agent_query dialect explicitly."""
    with override_flags(agents_unified_query=False):
        yield


def test_precomputed_fold_boundary_recomputes_when_fold_state_changes() -> None:
    """A worker result with stale fold levels must not overwrite newer UI state."""
    parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="parent",
        status="RUNNING",
        raw_suffix="ts1",
    )
    child = _make_agent(
        cl_name="child",
        status="DONE",
        parent_workflow="workflow",
        parent_timestamp="ts1",
        raw_suffix="ts1",
    )
    agents = [parent, child]

    app = FakeAgentApp()
    app._fold_manager.expand("ts1")
    expanded_levels = app._fold_manager.snapshot()
    prep = PreparedApplyData(
        filtered_agents=list(agents),
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    stale_boundary = prepare_loaded_agents_apply_boundary(
        prep,
        app._make_prepared_apply_snapshot(
            on_agents_tab=False,
            selected_identity=None,
            load_state=None,
        ),
    )

    app._fold_manager.collapse("ts1")
    app._apply_loaded_agents_prepared(
        prep,
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
        persist_dismissed_changes=False,
        incomplete_merge_already_applied=True,
        precomputed_boundary=stale_boundary,
        precomputed_fold_levels=expanded_levels,
    )

    assert app._agents_with_children == agents
    assert app._agents == [parent]
    assert app._fold_counts == {"ts1": (1, 0)}


def test_runner_capacity_installs_atomically_and_survives_local_refilters() -> None:
    """Fold/search presentation changes preserve the last global snapshot."""
    holder = _make_agent(
        cl_name="holder",
        status="RUNNING",
        raw_suffix="holder",
        pid=101,
        artifacts_dir="/tmp/artifacts/ace-run/holder",
        run_start_time=datetime(2026, 7, 20, 10, 0),
    )
    implicit_waiter = _make_agent(
        cl_name="implicit",
        status="WAITING",
        raw_suffix="implicit",
        pid=102,
        artifacts_dir="/tmp/artifacts/ace-run/implicit",
        wait_runners=9,
        wait_runners_explicit=False,
        slot_requested_at="2026-07-20T10:01:00Z",
    )
    explicit_waiter = _make_agent(
        cl_name="explicit",
        status="WAITING",
        raw_suffix="explicit",
        pid=103,
        artifacts_dir="/tmp/artifacts/ace-run/explicit",
        wait_runners=0,
        wait_runners_explicit=True,
        slot_requested_at="2026-07-20T10:02:00Z",
    )
    parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="workflow",
        status="DONE",
        raw_suffix="workflow",
    )
    child = _make_agent(
        cl_name="workflow-child",
        status="DONE",
        raw_suffix="workflow-child",
        parent_workflow="workflow",
        parent_timestamp="workflow",
    )
    agents = [holder, implicit_waiter, explicit_waiter, parent, child]
    app = FakeAgentApp()
    app._fold_manager.expand("workflow")
    prep = PreparedApplyData(
        filtered_agents=agents,
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
    )
    boundary = prepare_loaded_agents_apply_boundary(
        prep,
        snapshot,
        effective_runner_limit=10,
    )

    assert (
        boundary.runner_capacity.effective_limit,
        boundary.runner_capacity.slots_in_use,
        boundary.runner_capacity.queued_count,
    ) == (10, 1, 2)
    assert implicit_waiter.status == "QUEUED"
    assert explicit_waiter.status == "QUEUED"
    assert implicit_waiter.runner_slot_queue_position == 1
    assert explicit_waiter.runner_slot_queue_position == 2
    assert implicit_waiter.runner_slot_queue_size == 2
    assert explicit_waiter.runner_slot_queue_size == 2

    app._apply_loaded_agents_prepared(
        prep,
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
        persist_dismissed_changes=False,
        incomplete_merge_already_applied=True,
        precomputed_boundary=boundary,
        precomputed_fold_levels=snapshot.fold_levels,
    )
    expected_capacity = boundary.runner_capacity
    assert app._agent_runner_capacity == expected_capacity

    app._agent_search_query = "status:waiting"
    app._agent_query_cache = None
    app._refilter_agents(refresh_content_index=False)
    assert app._agent_runner_capacity == expected_capacity
    assert implicit_waiter not in app._agents
    assert explicit_waiter not in app._agents

    app._agent_search_query = "status:queued"
    app._agent_query_cache = None
    app._refilter_agents(refresh_content_index=False)
    assert implicit_waiter in app._agents
    assert explicit_waiter in app._agents

    app._agent_search_query = ""
    app._agent_query_cache = None
    app._fold_manager.collapse("workflow")
    app._refilter_agents(refresh_content_index=False)
    assert app._agent_runner_capacity == expected_capacity
    assert child not in app._agents


def test_worker_boundary_observes_changed_effective_runner_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits = iter((10, 4))
    monkeypatch.setattr("sase.config.core.get_max_running_agents", lambda: next(limits))
    app = FakeAgentApp()
    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
    )

    first = prepare_loaded_agents_worker_boundary([], [], set(), False, snapshot)
    second = prepare_loaded_agents_worker_boundary([], [], set(), False, snapshot)

    assert first.runner_capacity == RunnerCapacitySnapshot(10, 0, 0, (), 0.0)
    assert second.runner_capacity == RunnerCapacitySnapshot(4, 0, 0, (), 0.0)


@pytest.mark.parametrize("merge_incomplete", [True, False])
@pytest.mark.parametrize("incoming_has_proc", [False, True])
def test_apply_boundary_carries_cached_proc_shell_before_fold_filtering(
    merge_incomplete: bool,
    incoming_has_proc: bool,
) -> None:
    disk_agent = _make_agent(cl_name="disk", raw_suffix="disk")
    proc_shell = _make_agent(
        agent_type=AgentType.PROC_SHELL,
        cl_name="sase",
        raw_suffix="proc-123",
        status="RUNNING",
        proc_id="proc-123",
    )
    incoming = (
        merge_proc_shell_agents([disk_agent], [proc_shell])
        if incoming_has_proc
        else [disk_agent]
    )
    prep = PreparedApplyData(
        filtered_agents=incoming,
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )

    app = FakeAgentApp()
    app._agents_with_children = [disk_agent, proc_shell]
    boundary = prepare_loaded_agents_apply_boundary(
        prep,
        app._make_prepared_apply_snapshot(
            on_agents_tab=False,
            selected_identity=None,
            load_state=None,
        ),
        merge_incomplete=merge_incomplete,
    )

    assert [agent.identity for agent in boundary.fold.unfiltered_agents].count(
        proc_shell.identity
    ) == 1
    assert [agent.identity for agent in boundary.fold.visible_agents].count(
        proc_shell.identity
    ) == 1


def test_proc_shell_rows_do_not_occupy_runner_capacity() -> None:
    holder = _make_agent(
        cl_name="holder",
        status="RUNNING",
        raw_suffix="holder",
        pid=101,
        artifacts_dir="/tmp/artifacts/ace-run/holder",
        run_start_time=datetime(2026, 8, 23, 10, 0),
    )
    proc_shell = _make_agent(
        agent_type=AgentType.PROC_SHELL,
        cl_name="sase",
        raw_suffix="proc-123",
        status="RUNNING",
        proc_id="proc-123",
        pid=202,
        run_start_time=datetime(2026, 8, 23, 10, 1),
    )
    app = FakeAgentApp()
    app._agents_with_children = [holder, proc_shell]

    boundary = prepare_loaded_agents_apply_boundary(
        PreparedApplyData(
            filtered_agents=[holder],
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        app._make_prepared_apply_snapshot(
            on_agents_tab=False,
            selected_identity=None,
            load_state=None,
        ),
        effective_runner_limit=4,
    )

    assert boundary.runner_capacity.slots_in_use == 1
