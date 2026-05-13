"""Shared helpers for agent metadata enrichment tests."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.time import get_timezone


def make_agent(status: str = "RUNNING") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.sase",
        status=status,
        start_time=datetime(2026, 4, 10, 22, 0, 0),
    )


def local_time_from_iso(timestamp: str) -> datetime:
    return (
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        .astimezone(get_timezone())
        .replace(tzinfo=None)
    )
