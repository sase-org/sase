"""Integration tests for the sase-zf.2 agents-live query engine.

Mirrors ``tests/test_agents_tab_query_filter.py`` (the legacy-dialect "Off
state sweep") but drives :class:`AgentLoadingMixin._finalize_agent_list` and
:func:`_compute_finalize_plan` with the ``agents_unified_query`` sunset flag
forced on: Rust-backed committed-query filtering, hierarchy preservation,
parse-error fallback with the legacy-token hint, and mask-facade reuse
across renders.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from sase.ace.tui.actions.agents._filter_actions import AgentFilterActionsMixin
from sase.ace.tui.actions.agents._loading_compute_finalize import (
    _compute_finalize_plan,
)
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_content_search import AgentContentSearchIndex
from sase.feature_flags import override_flags

from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent


@pytest.fixture(autouse=True)
def _force_unified_agent_query_dialect() -> Iterator[None]:
    with override_flags(agents_unified_query=True):
        yield


def test_property_query_filters_correctly_unified() -> None:
    failed = _make_agent(status="FAILED", cl_name="a")
    running = _make_agent(status="RUNNING", cl_name="b")

    app = FakeAgentApp(query="status:FAILED")
    app._agents = [failed, running]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )

    assert app._agents == [failed]
    assert app._agent_query_parse_error is None


def test_matching_parent_keeps_workflow_children_visible_unified() -> None:
    parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="parent_cl",
        agent_name="frontend_workflow",
        status="RUNNING",
    )
    child = _make_agent(
        cl_name="child_cl",
        agent_name="frontend_workflow",
        status="DONE",
        parent_workflow="frontend_workflow",
    )
    other = _make_agent(cl_name="unrelated", status="DONE")

    app = FakeAgentApp(query="status:RUNNING")
    app._agents = [parent, child, other]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )

    assert parent in app._agents
    assert child in app._agents
    assert other not in app._agents


def test_bare_word_content_query_uses_prepared_index_unified() -> None:
    matching = _make_agent(cl_name="a")
    missing = _make_agent(cl_name="b")

    app = FakeAgentApp(query="needle")
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


def test_empty_query_means_no_filter_unified() -> None:
    a = _make_agent(cl_name="a")
    b = _make_agent(cl_name="b")
    app = FakeAgentApp(query="")
    app._agents = [a, b]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )
    assert app._agents == [a, b]
    assert app._agent_query_parse_error is None


def test_bad_query_falls_back_to_no_filter_and_records_error_unified() -> None:
    a = _make_agent(cl_name="a")
    b = _make_agent(cl_name="b")

    app = FakeAgentApp(query="bogus:value")
    app._agents = [a, b]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )

    assert a in app._agents
    assert b in app._agents
    assert app._agent_query_parse_error is not None
    assert "bogus" in app._agent_query_parse_error
    assert app.notify.call_count >= 1


@pytest.mark.parametrize(
    ("query", "hint"),
    [
        ("age>2h", "until:2h"),
        ("age>=2h", "until:2h"),
        ("age<5m", "since:5m"),
        ("age<=5m", "since:5m"),
        ("type:workflow", "kind:workflow"),
        ("type:run", "kind:agent"),
    ],
)
def test_legacy_token_hint_appended_to_parse_error(query: str, hint: str) -> None:
    app = FakeAgentApp(query=query)
    app._agents = [_make_agent()]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )

    assert app._agent_query_parse_error is not None
    assert hint in app._agent_query_parse_error


def test_facade_is_cached_and_reused_across_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second render with the same committed query skips rebuilding the corpus."""
    from sase.ace.tui.models import agent_live_query_engine as engine_mod

    build_calls = {"n": 0}
    real_build = engine_mod.build_agents_live_query_index

    def counting_build(*args: Any, **kwargs: Any) -> Any:
        build_calls["n"] += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(engine_mod, "build_agents_live_query_index", counting_build)

    running = _make_agent(status="RUNNING", cl_name="a")
    failed = _make_agent(status="FAILED", cl_name="b")
    app = FakeAgentApp(query="status:RUNNING")
    app._agents = [running, failed]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )
    assert app._agents == [running]
    assert build_calls["n"] == 1
    facade_after_first = app._agents_live_query_facade
    assert facade_after_first is not None

    # Re-render with the same committed query and the same underlying list —
    # the cached facade should be reused rather than rebuilding the corpus.
    app._agents = [running, failed]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )
    assert app._agents == [running]
    assert build_calls["n"] == 1
    assert app._agents_live_query_facade is facade_after_first

    # Changing the committed query invalidates the cached facade.
    app._agent_search_query = "status:FAILED"
    app._agents = [running, failed]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )
    assert app._agents == [failed]
    assert build_calls["n"] == 2


def test_edit_agent_search_query_validates_unified_dialect() -> None:
    class _App(AgentFilterActionsMixin):
        def __init__(self) -> None:
            self.hide_non_run_agents = False
            self._agent_search_query = ""
            self._agent_search_query_seeded = True
            self.pushed_screen: Any = None

        def push_screen(self, modal: Any, _callback: Any) -> None:
            self.pushed_screen = modal

    app = _App()
    app._edit_agent_search_query()
    modal = app.pushed_screen
    assert modal is not None
    assert "until:2h" in modal._hint

    # A unified-dialect query validates cleanly.
    modal._validator("until:2h")

    # A retired legacy spelling raises with the unified replacement hint.
    with pytest.raises(ValueError, match="until:2h"):
        modal._validator("age>2h")


def test_compute_finalize_plan_builds_live_facade_off_thread() -> None:
    """The off-thread compute path (full/delta reload) uses the same engine."""
    running = _make_agent(status="RUNNING", cl_name="a")
    failed = _make_agent(status="FAILED", cl_name="b")
    app = FakeAgentApp(query="status:RUNNING")
    app._agents = [running, failed]

    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=False, selected_identity=None, load_state=None
    )
    plan = _compute_finalize_plan([running, failed], snapshot)

    assert plan.query.filtered_agents == [running]
    assert plan.query.live_facade is not None
    assert plan.query.parse_error is None

    app._finalize_agent_list(
        on_agents_tab=False,
        selected_identity=None,
        save_unfiltered=False,
        fold_filter_already_applied=True,
        precomputed_plan=plan,
    )
    assert app._agents == [running]
    assert app._agents_live_query_facade is plan.query.live_facade
