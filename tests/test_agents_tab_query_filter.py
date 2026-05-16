"""Integration tests for the Phase-3 agents-tab query filter.

Drives :class:`AgentLoadingMixin._finalize_agent_list` with a synthetic
agent list and exercises the structured query path: hierarchy
preservation, parse-error fallback, and cached-AST reuse across
re-renders.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_content_search import AgentContentSearchIndex

from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent


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


def test_matching_parent_keeps_children_by_parent_timestamp() -> None:
    """Search preservation uses the same parent key as fold/render projection."""
    parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase-3r",
        agent_name="phase parent",
        status="RUNNING",
        raw_suffix="20260516095501",
    )
    child = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="prompt step",
        agent_name="different child name",
        status="DONE",
        parent_workflow="workflow-sase-3r",
        parent_timestamp="20260516095501",
        step_name="plan",
        step_type="agent",
        raw_suffix="20260516095501",
    )
    other = _make_agent(cl_name="unrelated", status="DONE")

    app = FakeAgentApp(query="status:running")
    app._fold_manager.expand("20260516095501")
    app._agents = [parent, child, other]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )

    assert app._agents == [parent, child]
    assert app._agents_with_children == [parent, child, other]


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
