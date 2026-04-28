"""Shared helpers for agent-list grouping tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.agent_list import _BANNER_ROW

BR = (_BANNER_ROW, None)


def make_agent(
    *,
    cl_name: str = "demo",
    project_file: str = "/repo/proj.gp",
    tag: str | None = None,
    agent_name: str | None = None,
    status: str = "RUNNING",
    start_time: datetime | None = datetime(2026, 4, 25, 12, 0, 0),
    wait_until: str | None = None,
    retried_as_timestamp: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=project_file,
        status=status,
        start_time=start_time,
        agent_name=agent_name,
        tag=tag,
        wait_until=wait_until,
        retried_as_timestamp=retried_as_timestamp,
    )
