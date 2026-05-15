"""Phase-5 tests for the precomputed agents-tab finalize plan.

Exercises selection restoration (by identity / by visual row), off-tab
``_agents_last_idx`` alignment, parse-error surfacing on the UI thread,
content-query workflow-child preservation, stale-plan discard when the query
changes mid-flight, and status-override cleanup.
"""

from __future__ import annotations

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    attach_finalize_plan_to_boundary,
    prepare_loaded_agents_apply_boundary,
)
from sase.ace.tui.actions.agents._loading_compute_finalize import (
    _compute_finalize_plan,
)
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_content_search import AgentContentSearchIndex

from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent


def test_finalize_plan_restores_selection_by_identity() -> None:
    """When the previously selected agent survives, focus returns to it."""
    a = _make_agent(cl_name="alpha", status="RUNNING")
    b = _make_agent(cl_name="beta", status="RUNNING")
    c = _make_agent(cl_name="gamma", status="RUNNING")
    app = FakeAgentApp()
    app._agents_with_children = [a, b, c]
    app._agents = [a, b, c]

    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=True,
        selected_identity=b.identity,
        load_state=None,
    )
    plan = _compute_finalize_plan([a, b, c], snapshot)
    assert plan.selection.identity_restored is True
    assert plan.selection.restored_idx == 1


def test_finalize_plan_falls_back_to_prior_visual_row_when_identity_gone() -> None:
    """Selection lands on the agent now occupying the prior visual row."""
    a = _make_agent(cl_name="alpha", status="RUNNING")
    c = _make_agent(cl_name="gamma", status="RUNNING")
    app = FakeAgentApp()
    app.current_idx = 1  # was on the removed middle agent
    app._agents_with_children = [a, c]
    app._agents = [a, c]

    missing_b = _make_agent(cl_name="beta", status="RUNNING")
    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=True,
        selected_identity=missing_b.identity,
        load_state=None,
    )
    plan = _compute_finalize_plan([a, c], snapshot)
    assert plan.selection.identity_restored is False
    # prior_visual_row=1 clamps to the agent that slid into that slot.
    assert plan.selection.restored_idx == 1


def test_off_tab_finalize_keeps_last_idx_and_identity_consistent() -> None:
    """Off-tab apply keeps ``_agents_last_idx`` aligned with its identity."""
    a = _make_agent(cl_name="alpha", status="RUNNING")
    b = _make_agent(cl_name="beta", status="RUNNING")
    app = FakeAgentApp()
    app.current_tab = "changespecs"
    app._agents_last_idx = 0
    app._agents_last_identity = a.identity

    prep = PreparedApplyData(
        filtered_agents=[a, b],
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
    boundary = prepare_loaded_agents_apply_boundary(prep, snapshot)
    boundary = attach_finalize_plan_to_boundary(boundary, snapshot, content_index=None)

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

    assert 0 <= app._agents_last_idx < len(app._agents)
    assert app._agents_last_identity == app._agents[app._agents_last_idx].identity


def test_finalize_plan_surfaces_parse_error_on_ui_thread() -> None:
    """Bad query: worker plan records the error and UI emits the toast."""
    a = _make_agent(cl_name="alpha", status="RUNNING")
    b = _make_agent(cl_name="beta", status="RUNNING")
    app = FakeAgentApp(query="bogus:value")
    app._agents = [a, b]

    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
    )
    plan = _compute_finalize_plan([a, b], snapshot)
    assert plan.query.parse_error is not None
    assert plan.query.filtered_agents == [a, b]

    app._finalize_agent_list(
        on_agents_tab=False,
        selected_identity=None,
        save_unfiltered=False,
        fold_filter_already_applied=True,
        precomputed_plan=plan,
    )
    assert app._agents == [a, b]
    assert app._agent_query_parse_error is not None
    assert app.notify.call_count >= 1


def test_content_query_preserves_workflow_children_via_plan() -> None:
    """Content-query matching keeps non-matching children of matching parents."""
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
    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
    )
    plan = _compute_finalize_plan(
        [parent, child, other],
        snapshot,
        content_index=app._agent_content_search_index,
    )
    assert parent in plan.query.filtered_agents
    assert child in plan.query.filtered_agents
    assert other not in plan.query.filtered_agents


def test_stale_plan_is_discarded_when_query_changes_after_worker() -> None:
    """Plan computed for an old query must not leak into a new query render."""
    a = _make_agent(cl_name="alpha", status="RUNNING")
    b = _make_agent(cl_name="beta", status="FAILED")
    app = FakeAgentApp(query="status:running")
    app._agents = [a, b]

    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
    )
    prep = PreparedApplyData(
        filtered_agents=[a, b],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    boundary = prepare_loaded_agents_apply_boundary(prep, snapshot)
    boundary = attach_finalize_plan_to_boundary(boundary, snapshot, content_index=None)

    # The user typed a new query while the worker was in flight.
    app._agent_search_query = "status:failed"

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

    # Apply must reflect the new query, not the worker's old one.
    assert app._agents == [b]


def test_status_override_plan_clears_dismissable_overrides() -> None:
    """Agents in terminal statuses drop their stale PLAN/QUESTION override."""
    running = _make_agent(cl_name="run", status="RUNNING")
    done = _make_agent(cl_name="done", status="DONE")
    app = FakeAgentApp()
    app._agent_status_overrides = {
        running.identity: "PLAN",
        done.identity: "PLAN APPROVED",
    }
    app._agent_pre_question_status = {done.identity: "RUNNING"}
    app._agents = [running, done]

    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
    )
    plan = _compute_finalize_plan([running, done], snapshot)

    app._finalize_agent_list(
        on_agents_tab=False,
        selected_identity=None,
        save_unfiltered=False,
        fold_filter_already_applied=True,
        precomputed_plan=plan,
    )

    assert running.status == "PLAN"
    assert done.status == "DONE"
    assert done.identity not in app._agent_status_overrides
    assert done.identity not in app._agent_pre_question_status
    assert app._agent_status_overrides[running.identity] == "PLAN"
