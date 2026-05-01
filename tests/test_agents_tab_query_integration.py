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
from sase.ace.tui.actions.agents._loading_finalize import (
    apply_transient_status_overrides,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.fold_state import FoldStateManager


_NOW = datetime(2026, 4, 26, 12, 0, 0)


def _make_agent(**overrides: Any) -> Agent:
    defaults: dict[str, Any] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "my_cl",
        "project_file": "/tmp/projects/myproj/myproj.gp",
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


# --- Transient status overrides ---------------------------------------------


def test_transient_override_updates_active_agent_status() -> None:
    agent = _make_agent(status="RUNNING", raw_suffix="20260501090000")
    status_overrides = {agent.identity: "QUESTION"}
    pre_question_status = {agent.identity: "PLAN APPROVED"}

    cleared = apply_transient_status_overrides(
        [agent],
        status_overrides,
        pre_question_status,
    )

    assert agent.status == "QUESTION"
    assert status_overrides == {agent.identity: "QUESTION"}
    assert pre_question_status == {agent.identity: "PLAN APPROVED"}
    assert cleared == ()


def test_transient_override_clears_terminal_agent_state() -> None:
    agent = _make_agent(status="DONE", raw_suffix="20260501090000")
    status_overrides = {agent.identity: "QUESTION"}
    pre_question_status = {agent.identity: "PLAN APPROVED"}

    cleared = apply_transient_status_overrides(
        [agent],
        status_overrides,
        pre_question_status,
    )

    assert agent.status == "DONE"
    assert status_overrides == {}
    assert pre_question_status == {}
    assert cleared == (agent.identity,)


def test_transient_override_clears_missing_agent_state() -> None:
    gone_identity = (AgentType.RUNNING, "missing", "20260501090000")
    status_overrides = {gone_identity: "QUESTION"}
    pre_question_status = {gone_identity: "PLAN APPROVED"}

    cleared = apply_transient_status_overrides(
        [_make_agent(cl_name="present")],
        status_overrides,
        pre_question_status,
    )

    assert status_overrides == {}
    assert pre_question_status == {}
    assert cleared == (gone_identity,)
