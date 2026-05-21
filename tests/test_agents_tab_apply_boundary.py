"""Integration tests for the agents-tab apply boundary and refresh paths.

Covers prepared apply-boundary projections, fold-state recomputation when
stale worker results race with newer UI state, deferred selected-agent file
refresh, and background content-index refresh scheduling.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
    merge_incomplete_load_after_complete_history,
    prepare_loaded_agents_apply_boundary,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_content_search import AgentContentSearchCache
from sase.ace.tui.models.agent_loader import AgentLoadState

from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent


def test_prepared_apply_boundary_matches_apply_projection_for_folded_data() -> None:
    """The apply path should install the prepared unfiltered/folded payload."""
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
    hidden_child = _make_agent(
        cl_name="hidden_child",
        status="DONE",
        parent_workflow="workflow",
        parent_timestamp="ts1",
        raw_suffix="ts1",
        is_hidden_step=True,
    )
    agents = [parent, child, hidden_child]

    app = FakeAgentApp()
    app._fold_manager.expand("ts1")
    prep = PreparedApplyData(
        filtered_agents=list(agents),
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    boundary = prepare_loaded_agents_apply_boundary(
        prep,
        app._make_prepared_apply_snapshot(
            on_agents_tab=False,
            selected_identity=None,
            load_state=None,
        ),
    )

    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=list(agents),
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
        persist_dismissed_changes=False,
    )

    assert app._agents_with_children == boundary.fold.unfiltered_agents
    assert app._agents == boundary.fold.visible_agents
    assert app._fold_counts == boundary.fold.fold_counts


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


def test_incomplete_merge_refresh_preserves_child_derived_timestamps() -> None:
    """Tier-1 patch merge must rebuild parent fields derived from cached children."""
    parent_ts = "20260521090000"
    code_ts = "20260521090800"
    code_started = datetime(2026, 5, 21, 9, 8, 5)
    cached_parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 21, 9, 0, 0),
        raw_suffix=parent_ts,
        role_suffix=".plan",
    )
    cached_parent.plan_times = [datetime(2026, 5, 21, 9, 4, 0)]
    cached_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl.code",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 21, 9, 8, 0),
        run_start_time=code_started,
        raw_suffix=code_ts,
        parent_timestamp=parent_ts,
        role_suffix=".code",
    )
    cached_parent.code_time = code_started
    cached_parent.runtime_children.append(cached_child)

    fresh_parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 21, 9, 0, 0),
        raw_suffix=parent_ts,
        role_suffix=".plan",
    )
    fresh_parent.plan_times = list(cached_parent.plan_times)
    prep = PreparedApplyData(
        filtered_agents=[fresh_parent],
        has_always_visible=False,
        hidden_count=0,
        hideable_agents=[fresh_parent],
        dismissed_agent_objects=[],
    )
    snapshot = PreparedApplySnapshot(
        cached_agents_with_children=[cached_parent, cached_child],
        dismissed_agents=set(),
        agents_seen_complete_history=True,
        hide_non_run_agents=False,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
        ),
        fold_levels=None,
        selection=PreparedApplySelectionInputs(
            on_agents_tab=False,
            selected_identity=None,
            prior_visual_row=None,
        ),
    )

    merge_incomplete_load_after_complete_history(prep, snapshot)

    assert prep.filtered_agents[0] is fresh_parent
    assert prep.filtered_agents.index(cached_child) > prep.filtered_agents.index(
        fresh_parent
    )
    assert fresh_parent.code_time == code_started
    assert cached_child in fresh_parent.runtime_children
    assert cached_child in prep.filtered_agents
    assert "CODE  | 2026-05-21 09:08:05" in fresh_parent.timestamps_display


def test_on_tab_finalizer_defers_selected_agent_file_refresh() -> None:
    """Agent-list finalization must not start file/diff work inline."""
    agent = _make_agent(status="RUNNING", cl_name="active")
    app = FakeAgentApp(query="")
    app.current_tab = "agents"
    app._agents = [agent]
    refresh_calls: list[dict[str, object]] = []
    refresh_file_calls = 0

    class _Detail:
        def refresh_current_file(self, _agent: Agent) -> None:
            nonlocal refresh_file_calls
            refresh_file_calls += 1

    def _refresh_agents_display(**kwargs: object) -> None:
        refresh_calls.append(kwargs)

    app._refresh_agents_display = _refresh_agents_display  # type: ignore[method-assign]
    app._get_selected_agent = lambda: agent  # type: ignore[method-assign]
    app.query_one = lambda *_args, **_kwargs: _Detail()  # type: ignore[method-assign]

    app._finalize_agent_list(
        on_agents_tab=True, selected_identity=agent.identity, save_unfiltered=True
    )

    assert refresh_calls == [{"list_changed": True, "defer_detail": True}]
    assert refresh_file_calls == 0


@pytest.mark.asyncio
async def test_refilter_schedules_background_content_index_refresh(
    tmp_path: Any,
) -> None:
    (tmp_path / "live_reply.md").write_text("BACKGROUND NEEDLE", encoding="utf-8")
    agent = _make_agent(cl_name="metadata_miss", artifacts_dir=str(tmp_path))
    app = FakeAgentApp(query="needle")
    app._agent_content_search_cache = AgentContentSearchCache()
    app._agents_with_children = [agent]
    app._agents = [agent]

    app._refilter_agents()

    assert app._agents == []
    task = app._agent_content_search_refresh_task
    assert task is not None
    await task

    assert app._agent_content_search_index is not None
    assert app._agents == [agent]


@pytest.mark.asyncio
async def test_stale_background_content_index_generation_is_ignored(
    tmp_path: Any,
) -> None:
    (tmp_path / "live_reply.md").write_text("STALE NEEDLE", encoding="utf-8")
    agent = _make_agent(cl_name="metadata_miss", artifacts_dir=str(tmp_path))
    app = FakeAgentApp(query="needle")
    app._agent_content_search_cache = AgentContentSearchCache()
    app._agents_with_children = [agent]
    app._agent_content_search_refresh_generation = 2
    worker_cache = app._agent_content_search_cache.fork()

    await app._run_agent_content_search_index_refresh(
        worker_cache=worker_cache,
        agents=[agent],
        query="needle",
        generation=1,
        source_generation=0,
        source_identities=(agent.identity,),
    )

    assert app._agent_content_search_index is None
    assert app._agents == []
