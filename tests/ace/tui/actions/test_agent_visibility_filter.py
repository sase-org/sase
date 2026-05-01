"""Regression tests for Agents-tab default visibility filtering."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._loading_compute import compute_apply_loaded_agents
from sase.ace.tui.models.agent import Agent, AgentType


def _agent(
    name: str,
    status: str,
    *,
    agent_type: AgentType = AgentType.RUNNING,
    raw_suffix: str | None = None,
    parent_timestamp: str | None = None,
    parent_workflow: str | None = None,
    hidden: bool = False,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=name,
        project_file="/repo/project.gp",
        status=status,
        start_time=datetime(2026, 5, 1, 12, 0, 0),
        raw_suffix=raw_suffix or name,
        parent_timestamp=parent_timestamp,
        parent_workflow=parent_workflow,
        hidden=hidden,
        workflow="workflow-demo" if agent_type == AgentType.WORKFLOW else None,
    )


def _compute(agents: list[Agent], *, hide_non_run_agents: bool = True):
    return compute_apply_loaded_agents(
        agents,
        dismissed_from_loader=[],
        dismissed_snapshot=set(),
        hide_non_run_agents=hide_non_run_agents,
    )


def test_completed_top_level_agents_are_hidden_when_active_agents_exist() -> None:
    running = _agent("running", "RUNNING")
    done = _agent("done", "DONE")
    failed = _agent("failed", "FAILED")

    result = _compute([running, done, failed])

    assert result.filtered_agents == [running]
    assert result.hideable_agents == [done, failed]
    assert result.hidden_count == 2
    assert result.has_always_visible is True


def test_completed_agents_remain_visible_when_they_are_the_only_entries() -> None:
    done = _agent("done", "DONE")
    failed = _agent("failed", "FAILED")

    result = _compute([done, failed])

    assert result.filtered_agents == [done, failed]
    assert result.hideable_agents == [done, failed]
    assert result.hidden_count == 0
    assert result.has_always_visible is False


def test_completed_workflow_children_hide_with_completed_parent() -> None:
    running = _agent("running", "RUNNING")
    parent = _agent(
        "workflow-parent",
        "DONE",
        agent_type=AgentType.WORKFLOW,
        raw_suffix="parent-ts",
    )
    child = _agent(
        "workflow-child",
        "DONE",
        agent_type=AgentType.WORKFLOW,
        parent_workflow="workflow-demo",
        parent_timestamp="parent-ts",
    )

    result = _compute([running, parent, child])

    assert result.filtered_agents == [running]
    assert result.hideable_agents == [parent, child]
    assert result.hidden_count == 2


def test_active_workflow_children_remain_visible() -> None:
    parent = _agent(
        "workflow-parent",
        "RUNNING",
        agent_type=AgentType.WORKFLOW,
        raw_suffix="parent-ts",
    )
    running_child = _agent(
        "running-child",
        "RUNNING",
        agent_type=AgentType.WORKFLOW,
        parent_workflow="workflow-demo",
        parent_timestamp="parent-ts",
    )
    waiting_child = _agent(
        "waiting-child",
        "WAITING",
        agent_type=AgentType.WORKFLOW,
        parent_workflow="workflow-demo",
        parent_timestamp="parent-ts",
    )
    waiting_input_child = _agent(
        "waiting-input-child",
        "WAITING INPUT",
        agent_type=AgentType.WORKFLOW,
        parent_workflow="workflow-demo",
        parent_timestamp="parent-ts",
    )
    done_child = _agent(
        "done-child",
        "DONE",
        agent_type=AgentType.WORKFLOW,
        parent_workflow="workflow-demo",
        parent_timestamp="parent-ts",
    )

    result = _compute(
        [parent, running_child, waiting_child, waiting_input_child, done_child]
    )

    assert result.filtered_agents == [
        parent,
        running_child,
        waiting_child,
        waiting_input_child,
    ]
    assert result.hideable_agents == [done_child]
    assert result.hidden_count == 1


def test_explicit_hidden_agents_are_still_hideable_even_when_active() -> None:
    running = _agent("running", "RUNNING")
    hidden_running = _agent("hidden-running", "RUNNING", hidden=True)

    result = _compute([running, hidden_running])

    assert result.filtered_agents == [running]
    assert result.hideable_agents == [hidden_running]
    assert result.hidden_count == 1
