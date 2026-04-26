"""Shared helpers for the ``test_agent_groups_*`` test modules."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import TreeEntry

_NOW = datetime(2026, 4, 26, 12, 0, 0)


def _agent(
    *,
    cl_name: str = "demo",
    project_file: str = "/repo/proj.gp",
    tag: str | None = None,
    agent_name: str | None = None,
    raw_suffix: str | None = None,
    parent_workflow: str | None = None,
    parent_timestamp: str | None = None,
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
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        tag=tag,
        parent_workflow=parent_workflow,
        parent_timestamp=parent_timestamp,
        wait_until=wait_until,
        retried_as_timestamp=retried_as_timestamp,
    )


def _kinds(entries: list[TreeEntry]) -> list[tuple[str, int | None]]:
    """Reduce entries to (kind, level/agent_idx) pairs for readable assertions."""
    out: list[tuple[str, int | None]] = []
    for e in entries:
        if e.kind == "group":
            assert e.group is not None
            out.append(("group", e.group.level))
        else:
            out.append(("agent", e.agent_idx))
    return out


def _group_keys(entries: list[TreeEntry], level: int) -> list[tuple[str, ...]]:
    return [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == level
    ]
