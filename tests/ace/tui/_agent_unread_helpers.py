"""Shared helpers for unread agent indicator tests."""

from __future__ import annotations

from datetime import datetime
from sase.ace.tui.models.agent import Agent, AgentType

_DEFAULT_START_TIME = datetime(2026, 5, 7, 9, 0, 0)


def make_agent(
    *,
    name: str = "demo",
    status: str = "RUNNING",
    raw_suffix: str = "20260507090000",
    start_time: datetime | None = _DEFAULT_START_TIME,
    stop_time: datetime | None = None,
    tag: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/projects/demo/demo.sase",
        status=status,
        start_time=start_time,
        stop_time=stop_time,
        raw_suffix=raw_suffix,
        tribe=tag,
    )
