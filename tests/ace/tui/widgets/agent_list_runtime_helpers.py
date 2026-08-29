"""Shared fixtures for AgentList runtime tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from textual.app import App

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.agent_list import AgentList

_DEFAULT_RUN_START: Any = object()


def agent(
    *,
    agent_type: AgentType = AgentType.RUNNING,
    status: str = "RUNNING",
    start: datetime | None = datetime(2026, 4, 25, 14, 30, 0),
    run_start: datetime | None | Any = _DEFAULT_RUN_START,
    stop: datetime | None = None,
    plan_times: list[datetime] | None = None,
    code_time: datetime | None = None,
    role_suffix: str | None = None,
    raw_suffix: str = "20260425143000",
    cl_name: str = "demo",
) -> Agent:
    resolved_run_start: datetime | None = (
        start if run_start is _DEFAULT_RUN_START else run_start
    )
    result = Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file="/tmp/p.sase",
        status=status,
        start_time=start,
        run_start_time=resolved_run_start,
        stop_time=stop,
        raw_suffix=raw_suffix,
    )
    if plan_times is not None:
        result.plan_times = plan_times
    result.code_time = code_time
    result.role_suffix = role_suffix
    return result


def workflow_child(
    *,
    step_type: str,
    status: str = "RUNNING",
    start: datetime | None = datetime(2026, 4, 25, 14, 30, 0),
    run_start: datetime | None | Any = _DEFAULT_RUN_START,
    stop: datetime | None = None,
    plan_times: list[datetime] | None = None,
    code_time: datetime | None = None,
    role_suffix: str | None = None,
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
        code_time=code_time,
        role_suffix=role_suffix,
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


def monitor_shell(
    *,
    status: str = "MONITORING",
    start: datetime | None = datetime(2026, 4, 25, 14, 35, 0),
    run_start: datetime | None | Any = _DEFAULT_RUN_START,
    stop: datetime | None = None,
    raw_suffix: str = "20260425143500",
    cl_name: str = "demo--mon",
    monitor_state: str = "running",
) -> Agent:
    result = agent(
        status=status,
        start=start,
        run_start=run_start,
        stop=stop,
        role_suffix="--mon",
        raw_suffix=raw_suffix,
        cl_name=cl_name,
    )
    result.agent_family_role = "monitor"
    result.monitor_id = "m-demo"
    result.monitor_state = monitor_state
    return result


def gate_shell(
    *,
    status: str = "GATE",
    start: datetime | None = datetime(2026, 4, 25, 14, 35, 0),
    run_start: datetime | None | Any = _DEFAULT_RUN_START,
    stop: datetime | None = None,
    raw_suffix: str = "20260425143500",
    cl_name: str = "demo--gate",
    gate_state: str = "pending",
) -> Agent:
    result = agent(
        status=status,
        start=start,
        run_start=run_start,
        stop=stop,
        role_suffix="--gate",
        raw_suffix=raw_suffix,
        cl_name=cl_name,
    )
    result.agent_family_role = "gate"
    result.gate_id = "g-demo"
    result.gate_state = gate_state
    return result


def family_container(
    member: Agent,
    *,
    status: str = "DONE",
    start: datetime | None = datetime(2026, 4, 25, 14, 30, 0),
    run_start: datetime | None | Any = _DEFAULT_RUN_START,
    stop: datetime | None = datetime(2026, 4, 25, 14, 35, 0),
    raw_suffix: str = "20260425143000",
    cl_name: str = "demo",
) -> Agent:
    result = agent(
        status=status,
        start=start,
        run_start=run_start,
        stop=stop,
        raw_suffix=raw_suffix,
        cl_name=cl_name,
    )
    result.agent_family_role = "root"
    result.followup_agents.append(member)
    result.runtime_children.append(member)
    return result


class AgentListHarness(App):
    """Mount a single AgentList for row-patching tests."""

    def compose(self):
        yield AgentList(id="agent-list")


def agent_row_index(widget: AgentList, agent_idx: int) -> int:
    return widget._row_index_for_agent(agent_idx)  # type: ignore[return-value]
