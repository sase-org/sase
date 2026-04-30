"""Tests for the Agents cleanup panel shell."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sase.ace.tui.modals import (
    AgentCleanupCustomModal,
    AgentCleanupModal,
    AgentCleanupPanelState,
    AgentCleanupResult,
    AgentCleanupTagModal,
)
from sase.ace.tui.models.agent import Agent, AgentType


def _state(**overrides: Any) -> AgentCleanupPanelState:
    base = AgentCleanupPanelState(
        focused_panel_label="@fix",
        panel_running_count=1,
        panel_completed_count=2,
        panel_failed_count=1,
        all_running_count=3,
        all_completed_count=4,
        all_failed_count=1,
        marked_count=2,
        group_count=5,
        tag_count=2,
    )
    return replace(base, **overrides)


def test_agent_cleanup_modal_action_availability() -> None:
    modal = AgentCleanupModal(
        _state(
            panel_running_count=0,
            panel_completed_count=0,
            marked_count=0,
            group_count=0,
        )
    )

    rows = {row.action: row for row in modal._rows}
    assert rows["dismiss_panel_done"].enabled is False
    assert rows["kill_panel"].enabled is False
    assert rows["marked"].enabled is False
    assert rows["group"].enabled is False
    assert rows["dismiss_all_done"].enabled is True
    assert rows["kill_all"].enabled is True
    assert rows["tag"].enabled is True
    assert rows["custom"].enabled is False


def test_agent_cleanup_modal_selected_result(monkeypatch: Any) -> None:
    modal = AgentCleanupModal(_state())
    dismissed: list[AgentCleanupResult | None] = []
    monkeypatch.setattr(modal, "dismiss", dismissed.append)

    modal.action_kill_panel()

    assert dismissed == [AgentCleanupResult(action="kill_panel")]


def test_agent_cleanup_modal_disabled_action_does_not_dismiss(monkeypatch: Any) -> None:
    modal = AgentCleanupModal(_state(marked_count=0))
    dismissed: list[AgentCleanupResult | None] = []
    monkeypatch.setattr(modal, "dismiss", dismissed.append)

    modal.action_marked()

    assert dismissed == []


def _agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "cl",
        "project_file": "/tmp/project/project.gp",
        "status": "RUNNING",
        "start_time": None,
        "raw_suffix": "ts",
        "pid": 100,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def test_agent_cleanup_tag_modal_previews_and_disables_empty_tags() -> None:
    fix = _agent(cl_name="fix", raw_suffix="fix-ts", tag="fix", pid=10)
    review = _agent(
        cl_name="review",
        raw_suffix="review-ts",
        tag="review",
        status="DONE",
        pid=None,
    )

    modal = AgentCleanupTagModal(
        tags=("fix", "review", "empty"),
        targets=[fix, review],
    )

    rows = {row.tag: row for row in modal._rows}
    assert rows["fix"].plan.counts.kill == 1
    assert rows["review"].plan.counts.dismiss == 1
    assert rows["empty"].plan.counts.kill == 0
    assert rows["empty"].plan.counts.dismiss == 0


def test_agent_cleanup_custom_modal_filters_and_selects_done_agents() -> None:
    running = _agent(cl_name="running", raw_suffix="run-ts", status="RUNNING", pid=10)
    done = _agent(cl_name="done", raw_suffix="done-ts", status="DONE", pid=None)
    waiting = _agent(cl_name="waiting", raw_suffix="wait-ts", status="WAITING", pid=11)
    modal = AgentCleanupCustomModal(
        candidates=[running, done, waiting],
        targets=[running, done, waiting],
        focused_panel_label="(untagged)",
    )

    modal.action_filter_done()
    assert modal._filtered_agents == [done]

    modal.action_toggle_all_filtered()
    assert modal._selected == {done.identity}
    assert modal._plan.counts.dismiss == 1
    assert modal._plan.counts.kill == 0


def test_agent_cleanup_custom_modal_workflow_parent_cascades_child() -> None:
    parent = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="wf-cl",
        workflow="wf",
        raw_suffix="parent-ts",
        status="RUNNING",
        pid=99,
        tag="fix",
    )
    child = _agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="step",
        workflow="wf-step",
        raw_suffix="child-ts",
        status="RUNNING",
        pid=100,
        parent_workflow="wf",
        parent_timestamp="parent-ts",
    )
    modal = AgentCleanupCustomModal(
        candidates=[parent, child],
        targets=[parent, child],
        focused_panel_label="@fix",
    )

    modal.action_cycle_tag_filter()
    assert modal._filtered_agents == [parent, child]

    modal._selected.add(parent.identity)
    modal._plan = modal._recompute_plan()

    assert modal._plan.counts.kill == 1
    assert modal._plan.counts.cascaded_workflow_children == 1
