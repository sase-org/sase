"""Workflow-tree refresh paths for finalized Agents-tab display diffs."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sase.ace.tui.actions.agents._display_diff import (
    build_agent_display_diff,
    diff_touches_workflow_tree,
)
from sase.ace.tui.models.agent import AgentType

from ._agent_display_diff_helpers import (
    _DisplayDiffApp,
    _agent,
    _display_costs,
    _touches_workflow_tree,
    _workflow_agent,
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
    touches_tree = diff_touches_workflow_tree(
        diff,
        [workflow, workflow_step, followup],
        next_agents,
    )
    assert touches_tree is False


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


def test_added_removed_and_moved_workflow_rows_touch_tree() -> None:
    workflow = _workflow_agent("flow", suffix="wf1")
    ordinary = _agent("ordinary", tribe=None, suffix="run1")

    assert _touches_workflow_tree([], [workflow]) is True
    assert _touches_workflow_tree([workflow], []) is True
    assert _touches_workflow_tree([workflow, ordinary], [ordinary, workflow]) is True


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


def test_workflow_structural_row_change_falls_back_to_full_rebuild(
    monkeypatch: Any,
) -> None:
    old_agent = _workflow_agent("flow", suffix="wf1", status="RUNNING")
    new_agent = replace(old_agent, status="DONE")
    app = _DisplayDiffApp([old_agent], monkeypatch)

    app._agents = [new_agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[old_agent],
        defer_detail=True,
    )

    assert app.full_rebuilds == 1
    assert any(
        record.fallback_reason == "workflow_tree_change"
        for record in app._agents_refresh_trace_records
    )
    assert "display_full_rebuild" in _display_costs(app)
