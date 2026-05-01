"""Plan-chain phases remain independent rows in Agents-tab rendering."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _sort_and_reorder


def _agent(
    *,
    cl_name: str,
    raw_suffix: str,
    start_time: datetime,
    parent_timestamp: str | None = None,
    plan_chain_parent_timestamp: str | None = None,
    role_suffix: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/repo/proj.gp",
        status="RUNNING",
        start_time=start_time,
        raw_suffix=raw_suffix,
        parent_timestamp=parent_timestamp,
        plan_chain_parent_timestamp=plan_chain_parent_timestamp,
        role_suffix=role_suffix,
    )


def test_sort_does_not_insert_plan_chain_phase_under_parent() -> None:
    parent = _agent(
        cl_name="demo.plan",
        raw_suffix="ts-parent",
        start_time=datetime(2026, 4, 25, 10, 0, 0),
        role_suffix=".plan",
    )
    coder = _agent(
        cl_name="demo.coder",
        raw_suffix="ts-coder",
        start_time=datetime(2026, 4, 25, 11, 0, 0),
        parent_timestamp="ts-parent",
        plan_chain_parent_timestamp="ts-parent",
        role_suffix=".coder",
    )

    result = _sort_and_reorder([parent, coder], workflow_agent_steps=[])

    assert [agent.cl_name for agent in result] == ["demo.coder", "demo.plan"]


def test_sort_still_nests_workflow_prompt_steps_under_parent() -> None:
    parent = _agent(
        cl_name="workflow",
        raw_suffix="ts-parent",
        start_time=datetime(2026, 4, 25, 10, 0, 0),
    )
    parent.agent_type = AgentType.WORKFLOW
    parent.workflow = "workflow-demo"
    step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="step",
        project_file="/repo/proj.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        parent_workflow="workflow-demo",
        parent_timestamp="ts-parent",
        step_type="agent",
        step_index=0,
        total_steps=1,
    )

    result = _sort_and_reorder([parent], workflow_agent_steps=[step])

    assert result == [parent, step]
