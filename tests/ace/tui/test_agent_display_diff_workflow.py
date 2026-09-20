"""Workflow-tree refresh paths for finalized Agents-tab display diffs."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sase.ace.tui.actions.agents._display_diff import build_agent_display_diff
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_groups import GroupingMode

from ._agent_display_diff_helpers import (
    _DisplayDiffApp,
    _agent,
    _apply_roster,
    _display_costs,
    _panel_attributions,
    _panel_id,
    _panel_rows,
    _touches_workflow_tree,
    _widget_sel,
    _workflow_agent,
    _workflow_tree_keys,
)


def test_workflow_cosmetic_same_position_changes_do_not_touch_tree() -> None:
    workflow = _workflow_agent("flow", suffix="wf1", activity="initial")
    workflow_step = _workflow_agent(
        "flow-step",
        suffix="step1",
        step_output={"state": "old"},
        parent_timestamp="wf1",
        parent_workflow="flow",
    )
    followup = _workflow_agent(
        "followup",
        suffix="child1",
        agent_type=AgentType.RUNNING,
        activity="old",
        parent_timestamp="wf1",
    )
    next_agents = [
        replace(workflow, activity="building pdf"),
        replace(workflow_step, step_output={"state": "new"}),
        replace(followup, activity="polling"),
    ]
    diff = build_agent_display_diff([workflow, workflow_step, followup], next_agents)

    assert diff.changed_same_position == (0, 1, 2)
    assert (
        _touches_workflow_tree([workflow, workflow_step, followup], next_agents)
        is False
    )


def test_workflow_same_position_structural_change_touches_tree() -> None:
    workflow = _workflow_agent("flow", suffix="wf1")
    structural_variants = [
        replace(workflow, status="DONE"),
        replace(workflow, hidden=True),
        replace(workflow, parent_timestamp="parent1"),
        replace(workflow, parent_workflow="outer-flow"),
    ]

    for next_agent in structural_variants:
        assert _touches_workflow_tree([workflow], [next_agent]) is True


def test_added_removed_and_reordered_workflow_rows_touch_tree() -> None:
    workflow = _workflow_agent("flow", suffix="wf1")
    other = _workflow_agent("other", suffix="wf2")
    ordinary = _agent("ordinary", tribe=None, suffix="run1")

    assert _touches_workflow_tree([], [workflow]) is True
    assert _touches_workflow_tree([workflow], []) is True
    assert _touches_workflow_tree([workflow, other], [other, workflow]) is True
    # A workflow row reordered against an ordinary one leaves the workflow tree
    # itself alone; the panel's ordinary move handling (and the widget's own
    # ordered-subsequence gate) rebuilds it.
    assert _touches_workflow_tree([workflow, ordinary], [ordinary, workflow]) is False


def test_workflow_cosmetic_row_change_patches_without_tree_fallback(
    monkeypatch: Any,
) -> None:
    old_agent = _workflow_agent("flow", suffix="wf1", activity="initial")
    new_agent = replace(old_agent, activity="running")
    app = _DisplayDiffApp([old_agent], monkeypatch)
    widget = app._widgets["#agent-list-panel"]

    app._agents = [new_agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[old_agent],
        defer_detail=True,
    )

    assert widget.update_list_calls == 1
    assert widget._agents[0].activity == "running"
    assert app.full_rebuilds == 0
    assert "row_patch" in _display_costs(app)
    assert all(
        record.fallback_reason != "workflow_tree_change"
        for record in app._agents_refresh_trace_records
    )


def test_workflow_structural_row_change_rebuilds_its_panel_not_the_tab(
    monkeypatch: Any,
) -> None:
    old_agent = _workflow_agent("flow", suffix="wf1", status="RUNNING")
    new_agent = replace(old_agent, status="DONE")
    app = _DisplayDiffApp([old_agent], monkeypatch)
    widget = app._widgets["#agent-list-panel"]
    repaints = widget.update_list_calls

    app._agents = [new_agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[old_agent],
        defer_detail=True,
    )

    assert app.full_rebuilds == 0
    assert widget.update_list_calls == repaints + 1
    assert widget._agents[0].status == "DONE"
    attributions = [
        record
        for record in app._agents_refresh_trace_records
        if record.fallback_reason == "workflow_tree_change"
    ]
    assert [(r.display_cost, r.panel) for r in attributions] == [
        ("display_panel_rebuild", "agent-list-panel")
    ]
    assert "display_full_rebuild" not in _display_costs(app)


def test_a_workflow_change_in_one_panel_leaves_its_sibling_panels_alone(
    monkeypatch: Any,
) -> None:
    flow = _workflow_agent("flow", suffix="wf1", tribe="apple")
    apple = _agent("apple-one", tribe="apple", suffix="a1")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    app = _DisplayDiffApp([flow, apple, banana], monkeypatch)
    apple_widget = app._widgets[_widget_sel("apple")]
    banana_widget = app._widgets[_widget_sel("banana")]
    apple_repaints = apple_widget.update_list_calls
    banana_repaints = banana_widget.update_list_calls
    app._agents_refresh_trace_records.clear()

    done = replace(flow, status="DONE")
    banana_progress = replace(banana, activity="still going")
    app._agents = [done, apple, banana_progress]
    app._refresh_agents_display_after_finalize(
        previous_agents=[flow, apple, banana],
        defer_detail=True,
    )

    assert app.full_rebuilds == 0
    assert apple_widget.update_list_calls == apple_repaints + 1
    assert banana_widget.update_list_calls == banana_repaints  # patched, not rebuilt
    assert banana_widget._agents[0].activity == "still going"
    panels = [
        record.panel
        for record in app._agents_refresh_trace_records
        if record.fallback_reason == "workflow_tree_change"
    ]
    assert panels == ["agent-list-panel-apple"]
    costs = _display_costs(app)
    assert "row_patch" in costs
    assert "display_full_rebuild" not in costs


def test_a_workflow_row_that_only_shifts_index_does_not_touch_its_tree() -> None:
    flow = _workflow_agent("flow", suffix="wf1", tribe="banana")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    apple = _agent("apple-one", tribe="apple", suffix="a1")
    arrival = _agent("apple-two", tribe="apple", suffix="a2")

    # ``flow`` and ``banana`` move down one roster slot, but they keep their
    # panel, their order, and their neighbours in it.
    assert (
        _workflow_tree_keys([apple, flow, banana], [apple, arrival, flow, banana])
        == set()
    )


def test_workflow_tree_attribution_names_only_the_panels_it_concerns() -> None:
    apple_flow = _workflow_agent("flow-a", suffix="wf1", tribe="apple")
    banana_flow = _workflow_agent("flow-b", suffix="wf2", tribe="banana")
    ordinary = _agent("plain", tribe="banana", suffix="p1")
    base = [apple_flow, banana_flow, ordinary]

    added = _workflow_agent("flow-c", suffix="wf3", tribe="apple")
    assert _workflow_tree_keys(base, [*base, added]) == {"apple"}
    assert _workflow_tree_keys(base, base[1:]) == {"apple"}  # a removal
    assert _workflow_tree_keys(
        base, [replace(banana_flow, status="DONE"), *base[:1], ordinary]
    ) == {"banana"}
    # A reorder among a panel's workflow rows is a tree change for that panel.
    second = _workflow_agent("flow-d", suffix="wf4", tribe="banana")
    assert _workflow_tree_keys([banana_flow, second], [second, banana_flow]) == {
        "banana"
    }
    # A row that changes panel concerns both the panel it left and the one it joined.
    moved = replace(banana_flow, tribe="apple")
    assert _workflow_tree_keys(base, [apple_flow, moved, ordinary]) == {
        "apple",
        "banana",
    }


def test_a_workflow_child_reanchored_by_a_starting_parent_names_both_panels() -> None:
    child = _workflow_agent(
        "step",
        suffix="c1",
        agent_type=AgentType.RUNNING,
        parent_timestamp="wf1",
        tribe="apple",
    )
    parent = _workflow_agent("flow", suffix="wf1", status="STARTING", tribe="banana")

    # The STARTING parent has no row of its own, but it re-anchors its child
    # from the panel it sat in alone to the parent's panel.
    assert _workflow_tree_keys([child], [child, parent]) >= {"banana"}


def test_workflow_tree_attribution_collapses_to_one_panel_when_merged() -> None:
    flow = _workflow_agent("flow", suffix="wf1", tribe="apple")
    ordinary = _agent("plain", tribe="banana", suffix="p1")

    keys = _workflow_tree_keys(
        [flow, ordinary],
        [replace(flow, status="DONE"), ordinary],
        merge_tribe_panels=True,
    )

    assert keys == {None}


def test_a_workflow_family_leaving_one_panel_rebuilds_only_that_panel(
    monkeypatch: Any,
) -> None:
    flow = _workflow_agent("flow", suffix="wf1", tribe="apple")
    apple = _agent("apple-one", tribe="apple", suffix="a1")
    banana = _agent("banana-one", tribe="banana", suffix="b1")
    app = _DisplayDiffApp([flow, apple, banana], monkeypatch)
    app._grouping_mode = GroupingMode.BY_STATUS
    app._refresh_panel_widgets(jump_hints=None)
    app._agents_refresh_trace_records.clear()
    apple_widget = app._widgets[_widget_sel("apple")]
    banana_widget = app._widgets[_widget_sel("banana")]
    apple_repaints = apple_widget.update_list_calls
    banana_repaints = banana_widget.update_list_calls

    _apply_roster(app, [flow, apple, banana], [apple, banana])

    assert app.full_rebuilds == 0
    assert apple_widget.update_list_calls == apple_repaints + 1
    assert banana_widget.update_list_calls == banana_repaints
    assert _panel_rows(app, "apple") == [apple.identity]
    assert _panel_attributions(app) == [(_panel_id("apple"), "workflow_tree_change")]
    assert "display_full_rebuild" not in _display_costs(app)
