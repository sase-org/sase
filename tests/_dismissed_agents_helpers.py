"""Shared helpers for dismissed agent persistence tests."""

from datetime import datetime
from sase.ace.tui.models.agent import Agent, AgentType


def make_agent(
    *,
    agent_type: AgentType = AgentType.RUNNING,
    cl_name: str = "test_cl",
    raw_suffix: str | None = "20250615103000",
    status: str = "DONE",
    workflow: str | None = None,
    parent_workflow: str | None = None,
    parent_timestamp: str | None = None,
    step_index: int | None = None,
) -> Agent:
    """Create a test Agent."""
    return Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=datetime(2025, 6, 15, 10, 30, 0),
        raw_suffix=raw_suffix,
        workflow=workflow,
        parent_workflow=parent_workflow,
        parent_timestamp=parent_timestamp,
        step_index=step_index,
    )
