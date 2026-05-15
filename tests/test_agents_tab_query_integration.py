"""Integration tests for the Phase-3 agents-tab query filter.

Drives :class:`AgentLoadingMixin._finalize_agent_list` with a synthetic
agent list and exercises the structured query path: hierarchy
preservation, parse-error fallback, and cached-AST reuse across
re-renders.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    prepare_loaded_agents_apply_boundary,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_content_search import (
    AgentContentSearchCache,
    AgentContentSearchIndex,
)
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.fold_state import FoldStateManager


_NOW = datetime(2026, 4, 26, 12, 0, 0)


def _make_agent(**overrides: Any) -> Agent:
    defaults: dict[str, Any] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "my_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "RUNNING",
        "start_time": _NOW,
    }
    defaults.update(overrides)
    return Agent(**defaults)


class _FakeContentCache:
    """Empty content cache stub — metadata-only matching."""

    def get_haystack(self, _agent: Agent) -> str:
        return ""

    def prune(self, _agents: Any) -> None:
        pass


class _FakeFoldRegistry:
    def clear_unknown(self, _keys: Any) -> None:
        pass


class FakeAgentApp(AgentLoadingMixin):
    """Minimal app exposing just the attributes ``_finalize_agent_list`` needs."""

    def __init__(self, query: str = "") -> None:
        self.current_tab = "changespecs"  # avoid widget queries
        self.current_idx = 0
        self.hide_non_run_agents = False
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agents_last_idx = 0
        self._has_always_visible = False
        self._hidden_count = 0
        self._hideable_agents: list[Agent] = []
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}
        self._agent_search_query = query
        self._agent_content_search_cache = _FakeContentCache()  # type: ignore[assignment]
        self._agent_content_search_index = None
        self._agent_content_search_source_generation = 0
        self._agent_content_search_refresh_generation = 0
        self._agent_query_cache = None
        self._agent_query_parse_error = None
        self._fold_manager = FoldStateManager()
        self._fold_counts = {}
        self._group_fold_registry = _FakeFoldRegistry()  # type: ignore[assignment]
        self._grouping_mode = GroupingMode.STANDARD
        self._agents_loading = False
        self._agents_first_load_done = True
        self.notify = MagicMock()  # type: ignore[assignment]

    # Stubs for methods the finalizer calls when on agents tab — not
    # exercised because our fake stays on changespecs tab.
    def _refresh_agents_display(self, **_kwargs: Any) -> None:
        pass

    def _get_selected_agent(self) -> Agent | None:
        return None

    def _restore_focus_after_removal(self, _prior_pos: int) -> None:
        pass

    def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("widgets not mounted")


# --- Hierarchy preservation --------------------------------------------------


def test_matching_parent_keeps_workflow_children_visible() -> None:
    """A parent that matches a structured query keeps non-matching children visible."""
    parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="parent_cl",
        agent_name="frontend_workflow",
        status="RUNNING",
    )
    # ``is_workflow_child`` is a derived property — a child is one that
    # carries a parent_workflow / parent_timestamp pointer.
    child = _make_agent(
        cl_name="child_cl",
        agent_name="frontend_workflow",
        status="DONE",
        parent_workflow="frontend_workflow",
    )
    other = _make_agent(cl_name="unrelated", status="DONE")

    app = FakeAgentApp(query="status:running")
    app._agents = [parent, child, other]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )

    # Parent matches the query; child is preserved despite not matching.
    # ``other`` does not match and has no matching parent → filtered out.
    assert parent in app._agents
    assert child in app._agents
    assert other not in app._agents


def test_property_query_filters_correctly() -> None:
    failed = _make_agent(status="FAILED", cl_name="a")
    running = _make_agent(status="RUNNING", cl_name="b")

    app = FakeAgentApp(query="status:failed")
    app._agents = [failed, running]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )

    assert app._agents == [failed]


def test_content_query_uses_prepared_index() -> None:
    matching = _make_agent(cl_name="a")
    missing = _make_agent(cl_name="b")

    app = FakeAgentApp(query="text:needle")
    app._agent_content_search_index = AgentContentSearchIndex(
        {
            matching.identity: "worker prepared needle",
            missing.identity: "other text",
        }
    )
    app._agents = [matching, missing]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )

    assert app._agents == [matching]


def test_missing_content_index_falls_back_to_metadata_only() -> None:
    agent = _make_agent(cl_name="a")
    cache = MagicMock()
    cache.get_haystack.side_effect = AssertionError(
        "finalizer must not read content files"
    )
    cache.prune = MagicMock()

    app = FakeAgentApp(query="text:needle")
    app._agent_content_search_cache = cache  # type: ignore[assignment]
    app._agent_content_search_index = None
    app._agents = [agent]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )

    assert app._agents == []
    cache.get_haystack.assert_not_called()
    cache.prune.assert_called_once_with([])


def test_content_matched_parent_keeps_workflow_children_visible() -> None:
    parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="parent_cl",
        agent_name="content_parent",
        status="RUNNING",
    )
    child = _make_agent(
        cl_name="child_cl",
        agent_name="content_parent",
        status="DONE",
        parent_workflow="content_parent",
    )
    other = _make_agent(cl_name="other", status="DONE")

    app = FakeAgentApp(query="needle")
    app._agent_content_search_index = AgentContentSearchIndex(
        {
            parent.identity: "content needle",
            child.identity: "",
            other.identity: "",
        }
    )
    app._agents = [parent, child, other]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )

    assert parent in app._agents
    assert child in app._agents
    assert other not in app._agents


# --- Parse-error fallback ----------------------------------------------------


def test_bad_query_falls_back_to_no_filter_and_records_error() -> None:
    a = _make_agent(cl_name="a")
    b = _make_agent(cl_name="b")

    # Unknown property keys raise during tokenization.
    app = FakeAgentApp(query="bogus:value")
    app._agents = [a, b]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )

    # Parse failure → no filter applied → both agents stay visible.
    assert a in app._agents
    assert b in app._agents
    # Error message is preserved on self for the modal.
    assert app._agent_query_parse_error is not None
    assert "bogus" in app._agent_query_parse_error
    # Toast was emitted.
    assert app.notify.call_count >= 1


# --- Cached-AST reuse --------------------------------------------------------


def test_parse_is_cached_across_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same raw query parses once across repeated renders."""
    from sase.ace import agent_query as aq_pkg
    from sase.ace.tui.actions.agents import _loading as loading_mod

    real_parse = aq_pkg.parse_agent_query
    call_count = {"n": 0}

    def counting_parse(q: str) -> Any:
        call_count["n"] += 1
        return real_parse(q)

    # Patch the package-level symbol so the lazy import inside
    # ``_get_or_parse_agent_query`` resolves to the counter.
    monkeypatch.setattr(aq_pkg, "parse_agent_query", counting_parse)
    # Defensive: also patch the symbol on the loading module if it has
    # already imported it eagerly (it shouldn't — uses a lazy import —
    # but this keeps the test robust to refactors).
    if hasattr(loading_mod, "parse_agent_query"):
        monkeypatch.setattr(loading_mod, "parse_agent_query", counting_parse)

    app = FakeAgentApp(query="status:running")
    app._agents = [_make_agent(status="RUNNING")]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )
    first = call_count["n"]

    # Re-render with the same query — cache should short-circuit.
    app._agents = [_make_agent(status="RUNNING")]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )
    second = call_count["n"]

    assert first == 1
    assert second == 1, "Same raw query should not re-parse"

    # Changing the query invalidates the cache and triggers a re-parse.
    app._agent_search_query = "status:failed"
    app._agents = [_make_agent(status="FAILED")]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )
    assert call_count["n"] == 2


def test_empty_query_means_no_filter() -> None:
    a = _make_agent(cl_name="a")
    b = _make_agent(cl_name="b")
    app = FakeAgentApp(query="")
    app._agents = [a, b]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )
    assert app._agents == [a, b]
    assert app._agent_query_cache is None
    assert app._agent_query_parse_error is None


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
