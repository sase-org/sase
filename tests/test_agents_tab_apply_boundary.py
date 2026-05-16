"""Integration tests for the agents-tab apply boundary and refresh paths.

Covers prepared apply-boundary projections, fold-state recomputation when
stale worker results race with newer UI state, deferred selected-agent file
refresh, and background content-index refresh scheduling.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from sase.ace.tui.actions.agents import _loading
from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    prepare_loaded_agents_apply_boundary,
)
from sase.ace.tui.actions.agents._loading_helpers import _AgentDiskLoadResult
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_content_search import AgentContentSearchCache
from sase.ace.tui.models.agent_loader import AgentLoadState

from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent


_INCOMPLETE_INDEX_STATE = AgentLoadState(
    tier="tier1",
    complete_history=False,
    artifact_source="artifact_index",
    used_artifact_index=True,
)

_MISSING_INDEX_STATE = AgentLoadState(
    tier="tier1",
    complete_history=False,
    artifact_source="artifact_index",
    used_artifact_index=True,
    index_missing=True,
)


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


def test_empty_incomplete_load_preserves_existing_projection() -> None:
    """A zero-row incomplete Tier 1 load must not blank populated rows."""
    agent = _make_agent(status="RUNNING", cl_name="active")
    app = FakeAgentApp()
    app._agents_with_children = [agent]
    app._agents = [agent]

    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[],
            has_always_visible=False,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=_MISSING_INDEX_STATE,
        persist_dismissed_changes=False,
    )

    assert app._agents_with_children == [agent]
    assert app._agents == [agent]


def test_initial_empty_incomplete_load_can_render_empty() -> None:
    """The preservation guard should not invent rows for a genuinely empty app."""
    app = FakeAgentApp()

    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[],
            has_always_visible=False,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=_MISSING_INDEX_STATE,
        persist_dismissed_changes=False,
    )

    assert app._agents_with_children == []
    assert app._agents == []


@pytest.mark.asyncio
async def test_stale_async_empty_load_cannot_overwrite_newer_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late older zero-row async result is discarded after a newer apply."""
    agent = _make_agent(status="RUNNING", cl_name="newer")
    app = FakeAgentApp()
    app._agents_repro_capture = None
    app._agents_load_request_generation = 2
    app._agents_load_latest_scheduled_generation = 1
    app._agents_load_latest_applied_generation = 0

    first_loader_started = asyncio.Event()
    release_first_loader = threading.Event()
    call_count = 0
    call_count_lock = threading.Lock()
    loop = asyncio.get_running_loop()

    def fake_loader(*_args: Any, **_kwargs: Any) -> _AgentDiskLoadResult:
        nonlocal call_count
        with call_count_lock:
            call_count += 1
            call_number = call_count
        if call_number == 1:
            loop.call_soon_threadsafe(first_loader_started.set)
            assert release_first_loader.wait(timeout=5)
            return _AgentDiskLoadResult([], [], _MISSING_INDEX_STATE)
        return _AgentDiskLoadResult([agent], [], _INCOMPLETE_INDEX_STATE)

    monkeypatch.setattr(_loading, "load_agents_from_disk_with_state", fake_loader)
    monkeypatch.setattr(
        app, "_external_dismissal_merge_result", lambda _dismissed: None
    )

    older_task = asyncio.create_task(app._load_agents_async(generation=1))
    await asyncio.wait_for(first_loader_started.wait(), timeout=5)

    app._agents_load_latest_scheduled_generation = 2
    await app._load_agents_async(generation=2)
    release_first_loader.set()
    await older_task

    assert app._agents_with_children == [agent]
    assert app._agents == [agent]
    assert app._agents_load_latest_applied_generation == 2


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
