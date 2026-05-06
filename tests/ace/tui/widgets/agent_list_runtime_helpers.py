"""Shared fixtures for AgentList runtime tests."""

from __future__ import annotations

from datetime import datetime

from textual.app import App

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.agent_list import AgentList


def agent(
    *,
    agent_type: AgentType = AgentType.RUNNING,
    status: str = "RUNNING",
    start: datetime | None = datetime(2026, 4, 25, 14, 30, 0),
    run_start: datetime | None = None,
    stop: datetime | None = None,
    plan_times: list[datetime] | None = None,
    raw_suffix: str = "20260425143000",
    cl_name: str = "demo",
) -> Agent:
    result = Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file="/tmp/p.gp",
        status=status,
        start_time=start,
        run_start_time=run_start,
        stop_time=stop,
        raw_suffix=raw_suffix,
    )
    if plan_times is not None:
        result.plan_times = plan_times
    return result


def workflow_child(
    *,
    step_type: str,
    status: str = "RUNNING",
    start: datetime | None = datetime(2026, 4, 25, 14, 30, 0),
    run_start: datetime | None = None,
    stop: datetime | None = None,
    plan_times: list[datetime] | None = None,
    raw_suffix: str = "20260425143000",
    cl_name: str | None = None,
    parent_appears_as_agent: bool = False,
) -> Agent:
    result = agent(
        agent_type=AgentType.WORKFLOW,
        status=status,
        start=start,
        run_start=run_start,
        stop=stop,
        plan_times=plan_times,
        raw_suffix=raw_suffix,
        cl_name=cl_name or f"{step_type}-step",
    )
    result.parent_workflow = "demo-workflow"
    result.parent_timestamp = "20260425140000"
    result.step_name = result.cl_name
    result.step_type = step_type
    result.parent_appears_as_agent = parent_appears_as_agent
    return result


def linked_followup_workflow(
    *,
    status: str = "RUNNING",
    start: datetime | None = datetime(2026, 4, 25, 14, 30, 0),
    raw_suffix: str = "20260425143100",
    parent_timestamp: str = "20260425140000",
) -> Agent:
    result = agent(
        agent_type=AgentType.WORKFLOW,
        status=status,
        start=start,
        raw_suffix=raw_suffix,
        cl_name="followup",
    )
    result.appears_as_agent = True
    result.parent_timestamp = parent_timestamp
    return result


class AgentListHarness(App):
    """Mount a single AgentList for row-patching tests."""

    def compose(self):
        yield AgentList(id="agent-list")


def agent_row_index(widget: AgentList, agent_idx: int) -> int:
    return widget._row_index_for_agent(agent_idx)  # type: ignore[return-value]
